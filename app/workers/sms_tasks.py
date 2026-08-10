import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.job_record import JobRecord
from app.models.meeting import Meeting, MeetingStatus
from app.models.sms_log import SmsLog
from app.services.meeting_sms import _reminder_message
from app.services.parent_directory import meeting_recipient_phones
from app.services.dues_sms import send_dues_sms_for_config
from app.services.sms import send_sms_sync
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def send_meeting_reminder(self, meeting_id: str, reminder_type: str):
    """Fire a single meeting reminder at its ETA. Skips if meeting/jobs were cancelled."""
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting or not meeting.is_active:
            logger.info("Meeting reminder skipped — meeting missing/inactive: %s", meeting_id)
            return {"skipped": True, "reason": "missing"}

        status = meeting.status.value if hasattr(meeting.status, "value") else str(meeting.status)
        if status != MeetingStatus.SCHEDULED.value:
            logger.info("Meeting reminder skipped — status=%s id=%s", status, meeting_id)
            return {"skipped": True, "reason": "not_scheduled"}

        # Honour the latest job row for this reminder (reschedule cancels older ones)
        latest_job = (
            db.query(JobRecord)
            .filter(
                JobRecord.reference_id == meeting_id,
                JobRecord.job_type == f"MEETING_REMINDER_{reminder_type}",
            )
            .order_by(JobRecord.created_at.desc())
            .first()
        )
        if latest_job and latest_job.status == "CANCELLED":
            logger.info("Meeting reminder skipped — job cancelled: %s %s", meeting_id, reminder_type)
            return {"skipped": True, "reason": "cancelled"}

        message = _reminder_message(meeting, reminder_type)
        audience = (
            meeting.audience_track.value
            if hasattr(meeting.audience_track, "value")
            else str(getattr(meeting, "audience_track", None) or "BOTH")
        )
        phones = meeting_recipient_phones(db, audience)
        sent = 0
        for phone in phones:
            try:
                send_sms_sync(phone, message)
                db.add(
                    SmsLog(
                        message_type=f"MEETING_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="SENT",
                        sent_at=datetime.utcnow(),
                    )
                )
                sent += 1
            except Exception as e:
                logger.error("Meeting reminder failed to %s: %s", phone, e)
                db.add(
                    SmsLog(
                        message_type=f"MEETING_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="FAILED",
                        sent_at=datetime.utcnow(),
                    )
                )

        if latest_job and latest_job.status == "WAITING":
            latest_job.status = "COMPLETED"
        db.commit()
        logger.info(
            "Meeting reminder %s for %s sent to %s/%s parents",
            reminder_type,
            meeting_id,
            sent,
            len(phones),
        )
        return {"sent": sent, "total": len(phones)}
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def send_dues_announcement(self, dues_config_id: str):
    """Instant SMS when a new dues configuration is published (personalized by ward names)."""
    db = SessionLocal()
    try:
        sent = send_dues_sms_for_config(db, dues_config_id, "NEW")
        return {"sent": sent}
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def send_dues_reminder(self, dues_config_id: str, reminder_type: str):
    """
    Personalized outstanding-dues SMS (D3 / D1 / OVERDUE).
    One message per parent phone listing every owing ward by name + amount.
    """
    db = SessionLocal()
    try:
        sent = send_dues_sms_for_config(db, dues_config_id, reminder_type)
        return {"sent": sent, "reminder_type": reminder_type}
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

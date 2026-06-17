import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.meeting import Meeting
from app.models.sms_log import SmsLog
from app.services.sms import send_sms_sync
from app.services.parent_directory import meeting_recipient_phones
from app.services.dues_sms import send_dues_sms_for_config
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def send_meeting_reminder(self, meeting_id: str, reminder_type: str):
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting or meeting.status != "SCHEDULED":
            return
        message = (
            f"PTA Meeting Reminder: {meeting.title} on {meeting.date.strftime('%d %b %Y')} at {meeting.time}, "
            f"{meeting.venue}. Agenda available on the app. —SchoolPulse"
        )
        phones = meeting_recipient_phones(db)
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
            except Exception as e:
                logger.error(f"Meeting reminder failed to {phone}: {e}")
                db.add(
                    SmsLog(
                        message_type=f"MEETING_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="FAILED",
                        sent_at=datetime.utcnow(),
                    )
                )
        db.commit()
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def send_dues_announcement(self, dues_config_id: str):
    """Instant SMS when a new dues configuration is published."""
    db = SessionLocal()
    try:
        send_dues_sms_for_config(db, dues_config_id, "NEW")
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def send_dues_reminder(self, dues_config_id: str, reminder_type: str):
    db = SessionLocal()
    try:
        send_dues_sms_for_config(db, dues_config_id, reminder_type)
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

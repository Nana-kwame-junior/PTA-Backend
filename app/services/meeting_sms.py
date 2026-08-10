"""Meeting SMS: create notice, timed reminders, update/cancel notices.

Reminder timeline (Africa/Accra local time), relative to meeting START:
  D7       — 7 days before start, at 09:00
  D4       — 4 days before start, at 09:00
  D2       — 2 days before start, at 09:00
  D0       — morning of start day, at 07:00
  AT_TIME  — exactly when the meeting starts

Reminders are only scheduled if their send time is still before the meeting END
(when end_date/end_time is set). After the meeting ends, no further SMS is sent.

Celery ETA is preferred. If the broker is unavailable, reminders fall back
to mNotify scheduled SMS so parents still get notified.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.announcement import AnnouncementType
from app.models.job_record import JobRecord
from app.models.meeting import Meeting, MeetingStatus
from app.models.sms_log import SmsLog
from app.services.parent_directory import meeting_recipient_phones
from app.services.sms import schedule_sms, send_bulk_sms
from app.services.task_queue import safe_apply_async

logger = logging.getLogger(__name__)

ACCRA = ZoneInfo("Africa/Accra")


def _phones_for_meeting(db: Session, meeting: Meeting) -> list[str]:
    audience = (
        meeting.audience_track.value
        if hasattr(meeting.audience_track, "value")
        else str(getattr(meeting, "audience_track", None) or "BOTH")
    )
    return meeting_recipient_phones(db, audience)

# (reminder_type, days_before, hour, minute) — AT_TIME uses meeting clock time
DAY_REMINDERS = [
    ("D7", 7, 9, 0),
    ("D4", 4, 9, 0),
    ("D2", 2, 9, 0),
    ("D0", 0, 7, 0),
]


def _combine_date_time(d: datetime, time_raw: str | None, *, default_hour: int, default_minute: int = 0) -> datetime:
    hour, minute = default_hour, default_minute
    raw = (time_raw or "").strip()
    if raw:
        parts = raw.replace(".", ":").split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (TypeError, ValueError):
            hour, minute = default_hour, default_minute
    naive = datetime(d.year, d.month, d.day, hour, minute, 0)
    if d.tzinfo is not None:
        local = d.astimezone(ACCRA)
        naive = datetime(local.year, local.month, local.day, hour, minute, 0)
    return naive.replace(tzinfo=ACCRA)


def parse_meeting_start(meeting: Meeting) -> datetime:
    """Combine meeting.date + meeting.time into an Accra-aware datetime."""
    return _combine_date_time(meeting.date, meeting.time, default_hour=10)


def parse_meeting_end(meeting: Meeting) -> datetime | None:
    """Combine end_date + end_time; defaults end_time to 12:00 if only end_date is set."""
    if not meeting.end_date:
        return None
    return _combine_date_time(meeting.end_date, meeting.end_time, default_hour=12)


def compute_reminder_etas(meeting: Meeting) -> list[tuple[str, datetime]]:
    """Return (type, eta) pairs still in the future and before meeting end."""
    start = parse_meeting_start(meeting)
    end = parse_meeting_end(meeting)
    meeting_day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(ACCRA)
    etas: list[tuple[str, datetime]] = []

    for reminder_type, days_before, hour, minute in DAY_REMINDERS:
        eta = (meeting_day - timedelta(days=days_before)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if eta > now and (end is None or eta < end):
            etas.append((reminder_type, eta))

    if start > now and (end is None or start < end or start <= end):
        # AT_TIME at start is allowed when start == end is unlikely; always allow at start if before/at end.
        if end is None or start <= end:
            etas.append(("AT_TIME", start))

    return etas


def reminder_plan_summary(meeting: Meeting) -> dict:
    start = parse_meeting_start(meeting)
    end = parse_meeting_end(meeting)
    plan = {
        reminder_type.lower(): {"scheduled_for": eta.isoformat()}
        for reminder_type, eta in compute_reminder_etas(meeting)
    }
    return {
        "start_at": start.isoformat(),
        "end_at": end.isoformat() if end else None,
        "audience_track": (
            meeting.audience_track.value
            if hasattr(meeting.audience_track, "value")
            else str(meeting.audience_track or "BOTH")
        ),
        "reminders": plan,
        "timeline": [
            {"type": reminder_type, "scheduled_for": eta.isoformat()}
            for reminder_type, eta in compute_reminder_etas(meeting)
        ],
    }


def _reminder_message(meeting: Meeting, reminder_type: str) -> str:
    when = parse_meeting_start(meeting).strftime("%d %b %Y")
    clock = meeting.time or parse_meeting_start(meeting).strftime("%H:%M")
    labels = {
        "D7": "in 7 days",
        "D4": "in 4 days",
        "D2": "in 2 days",
        "D0": "today",
        "AT_TIME": "starting now",
    }
    label = labels.get(reminder_type, reminder_type)
    return (
        f"PTA Meeting Reminder ({label}): {meeting.title} on {when} at {clock}, "
        f"{meeting.venue}. See the Mawuli PTA app. — Mawuli SHS PTA"
    )


def _created_message(meeting: Meeting) -> str:
    when = parse_meeting_start(meeting).strftime("%d %b %Y")
    clock = meeting.time or ""
    prefix = "URGENT: " if meeting.category == AnnouncementType.URGENT else ""
    return (
        f"{prefix}PTA Meeting scheduled: {meeting.title} on {when} at {clock}, "
        f"{meeting.venue}. You will receive reminders before the meeting. — Mawuli SHS PTA"
    )


def _updated_message(meeting: Meeting, *, old_date: datetime, old_time: str | None, old_venue: str | None) -> str:
    new_when = parse_meeting_start(meeting).strftime("%d %b %Y")
    old_when = old_date.strftime("%d %b %Y") if old_date else "earlier"
    return (
        f"UPDATED PTA Meeting: {meeting.title} moved from {old_when} {old_time or ''} "
        f"to {new_when} at {meeting.time}, {meeting.venue}. "
        f"(Was: {old_venue or 'previous venue'}). — Mawuli SHS PTA"
    )


def _cancelled_message(meeting: Meeting, reason: str) -> str:
    when = parse_meeting_start(meeting).strftime("%d %b %Y")
    return (
        f"CANCELLED: The PTA meeting “{meeting.title}” on {when} at {meeting.time} "
        f"has been cancelled. Reason: {reason}. — Mawuli SHS PTA"
    )


def _log_bulk(db: Session, phones: list[str], message: str, message_type: str, status: str) -> None:
    for phone in phones:
        db.add(
            SmsLog(
                message_type=message_type,
                recipient_phone=phone,
                content=message,
                status=status,
            )
        )
    db.commit()


async def _send_bulk_logged(
    db: Session,
    phones: list[str],
    message: str,
    message_type: str,
) -> int:
    if not phones:
        return 0
    try:
        await send_bulk_sms(phones, message)
        _log_bulk(db, phones, message, message_type, "SENT")
        return len(phones)
    except Exception as exc:
        logger.error("Bulk SMS (%s) failed: %s", message_type, exc)
        db.rollback()
        try:
            _log_bulk(db, phones, message, message_type, "FAILED")
        except Exception:
            db.rollback()
        return 0


def cancel_meeting_sms_jobs(db: Session, meeting_id: str) -> int:
    """Mark pending reminder jobs cancelled and revoke Celery tasks when possible."""
    jobs = (
        db.query(JobRecord)
        .filter(
            JobRecord.reference_id == meeting_id,
            JobRecord.status.in_(["WAITING", "SCHEDULED", "PENDING"]),
        )
        .all()
    )
    revoked = 0
    try:
        from app.workers.celery_app import celery_app
    except Exception:
        celery_app = None

    for job in jobs:
        job.status = "CANCELLED"
        if celery_app and job.job_id and not str(job.job_id).startswith("mnotify:"):
            try:
                celery_app.control.revoke(job.job_id, terminate=False)
                revoked += 1
            except Exception as exc:
                logger.warning("Could not revoke Celery job %s: %s", job.job_id, exc)
    db.commit()
    logger.info("Cancelled %s meeting SMS job(s) for %s (revoked=%s)", len(jobs), meeting_id, revoked)
    return len(jobs)


def _enqueue_celery_reminder(meeting_id: str, reminder_type: str, eta: datetime):
    from app.workers.sms_tasks import send_meeting_reminder

    # Celery with enable_utc expects aware datetimes
    return safe_apply_async(
        send_meeting_reminder,
        args=[meeting_id, reminder_type],
        eta=eta,
    )


async def schedule_meeting_reminders(db: Session, meeting: Meeting) -> dict:
    """Schedule all future reminders for a SCHEDULED meeting. Idempotent after cancel."""
    if meeting.status != MeetingStatus.SCHEDULED:
        return {}
    if not meeting.is_active:
        return {}

    phones = _phones_for_meeting(db, meeting)
    if not phones:
        logger.warning("No SMS recipients for meeting reminders %s", meeting.id)
        return {}

    plan: dict = {}
    etas = compute_reminder_etas(meeting)

    for reminder_type, eta in etas:
        message = _reminder_message(meeting, reminder_type)
        celery_result = _enqueue_celery_reminder(str(meeting.id), reminder_type, eta)
        used_mnotify = False

        if celery_result is None:
            # Broker down — schedule via mNotify if configured
            if settings.mnotify_api_key:
                schedule_str = eta.astimezone(ACCRA).strftime("%Y-%m-%d %H:%M")
                try:
                    await schedule_sms(phones, message, schedule_str)
                    used_mnotify = True
                    _log_bulk(db, phones, message, f"MEETING_REMINDER_{reminder_type}", "SCHEDULED")
                except Exception as exc:
                    logger.error("mNotify schedule failed (%s): %s", reminder_type, exc)
                    db.rollback()
                    continue
            else:
                logger.warning(
                    "Skipped reminder %s for %s — no Celery broker and no mNotify key",
                    reminder_type,
                    meeting.id,
                )
                continue

        job_id = None
        if celery_result is not None:
            job_id = getattr(celery_result, "id", None) or str(celery_result)
        elif used_mnotify:
            job_id = f"mnotify:{reminder_type}:{eta.isoformat()}"

        db.add(
            JobRecord(
                job_id=job_id,
                job_type=f"MEETING_REMINDER_{reminder_type}",
                reference_id=str(meeting.id),
                scheduled_for=eta.replace(tzinfo=None) if eta.tzinfo else eta,
                status="WAITING",
            )
        )
        db.commit()
        plan[reminder_type.lower()] = {"scheduled_for": eta.isoformat(), "via": "celery" if celery_result else "mnotify"}
        logger.info(
            "Scheduled meeting %s reminder %s for %s via %s",
            meeting.id,
            reminder_type,
            eta.isoformat(),
            "celery" if celery_result else "mnotify",
        )

    return plan


async def send_meeting_created_notice(db: Session, meeting: Meeting) -> int:
    if not settings.mnotify_api_key:
        logger.info("mNotify not configured — meeting created SMS skipped")
        return 0
    if meeting.status != MeetingStatus.SCHEDULED:
        return 0
    phones = _phones_for_meeting(db, meeting)
    if not phones:
        logger.warning("No SMS recipients for new meeting %s", meeting.id)
        return 0
    return await _send_bulk_logged(db, phones, _created_message(meeting), "MEETING_CREATED")


async def send_meeting_updated_notice(
    db: Session,
    meeting: Meeting,
    *,
    old_date: datetime,
    old_time: Optional[str],
    old_venue: Optional[str],
) -> int:
    if not settings.mnotify_api_key:
        logger.info("mNotify not configured — meeting update SMS skipped")
        return 0
    phones = _phones_for_meeting(db, meeting)
    if not phones:
        return 0
    message = _updated_message(meeting, old_date=old_date, old_time=old_time, old_venue=old_venue)
    return await _send_bulk_logged(db, phones, message, "MEETING_UPDATED")


async def send_meeting_cancelled_notice(db: Session, meeting: Meeting, reason: str) -> int:
    if not settings.mnotify_api_key:
        return 0
    phones = _phones_for_meeting(db, meeting)
    if not phones:
        return 0
    return await _send_bulk_logged(db, phones, _cancelled_message(meeting, reason), "MEETING_CANCELLED")


async def meeting_sms_on_create(db: Session, meeting: Meeting) -> dict:
    sent = await send_meeting_created_notice(db, meeting)
    plan = await schedule_meeting_reminders(db, meeting)
    return {"created_sms_recipients": sent, "reminders": plan}


async def meeting_sms_on_update(
    db: Session,
    meeting: Meeting,
    *,
    old_date: datetime,
    old_time: Optional[str],
    old_venue: Optional[str],
    reschedule: bool,
) -> dict:
    """Notify parents of changes; if date/time changed, cancel + reschedule reminders."""
    updated = await send_meeting_updated_notice(
        db,
        meeting,
        old_date=old_date,
        old_time=old_time,
        old_venue=old_venue,
    )
    plan: dict = {}
    if reschedule and meeting.status == MeetingStatus.SCHEDULED and meeting.is_active:
        cancel_meeting_sms_jobs(db, str(meeting.id))
        plan = await schedule_meeting_reminders(db, meeting)
    return {"updated_sms_recipients": updated, "reminders": plan}


async def meeting_sms_on_cancel(db: Session, meeting: Meeting, reason: str) -> dict:
    cancel_meeting_sms_jobs(db, str(meeting.id))
    sent = await send_meeting_cancelled_notice(db, meeting, reason)
    return {"cancelled_sms_recipients": sent}


# Sync wrappers for FastAPI BackgroundTasks / Celery-less hosts

def meeting_sms_on_create_sync(db: Session, meeting: Meeting) -> dict:
    return asyncio.run(meeting_sms_on_create(db, meeting))


def meeting_sms_on_update_sync(
    db: Session,
    meeting: Meeting,
    *,
    old_date: datetime,
    old_time: Optional[str],
    old_venue: Optional[str],
    reschedule: bool,
) -> dict:
    return asyncio.run(
        meeting_sms_on_update(
            db,
            meeting,
            old_date=old_date,
            old_time=old_time,
            old_venue=old_venue,
            reschedule=reschedule,
        )
    )


def meeting_sms_on_cancel_sync(db: Session, meeting: Meeting, reason: str) -> dict:
    return asyncio.run(meeting_sms_on_cancel(db, meeting, reason))


def schedule_meeting_reminders_sync(db: Session, meeting: Meeting) -> dict:
    return asyncio.run(schedule_meeting_reminders(db, meeting))

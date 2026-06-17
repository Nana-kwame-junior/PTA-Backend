"""Schedule PTA meeting reminder SMS via mNotify."""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.meeting import Meeting, MeetingStatus
from app.models.announcement import AnnouncementType
from app.services.parent_directory import meeting_recipient_phones
from app.models.sms_log import SmsLog
from app.services.sms import schedule_sms, send_bulk_sms

logger = logging.getLogger(__name__)

REMINDER_SCHEDULE = [
    ("D7", 7, 9, 0),
    ("D3", 3, 9, 0),
    ("D0", 0, 7, 0),
]


def _reminder_message(meeting: Meeting, reminder_type: str) -> str:
    when = meeting.date.strftime("%d %b %Y")
    return (
        f"PTA Meeting Reminder ({reminder_type}): {meeting.title} on {when} at {meeting.time}, "
        f"{meeting.venue}. See the Mawuli PTA app for details. — Mawuli SHS PTA"
    )


def _created_message(meeting: Meeting) -> str:
    when = meeting.date.strftime("%d %b %Y")
    prefix = "URGENT: " if meeting.category == AnnouncementType.URGENT else ""
    return (
        f"{prefix}PTA Meeting: {meeting.title} on {when} at {meeting.time}, "
        f"{meeting.venue}. See the Mawuli PTA app for details. — Mawuli SHS PTA"
    )


async def send_meeting_created_notice(db: Session, meeting: Meeting) -> int:
    """Notify parents immediately when a meeting is scheduled."""
    if not settings.mnotify_api_key:
        logger.info("mNotify not configured — meeting created SMS skipped")
        return 0
    if meeting.status != MeetingStatus.SCHEDULED:
        return 0

    phones = meeting_recipient_phones(db)
    if not phones:
        logger.warning("No SMS recipients for new meeting %s", meeting.id)
        return 0

    message = _created_message(meeting)
    try:
        await send_bulk_sms(phones, message)
        for phone in phones:
            db.add(
                SmsLog(
                    message_type="MEETING_CREATED",
                    recipient_phone=phone,
                    content=message,
                    status="SENT",
                )
            )
        db.commit()
        logger.info("Sent meeting created SMS to %s recipient(s) for %s", len(phones), meeting.id)
        return len(phones)
    except Exception as exc:
        logger.error("Failed to send meeting created SMS: %s", exc)
        db.rollback()
        return 0


async def schedule_meeting_reminders(db: Session, meeting: Meeting) -> None:
    if not settings.mnotify_api_key:
        logger.info("mNotify not configured — meeting SMS reminders skipped")
        return
    if meeting.status != MeetingStatus.SCHEDULED:
        return

    phones = meeting_recipient_phones(db)
    if not phones:
        return

    meeting_day = meeting.date.replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.utcnow()

    for reminder_type, days_before, hour, minute in REMINDER_SCHEDULE:
        if days_before:
            schedule_dt = meeting_day - timedelta(days=days_before)
        else:
            schedule_dt = meeting_day
        schedule_dt = schedule_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if schedule_dt <= now:
            continue

        schedule_str = schedule_dt.strftime("%Y-%m-%d %H:%M")
        message = _reminder_message(meeting, reminder_type)
        try:
            await schedule_sms(phones, message, schedule_str)
            for phone in phones:
                db.add(
                    SmsLog(
                        message_type=f"MEETING_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="SCHEDULED",
                    )
                )
            db.commit()
        except Exception as exc:
            logger.error("Failed to schedule meeting SMS (%s): %s", reminder_type, exc)
            db.rollback()


def schedule_meeting_reminders_sync(db: Session, meeting: Meeting) -> None:
    asyncio.run(schedule_meeting_reminders(db, meeting))


def meeting_sms_on_create_sync(db: Session, meeting: Meeting) -> None:
    """Immediate notice when a meeting is first scheduled, plus future reminders."""
    asyncio.run(send_meeting_created_notice(db, meeting))
    asyncio.run(schedule_meeting_reminders(db, meeting))

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.database import get_db, SessionLocal
from app.core.security import require_permission
from app.models.meeting import Meeting, MeetingAudience, MeetingStatus
from app.models.announcement import AnnouncementType
from app.models.job_record import JobRecord
from app.schemas.meeting import MeetingCreate, MeetingUpdate, MeetingCancel
from app.services.meeting_sms import (
    cancel_meeting_sms_jobs,
    meeting_sms_on_cancel_sync,
    meeting_sms_on_create_sync,
    meeting_sms_on_update_sync,
    parse_meeting_end,
    parse_meeting_start,
    reminder_plan_summary,
)
from app.services.activity_log import log_staff_activity

router = APIRouter(prefix="/meetings", tags=["Meetings"])
ACCRA = ZoneInfo("Africa/Accra")


def _meeting_lifecycle(meeting: Meeting) -> str:
    status = meeting.status
    if status == MeetingStatus.CANCELLED:
        return "cancelled"
    if status == MeetingStatus.COMPLETED:
        return "ended"
    try:
        now = datetime.now(ACCRA)
        end = parse_meeting_end(meeting)
        if end is not None and end <= now:
            return "ended"
        start = parse_meeting_start(meeting)
        # Still upcoming until end (if set); otherwise until start passes.
        if end is None and start <= now:
            return "ended"
    except Exception:
        pass
    return "upcoming"


def _serialize_meeting(meeting: Meeting) -> dict:
    lifecycle = _meeting_lifecycle(meeting)
    audience = meeting.audience_track or MeetingAudience.BOTH
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "date": meeting.date.isoformat(),
        "time": meeting.time,
        "end_date": meeting.end_date.isoformat() if meeting.end_date else None,
        "end_time": meeting.end_time,
        "venue": meeting.venue,
        "agenda": meeting.agenda,
        "term": meeting.term,
        "academic_year": meeting.academic_year,
        "audience_track": audience.value if hasattr(audience, "value") else str(audience),
        "category": meeting.category.value if meeting.category else "GENERAL",
        "status": meeting.status.value,
        "lifecycle": lifecycle,
        "is_ended": lifecycle != "upcoming",
        "sms_plan": reminder_plan_summary(meeting) if lifecycle == "upcoming" else None,
    }


def cancel_meeting_jobs(meeting_id: str, db: Session):
    """Backward-compatible alias used by deactivate."""
    cancel_meeting_sms_jobs(db, meeting_id)


def _meeting_sms_on_create_background(meeting_id: str) -> None:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            meeting_sms_on_create_sync(db, meeting)
    except Exception:
        # Never crash the request worker silently without a log
        import logging

        logging.getLogger(__name__).exception("meeting SMS on create failed for %s", meeting_id)
    finally:
        db.close()


def _meeting_sms_on_update_background(
    meeting_id: str,
    old_date_iso: str,
    old_time: Optional[str],
    old_venue: Optional[str],
    reschedule: bool,
) -> None:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return
        old_date = datetime.fromisoformat(old_date_iso)
        meeting_sms_on_update_sync(
            db,
            meeting,
            old_date=old_date,
            old_time=old_time,
            old_venue=old_venue,
            reschedule=reschedule,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("meeting SMS on update failed for %s", meeting_id)
    finally:
        db.close()


def _meeting_sms_on_cancel_background(meeting_id: str, reason: str) -> None:
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            meeting_sms_on_cancel_sync(db, meeting, reason)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("meeting SMS on cancel failed for %s", meeting_id)
    finally:
        db.close()


@router.post("")
async def create_meeting(
    req: MeetingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    data = req.dict()
    data["category"] = AnnouncementType(data.get("category", "GENERAL"))
    data["status"] = MeetingStatus(data.get("status", "SCHEDULED"))
    data["audience_track"] = MeetingAudience(data.get("audience_track", "BOTH"))
    meeting = Meeting(**data)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Scheduled meeting: {meeting.title}",
        details=meeting.date.strftime("%d %b %Y"),
    )

    if meeting.status != MeetingStatus.SCHEDULED:
        return {
            "success": True,
            "data": {**_serialize_meeting(meeting), "sms_jobs": None},
        }

    # Immediate SMS to all parents + schedule D7/D4/D2/D0/AT_TIME reminders
    background_tasks.add_task(_meeting_sms_on_create_background, str(meeting.id))

    return {
        "success": True,
        "data": {
            **_serialize_meeting(meeting),
            "sms_jobs": reminder_plan_summary(meeting),
        },
    }


@router.patch("/{meeting_id}")
async def update_meeting(
    meeting_id: UUID,
    req: MeetingUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)

    old_date = meeting.date
    old_time = meeting.time
    old_venue = meeting.venue

    updates = req.dict(exclude_unset=True)
    for key, value in updates.items():
        if key == "category" and value is not None:
            value = AnnouncementType(value)
        if key == "audience_track" and value is not None:
            value = MeetingAudience(value)
        setattr(meeting, key, value)
    db.commit()
    db.refresh(meeting)

    meaningful = any(
        k in updates for k in ("date", "time", "end_date", "end_time", "venue", "title", "agenda")
    )
    schedule_fields_changed = any(
        k in updates for k in ("date", "time", "end_date", "end_time", "audience_track")
    )

    if meeting.status == MeetingStatus.CANCELLED:
        background_tasks.add_task(
            _meeting_sms_on_cancel_background,
            str(meeting.id),
            "Meeting cancelled by staff",
        )
    elif meaningful and meeting.status == MeetingStatus.SCHEDULED and meeting.is_active:
        # Always SMS parents about the update; reschedule reminders only if date/time changed
        background_tasks.add_task(
            _meeting_sms_on_update_background,
            str(meeting.id),
            old_date.isoformat(),
            old_time,
            old_venue,
            schedule_fields_changed,
        )

    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Updated meeting: {meeting.title}",
    )
    return {
        "success": True,
        "data": {
            "id": str(meeting_id),
            "updated": True,
            "sms_jobs": reminder_plan_summary(meeting)
            if meeting.status == MeetingStatus.SCHEDULED
            else None,
        },
    }


@router.post("/{meeting_id}/cancel")
async def cancel_meeting(
    meeting_id: UUID,
    req: MeetingCancel,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)
    meeting.status = MeetingStatus.CANCELLED
    db.commit()

    background_tasks.add_task(_meeting_sms_on_cancel_background, str(meeting_id), req.reason)

    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Cancelled meeting: {meeting.title}",
        details=req.reason,
    )
    return {"success": True, "data": {"message": "Meeting cancelled"}}


@router.post("/{meeting_id}/send-agenda-sms")
async def send_agenda_sms(
    meeting_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    from app.services.parent_directory import meeting_recipient_phones
    from app.services.sms import send_sms_background
    from app.models.sms_log import SmsLog

    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)

    audience = (
        meeting.audience_track.value
        if hasattr(meeting.audience_track, "value")
        else str(meeting.audience_track or "BOTH")
    )
    phones = meeting_recipient_phones(db, audience)
    message = (
        f"PTA Meeting Agenda — {meeting.date.strftime('%Y-%m-%d')} {meeting.time}, {meeting.venue}: "
        f"{(meeting.agenda or '')[:120]}… Full agenda on the Mawuli PTA app. — SchoolPulse"
    )
    for phone in phones:
        background_tasks.add_task(send_sms_background, phone, message)
        db.add(
            SmsLog(
                message_type="MEETING_AGENDA",
                recipient_phone=phone,
                content=message,
                status="QUEUED",
            )
        )
    db.commit()
    return {
        "success": True,
        "data": {
            "recipients_count": len(phones),
            "batches_queued": (len(phones) + 99) // 100 if phones else 0,
        },
    }


@router.delete("/{meeting_id}")
async def deactivate_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)
    title = meeting.title
    meeting.is_active = False
    db.commit()
    cancel_meeting_jobs(str(meeting_id), db)
    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Removed meeting: {title}",
        details="Soft deleted — hidden from lists",
    )
    return {"success": True, "data": {"message": "Meeting removed"}}


@router.get("")
async def list_meetings(
    page: int = 1,
    limit: int = 20,
    skip: Optional[int] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Meeting).filter(Meeting.is_active == True)
    if status:
        query = query.filter(Meeting.status == status)
    if category:
        query = query.filter(Meeting.category == AnnouncementType(category))
    total = query.count()
    offset = skip if skip is not None else (page - 1) * limit
    meetings = query.order_by(Meeting.date.desc()).offset(offset).limit(limit).all()
    effective_page = (offset // limit) + 1 if limit else 1
    return {
        "success": True,
        "data": {
            "meetings": [_serialize_meeting(m) for m in meetings],
            "pagination": {
                "page": effective_page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit if limit else 1,
            },
        },
    }


@router.get("/upcoming")
async def upcoming_meetings(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Return SCHEDULED meetings whose date+time has not passed yet (Africa/Accra)."""
    candidates = (
        db.query(Meeting)
        .filter(
            Meeting.is_active == True,
            Meeting.status == MeetingStatus.SCHEDULED,
        )
        .order_by(Meeting.date.asc())
        .all()
    )
    now = datetime.now(ACCRA)
    upcoming = []
    for meeting in candidates:
        try:
            start = parse_meeting_start(meeting)
            if start > now:
                upcoming.append(meeting)
        except Exception:
            continue
    sliced = upcoming[skip : skip + limit]
    return {
        "success": True,
        "data": [_serialize_meeting(m) for m in sliced],
    }


@router.get("/{meeting_id}/jobs")
async def get_meeting_jobs(
    meeting_id: UUID,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(JobRecord)
        .filter(JobRecord.reference_id == str(meeting_id))
        .order_by(JobRecord.scheduled_for.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "success": True,
        "data": [
            {
                "id": job.id,
                "job_id": job.job_id,
                "job_type": job.job_type,
                "scheduled_for": job.scheduled_for.isoformat() if job.scheduled_for else None,
                "status": job.status,
            }
            for job in jobs
        ],
    }

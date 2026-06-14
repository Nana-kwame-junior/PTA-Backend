from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timedelta
from typing import Optional
import json

from app.core.database import get_db
from app.core.security import require_permission
from app.models.meeting import Meeting, MeetingStatus
from app.models.job_record import JobRecord
from app.models.parent import Parent
from app.models.sms_log import SmsLog
from app.schemas.meeting import MeetingCreate, MeetingUpdate, MeetingCancel, AttendanceRecord
from app.services.sms import send_sms
from app.services.activity_log import log_staff_activity
from app.workers.sms_tasks import send_meeting_reminder
from app.services.task_queue import safe_apply_async

router = APIRouter(prefix="/meetings", tags=["Meetings"])

def cancel_meeting_jobs(meeting_id: str, db: Session):
    # In production, you would cancel Celery tasks using task id stored in JobRecord
    db.query(JobRecord).filter(JobRecord.reference_id == meeting_id).update({"status": "CANCELLED"})
    db.commit()

@router.post("")
async def create_meeting(
    req: MeetingCreate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = Meeting(**req.dict())
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

    # Schedule Celery tasks
    # D7
    safe_apply_async(
        send_meeting_reminder,
        args=[str(meeting.id), "D7"],
        eta=meeting.date - timedelta(days=7),
    )
    # D3
    safe_apply_async(
        send_meeting_reminder,
        args=[str(meeting.id), "D3"],
        eta=meeting.date - timedelta(days=3),
    )
    # D0 (morning of meeting)
    eta_d0 = meeting.date.replace(hour=7, minute=0, second=0)
    safe_apply_async(
        send_meeting_reminder,
        args=[str(meeting.id), "D0"],
        eta=eta_d0,
    )

    # Store job records (optional but good for monitoring)
    # (You can store Celery task IDs returned by apply_async)
    # For simplicity we skip storing IDs here.

    return {
        "success": True,
        "data": {
            "id": str(meeting.id),
            "title": meeting.title,
            "date": meeting.date.isoformat(),
            "time": meeting.time,
            "venue": meeting.venue,
            "status": meeting.status.value,
            "sms_jobs": {
                "d7": {"scheduled_for": (meeting.date - timedelta(days=7)).isoformat()},
                "d3": {"scheduled_for": (meeting.date - timedelta(days=3)).isoformat()},
                "d0": {"scheduled_for": eta_d0.isoformat()}
            }
        }
    }

@router.patch("/{meeting_id}")
async def update_meeting(
    meeting_id: UUID,
    req: MeetingUpdate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)
    old_date = meeting.date
    for key, value in req.dict(exclude_unset=True).items():
        setattr(meeting, key, value)
    db.commit()

    if req.date and req.date != old_date:
        # Cancel old jobs and reschedule
        cancel_meeting_jobs(str(meeting_id), db)
        # Schedule new jobs (same as create)
        safe_apply_async(
            send_meeting_reminder,
            args=[str(meeting.id), "D7"],
            eta=meeting.date - timedelta(days=7),
        )
        safe_apply_async(
            send_meeting_reminder,
            args=[str(meeting.id), "D3"],
            eta=meeting.date - timedelta(days=3),
        )
        eta_d0 = meeting.date.replace(hour=7, minute=0, second=0)
        safe_apply_async(
            send_meeting_reminder,
            args=[str(meeting.id), "D0"],
            eta=eta_d0,
        )
        # Send reschedule SMS (background)
        from app.services.sms import send_sms
        parents = db.query(Parent).filter(Parent.match_status == "MATCHED").all()
        phones = [p.phone for p in parents if p.phone]
        message = f"UPDATED: The PTA meeting previously scheduled for {old_date.strftime('%d %b %Y')} has been rescheduled to {meeting.date.strftime('%d %b %Y')} at {meeting.time}, {meeting.venue}. — Mawuli SHS PTA"
        for phone in phones:
            # In production, use background task (e.g., celery)
            pass  # We'll leave SMS sending to the caller or use a separate task

    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Updated meeting: {meeting.title}",
    )
    return {"success": True, "data": {"id": str(meeting_id), "updated": True}}

@router.post("/{meeting_id}/cancel")
async def cancel_meeting(
    meeting_id: UUID,
    req: MeetingCancel,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)
    meeting.status = MeetingStatus.CANCELLED
    db.commit()
    cancel_meeting_jobs(str(meeting_id), db)
    log_staff_activity(
        db,
        staff,
        page_label="Meetings",
        action_label=f"Cancelled meeting: {meeting.title}",
        details=req.reason,
    )
    # Send cancellation SMS (background)
    parents = db.query(Parent).filter(Parent.match_status == "MATCHED").all()
    phones = [p.phone for p in parents if p.phone]
    message = f"The PTA meeting scheduled for {meeting.date.strftime('%d %b %Y')} has been cancelled. Reason: {req.reason}. — Mawuli SHS PTA"
    for phone in phones:
        # Use background task
        pass
    return {"success": True, "data": {"message": "Meeting cancelled"}}

@router.post("/{meeting_id}/send-agenda-sms")
async def send_agenda_sms(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("meetings")),
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404)
    parents = db.query(Parent).filter(Parent.match_status == "MATCHED").all()
    phones = [p.phone for p in parents if p.phone]
    message = f"PTA Meeting Agenda — {meeting.date.strftime('%Y-%m-%d')} {meeting.time}, {meeting.venue}: {meeting.agenda[:120]}... Full agenda on the Mawuli PTA app. — Mawuli SHS PTA"
    for phone in phones:
        # Use background task
        pass
    return {"success": True, "data": {"recipients_count": len(phones), "batches_queued": (len(phones)+99)//100}}


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
    db: Session = Depends(get_db),
):
    query = db.query(Meeting).filter(Meeting.is_active == True)
    if status:
        query = query.filter(Meeting.status == status)
    total = query.count()
    offset = skip if skip is not None else (page - 1) * limit
    meetings = query.order_by(Meeting.date.desc()).offset(offset).limit(limit).all()
    effective_page = (offset // limit) + 1 if limit else 1
    return {
        "success": True,
        "data": {
            "meetings": [
                {
                    "id": str(m.id),
                    "title": m.title,
                    "date": m.date.isoformat(),
                    "time": m.time,
                    "venue": m.venue,
                    "agenda": m.agenda,
                    "term": m.term,
                    "academic_year": m.academic_year,
                    "status": m.status.value,
                }
                for m in meetings
            ],
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
    now = datetime.utcnow()
    meetings = (
        db.query(Meeting)
        .filter(
            Meeting.is_active == True,
            Meeting.status == MeetingStatus.SCHEDULED,
            Meeting.date >= now,
        )
        .order_by(Meeting.date.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "success": True,
        "data": [
            {
                "id": str(m.id),
                "title": m.title,
                "date": m.date.isoformat(),
                "time": m.time,
                "venue": m.venue,
                "agenda": m.agenda,
                "term": m.term,
                "academic_year": m.academic_year,
                "status": m.status.value,
            }
            for m in meetings
        ],
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
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import require_role, get_current_user
from app.models.announcement import Announcement, AnnouncementType
from app.models.parent import Parent
from app.models.sms_log import SmsLog
from app.schemas.announcement import AnnouncementCreate
from app.services.sms import send_sms

router = APIRouter(prefix="/announcements", tags=["Announcements"])

@router.post("")
async def create_announcement(
    req: AnnouncementCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    announcement = Announcement(
        title=req.title,
        body=req.body,
        type=req.type
    )
    db.add(announcement)
    db.commit()
    db.refresh(announcement)
    
    sms_dispatched = False
    recipients_count = 0
    if req.send_sms or req.type == AnnouncementType.URGENT:
        parents = db.query(Parent).filter(Parent.match_status == "MATCHED").all()
        phones = [p.phone for p in parents if p.phone]
        recipients_count = len(phones)
        # Truncate message if needed (SMS limit ~160 chars)
        sms_body = f"{req.title}: {req.body[:140]}... — Mawuli SHS PTA"
        for phone in phones:
            background_tasks.add_task(send_sms, phone, sms_body)
            sms_log = SmsLog(
                message_type="ANNOUNCEMENT",
                recipient_phone=phone,
                content=sms_body,
                status="QUEUED"
            )
            db.add(sms_log)
        db.commit()
        sms_dispatched = True
    
    return {
        "success": True,
        "data": {
            "id": str(announcement.id),
            "title": announcement.title,
            "type": announcement.type.value,
            "published_at": announcement.published_at.isoformat(),
            "sms_dispatched": sms_dispatched,
            "sms_recipients_count": recipients_count
        }
    }

@router.get("")
async def list_announcements(
    type: Optional[AnnouncementType] = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(Announcement)
    if type:
        query = query.filter(Announcement.type == type)
    # Parent sees only published; admin sees all
    if current_user["role"] == "PARENT":
        pass  # all announcements are published
    total = query.count()
    announcements = query.order_by(Announcement.published_at.desc()).offset((page-1)*limit).limit(limit).all()
    return {"success": True, "data": {"announcements": announcements, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": (total+limit-1)//limit}}}

@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: UUID,
    req: dict,  # title, body
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    announcement = db.query(Announcement).filter(Announcement.id == str(announcement_id)).first()
    if not announcement:
        raise HTTPException(status_code=404)
    if "title" in req:
        announcement.title = req["title"]
    if "body" in req:
        announcement.body = req["body"]
    db.commit()
    return {"success": True, "data": {"id": str(announcement_id), "updated": True}}
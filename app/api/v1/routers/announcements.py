from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, UploadFile
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import require_role, get_current_user
from app.models.announcement import Announcement, AnnouncementType
from app.models.parent import Parent
from app.models.sms_log import SmsLog
from app.schemas.announcement import AnnouncementCreate
from app.services.sms import send_sms_background
from app.services.activity_log import log_staff_activity
from app.services.cloudinary_upload import upload_announcement_images

router = APIRouter(prefix="/announcements", tags=["Announcements"])


def _serialize_announcement(announcement: Announcement) -> dict:
    urls = announcement.image_urls if isinstance(announcement.image_urls, list) else []
    return {
        "id": str(announcement.id),
        "title": announcement.title,
        "body": announcement.body or "",
        "type": announcement.type.value if announcement.type else AnnouncementType.GENERAL.value,
        "published_at": announcement.published_at.isoformat() if announcement.published_at else None,
        "image_urls": [str(u) for u in urls if u],
    }


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def _parse_create_payload(request: Request) -> tuple[AnnouncementCreate, list[UploadFile]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        title = str(form.get("title") or "").strip()
        body = str(form.get("body") or "").strip()
        type_raw = str(form.get("type") or "GENERAL").strip().upper()
        send_sms = _parse_bool(form.get("send_sms"))
        try:
            ann_type = AnnouncementType(type_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid announcement type") from exc
        if not title or not body:
            raise HTTPException(status_code=400, detail="Title and body are required")
        files: list[UploadFile] = []
        for key in ("images", "images[]", "image"):
            for item in form.getlist(key):
                if isinstance(item, UploadFile) and item.filename:
                    files.append(item)
        # de-dupe by object identity while preserving order
        seen: set[int] = set()
        unique_files: list[UploadFile] = []
        for f in files:
            oid = id(f)
            if oid in seen:
                continue
            seen.add(oid)
            unique_files.append(f)
        return (
            AnnouncementCreate(title=title, body=body, type=ann_type, send_sms=send_sms),
            unique_files,
        )

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    try:
        req = AnnouncementCreate(**payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid announcement payload") from exc
    return req, []


@router.post("")
async def create_announcement(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    req, files = await _parse_create_payload(request)
    image_urls = await upload_announcement_images(files) if files else []

    announcement = Announcement(
        title=req.title,
        body=req.body,
        type=req.type,
        image_urls=image_urls,
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
        sms_body = f"{req.title}: {req.body[:140]}... —SchoolPulse"
        for phone in phones:
            background_tasks.add_task(send_sms_background, phone, sms_body)
            sms_log = SmsLog(
                message_type="ANNOUNCEMENT",
                recipient_phone=phone,
                content=sms_body,
                status="QUEUED",
            )
            db.add(sms_log)
        db.commit()
        sms_dispatched = True

    log_staff_activity(
        db,
        admin,
        page_label="Announcements",
        action_label=f"Published announcement: {announcement.title}",
        details=announcement.type.value,
    )

    data = _serialize_announcement(announcement)
    data["sms_dispatched"] = sms_dispatched
    data["sms_recipients_count"] = recipients_count
    return {"success": True, "data": data}


@router.get("")
async def list_announcements(
    type: Optional[AnnouncementType] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(Announcement).filter(Announcement.is_active == True)
    if type:
        query = query.filter(Announcement.type == type)
    if current_user["role"] == "PARENT":
        pass  # all announcements are published
    total = query.count()
    announcements = (
        query.order_by(Announcement.published_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "success": True,
        "data": {
            "announcements": [_serialize_announcement(a) for a in announcements],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        },
    }


@router.patch("/{announcement_id}")
async def update_announcement(
    announcement_id: UUID,
    req: dict,  # title, body
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    announcement = db.query(Announcement).filter(Announcement.id == str(announcement_id)).first()
    if not announcement:
        raise HTTPException(status_code=404)
    if "title" in req:
        announcement.title = req["title"]
    if "body" in req:
        announcement.body = req["body"]
    db.commit()
    log_staff_activity(
        db,
        admin,
        page_label="Announcements",
        action_label=f"Updated announcement: {announcement.title}",
    )
    return {"success": True, "data": {"id": str(announcement_id), "updated": True}}


@router.delete("/{announcement_id}")
async def deactivate_announcement(
    announcement_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    announcement = db.query(Announcement).filter(Announcement.id == str(announcement_id)).first()
    if not announcement:
        raise HTTPException(status_code=404)
    title = announcement.title
    announcement.is_active = False
    db.commit()
    log_staff_activity(
        db,
        admin,
        page_label="Announcements",
        action_label=f"Removed announcement: {title}",
        details="Soft deleted",
    )
    return {"success": True, "data": {"message": "Announcement removed"}}

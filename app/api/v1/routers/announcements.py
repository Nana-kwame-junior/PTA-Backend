import json
from fastapi import APIRouter, Depends, File, HTTPException, BackgroundTasks, Request, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import require_permission, get_current_user
from app.models.announcement import Announcement, AnnouncementType
from app.models.parent import Parent
from app.models.sms_log import SmsLog
from app.schemas.announcement import AnnouncementCreate
from app.services.sms import send_sms_background
from app.services.activity_log import log_staff_activity
from app.services.cloudinary_upload import MAX_IMAGES, upload_announcement_images

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


def _is_upload_file(item) -> bool:
    return bool(getattr(item, "filename", None)) and hasattr(item, "read")


def _collect_upload_files(form) -> list[UploadFile]:
    files: list[UploadFile] = []
    for key in ("images", "images[]", "image"):
        for item in form.getlist(key):
            if _is_upload_file(item):
                files.append(item)
    seen: set[int] = set()
    unique: list[UploadFile] = []
    for f in files:
        oid = id(f)
        if oid in seen:
            continue
        seen.add(oid)
        unique.append(f)
    return unique


def _normalize_image_urls(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip().startswith("https://")]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(u).strip() for u in parsed if str(u).strip().startswith("https://")]


def _set_image_urls(announcement: Announcement, urls: list[str]) -> None:
    if len(urls) > MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"An announcement can have at most {MAX_IMAGES} images.",
        )
    announcement.image_urls = urls
    flag_modified(announcement, "image_urls")


def _parse_keep_urls(raw) -> Optional[list[str]]:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="keep_image_urls must be a JSON array") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="keep_image_urls must be a JSON array")
    return [str(u).strip() for u in parsed if str(u).strip()]


def _merge_image_urls(
    existing: list[str],
    *,
    keep_urls: Optional[list[str]],
    new_urls: list[str],
) -> list[str]:
    if keep_urls is None and not new_urls:
        return existing
    existing_set = set(existing)
    kept = [u for u in (keep_urls if keep_urls is not None else existing) if u in existing_set]
    merged = kept + new_urls
    if len(merged) > MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"An announcement can have at most {MAX_IMAGES} images.",
        )
    return merged


async def _parse_create_payload(request: Request) -> tuple[AnnouncementCreate, list[UploadFile]]:
    content_type = (request.headers.get("content-type") or "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        title = str(form.get("title") or "").strip()
        body = str(form.get("body") or "").strip()
        type_raw = str(form.get("type") or "GENERAL").strip().upper()
        send_sms = _parse_bool(form.get("send_sms"))
        image_urls = _normalize_image_urls(form.get("image_urls"))
        try:
            ann_type = AnnouncementType(type_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid announcement type") from exc
        if not title or not body:
            raise HTTPException(status_code=400, detail="Title and body are required")
        return (
            AnnouncementCreate(
                title=title,
                body=body,
                type=ann_type,
                send_sms=send_sms,
                image_urls=image_urls,
            ),
            _collect_upload_files(form),
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


async def _parse_update_payload(
    request: Request,
) -> tuple[dict, list[UploadFile], Optional[list[str]]]:
    """Return field updates, new image files, and optional keep_image_urls list."""
    content_type = (request.headers.get("content-type") or "").lower()
    fields: dict = {}
    if "multipart/form-data" in content_type:
        form = await request.form()
        if "title" in form:
            title = str(form.get("title") or "").strip()
            if not title:
                raise HTTPException(status_code=400, detail="Title cannot be empty")
            fields["title"] = title
        if "body" in form:
            body = str(form.get("body") or "").strip()
            if not body:
                raise HTTPException(status_code=400, detail="Body cannot be empty")
            fields["body"] = body
        if "type" in form and form.get("type") is not None and str(form.get("type")).strip() != "":
            type_raw = str(form.get("type")).strip().upper()
            try:
                fields["type"] = AnnouncementType(type_raw)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid announcement type") from exc
        keep_urls = _parse_keep_urls(form.get("keep_image_urls")) if "keep_image_urls" in form else None
        return fields, _collect_upload_files(form), keep_urls

    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid update payload")
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        fields["title"] = title
    if "body" in payload:
        body = str(payload.get("body") or "").strip()
        if not body:
            raise HTTPException(status_code=400, detail="Body cannot be empty")
        fields["body"] = body
    if "type" in payload and payload.get("type") is not None:
        try:
            fields["type"] = AnnouncementType(str(payload["type"]).strip().upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid announcement type") from exc
    keep_urls = _parse_keep_urls(payload.get("keep_image_urls")) if "keep_image_urls" in payload else None
    if "image_urls" in payload:
        # Full replace list from client (preferred path after /images upload).
        fields["image_urls"] = _normalize_image_urls(payload.get("image_urls"))
        keep_urls = None
    return fields, [], keep_urls


@router.post("/images")
async def upload_announcement_image_files(
    images: list[UploadFile] = File(...),
    staff=Depends(require_permission("announcements")),
):
    """Upload announcement images to Cloudinary and return HTTPS URLs."""
    files = [f for f in images if _is_upload_file(f)]
    if not files:
        raise HTTPException(status_code=400, detail="No image files provided")
    urls = await upload_announcement_images(files)
    return {"success": True, "data": {"image_urls": urls}}


@router.post("")
async def create_announcement(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("announcements")),
):
    req, files = await _parse_create_payload(request)
    uploaded = await upload_announcement_images(files) if files else []
    image_urls = list(req.image_urls or []) + uploaded
    if len(image_urls) > MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"An announcement can have at most {MAX_IMAGES} images.",
        )

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
        staff,
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
    request: Request,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("announcements")),
):
    announcement = db.query(Announcement).filter(Announcement.id == str(announcement_id)).first()
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")

    fields, files, keep_urls = await _parse_update_payload(request)
    if not fields and not files and keep_urls is None:
        raise HTTPException(status_code=400, detail="No changes provided")

    if "title" in fields:
        announcement.title = fields["title"]
    if "body" in fields:
        announcement.body = fields["body"]
    if "type" in fields:
        announcement.type = fields["type"]

    existing = [str(u) for u in (announcement.image_urls or []) if u]
    if "image_urls" in fields:
        _set_image_urls(announcement, fields["image_urls"])
    else:
        new_urls = await upload_announcement_images(files) if files else []
        if keep_urls is not None or new_urls:
            _set_image_urls(
                announcement,
                _merge_image_urls(
                    existing,
                    keep_urls=keep_urls,
                    new_urls=new_urls,
                ),
            )

    db.commit()
    db.refresh(announcement)
    log_staff_activity(
        db,
        staff,
        page_label="Announcements",
        action_label=f"Updated announcement: {announcement.title}",
    )
    return {"success": True, "data": _serialize_announcement(announcement)}


@router.delete("/{announcement_id}")
async def deactivate_announcement(
    announcement_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("announcements")),
):
    announcement = db.query(Announcement).filter(Announcement.id == str(announcement_id)).first()
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    title = announcement.title
    announcement.is_active = False
    db.commit()
    log_staff_activity(
        db,
        staff,
        page_label="Announcements",
        action_label=f"Removed announcement: {title}",
        details="Soft deleted",
    )
    return {"success": True, "data": {"message": "Announcement removed"}}

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
import secrets

from app.core.database import get_db
from app.core.security import require_role, hash_password, verify_password, get_current_user
from app.models.user import User, UserRole
from app.models.staff_activity import StaffActivityLog
from app.schemas.staff import StaffCreate, StaffUpdate
from app.services.email import send_temporary_password_email
from app.services.activity_log import log_staff_activity
from app.services.permissions import sanitize_permissions, resolve_user_permissions, ALL_STAFF_PERMISSIONS
from app.services.staff_job_titles import (
    DEFAULT_PERMISSIONS_BY_JOB_TITLE,
    STAFF_JOB_TITLES,
    display_job_title,
    sanitize_job_title,
    suggested_permissions_for_job_title,
)

router = APIRouter(prefix="/admin/staff", tags=["Staff Management"])


def _staff_payload(
    user: User,
    *,
    email_sent: bool | None = None,
    temporary_password: str | None = None,
) -> dict:
    data = {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "job_title": display_job_title(user),
        "is_active": user.is_active,
        "is_first_login": user.is_first_login,
        "permissions": resolve_user_permissions(user),
    }
    if email_sent is not None:
        data["email_sent"] = email_sent
    if temporary_password:
        data["temporary_password"] = temporary_password
    return data


@router.get("/job-titles")
async def list_job_titles(admin=Depends(require_role("ADMIN"))):
    return {
        "success": True,
        "data": {
            "job_titles": STAFF_JOB_TITLES,
            "permission_presets": DEFAULT_PERMISSIONS_BY_JOB_TITLE,
        },
    }


@router.get("/permissions")
async def list_assignable_permissions(admin=Depends(require_role("ADMIN"))):
    return {"success": True, "data": {"permissions": ALL_STAFF_PERMISSIONS}}


@router.get("/activity")
async def list_activity_logs(
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    query = db.query(StaffActivityLog).order_by(StaffActivityLog.created_at.desc())
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "success": True,
        "data": {
            "logs": [
                {
                    "id": r.id,
                    "user_name": r.user_name,
                    "user_email": r.user_email,
                    "page_label": r.page_label,
                    "action_label": r.action_label,
                    "details": r.details,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        },
    }


@router.post("")
async def create_staff(
    req: StaffCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    job_title = sanitize_job_title(req.job_title)
    if req.permissions is None:
        perms = sanitize_permissions(suggested_permissions_for_job_title(job_title))
    else:
        perms = sanitize_permissions(req.permissions)

    temp_password = secrets.token_urlsafe(12)

    new_staff = User(
        name=req.name,
        email=req.email,
        hashed_password=hash_password(temp_password),
        role=UserRole(req.role),
        job_title=job_title,
        is_active=True,
        is_first_login=True,
        permissions=perms,
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)

    email_sent = send_temporary_password_email(req.email, temp_password, new_staff.name)
    log_staff_activity(
        db,
        admin,
        page_label="Staff & Roles",
        action_label=f"Created staff account for {new_staff.name}",
        details=f"{new_staff.email} · {job_title}",
    )

    return {
        "success": True,
        "data": _staff_payload(
            new_staff,
            email_sent=email_sent,
            temporary_password=None if email_sent else temp_password,
        ),
    }


@router.get("")
async def list_staff(
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.FINANCIAL_STAFF])).all()
    return {"success": True, "data": {"staff": [_staff_payload(u) for u in staff]}}


@router.patch("/{staff_id}")
async def update_staff(
    staff_id: UUID,
    req: StaffUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)
    if staff.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot modify admin account here")
    if req.name is not None:
        staff.name = req.name
    if req.email is not None:
        existing = db.query(User).filter(User.email == req.email, User.id != str(staff_id)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already used")
        staff.email = req.email
    if req.job_title is not None:
        staff.job_title = sanitize_job_title(req.job_title)
    if req.permissions is not None:
        staff.permissions = sanitize_permissions(req.permissions)
    db.commit()
    log_staff_activity(
        db,
        admin,
        page_label="Staff & Roles",
        action_label=f"Updated access for {staff.name}",
        details=display_job_title(staff),
    )
    return {"success": True, "data": _staff_payload(staff)}


@router.post("/{staff_id}/deactivate")
async def deactivate_staff(
    staff_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)
    if staff.role == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Cannot deactivate admin")
    staff.is_active = False
    db.commit()
    log_staff_activity(
        db,
        admin,
        page_label="Staff & Roles",
        action_label=f"Deactivated {staff.name}",
        details=staff.email,
    )
    return {"success": True, "data": {"message": "Staff deactivated"}}


@router.post("/{staff_id}/activate")
async def activate_staff(
    staff_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)
    staff.is_active = True
    db.commit()
    log_staff_activity(
        db,
        admin,
        page_label="Staff & Roles",
        action_label=f"Reactivated {staff.name}",
        details=staff.email,
    )
    return {"success": True, "data": {"message": "Staff reactivated"}}


@router.post("/{staff_id}/reset-password")
async def reset_staff_password(
    staff_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)

    temp_password = secrets.token_urlsafe(12)
    staff.hashed_password = hash_password(temp_password)
    staff.is_first_login = True
    db.commit()

    email_sent = send_temporary_password_email(staff.email, temp_password, staff.name)
    log_staff_activity(
        db,
        admin,
        page_label="Staff & Roles",
        action_label=f"Reset password for {staff.name}",
        details=staff.email,
    )

    return {
        "success": True,
        "data": {
            "message": (
                "Password reset email sent"
                if email_sent
                else "Password reset — share the temporary password manually"
            ),
            "email_sent": email_sent,
            "temporary_password": None if email_sent else temp_password,
        },
    }


@router.post("/change-password")
async def change_password(
    old_password: str,
    new_password: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("ADMIN", "FINANCIAL_STAFF"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user or not verify_password(old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect current password")
    user.hashed_password = hash_password(new_password)
    user.is_first_login = False
    db.commit()
    log_staff_activity(
        db,
        current_user,
        page_label="Account",
        action_label="Changed account password",
    )
    return {"success": True, "data": {"message": "Password updated"}}

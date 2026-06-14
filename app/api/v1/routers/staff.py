from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
import secrets

from app.core.database import get_db
from app.core.security import require_role, hash_password, verify_password
from app.models.user import User, UserRole
from app.schemas.staff import StaffCreate
from app.services.email import send_temporary_password_email

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
        "is_active": user.is_active,
        "is_first_login": user.is_first_login,
    }
    if email_sent is not None:
        data["email_sent"] = email_sent
    if temporary_password:
        data["temporary_password"] = temporary_password
    return data


@router.post("")
async def create_staff(
    req: StaffCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already exists")

    temp_password = secrets.token_urlsafe(12)
    hashed = hash_password(temp_password)

    new_staff = User(
        name=req.name,
        email=req.email,
        hashed_password=hashed,
        role=UserRole(req.role),
        is_active=True,
        is_first_login=True,
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)

    email_sent = send_temporary_password_email(req.email, temp_password, new_staff.name)

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
    return {
        "success": True,
        "data": {"staff": [_staff_payload(u) for u in staff]},
    }


@router.patch("/{staff_id}")
async def update_staff(
    staff_id: UUID,
    req: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)
    if "name" in req:
        staff.name = req["name"]
    if "email" in req:
        existing = db.query(User).filter(User.email == req["email"], User.id != str(staff_id)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already used")
        staff.email = req["email"]
    if "role" in req:
        staff.role = UserRole(req["role"])
    db.commit()
    return {"success": True, "data": {"id": str(staff_id), "updated": True}}


@router.post("/{staff_id}/deactivate")
async def deactivate_staff(
    staff_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    staff = db.query(User).filter(User.id == str(staff_id)).first()
    if not staff:
        raise HTTPException(status_code=404)
    staff.is_active = False
    db.commit()
    return {"success": True, "data": {"message": "Staff deactivated"}}


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

    # Synchronous send — no BackgroundTasks (avoids ASGI crash after 200 response)
    email_sent = send_temporary_password_email(staff.email, temp_password, staff.name)

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
    current_user=Depends(require_role("FINANCIAL_STAFF")),
):
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not verify_password(old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect current password")
    user.hashed_password = hash_password(new_password)
    user.is_first_login = False
    db.commit()
    return {"success": True, "data": {"message": "Password updated"}}

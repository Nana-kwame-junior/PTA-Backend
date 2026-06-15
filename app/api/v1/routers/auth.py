from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    hash_password,
    get_current_user,
    require_registration_token,
)
from app.services.sms import send_verification_code_sms
from app.services.sms_errors import SmsDeliveryError
from app.services.otp_store import store_otp, fetch_otp, delete_otp
from app.services.matching import find_matches
from app.services.student_validation import validate_student_fields
from app.models.parent import Parent, MatchStatus
from app.models.user import User
from app.services.permissions import resolve_user_permissions
from app.models.student import Student
from app.models.pending_match import PendingMatch
from app.models.parent_student_link import ParentStudentLink
from app.models.class_level import ClassLevel
from app.schemas.auth import (
    WebLoginRequest,
    OtpRequest,
    OtpVerifyRequest,
    ParentRegisterRequest,
    SelectCandidateRequest,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    ResetPasswordTokenRequest,
    StaffProfileUpdate,
)
import random
import json
import secrets
from app.core.config import settings
from datetime import timedelta, datetime
from app.services.email import send_password_reset_email
from app.services.activity_log import log_staff_activity
from app.core.middleware import hash_reset_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _parent_profile_complete(parent: Parent) -> bool:
    return bool((parent.full_name or "").strip())


def _otp_flow_for_parent(parent: Parent | None) -> str:
    if not parent:
        return "REGISTER"
    if parent.match_status == MatchStatus.MATCHED or _parent_profile_complete(parent):
        return "LOGIN"
    return "REGISTER"


@router.get("/parent/class-levels")
async def parent_registration_class_levels(db: Session = Depends(get_db)):
    """Public list of PTA class levels for parent registration (no auth)."""
    rows = (
        db.query(ClassLevel)
        .filter(ClassLevel.is_active == True)
        .order_by(ClassLevel.sequence.asc())
        .all()
    )
    return {
        "success": True,
        "data": {
            "levels": [
                {
                    "name": row.name,
                    "requires_index_number": row.requires_index_number,
                    "requires_stream": row.requires_stream,
                }
                for row in rows
            ]
        },
    }


def _serialize_candidates(matches):
    return [
        {
            "student_id": str(m["student"].id),
            "full_name": m["student"].full_name,
            "index_number": m["student"].index_number,
            "score": round(m["score"] / 100, 2),
        }
        for m in matches
    ]


def _linked_students(db: Session, parent_id: str):
    links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent_id).all()
    students = []
    for link in links:
        student = db.query(Student).filter(Student.id == link.student_id).first()
        if student:
            students.append(
                {
                    "id": student.id,
                    "full_name": student.full_name,
                    "index_number": student.index_number,
                    "gender": student.gender,
                    "form": student.form,
                    "stream": student.stream,
                }
            )
    return students


def _parent_tokens(db: Session, parent: Parent):
    links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent.id).all()
    matched_ids = [link.student_id for link in links]
    access_token = create_access_token(
        {
            "sub": parent.id,
            "role": "PARENT",
            "phone": parent.phone,
            "matched_student_ids": matched_ids,
            "match_status": parent.match_status.value,
        }
    )
    refresh_token = create_refresh_token({"sub": parent.id, "role": "PARENT"})
    return access_token, refresh_token, matched_ids


@router.post("/web/login")
async def web_login(req: WebLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email, User.is_active == True).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    refresh_token = create_refresh_token({"sub": user.id, "role": user.role.value})
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "is_first_login": user.is_first_login,
                "permissions": resolve_user_permissions(user),
            },
        },
    }


@router.post("/parent/request-otp")
async def request_otp(req: OtpRequest, db: Session = Depends(get_db)):
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    flow = _otp_flow_for_parent(parent)

    if req.purpose == "login" and flow == "REGISTER":
        raise HTTPException(
            status_code=404,
            detail="No registered account for this number. Please create an account first.",
        )
    if req.purpose == "register" and flow == "LOGIN":
        raise HTTPException(
            status_code=409,
            detail="This number is already registered. Please sign in instead.",
        )

    code = str(random.randint(100000, 999999))
    store_otp(db, phone, code)
    try:
        await send_verification_code_sms(phone, code)
    except SmsDeliveryError as exc:
        delete_otp(db, phone)
        raise HTTPException(status_code=exc.status_code, detail=exc.user_message) from exc
    except Exception as exc:
        delete_otp(db, phone)
        raise HTTPException(
            status_code=503,
            detail="Could not send verification code by SMS. Try again shortly.",
        ) from exc
    return {
        "success": True,
        "data": {
            "message": f"Verification code sent to {phone}",
            "flow": flow,
            "expires_in_seconds": settings.otp_expiry_seconds,
            **({"dry_run": True} if settings.sms_dry_run else {}),
        },
    }


@router.post("/parent/verify-otp")
async def verify_otp(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    phone = req.phone
    stored_otp = fetch_otp(db, phone)
    if not stored_otp or stored_otp != req.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    delete_otp(db, phone)

    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if parent:
        if parent.match_status == MatchStatus.MATCHED or _parent_profile_complete(parent):
            access_token, refresh_token, _ = _parent_tokens(db, parent)
            return {
                "success": True,
                "data": {
                    "flow": "LOGIN",
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "parent": {
                        "id": parent.id,
                        "full_name": parent.full_name,
                        "phone": parent.phone,
                        "match_status": parent.match_status.value,
                        "linked_students": _linked_students(db, parent.id),
                    },
                },
            }
        reg_token = create_access_token(
            {"sub": parent.id, "role": "REGISTERING"},
            expires_delta=timedelta(minutes=settings.jwt_registration_expire_minutes),
        )
        return {
            "success": True,
            "data": {
                "flow": "REGISTER",
                "registration_token": reg_token,
                "message": "Complete registration.",
            },
        }

    new_parent = Parent(phone=phone, full_name="", match_status=MatchStatus.PENDING)
    db.add(new_parent)
    db.commit()
    db.refresh(new_parent)
    reg_token = create_access_token(
        {"sub": new_parent.id, "role": "REGISTERING"},
        expires_delta=timedelta(minutes=settings.jwt_registration_expire_minutes),
    )
    return {
        "success": True,
        "data": {
            "flow": "REGISTER",
            "registration_token": reg_token,
            "message": "Complete registration.",
        },
    }


@router.post("/parent/register")
async def parent_register(
    req: ParentRegisterRequest,
    payload=Depends(require_registration_token),
    db: Session = Depends(get_db),
):
    parent_id = payload.get("sub")
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    parent.full_name = req.full_name
    parent.relationship = req.relationship
    db.commit()

    try:
        ward_index, ward_stream, _ = validate_student_fields(
            db,
            req.ward_form,
            req.ward_index_number,
            req.ward_stream,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    matches = find_matches(
        parent,
        db,
        req.ward_name,
        req.ward_form,
        ward_index,
        ward_stream,
    )
    candidates = _serialize_candidates(matches)

    if len(matches) == 1 and matches[0]["score"] >= settings.match_auto_threshold:
        top = matches[0]
        return {
            "success": True,
            "data": {
                "match_result": "AUTO_MATCHED",
                "student_id": str(top["student"].id),
                "message": "We found a strong match for your ward.",
                "candidates": candidates,
            },
        }

    if matches and matches[0]["score"] >= settings.match_candidate_threshold:
        if len(matches) == 1:
            return {
                "success": True,
                "data": {
                    "match_result": "MULTIPLE_CANDIDATES",
                    "message": "Please confirm this is your ward.",
                    "candidates": candidates,
                },
            }
        return {
            "success": True,
            "data": {
                "match_result": "MULTIPLE_CANDIDATES",
                "message": "Multiple possible matches found. Select your ward.",
                "candidates": candidates,
            },
        }

    pending = PendingMatch(
        parent_id=parent.id,
        entered_ward_name=req.ward_name,
        entered_ward_form=req.ward_form,
        entered_index_number=ward_index,
        top_candidates=json.dumps(candidates),
    )
    db.add(pending)
    db.commit()
    return {
        "success": True,
        "data": {
            "match_result": "PENDING_ADMIN_REVIEW",
            "message": "No automatic match found. An admin will review your registration.",
            "candidates": candidates,
        },
    }


@router.post("/parent/select-candidate")
async def select_candidate(
    req: SelectCandidateRequest,
    payload=Depends(require_registration_token),
    db: Session = Depends(get_db),
):
    parent_id = payload.get("sub")
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    student = db.query(Student).filter(Student.id == str(req.student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    existing = (
        db.query(ParentStudentLink)
        .filter(
            ParentStudentLink.parent_id == parent_id,
            ParentStudentLink.student_id == str(req.student_id),
        )
        .first()
    )
    if not existing:
        db.add(
            ParentStudentLink(
                parent_id=parent_id,
                student_id=str(req.student_id),
                relationship=parent.relationship,
                confidence_score=100,
            )
        )

    parent.match_status = MatchStatus.MATCHED
    db.commit()
    db.refresh(parent)

    access_token, refresh_token, _ = _parent_tokens(db, parent)
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "message": "Successfully linked to your ward.",
            "parent": {
                "id": parent.id,
                "full_name": parent.full_name,
                "phone": parent.phone,
                "linked_students": _linked_students(db, parent.id),
            },
        },
    }


@router.get("/parent/me")
async def parent_me(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can access")
    parent = db.query(Parent).filter(Parent.id == current_user["id"]).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    return {
        "success": True,
        "data": {
            "id": parent.id,
            "full_name": parent.full_name,
            "phone": parent.phone,
            "match_status": parent.match_status.value,
            "linked_students": _linked_students(db, parent.id),
        },
    }


@router.post("/refresh")
async def refresh_token_endpoint(req: RefreshTokenRequest, db: Session = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub")
    role = payload.get("role")

    if role == "PARENT":
        parent = db.query(Parent).filter(Parent.id == user_id).first()
        if not parent:
            raise HTTPException(status_code=401, detail="Parent not found")
        access_token, refresh_token, _ = _parent_tokens(db, parent)
        return {
            "success": True,
            "data": {"access_token": access_token, "refresh_token": refresh_token},
        }

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    refresh_token = create_refresh_token({"sub": user.id, "role": user.role.value})
    return {
        "success": True,
        "data": {"access_token": access_token, "refresh_token": refresh_token},
    }


@router.get("/web/me")
async def web_me(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user["role"] not in ("ADMIN", "FINANCIAL_STAFF"):
        raise HTTPException(status_code=403, detail="Staff only")
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "success": True,
        "data": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "is_first_login": user.is_first_login,
            "permissions": resolve_user_permissions(user),
        },
    }


@router.patch("/web/me")
async def update_web_me(
    req: StaffProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("ADMIN", "FINANCIAL_STAFF"):
        raise HTTPException(status_code=403, detail="Staff only")
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        user.name = name
    if req.email is not None:
        existing = db.query(User).filter(User.email == req.email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = req.email
    db.commit()
    log_staff_activity(
        db,
        current_user,
        page_label="Settings",
        action_label="Updated staff profile",
        details=user.email,
    )
    return {
        "success": True,
        "data": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "is_first_login": user.is_first_login,
            "permissions": resolve_user_permissions(user),
        },
    }


@router.post("/web/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email, User.is_active == True).first()
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = hash_reset_token(token)
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        db.commit()
        send_password_reset_email(user.email, user.name, token)
    return {
        "success": True,
        "data": {
            "message": "If that email is registered, a password reset link has been sent.",
        },
    }


@router.post("/web/reset-password")
async def reset_password_with_token(req: ResetPasswordTokenRequest, db: Session = Depends(get_db)):
    from sqlalchemy.exc import OperationalError
    import time

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = None
    for attempt in range(3):
        try:
            user = db.query(User).filter(
                User.reset_token == hash_reset_token(req.token),
                User.is_active == True,
            ).first()
            break
        except OperationalError as exc:
            db.rollback()
            if attempt < 2:
                time.sleep(0.3 * (attempt + 1))
            else:
                raise HTTPException(
                    status_code=503,
                    detail="Database temporarily unavailable. Please try again.",
                ) from exc

    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.hashed_password = hash_password(req.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    user.is_first_login = False
    try:
        db.commit()
    except OperationalError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable. Please try again.",
        ) from exc
    return {
        "success": True,
        "data": {"message": "Password updated. You can sign in now."},
    }


@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):
    return {"success": True, "data": {"message": "Logged out"}}

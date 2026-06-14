from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    get_current_user,
    require_registration_token,
)
from app.services.sms import send_sms
from app.services.matching import find_matches
from app.models.parent import Parent, MatchStatus
from app.models.user import User
from app.models.student import Student
from app.models.pending_match import PendingMatch
from app.models.parent_student_link import ParentStudentLink
from app.schemas.auth import (
    WebLoginRequest,
    OtpRequest,
    OtpVerifyRequest,
    ParentRegisterRequest,
    SelectCandidateRequest,
    RefreshTokenRequest,
)
import random
import redis
import json
from app.core.config import settings
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])

redis_client = redis.Redis.from_url(settings.redis_url)


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
            },
        },
    }


@router.post("/parent/request-otp")
async def request_otp(req: OtpRequest, db: Session = Depends(get_db)):
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    flow = "LOGIN" if parent and parent.match_status == MatchStatus.MATCHED else "REGISTER"
    otp = str(random.randint(100000, 999999))
    redis_client.setex(f"otp:{phone}", settings.otp_expiry_seconds, otp)
    await send_sms(phone, f"Your PTA OTP is {otp}. Valid for 10 minutes.")
    return {
        "success": True,
        "data": {
            "message": f"OTP sent to {phone}",
            "flow": flow,
            "expires_in_seconds": settings.otp_expiry_seconds,
        },
    }


@router.post("/parent/verify-otp")
async def verify_otp(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    phone = req.phone
    stored_otp = redis_client.get(f"otp:{phone}")
    if not stored_otp or stored_otp.decode() != req.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    redis_client.delete(f"otp:{phone}")

    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if parent:
        if parent.match_status == MatchStatus.MATCHED:
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

    matches = find_matches(
        parent,
        db,
        req.ward_name,
        req.ward_form,
        req.ward_index_number,
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
        entered_index_number=req.ward_index_number,
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


@router.post("/logout")
async def logout(current_user=Depends(get_current_user)):
    return {"success": True, "data": {"message": "Logged out"}}

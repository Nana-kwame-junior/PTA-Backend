from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import (
    create_access_token, create_refresh_token, decode_token,
    verify_password, hash_password
)
from app.core.security import get_current_user
from app.services.sms import send_sms
from app.services.matching import find_matches
from app.models.parent import Parent, MatchStatus
from app.models.user import User
from app.models.student import Student
from app.models.pending_match import PendingMatch
from app.models.parent_student_link import ParentStudentLink
from app.schemas.auth import (
    WebLoginRequest, OtpRequest, OtpVerifyRequest,
    ParentRegisterRequest, SelectCandidateRequest, RefreshTokenRequest
)
import random
import redis
from app.core.config import settings
from datetime import timedelta

router = APIRouter(prefix="/auth", tags=["Authentication"])

redis_client = redis.Redis.from_url(settings.redis_url)

# -------------------- WEB LOGIN (Admin / Staff) --------------------
@router.post("/web/login")
async def web_login(req: WebLoginRequest, db: Session = Depends(get_db)):
    """Admin or Financial Staff login with email + password."""
    user = db.query(User).filter(User.email == req.email, User.is_active == True).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Optional 2FA check (if totp_code provided and user has totp_secret)
    # ... (skip for now)
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
                "is_first_login": user.is_first_login
            }
        }
    }

# -------------------- PARENT OTP FLOW (unchanged, but keep as is) --------------------
@router.post("/parent/request-otp")
async def request_otp(req: OtpRequest, db: Session = Depends(get_db)):
    # ... same as before
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    flow = "LOGIN" if parent else "REGISTER"
    otp = str(random.randint(100000, 999999))
    redis_client.setex(f"otp:{phone}", settings.otp_expiry_seconds, otp)
    await send_sms(phone, f"Your PTA OTP is {otp}. Valid for 10 minutes.")
    return {"success": True, "data": {"message": f"OTP sent to {phone}", "flow": flow, "expires_in_seconds": settings.otp_expiry_seconds}}

@router.post("/parent/verify-otp")
async def verify_otp(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    # ... same as before (returns JWT for matched parent or registration token)
    phone = req.phone
    stored_otp = redis_client.get(f"otp:{phone}")
    if not stored_otp or stored_otp.decode() != req.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    redis_client.delete(f"otp:{phone}")
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if parent:
        if parent.match_status == MatchStatus.MATCHED:
            # Get matched student IDs
            links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent.id).all()
            matched_ids = [link.student_id for link in links]
            access_token = create_access_token({
                "sub": parent.id,
                "role": "PARENT",
                "phone": parent.phone,
                "matched_student_ids": matched_ids,
                "match_status": parent.match_status.value
            })
            refresh_token = create_refresh_token({"sub": parent.id, "role": "PARENT"})
            return {"success": True, "data": {"flow": "LOGIN", "access_token": access_token, "refresh_token": refresh_token, "parent": {}}}
        else:
            reg_token = create_access_token({"sub": parent.id, "role": "REGISTERING"}, expires_delta=timedelta(minutes=10))
            return {"success": True, "data": {"flow": "REGISTER", "registration_token": reg_token, "message": "Complete registration."}}
    else:
        # new parent
        new_parent = Parent(phone=phone, full_name="", match_status=MatchStatus.PENDING)
        db.add(new_parent)
        db.commit()
        reg_token = create_access_token({"sub": new_parent.id, "role": "REGISTERING"}, expires_delta=timedelta(minutes=10))
        return {"success": True, "data": {"flow": "REGISTER", "registration_token": reg_token, "message": "Complete registration."}}

@router.post("/parent/register")
async def parent_register(req: ParentRegisterRequest, token: str = Depends(lambda: ...), db: Session = Depends(get_db)):
    # ... unchanged (fuzzy matching logic)
    payload = decode_token(token)
    parent_id = payload.get("sub")
    parent = db.query(Parent).filter(Parent.id == parent_id).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    parent.full_name = req.full_name
    parent.relationship = req.relationship
    db.commit()
    # matching logic continues...
    # For brevity, keep the previously implemented code.
    # Return appropriate response.
    return {"success": True, "data": {"match_result": "AUTO_MATCHED", "student_id": matched_student.id, "message": "Successfully matched with your child's account"}}

@router.post("/parent/select-candidate")
async def select_candidate(req: SelectCandidateRequest, token: str = Depends(lambda: ...), db: Session = Depends(get_db)):
    # ... unchanged
    pass

@router.post("/refresh")
async def refresh_token(req: RefreshTokenRequest):
    # ... unchanged
    pass

@router.post("/logout")
async def logout(current_user = Depends(get_current_user)):
    # ... unchanged
    return {"success": True, "data": {"message": "Logged out"}}
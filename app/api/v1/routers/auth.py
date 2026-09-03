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
    require_registration_or_parent,
)
from app.services.sms import send_verification_code_sms
from app.services.sms_errors import SmsDeliveryError
from app.services.otp_store import store_otp, fetch_otp, delete_otp
from app.services.matching import find_matches
from app.services.student_validation import validate_student_fields
from app.models.parent import Parent, MatchStatus
from app.models.user import User, UserRole
from app.services.permissions import resolve_user_permissions
from app.services.staff_job_titles import display_job_title
from app.models.student import Student
from app.models.pending_match import PendingMatch
from app.models.parent_student_link import ParentStudentLink
from app.models.class_level import ClassLevel
from app.schemas.auth import (
    WebLoginRequest,
    OtpRequest,
    OtpVerifyRequest,
    ParentPhoneRequest,
    ParentRegisterRequest,
    WardRegisterEntry,
    LinkWardRequest,
    SelectCandidateRequest,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    ResetPasswordTokenRequest,
    StaffProfileUpdate,
    UnlinkWardRequest,
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


@router.get("/parent/students/search")
async def search_students_for_registration(
    name: str,
    form: str | None = None,
    payload=Depends(require_registration_or_parent),
    db: Session = Depends(get_db),
):
    """Search active students by name during registration or while linking a ward."""
    query_text = (name or "").strip()
    if len(query_text) < 2:
        return {"success": True, "data": {"students": []}}

    query = db.query(Student).filter(
        Student.is_active == True,
        Student.full_name.ilike(f"%{query_text}%"),
    )
    if form and form.strip():
        query = query.filter(Student.form.ilike(form.strip()))

    rows = query.order_by(Student.full_name.asc()).limit(10).all()
    return {
        "success": True,
        "data": {
            "students": [
                {
                    "id": str(row.id),
                    "full_name": row.full_name,
                    "index_number": row.index_number,
                    "form": row.form,
                    "stream": row.stream,
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
                    "status": getattr(link, "status", "ACTIVE") or "ACTIVE",
                    "unlink_pending": (getattr(link, "status", "ACTIVE") or "ACTIVE") == "PENDING_UNLINK",
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


def _serialize_parent(db: Session, parent: Parent) -> dict:
    return {
        "id": parent.id,
        "full_name": parent.full_name,
        "phone": parent.phone,
        "match_status": parent.match_status.value,
        "linked_students": _linked_students(db, parent.id),
    }


def _process_ward_match(
    db: Session,
    parent: Parent,
    ward_name: str,
    ward_form: str,
    ward_index_number: str | None,
    ward_stream: str | None,
):
    """Run matching algorithm and return registration response payload."""
    try:
        ward_index, ward_stream_norm, _ = validate_student_fields(
            db,
            ward_form,
            ward_index_number,
            ward_stream,
            require_index=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    matches = find_matches(
        parent,
        db,
        ward_name,
        ward_form,
        ward_index,
        ward_stream_norm,
    )
    candidates = _serialize_candidates(matches)

    if len(matches) == 1 and matches[0]["score"] >= settings.match_auto_threshold:
        top = matches[0]
        return {
            "match_result": "AUTO_MATCHED",
            "student_id": str(top["student"].id),
            "message": "We found a strong match for your ward.",
            "candidates": candidates,
        }

    if matches and matches[0]["score"] >= settings.match_candidate_threshold:
        return {
            "match_result": "MULTIPLE_CANDIDATES",
            "message": "Please confirm this is your ward."
            if len(matches) == 1
            else "Multiple possible matches found. Select your ward.",
            "candidates": candidates,
        }

    pending = PendingMatch(
        parent_id=parent.id,
        entered_ward_name=ward_name,
        entered_ward_form=ward_form,
        entered_index_number=ward_index,
        top_candidates=json.dumps(candidates),
    )
    db.add(pending)
    db.commit()
    return {
        "match_result": "PENDING_ADMIN_REVIEW",
        "message": "No automatic match found. An admin will review your registration.",
        "candidates": candidates,
    }


async def _send_phone_verification_code(db: Session, phone: str) -> None:
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


def _registration_token_for_phone(db: Session, phone: str) -> str:
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if not parent:
        parent = Parent(phone=phone, full_name="", match_status=MatchStatus.PENDING)
        db.add(parent)
        db.commit()
        db.refresh(parent)
    return create_access_token(
        {"sub": parent.id, "role": "REGISTERING"},
        expires_delta=timedelta(minutes=settings.jwt_registration_expire_minutes),
    )


@router.post("/parent/login")
async def parent_login(req: ParentPhoneRequest, db: Session = Depends(get_db)):
    """Sign in an existing parent with phone only — no OTP required."""
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if not parent or not _parent_profile_complete(parent):
        raise HTTPException(
            status_code=404,
            detail="No registered account for this number. Please create an account first.",
        )
    access_token, refresh_token, _ = _parent_tokens(db, parent)
    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "parent": _serialize_parent(db, parent),
        },
    }


@router.post("/parent/register/send-code")
async def parent_register_send_code(req: ParentPhoneRequest, db: Session = Depends(get_db)):
    """Send SMS verification code — registration only (first-time sign-up)."""
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if parent and parent.match_status == MatchStatus.MATCHED:
        raise HTTPException(
            status_code=409,
            detail="This number is already registered. Please sign in instead.",
        )
    await _send_phone_verification_code(db, phone)
    return {
        "success": True,
        "data": {
            "message": f"Verification code sent to {phone}",
            "expires_in_seconds": settings.otp_expiry_seconds,
            **({"dry_run": True} if settings.sms_dry_run else {}),
        },
    }


@router.post("/parent/register/verify-code")
async def parent_register_verify_code(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    """Verify SMS code during registration and return a registration session token."""
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if parent and parent.match_status == MatchStatus.MATCHED:
        raise HTTPException(
            status_code=409,
            detail="This number is already registered. Please sign in instead.",
        )

    stored_otp = fetch_otp(db, phone)
    if not stored_otp or stored_otp != req.otp:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    delete_otp(db, phone)

    reg_token = _registration_token_for_phone(db, phone)
    return {
        "success": True,
        "data": {
            "registration_token": reg_token,
            "message": "Phone verified. Complete your registration.",
        },
    }


@router.post("/parent/register/resume-session")
async def parent_register_resume_session(req: ParentPhoneRequest, db: Session = Depends(get_db)):
    """Re-issue a registration token after app reload — phone must have passed OTP earlier."""
    phone = req.phone
    parent = db.query(Parent).filter(Parent.phone == phone).first()
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="No registration in progress for this number. Verify your phone to continue.",
        )
    if _parent_profile_complete(parent) and parent.match_status == MatchStatus.MATCHED:
        raise HTTPException(
            status_code=409,
            detail="This number is already registered. Please sign in instead.",
        )
    reg_token = _registration_token_for_phone(db, phone)
    return {
        "success": True,
        "data": {
            "registration_token": reg_token,
            "message": "Registration session restored. Continue where you left off.",
        },
    }


@router.post("/web/login")
async def web_login(req: WebLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        admin = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN, User.is_active == True)
            .order_by(User.created_at.asc())
            .first()
        )
        admin_email = admin.email if admin else settings.pta_chairperson_email
        raise HTTPException(
            status_code=403,
            detail=(
                "Your account has been deactivated. Contact the school admin "
                f"({admin_email}) to request reactivation."
            ),
        )
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
                "job_title": display_job_title(user),
                "is_first_login": user.is_first_login,
                "permissions": resolve_user_permissions(user),
            },
        },
    }


@router.post("/parent/request-otp")
async def request_otp(req: OtpRequest, db: Session = Depends(get_db)):
    """Deprecated — use POST /parent/login or POST /parent/register/send-code."""
    if req.purpose == "login":
        raise HTTPException(
            status_code=400,
            detail="Use POST /auth/parent/login to sign in. OTP is only required during registration.",
        )
    phone_req = ParentPhoneRequest(phone=req.phone)
    return await parent_register_send_code(phone_req, db)


@router.post("/parent/verify-otp")
async def verify_otp(req: OtpVerifyRequest, db: Session = Depends(get_db)):
    """Deprecated — use POST /parent/register/verify-code for registration."""
    return await parent_register_verify_code(req, db)


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

    if req.wards:
        wards = req.wards
    elif req.ward_name and req.ward_form:
        wards = [
            WardRegisterEntry(
                ward_name=req.ward_name,
                ward_form=req.ward_form,
                ward_index_number=req.ward_index_number,
                ward_stream=req.ward_stream,
            )
        ]
    else:
        raise HTTPException(status_code=400, detail="Add at least one ward")

    parent.full_name = req.full_name
    parent.relationship = req.relationship
    db.commit()

    ward_results = []
    for ward in wards:
        result = _process_ward_match(
            db,
            parent,
            ward.ward_name,
            ward.ward_form,
            ward.ward_index_number,
            ward.ward_stream,
        )
        ward_results.append(
            {
                **result,
                "ward_name": ward.ward_name,
                "ward_form": ward.ward_form,
            }
        )

    auto_ids = [
        r["student_id"]
        for r in ward_results
        if r.get("match_result") == "AUTO_MATCHED" and r.get("student_id")
    ]
    for student_id in auto_ids:
        _attach_student_link(db, parent, str(student_id))
    if auto_ids:
        db.commit()
        db.refresh(parent)

    session_payload = {}
    if parent.match_status == MatchStatus.MATCHED:
        access_token, refresh_token, _ = _parent_tokens(db, parent)
        session_payload = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "parent": _serialize_parent(db, parent),
        }

    if len(ward_results) == 1:
        data = {**ward_results[0], **session_payload}
        return {"success": True, "data": data}

    any_pending = any(r.get("match_result") == "PENDING_ADMIN_REVIEW" for r in ward_results)
    needs_pick = any(r.get("match_result") == "MULTIPLE_CANDIDATES" for r in ward_results)

    if parent.match_status == MatchStatus.MATCHED and not needs_pick:
        return {
            "success": True,
            "data": {
                "match_result": "AUTO_MATCHED",
                "message": f"Linked {len(auto_ids)} ward(s) successfully.",
                "ward_results": ward_results,
                **session_payload,
            },
        }

    if any_pending and not needs_pick and not auto_ids:
        return {
            "success": True,
            "data": {
                **ward_results[0],
                "ward_results": ward_results,
            },
        }

    merged_candidates = []
    for i, result in enumerate(ward_results):
        for candidate in result.get("candidates") or []:
            merged_candidates.append({**candidate, "ward_index": i, "ward_name": wards[i].ward_name})

    return {
        "success": True,
        "data": {
            "match_result": "MULTI_WARD" if len(ward_results) > 1 else ward_results[0].get("match_result"),
            "message": "Please confirm your ward(s)." if needs_pick else ward_results[0].get("message", ""),
            "candidates": merged_candidates or ward_results[0].get("candidates"),
            "ward_results": ward_results,
        },
    }


@router.post("/parent/link-ward")
async def link_additional_ward(
    req: LinkWardRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Link another ward to an already registered parent account."""
    if current_user["role"] != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can access")

    parent = db.query(Parent).filter(Parent.id == current_user["id"]).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    result = _process_ward_match(
        db,
        parent,
        req.ward_name,
        req.ward_form,
        req.ward_index_number,
        req.ward_stream,
    )
    if result.get("match_result") == "PENDING_ADMIN_REVIEW":
        result["message"] = (
            "No match found for this ward. Please contact the school admin "
            "(office or PTA chairperson) for a proper records check. "
            "You cannot continue with status checks from the app until an admin links your child."
        )
        result["requires_admin_contact"] = True
    return {"success": True, "data": result}


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

    data = _link_parent_to_student(db, parent, str(req.student_id))
    return {"success": True, "data": data}


def _attach_student_link(db: Session, parent: Parent, student_id: str) -> None:
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    existing = (
        db.query(ParentStudentLink)
        .filter(
            ParentStudentLink.parent_id == parent.id,
            ParentStudentLink.student_id == str(student_id),
        )
        .first()
    )
    if not existing:
        db.add(
            ParentStudentLink(
                parent_id=parent.id,
                student_id=str(student_id),
                relationship=parent.relationship,
                confidence_score=100,
            )
        )

    parent.match_status = MatchStatus.MATCHED


def _link_parent_to_student(db: Session, parent: Parent, student_id: str) -> dict:
    _attach_student_link(db, parent, student_id)
    db.commit()
    db.refresh(parent)
    access_token, refresh_token, _ = _parent_tokens(db, parent)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "message": "Successfully linked to your ward.",
        "parent": _serialize_parent(db, parent),
    }


@router.post("/parent/confirm-ward")
async def confirm_ward_link(
    req: SelectCandidateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can access")
    parent = db.query(Parent).filter(Parent.id == current_user["id"]).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")
    data = _link_parent_to_student(db, parent, str(req.student_id))
    return {"success": True, "data": data}


@router.post("/parent/unlink-ward")
async def parent_unlink_ward(
    req: UnlinkWardRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] != "PARENT":
        raise HTTPException(status_code=403, detail="Only parents can access")
    parent = db.query(Parent).filter(Parent.id == current_user["id"]).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Parent not found")

    student_id_str = str(req.student_id)
    link = (
        db.query(ParentStudentLink)
        .filter(
            ParentStudentLink.parent_id == parent.id,
            ParentStudentLink.student_id == student_id_str,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Ward link not found")

    student = db.query(Student).filter(Student.id == student_id_str).first()
    ward_name = student.full_name if student else "Unknown Student"
    ward_form = student.form if student else "N/A"

    # Mark link as pending unlink
    link.status = "PENDING_UNLINK"

    # Check if a pending unlink record already exists
    existing_pending = (
        db.query(PendingMatch)
        .filter(
            PendingMatch.parent_id == parent.id,
            PendingMatch.student_id == student_id_str,
            PendingMatch.request_type == "UNLINK",
            PendingMatch.status == "PENDING",
        )
        .first()
    )
    if not existing_pending:
        new_pending = PendingMatch(
            parent_id=parent.id,
            entered_ward_name=ward_name,
            entered_ward_form=ward_form,
            request_type="UNLINK",
            student_id=student_id_str,
            status="PENDING",
        )
        db.add(new_pending)

    db.commit()

    db.refresh(parent)
    access_token, refresh_token, _ = _parent_tokens(db, parent)
    return {
        "success": True,
        "data": {
            "message": "Unlink request submitted. An admin will review and approve your request shortly.",
            "access_token": access_token,
            "refresh_token": refresh_token,
            "parent": _serialize_parent(db, parent),
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
            "job_title": display_job_title(user),
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
            "job_title": display_job_title(user),
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
async def logout():
    """Client clears tokens locally; always succeed so logout never surfaces auth errors."""
    return {"success": True, "data": {"message": "Logged out"}}

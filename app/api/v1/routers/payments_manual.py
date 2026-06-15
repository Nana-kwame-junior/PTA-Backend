from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import logging
from typing import Optional

from app.core.database import get_db
from app.core.security import require_role, require_permission, get_current_user
from app.models.manual_payment import ManualPayment, ManualPaymentMode
from app.models.manual_amendment import ManualAmendment
from app.models.student import Student
from app.models.user import User
from app.models.dues_config import DuesConfig
from app.models.sms_log import SmsLog
from app.models.parent_student_link import ParentStudentLink
from app.models.parent import Parent
from app.schemas.payment import ManualPaymentRequest, ManualPaymentUpdate, AmendmentRequest, FlagPaymentRequest
from app.services.sms import send_sms_background
from app.services.pdf import generate_receipt
from app.core.config import settings
from fastapi.responses import StreamingResponse
from app.workers.lock_tasks import lock_manual_payment
from app.services.activity_log import log_staff_activity
from app.services.task_queue import safe_apply_async
from app.services.dues_balance import student_term_dues_balance, format_payment_sms

router = APIRouter(prefix="/payments/manual", tags=["Manual Payments"])
logger = logging.getLogger(__name__)

def generate_receipt_number(db: Session) -> str:
    year = datetime.utcnow().year
    last = db.query(ManualPayment).filter(ManualPayment.receipt_number.like(f"MNL-{year}-%")).count()
    return f"MNL-{year}-{last+1:05d}"

@router.post("")
async def record_manual_payment(
    req: ManualPaymentRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.record")),
):
    if req.student_id:
        student = db.query(Student).filter(
            Student.id == str(req.student_id),
            Student.is_active == True,
        ).first()
    else:
        student = db.query(Student).filter(
            Student.index_number == req.student_index_number,
            Student.is_active == True,
        ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    dues_config = db.query(DuesConfig).filter(
        DuesConfig.id == str(req.dues_config_id),
        DuesConfig.is_active == True,
    ).first()
    if not dues_config:
        raise HTTPException(status_code=404, detail="Dues configuration not found")
    
    # Get staff user details
    user = db.query(User).filter(User.id == staff["id"]).first()
    
    parent_phones = []
    links = db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student.id).all()
    for link in links:
        parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
        if parent and parent.phone:
            parent_phones.append(parent.phone)
    if student.parent_phone_1:
        parent_phones.append(student.parent_phone_1)
    if student.parent_phone_2:
        parent_phones.append(student.parent_phone_2)
    parent_phones = list(dict.fromkeys(parent_phones))
    parent_phone = parent_phones[0] if parent_phones else None

    balance_info = student_term_dues_balance(
        db,
        student_id=student.id,
        academic_year=dues_config.academic_year,
        term=dues_config.term,
    )
    balance_before = balance_info["remaining_ghs"]
    balance_after = max(balance_before - Decimal(str(req.amount_ghs)), Decimal("0"))
    
    receipt_number = generate_receipt_number(db)
    manual_payment = ManualPayment(
        receipt_number=receipt_number,
        student_id=student.id,
        student_index_no=student.index_number,
        student_name=student.full_name,
        parent_phone=parent_phone,
        term=dues_config.term,
        academic_year=dues_config.academic_year,
        amount_ghs=req.amount_ghs,
        payment_mode=req.payment_mode,
        payment_date=req.payment_date,
        recorded_by_user_id=staff["id"],
        recorded_by_name=user.name if user else staff["id"],
        recorded_at=datetime.utcnow(),
        ip_address=request.client.host,
        notes=req.notes,
        is_locked=False
    )
    db.add(manual_payment)
    db.commit()
    db.refresh(manual_payment)
    log_staff_activity(
        db,
        staff,
        page_label="Record Payment",
        action_label=f"Recorded GH₵{req.amount_ghs} for {student.full_name}",
        details=receipt_number,
    )
    
    # Send SMS to all parent phones (non-blocking; failures must not undo payment)
    try:
        sms_body = format_payment_sms(
            student_name=student.full_name,
            amount_ghs=req.amount_ghs,
            term=dues_config.term,
            academic_year=dues_config.academic_year,
            receipt_number=receipt_number,
            balance_before=balance_before,
            balance_after=balance_after,
            channel="Manual payment",
        )
        for phone in parent_phones:
            background_tasks.add_task(send_sms_background, phone, sms_body)
            db.add(
                SmsLog(
                    message_type="MANUAL_PAYMENT",
                    recipient_phone=phone,
                    content=sms_body,
                    status="QUEUED",
                )
            )
        manual_payment.sms_sent = bool(parent_phones)
        if parent_phones:
            manual_payment.sms_sent_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("SMS logging failed after payment recorded: %s", exc)

    lock_time = datetime.utcnow() + timedelta(hours=24)
    safe_apply_async(
        lock_manual_payment,
        args=[str(manual_payment.id)],
        countdown=24 * 60 * 60,
    )
    
    return {
        "success": True,
        "data": {
            "id": str(manual_payment.id),
            "receipt_number": receipt_number,
            "student_index_number": student.index_number,
            "student_name": student.full_name,
            "amount_ghs": str(req.amount_ghs),
            "payment_mode": req.payment_mode.value,
            "payment_date": req.payment_date.isoformat(),
            "recorded_by": user.name if user else staff["id"],
            "recorded_at": manual_payment.recorded_at.isoformat(),
            "is_locked": False,
            "lock_at": lock_time.isoformat(),
            "sms_sent": True
        }
    }

@router.patch("/{payment_id}")
async def update_manual_payment(
    payment_id: UUID,
    req: ManualPaymentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    payment = db.query(ManualPayment).filter(ManualPayment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.is_locked:
        raise HTTPException(status_code=403, detail="Payment is locked (older than 24 hours)")
    # Check permissions: FINANCIAL_STAFF can edit only own records within 24h; ADMIN any
    if current_user["role"] == "FINANCIAL_STAFF" and payment.recorded_by_user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Cannot edit another staff's payment")
    
    for key, value in req.dict(exclude_unset=True).items():
        setattr(payment, key, value)
    db.commit()
    return {"success": True, "data": {"id": str(payment_id), "updated": True}}

@router.post("/{payment_id}/amend")
async def amend_locked_payment(
    payment_id: UUID,
    req: AmendmentRequest,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    payment = db.query(ManualPayment).filter(ManualPayment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404)
    # Create amendment record
    amendment = ManualAmendment(
        manual_payment_id=str(payment_id),
        original_values={
            "amount_ghs": str(payment.amount_ghs),
            "payment_mode": payment.payment_mode.value if payment.payment_mode else None,
            "payment_date": payment.payment_date.isoformat()
        },
        corrected_values={
            "amount_ghs": str(req.corrected_amount_ghs),
            "payment_mode": req.corrected_payment_mode.value,
            "payment_date": req.corrected_payment_date.isoformat()
        },
        reason=req.reason,
        amended_by_user_id=admin["id"],
        amended_at=datetime.utcnow()
    )
    db.add(amendment)
    payment.amendment_id = str(amendment.id)
    # Optionally update the payment with corrected values? PRD says original remains unchanged, but amendment record stores correction.
    db.commit()
    return {"success": True, "data": {"message": "Amendment recorded"}}

@router.post("/{payment_id}/flag")
async def flag_manual_payment(
    payment_id: UUID,
    req: FlagPaymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    payment = db.query(ManualPayment).filter(ManualPayment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404)
    payment.is_flagged = True
    payment.flag_reason = req.reason
    db.commit()
    # Send email alert to PTA chairperson
    background_tasks.add_task(send_email_alert, payment, req.reason)
    return {"success": True, "data": {"message": "Payment flagged"}}

async def send_email_alert(payment: ManualPayment, reason: str):
    # Implement email sending using SMTP
    pass

@router.get("")
async def list_manual_payments(
    student_id: Optional[UUID] = None,
    academic_year: Optional[str] = None,
    term: Optional[str] = None,
    recorded_by_user_id: Optional[UUID] = None,
    payment_mode: Optional[ManualPaymentMode] = None,
    is_flagged: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.history")),
):
    query = db.query(ManualPayment)
    if student_id:
        query = query.filter(ManualPayment.student_id == str(student_id))
    if academic_year:
        query = query.filter(ManualPayment.academic_year == academic_year)
    if term:
        query = query.filter(ManualPayment.term == term)
    if recorded_by_user_id:
        query = query.filter(ManualPayment.recorded_by_user_id == str(recorded_by_user_id))
    if payment_mode:
        query = query.filter(ManualPayment.payment_mode == payment_mode)
    if is_flagged is not None:
        query = query.filter(ManualPayment.is_flagged == is_flagged)
    if date_from:
        query = query.filter(ManualPayment.payment_date >= date_from)
    if date_to:
        query = query.filter(ManualPayment.payment_date <= date_to)
    total = query.count()
    payments = query.offset((page-1)*limit).limit(limit).all()
    return {
        "success": True,
        "data": {
            "payments": payments,
            "pagination": {"page": page, "limit": limit, "total": total, "total_pages": (total+limit-1)//limit}
        }
    }

@router.get("/audit-log")
async def manual_payment_audit_log(
    format: str = "json",
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # For simplicity, return amendments list
    amendments = db.query(ManualAmendment).all()
    if format == "csv":
        # Return CSV
        import csv
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "payment_id", "reason", "amended_at"])
        for a in amendments:
            writer.writerow([a.id, a.manual_payment_id, a.reason, a.amended_at])
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    return {"success": True, "data": {"audit_log": amendments}}

@router.get("/{payment_id}/receipt")
async def download_manual_receipt(
    payment_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.history")),
):
    payment = db.query(ManualPayment).filter(ManualPayment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404)
    student = db.query(Student).filter(Student.id == payment.student_id).first()
    receipt_data = {
        "receipt_number": payment.receipt_number,
        "student_name": payment.student_name,
        "amount_ghs": str(payment.amount_ghs),
        "date": payment.payment_date.strftime("%Y-%m-%d %H:%M:%S"),
        "type": "Manual Payment (Cash/Cheque)"
    }
    pdf_buffer = generate_receipt(receipt_data)
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=receipt_{payment.receipt_number}.pdf"})
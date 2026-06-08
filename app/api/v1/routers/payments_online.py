from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
import hmac
import hashlib
from decimal import Decimal
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_parent_match, get_current_user, require_role
from app.models.payment import Payment, PaymentStatus
from app.models.student import Student
from app.models.parent import Parent
from app.models.dues_config import DuesConfig
from app.models.sms_log import SmsLog
from app.schemas.payment import InitiatePaymentRequest
from app.services.paystack import initialize_transaction, verify_webhook_signature
from app.services.sms import send_sms
from app.services.pdf import generate_receipt
from app.core.config import settings
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter(prefix="/payments/online", tags=["Online Payments"])

@router.post("/initiate")
async def initiate_payment(
    req: InitiatePaymentRequest,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match)
):
    # Verify student belongs to parent
    if str(req.student_id) not in parent.get("matched_student_ids", []):
        raise HTTPException(status_code=403, detail="Student not linked to this parent")
    
    student = db.query(Student).filter(Student.id == str(req.student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    dues_config = db.query(DuesConfig).filter(DuesConfig.id == str(req.dues_config_id)).first()
    if not dues_config:
        raise HTTPException(status_code=404, detail="Dues configuration not found")
    
    # Check if already paid? (optional)
    existing = db.query(Payment).filter(
        Payment.student_id == str(req.student_id),
        Payment.dues_config_id == str(req.dues_config_id),
        Payment.status == PaymentStatus.COMPLETED
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Dues already paid for this term")
    
    # Create pending payment record
    payment_ref = f"mwl-{uuid.uuid4().hex[:8]}"
    payment = Payment(
        student_id=str(req.student_id),
        dues_config_id=str(req.dues_config_id),
        parent_id=parent["id"],
        amount_ghs=dues_config.amount_ghs,
        paystack_reference=payment_ref,
        status=PaymentStatus.PENDING
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    
    # Initialize Paystack transaction
    amount_in_pesewas = int(dues_config.amount_ghs * 100)
    result = await initialize_transaction(
        email="parent@example.com",  # In real scenario, parent email would be collected
        amount=amount_in_pesewas,
        reference=payment_ref,
        metadata={"payment_id": str(payment.id), "student_id": str(req.student_id)}
    )
    
    if not result.get("status"):
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(status_code=400, detail=result.get("message", "Paystack initialization failed"))
    
    return {
        "success": True,
        "data": {
            "payment_id": str(payment.id),
            "paystack_reference": payment_ref,
            "authorization_url": result["data"]["authorization_url"],
            "amount_ghs": str(dues_config.amount_ghs)
        }
    }

@router.post("/webhook")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # Verify signature
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    
    body = await request.body()
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = await request.json()
    event = payload.get("event")
    
    if event == "charge.success":
        data = payload["data"]
        reference = data["reference"]
        payment = db.query(Payment).filter(Payment.paystack_reference == reference).first()
        if payment and payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.COMPLETED
            payment.paid_at = datetime.utcnow()
            # Generate receipt number
            year = datetime.utcnow().year
            last = db.query(Payment).filter(Payment.receipt_number.like(f"PST-{year}-%")).count()
            payment.receipt_number = f"PST-{year}-{last+1:05d}"
            db.commit()
            
            # Send SMS to parent
            parent = db.query(Parent).filter(Parent.id == payment.parent_id).first()
            student = db.query(Student).filter(Student.id == payment.student_id).first()
            if parent and student:
                message = f"Payment of GH₵{payment.amount_ghs} received for {student.full_name} ({student.index_number}), Term 1 dues. Receipt: {payment.receipt_number}. — Mawuli SHS PTA"
                background_tasks.add_task(send_sms, parent.phone, message)
                sms_log = SmsLog(
                    message_type="PAYMENT_CONFIRMATION",
                    recipient_phone=parent.phone,
                    content=message,
                    status="QUEUED"
                )
                db.add(sms_log)
                db.commit()
    
    elif event == "charge.failed":
        reference = payload["data"]["reference"]
        payment = db.query(Payment).filter(Payment.paystack_reference == reference).first()
        if payment:
            payment.status = PaymentStatus.FAILED
            db.commit()
    
    return {"status": "ok"}

@router.get("")
async def list_online_payments(
    student_id: UUID = None,
    academic_year: str = None,
    term: str = None,
    status: PaymentStatus = None,
    page: int = 1,
    limit: int = 50,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    query = db.query(Payment)
    if student_id:
        query = query.filter(Payment.student_id == str(student_id))
    if status:
        query = query.filter(Payment.status == status)
    # Additional filters via join to DuesConfig
    if academic_year or term:
        query = query.join(DuesConfig, Payment.dues_config_id == DuesConfig.id)
        if academic_year:
            query = query.filter(DuesConfig.academic_year == academic_year)
        if term:
            query = query.filter(DuesConfig.term == term)
    
    total = query.count()
    payments = query.offset((page-1)*limit).limit(limit).all()
    return {
        "success": True,
        "data": {
            "payments": payments,
            "pagination": {"page": page, "limit": limit, "total": total, "total_pages": (total+limit-1)//limit}
        }
    }

@router.get("/parent")
async def parent_payment_history(
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match)
):
    payments = db.query(Payment).filter(Payment.parent_id == parent["id"]).all()
    return {"success": True, "data": {"payments": payments}}

@router.get("/{payment_id}/receipt")
async def download_online_receipt(
    payment_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    payment = db.query(Payment).filter(Payment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    # Permission check
    if current_user["role"] == "PARENT" and payment.parent_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not your payment")
    
    student = db.query(Student).filter(Student.id == payment.student_id).first()
    receipt_data = {
        "receipt_number": payment.receipt_number,
        "student_name": student.full_name if student else "Unknown",
        "amount_ghs": str(payment.amount_ghs),
        "date": payment.paid_at.strftime("%Y-%m-%d %H:%M:%S") if payment.paid_at else "",
        "type": "Online Payment"
    }
    pdf_buffer = generate_receipt(receipt_data)
    return StreamingResponse(pdf_buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=receipt_{payment.receipt_number}.pdf"})
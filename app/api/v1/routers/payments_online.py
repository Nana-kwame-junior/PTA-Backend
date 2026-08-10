from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
import uuid
import json
from decimal import Decimal
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_parent_match, get_current_user, require_permission
from app.models.payment import Payment, PaymentStatus
from app.models.student import Student
from app.models.parent import Parent
from app.models.dues_config import DuesConfig
from app.models.sms_log import SmsLog
from app.schemas.payment import InitiatePaymentRequest
from app.services.paystack import (
    initialize_transaction,
    verify_transaction,
    verify_webhook_signature,
    paystack_callback_url,
    paystack_is_configured,
)
from app.services.sms import send_sms_background
from app.services.dues_balance import (
    student_term_dues_balance,
    student_outstanding_summary,
    apply_online_payment_allocations,
    format_payment_sms,
)
from app.models.class_level import Track
from app.services.pdf import generate_receipt
from app.core.config import settings
from fastapi.responses import StreamingResponse, HTMLResponse

router = APIRouter(prefix="/payments/online", tags=["Online Payments"])


def _paystack_email(phone: str) -> str:
    digits = phone.replace("+", "").replace(" ", "")
    return f"{digits}@parents.mawulishs.edu.gh"


def _serialize_payment(payment: Payment, student: Student | None = None) -> dict:
    return {
        "id": str(payment.id),
        "student_id": str(payment.student_id),
        "dues_config_id": str(payment.dues_config_id),
        "parent_id": str(payment.parent_id),
        "amount_ghs": str(payment.amount_ghs),
        "paystack_reference": payment.paystack_reference,
        "status": payment.status.value if payment.status else "PENDING",
        "receipt_number": payment.receipt_number,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "student": {
            "full_name": student.full_name,
            "index_number": student.index_number,
        }
        if student
        else None,
    }


def _generate_receipt_number(db: Session) -> str:
    year = datetime.utcnow().year
    last = db.query(Payment).filter(Payment.receipt_number.like(f"PST-{year}-%")).count()
    return f"PST-{year}-{last + 1:05d}"


async def _mark_payment_completed(payment: Payment, db: Session, background_tasks: BackgroundTasks):
    if payment.status == PaymentStatus.COMPLETED:
        return
    payment.status = PaymentStatus.COMPLETED
    payment.paid_at = datetime.utcnow()
    if not payment.receipt_number:
        payment.receipt_number = _generate_receipt_number(db)
    db.commit()

    parent = db.query(Parent).filter(Parent.id == payment.parent_id).first()
    student = db.query(Student).filter(Student.id == payment.student_id).first()
    dues = db.query(DuesConfig).filter(DuesConfig.id == payment.dues_config_id).first()
    if parent and student and dues:
        apply_online_payment_allocations(
            db,
            payment=payment,
            student=student,
            parent_phone=parent.phone,
        )
        track = student.track if student.track else Track.BASIC
        summary = student_outstanding_summary(db, student_id=student.id, track=track)
        balance_after = Decimal(summary["total_due_ghs"])
        balance_before = balance_after + Decimal(str(payment.amount_ghs))
        message = format_payment_sms(
            student_name=student.full_name,
            amount_ghs=payment.amount_ghs,
            term=dues.term,
            academic_year=dues.academic_year,
            receipt_number=payment.receipt_number or payment.paystack_reference,
            balance_before=balance_before,
            balance_after=balance_after,
            channel="Online payment",
        )
        background_tasks.add_task(send_sms_background, parent.phone, message)
        db.add(
            SmsLog(
                message_type="PAYMENT_CONFIRMATION",
                recipient_phone=parent.phone,
                content=message,
                status="QUEUED",
            )
        )
        db.commit()


@router.get("/config")
async def paystack_config():
    """Public Paystack client config — public key is safe to expose."""
    return {
        "success": True,
        "data": {
            "public_key": settings.paystack_public_key,
            "callback_url": paystack_callback_url(),
            "configured": paystack_is_configured(),
        },
    }


@router.post("/initiate")
async def initiate_payment(
    req: InitiatePaymentRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    if not paystack_is_configured():
        raise HTTPException(
            status_code=503,
            detail="Paystack is not configured. Set PAYSTACK_SECRET_KEY and PAYSTACK_PUBLIC_KEY on the server.",
        )

    if str(req.student_id) not in parent.get("matched_student_ids", []):
        raise HTTPException(status_code=403, detail="Student not linked to this parent")

    student = db.query(Student).filter(Student.id == str(req.student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    dues_config = db.query(DuesConfig).filter(DuesConfig.id == str(req.dues_config_id)).first()
    if not dues_config:
        raise HTTPException(status_code=404, detail="Dues configuration not found")

    track = student.track if student.track else Track.BASIC
    outstanding = student_outstanding_summary(db, student_id=str(req.student_id), track=track)
    total_due = Decimal(outstanding["total_due_ghs"])
    if total_due <= 0:
        return {
            "success": True,
            "data": {
                "paid_up": True,
                "authorization_url": None,
                "paystack_reference": None,
                "payment_id": None,
                "amount_ghs": "0.00",
                "breakdown": outstanding["breakdown"],
                "arrears_ghs": outstanding["arrears_ghs"],
                "current_term_amount_ghs": outstanding["current_term_amount_ghs"],
                "public_key": settings.paystack_public_key,
            },
        }

    # Retire any abandoned PENDING checkout. Re-using the same Paystack reference
    # fails with "Duplicate Transaction Reference" and leaves the app hanging.
    pending_rows = (
        db.query(Payment)
        .filter(
            Payment.student_id == str(req.student_id),
            Payment.dues_config_id == str(req.dues_config_id),
            Payment.status == PaymentStatus.PENDING,
        )
        .all()
    )
    for pending in pending_rows:
        verify = await verify_transaction(pending.paystack_reference)
        verify_status = verify.get("data", {}).get("status") if verify.get("status") else None
        if verify_status == "success":
            await _mark_payment_completed(pending, db, background_tasks)
            db.commit()
            raise HTTPException(status_code=409, detail="All dues are paid for this student")
        pending.status = PaymentStatus.FAILED
        db.commit()

    amount_in_pesewas = int(float(total_due) * 100)
    parent_row = db.query(Parent).filter(Parent.id == parent["id"]).first()
    paystack_email = _paystack_email(parent_row.phone if parent_row else parent.get("phone", ""))

    payment_ref = f"mwl-{uuid.uuid4().hex[:8]}"
    payment = Payment(
        student_id=str(req.student_id),
        dues_config_id=str(req.dues_config_id),
        parent_id=parent["id"],
        amount_ghs=total_due,
        paystack_reference=payment_ref,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    result = await initialize_transaction(
        email=paystack_email,
        amount=amount_in_pesewas,
        reference=payment_ref,
        metadata={"payment_id": str(payment.id), "student_id": str(req.student_id)},
    )

    if not result.get("status"):
        payment.status = PaymentStatus.FAILED
        db.commit()
        message = result.get("message", "Paystack initialization failed")
        raise HTTPException(status_code=400, detail=message)

    return {
        "success": True,
        "data": {
            "paid_up": False,
            "payment_id": str(payment.id),
            "paystack_reference": payment_ref,
            "authorization_url": result["data"]["authorization_url"],
            "amount_ghs": str(total_due),
            "breakdown": outstanding["breakdown"],
            "arrears_ghs": outstanding["arrears_ghs"],
            "current_term_amount_ghs": outstanding["current_term_amount_ghs"],
            "public_key": settings.paystack_public_key,
        },
    }


@router.get("/verify/{reference}")
async def verify_payment_reference(
    reference: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    payment = db.query(Payment).filter(Payment.paystack_reference == reference).first()
    if not payment or payment.parent_id != parent["id"]:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status == PaymentStatus.COMPLETED:
        student = db.query(Student).filter(Student.id == payment.student_id).first()
        return {"success": True, "data": _serialize_payment(payment, student)}

    if not paystack_is_configured():
        raise HTTPException(status_code=503, detail="Paystack is not configured on the server")

    result = await verify_transaction(reference)
    if result.get("status") and result.get("data", {}).get("status") == "success":
        await _mark_payment_completed(payment, db, background_tasks)
        db.refresh(payment)
    elif result.get("data", {}).get("status") == "failed":
        payment.status = PaymentStatus.FAILED
        db.commit()

    student = db.query(Student).filter(Student.id == payment.student_id).first()
    return {"success": True, "data": _serialize_payment(payment, student)}


async def process_paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session,
) -> dict:
    """Shared Paystack webhook handler (signature + charge.success / charge.failed)."""
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    body = await request.body()
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event = payload.get("event")
    data = payload.get("data") or {}
    reference = data.get("reference")

    if event == "charge.success" and reference:
        payment = db.query(Payment).filter(Payment.paystack_reference == reference).first()
        if payment:
            await _mark_payment_completed(payment, db, background_tasks)

    elif event == "charge.failed" and reference:
        payment = db.query(Payment).filter(Payment.paystack_reference == reference).first()
        if payment and payment.status != PaymentStatus.COMPLETED:
            payment.status = PaymentStatus.FAILED
            db.commit()

    return {"status": "ok"}


@router.post("/webhook")
async def paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Canonical webhook: POST /api/v1/payments/online/webhook"""
    return await process_paystack_webhook(request, background_tasks, db)


@router.post("/webhook/paystack")
async def paystack_webhook_alias(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Alias: POST /api/v1/payments/online/webhook/paystack"""
    return await process_paystack_webhook(request, background_tasks, db)


@router.get("/callback")
async def paystack_callback(reference: str = None, trxref: str = None):
    ref = (reference or trxref or "").replace('"', "")
    deep_link = f"mawuli-pta://payment-callback?reference={ref}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Payment Complete</title>
      <script>
        (function () {{
          var target = {deep_link!r};
          try {{ window.location.replace(target); }} catch (e) {{}}
          setTimeout(function () {{
            try {{ window.location.href = target; }} catch (e) {{}}
          }}, 300);
        }})();
      </script>
    </head>
    <body style="font-family:sans-serif;text-align:center;padding:48px;background:#0A1628;color:#fff;">
      <h1>Payment received</h1>
      <p>Reference: {ref}</p>
      <p>Returning you to the SchoolPulse app…</p>
      <p style="margin-top:24px;"><a href="{deep_link}" style="color:#F5C518;">Tap here if the app does not open</a></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@router.get("")
async def list_online_payments(
    student_id: UUID = None,
    academic_year: str = None,
    term: str = None,
    status: PaymentStatus = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.online")),
):
    query = db.query(Payment)
    if student_id:
        query = query.filter(Payment.student_id == str(student_id))
    if status:
        query = query.filter(Payment.status == status)
    if academic_year or term:
        query = query.join(DuesConfig, Payment.dues_config_id == DuesConfig.id)
        if academic_year:
            query = query.filter(DuesConfig.academic_year == academic_year)
        if term:
            query = query.filter(DuesConfig.term == term)

    total = query.count()
    payments = query.offset((page - 1) * limit).limit(limit).all()
    rows = []
    for payment in payments:
        student = db.query(Student).filter(Student.id == payment.student_id).first()
        rows.append(_serialize_payment(payment, student))

    return {
        "success": True,
        "data": {
            "payments": rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        },
    }


@router.get("/parent")
async def parent_payment_history(
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    """
    Legacy online-only history.
    Prefer GET /payments/parent/history for manual + online ward history.
    Scoped to linked wards (not only payments initiated by this parent).
    """
    linked_ids = [str(sid) for sid in (parent.get("matched_student_ids") or [])]
    if not linked_ids:
        return {
            "success": True,
            "data": {
                "payments": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0},
            },
        }

    query = db.query(Payment).filter(Payment.student_id.in_(linked_ids))
    total = query.count()
    payments = (
        query.order_by(Payment.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    rows = []
    for payment in payments:
        student = db.query(Student).filter(Student.id == payment.student_id).first()
        rows.append(_serialize_payment(payment, student))
    return {
        "success": True,
        "data": {
            "payments": rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit if limit else 1,
            },
        },
    }


@router.get("/{payment_id}/receipt")
async def download_online_receipt(
    payment_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    payment = db.query(Payment).filter(Payment.id == str(payment_id)).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if current_user["role"] == "PARENT":
        linked = {str(sid) for sid in (current_user.get("matched_student_ids") or [])}
        if str(payment.student_id) not in linked and payment.parent_id != current_user["id"]:
            raise HTTPException(status_code=403, detail="Not your payment")

    student = db.query(Student).filter(Student.id == payment.student_id).first()
    receipt_data = {
        "receipt_number": payment.receipt_number,
        "student_name": student.full_name if student else "Unknown",
        "amount_ghs": str(payment.amount_ghs),
        "date": payment.paid_at.strftime("%Y-%m-%d %H:%M:%S") if payment.paid_at else "",
        "type": "Online Payment",
    }
    pdf_buffer = generate_receipt(receipt_data)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=receipt_{payment.receipt_number}.pdf"},
    )

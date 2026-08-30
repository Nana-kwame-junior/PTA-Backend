"""Parent-facing payment history (manual + online) for linked wards."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_parent_match
from app.models.dues_config import DuesConfig
from app.services.receipt_pdf import build_receipt_payload, generate_receipt
from fastapi.responses import StreamingResponse
from app.models.manual_payment import ManualPayment
from app.models.payment import Payment
from app.models.student import Student

router = APIRouter(prefix="/payments/parent", tags=["Parent Payments"])


def _student_payload(student: Student | None) -> dict | None:
    if not student:
        return None
    return {
        "full_name": student.full_name,
        "index_number": student.index_number,
        "form": student.form,
        "stream": student.stream,
    }


def _sort_key(item: dict):
    raw = item.get("paid_at") or item.get("created_at") or ""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        # Normalize to naive UTC-ish for safe sorting across mixed inputs.
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return datetime.min


@router.get("/history")
async def parent_payment_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    student_id: str | None = None,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    """
    Payment history for the logged-in guardian across all linked wards.
    Includes Paystack (online) and school-recorded manual payments.
    """
    linked_ids = [str(sid) for sid in (parent.get("matched_student_ids") or [])]
    parent_id = str(parent.get("id") or "")
    if not linked_ids and not parent_id:
        return {
            "success": True,
            "data": {
                "payments": [],
                "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0},
            },
        }

    if student_id is not None and str(student_id).strip():
        sid = str(student_id).strip()
        if sid not in linked_ids:
            raise HTTPException(status_code=403, detail="Student not linked to this parent")
        student_ids = [sid]
    else:
        student_ids = linked_ids

    students = {
        s.id: s
        for s in db.query(Student).filter(Student.id.in_(student_ids)).all()
    } if student_ids else {}

    rows: list[dict] = []
    scoped_to_one_student = bool(student_id and str(student_id).strip())

    online_filters = []
    if student_ids:
        online_filters.append(Payment.student_id.in_(student_ids))
    # When listing all history, also include payments initiated by this parent
    # even if the ward link row is missing/outdated.
    if parent_id and not scoped_to_one_student:
        online_filters.append(Payment.parent_id == parent_id)

    online_payments = (
        db.query(Payment).filter(or_(*online_filters)).all() if online_filters else []
    )
    for payment in online_payments:
        student = students.get(payment.student_id)
        if student is None and payment.student_id:
            student = db.query(Student).filter(Student.id == payment.student_id).first()
            if student:
                students[student.id] = student
        status = payment.status.value if payment.status else "PENDING"
        rows.append(
            {
                "id": str(payment.id),
                "channel": "ONLINE",
                "student_id": str(payment.student_id),
                "amount_ghs": str(payment.amount_ghs),
                "status": status,
                "payment_mode": "PAYSTACK",
                "receipt_number": payment.receipt_number,
                "reference": payment.paystack_reference,
                "paystack_reference": payment.paystack_reference,
                "term": None,
                "academic_year": None,
                "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
                "created_at": payment.created_at.isoformat() if payment.created_at else None,
                "student": _student_payload(student),
            }
        )

    # Exclude allocation rows created from online Paystack (avoid double-counting).
    manual_payments = []
    if student_ids:
        manual_payments = (
            db.query(ManualPayment)
            .filter(ManualPayment.student_id.in_(student_ids))
            .filter(
                or_(
                    ManualPayment.notes.is_(None),
                    ~ManualPayment.notes.like("%Online:%"),
                )
            )
            .all()
        )
    for payment in manual_payments:
        student = students.get(payment.student_id)
        mode = payment.payment_mode.value if payment.payment_mode else "CASH"
        rows.append(
            {
                "id": str(payment.id),
                "channel": "MANUAL",
                "student_id": str(payment.student_id),
                "amount_ghs": str(payment.amount_ghs),
                "status": "COMPLETED",
                "payment_mode": mode,
                "receipt_number": payment.receipt_number,
                "reference": payment.receipt_number,
                "paystack_reference": None,
                "term": payment.term,
                "academic_year": payment.academic_year,
                "paid_at": payment.payment_date.isoformat() if payment.payment_date else None,
                "created_at": payment.recorded_at.isoformat() if payment.recorded_at else None,
                "student": _student_payload(student)
                or {
                    "full_name": payment.student_name,
                    "index_number": payment.student_index_no,
                    "form": None,
                    "stream": None,
                },
            }
        )

    rows.sort(key=_sort_key, reverse=True)
    total = len(rows)
    start = (page - 1) * limit
    page_rows = rows[start : start + limit]
    total_pages = (total + limit - 1) // limit if limit else 1

    return {
        "success": True,
        "data": {
            "payments": page_rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": total_pages,
            },
        },
    }


@router.get("/history/{payment_id}/receipt")
async def parent_payment_receipt(
    payment_id: str,
    channel: str = Query("MANUAL", pattern="^(MANUAL|ONLINE)$"),
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    """Download PDF receipt for a payment linked to this parent's ward."""
    linked_ids = {str(sid) for sid in (parent.get("matched_student_ids") or [])}
    parent_id = str(parent.get("id") or "")

    if channel == "ONLINE":
        payment = db.query(Payment).filter(Payment.id == str(payment_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if str(payment.student_id) not in linked_ids and payment.parent_id != parent_id:
            raise HTTPException(status_code=403, detail="Not your payment")
        student = db.query(Student).filter(Student.id == payment.student_id).first()
        dues = (
            db.query(DuesConfig).filter(DuesConfig.id == payment.dues_config_id).first()
            if payment.dues_config_id
            else None
        )
        receipt_data = build_receipt_payload(
            receipt_number=payment.receipt_number or payment.paystack_reference,
            student_name=student.full_name if student else "Unknown",
            student_index=student.index_number if student else None,
            amount_ghs=str(payment.amount_ghs),
            payment_date=payment.paid_at.strftime("%d %b %Y %H:%M") if payment.paid_at else "",
            channel="Online payment (Paystack)",
            payment_mode="Paystack",
            term=dues.term if dues else None,
            academic_year=dues.academic_year if dues else None,
            recorded_by="Online",
            reference=payment.paystack_reference,
        )
    else:
        payment = db.query(ManualPayment).filter(ManualPayment.id == str(payment_id)).first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if str(payment.student_id) not in linked_ids:
            raise HTTPException(status_code=403, detail="Not your ward's payment")
        mode = payment.payment_mode.value if payment.payment_mode else "CASH"
        receipt_data = build_receipt_payload(
            receipt_number=payment.receipt_number,
            student_name=payment.student_name,
            student_index=payment.student_index_no,
            amount_ghs=str(payment.amount_ghs),
            payment_date=payment.payment_date.strftime("%d %b %Y %H:%M") if payment.payment_date else "",
            channel="School payment (manual)",
            payment_mode=mode.replace("_", " ").title(),
            term=payment.term,
            academic_year=payment.academic_year,
            recorded_by=payment.recorded_by_name,
            reference=payment.receipt_number,
        )

    pdf_buffer = generate_receipt(receipt_data)
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=receipt_{receipt_data['receipt_number']}.pdf"
        },
    )

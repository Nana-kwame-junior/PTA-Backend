"""Parent-facing payment history (manual + online) for linked wards."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_parent_match
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
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


@router.get("/history")
async def parent_payment_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    student_id: UUID | None = None,
    db: Session = Depends(get_db),
    parent=Depends(require_parent_match),
):
    """
    Payment history for the logged-in guardian across all linked wards.
    Includes Paystack (online) and school-recorded manual payments.
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

    if student_id is not None:
        sid = str(student_id)
        if sid not in linked_ids:
            raise HTTPException(status_code=403, detail="Student not linked to this parent")
        student_ids = [sid]
    else:
        student_ids = linked_ids

    students = {
        s.id: s
        for s in db.query(Student).filter(Student.id.in_(student_ids)).all()
    }

    rows: list[dict] = []

    online_payments = (
        db.query(Payment)
        .filter(Payment.student_id.in_(student_ids))
        .all()
    )
    for payment in online_payments:
        student = students.get(payment.student_id)
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

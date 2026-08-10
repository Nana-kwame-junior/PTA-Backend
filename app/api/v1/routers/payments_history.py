"""Staff-facing unified payment history (manual + online) across BASIC and SHS."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_permission
from app.models.class_level import Track
from app.models.dues_config import DuesConfig
from app.models.manual_payment import ManualPayment
from app.models.payment import Payment, PaymentStatus
from app.models.student import Student

router = APIRouter(prefix="/payments/history", tags=["Payment History"])

TrackFilter = Literal["BASIC", "SHS"]


def _track_value(student: Student | None) -> str:
    if not student or not student.track:
        return "BASIC"
    return student.track.value if hasattr(student.track, "value") else str(student.track)


@router.get("")
async def staff_payment_history(
    track: Optional[TrackFilter] = Query(
        None,
        description="Filter by student track. Omit for both BASIC and SHS.",
    ),
    channel: Optional[Literal["MANUAL", "ONLINE"]] = Query(
        None,
        description="Filter by payment channel. Omit for both.",
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.history")),
):
    rows: list[dict] = []

    if channel in (None, "MANUAL"):
        mq = db.query(ManualPayment, Student).outerjoin(
            Student, Student.id == ManualPayment.student_id
        )
        if track == "BASIC":
            mq = mq.filter((Student.track == Track.BASIC) | (Student.track.is_(None)))
        elif track == "SHS":
            mq = mq.filter(Student.track == Track.SHS)
        for payment, student in mq.all():
            paid_at = payment.payment_date or payment.recorded_at
            rows.append(
                {
                    "id": str(payment.id),
                    "channel": "MANUAL",
                    "receipt_number": payment.receipt_number,
                    "student_id": str(payment.student_id),
                    "student_name": payment.student_name
                    or (student.full_name if student else None),
                    "student_index_no": payment.student_index_no
                    or (student.index_number if student else None),
                    "track": _track_value(student),
                    "term": payment.term,
                    "academic_year": payment.academic_year,
                    "amount_ghs": str(payment.amount_ghs),
                    "payment_mode": (
                        payment.payment_mode.value
                        if hasattr(payment.payment_mode, "value")
                        else str(payment.payment_mode or "MANUAL")
                    ),
                    "status": (
                        "Flagged"
                        if payment.is_flagged
                        else "Locked"
                        if payment.is_locked
                        else "Verified"
                    ),
                    "recorded_by_name": payment.recorded_by_name,
                    "reference": None,
                    "payment_date": paid_at.isoformat() if paid_at else None,
                    "sort_at": paid_at or datetime.min,
                    "is_flagged": bool(payment.is_flagged),
                    "is_locked": bool(payment.is_locked),
                }
            )

    if channel in (None, "ONLINE"):
        oq = (
            db.query(Payment, Student, DuesConfig)
            .outerjoin(Student, Student.id == Payment.student_id)
            .outerjoin(DuesConfig, DuesConfig.id == Payment.dues_config_id)
            .filter(Payment.status == PaymentStatus.COMPLETED)
        )
        if track == "BASIC":
            oq = oq.filter((Student.track == Track.BASIC) | (Student.track.is_(None)))
        elif track == "SHS":
            oq = oq.filter(Student.track == Track.SHS)
        for payment, student, dues in oq.all():
            paid_at = payment.paid_at or payment.created_at
            rows.append(
                {
                    "id": str(payment.id),
                    "channel": "ONLINE",
                    "receipt_number": payment.receipt_number,
                    "student_id": str(payment.student_id),
                    "student_name": student.full_name if student else None,
                    "student_index_no": student.index_number if student else None,
                    "track": _track_value(student),
                    "term": dues.term if dues else None,
                    "academic_year": dues.academic_year if dues else None,
                    "amount_ghs": str(payment.amount_ghs),
                    "payment_mode": "PAYSTACK",
                    "status": "Completed",
                    "recorded_by_name": "Paystack",
                    "reference": payment.paystack_reference,
                    "payment_date": paid_at.isoformat() if paid_at else None,
                    "sort_at": paid_at or datetime.min,
                    "is_flagged": False,
                    "is_locked": True,
                }
            )

    rows.sort(key=lambda r: r["sort_at"], reverse=True)
    total = len(rows)
    start = (page - 1) * limit
    page_rows = rows[start : start + limit]
    for row in page_rows:
        row.pop("sort_at", None)

    return {
        "success": True,
        "data": {
            "payments": page_rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit if limit else 1,
            },
        },
    }

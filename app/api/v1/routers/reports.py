from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from decimal import Decimal
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_permission
from app.models.payment import Payment, PaymentStatus
from app.models.manual_payment import ManualPayment
from app.models.student import Student
from app.models.dues_config import DuesConfig
from app.models.user import User
from app.models.expenditure import Expenditure
from app.models.class_level import Track
from app.schemas.report import ExpenditureCreate
from app.services.report_generator import generate_financial_report_excel
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/reports", tags=["Reports"])


def _term_payment_filters(db, academic_year: str, term: str):
    """Base filters for online payments scoped to a year/term."""
    return (
        db.query(Payment)
        .join(DuesConfig, Payment.dues_config_id == DuesConfig.id)
        .filter(
            DuesConfig.academic_year == academic_year,
            DuesConfig.term == term,
            Payment.status == PaymentStatus.COMPLETED,
        )
    )


@router.get("/financial")
async def financial_report(
    academic_year: str,
    term: str,
    track: Optional[str] = Query(None, description="Optional track filter: BASIC or SHS"),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("reports")),
):
    dues = (
        db.query(DuesConfig)
        .filter(
            DuesConfig.academic_year == academic_year,
            DuesConfig.term == term,
            DuesConfig.is_active == True,
        )
        .first()
    )
    # Allow reports even when dues config is missing for a track/term
    # (e.g. SHS current term before dues are published).
    dues_amount = dues.amount_ghs if dues else Decimal("0")

    track_enum: Optional[Track] = None
    if track:
        t = str(track).strip().upper()
        if t not in {"BASIC", "SHS"}:
            raise HTTPException(status_code=400, detail="track must be one of: BASIC, SHS")
        track_enum = Track.BASIC if t == "BASIC" else Track.SHS

    # Prefer track-scoped active students; academic_year on student can lag term year.
    student_filters = [Student.is_active == True]
    if track_enum is not None:
        student_filters.append(Student.track == track_enum)
    else:
        student_filters.append(Student.academic_year == academic_year)

    total_students = (
        db.query(Student).filter(*student_filters).count()
    )

    online_query = _term_payment_filters(db, academic_year, term)
    if track_enum is not None:
        online_query = online_query.join(Student, Payment.student_id == Student.id).filter(
            Student.track == track_enum
        )
    online_paid = online_query.all()
    online_collected = sum(p.amount_ghs for p in online_paid) if online_paid else Decimal(0)

    manual_query = db.query(ManualPayment).filter(
        ManualPayment.academic_year == academic_year, ManualPayment.term == term
    )
    if track_enum is not None:
        manual_query = manual_query.join(Student, ManualPayment.student_id == Student.id).filter(
            Student.track == track_enum
        )
    manual_paid = manual_query.all()
    manual_collected = sum(m.amount_ghs for m in manual_paid) if manual_paid else Decimal(0)

    total_collected = online_collected + manual_collected
    expected_total = dues_amount * total_students
    paid_student_ids = {p.student_id for p in online_paid} | {m.student_id for m in manual_paid}
    paid_count = len(paid_student_ids)
    unpaid_count = max(total_students - paid_count, 0)

    forms = (
        db.query(Student.form)
        .filter(*student_filters)
        .distinct()
        .all()
    )
    by_form = []
    for form_row in forms:
        form_name = form_row[0]
        if not form_name:
            continue
        form_student_filters = list(student_filters) + [Student.form == form_name]
        students_in_form = (
            db.query(Student)
            .filter(*form_student_filters)
            .count()
        )
        online_in_form_query = _term_payment_filters(db, academic_year, term).join(
            Student, Payment.student_id == Student.id
        ).filter(Student.form == form_name)
        if track_enum is not None:
            online_in_form_query = online_in_form_query.filter(Student.track == track_enum)
        online_in_form = online_in_form_query.count()

        manual_in_form_query = (
            db.query(ManualPayment)
            .join(Student, ManualPayment.student_id == Student.id)
            .filter(
                ManualPayment.academic_year == academic_year,
                ManualPayment.term == term,
                Student.form == form_name,
            )
        )
        if track_enum is not None:
            manual_in_form_query = manual_in_form_query.filter(Student.track == track_enum)
        manual_in_form = manual_in_form_query.count()

        paid_in_form = len(
            {
                p.student_id
                for p in (
                    _term_payment_filters(db, academic_year, term)
                    .join(Student, Payment.student_id == Student.id)
                    .filter(Student.form == form_name)
                    .filter(*([Student.track == track_enum] if track_enum is not None else []))
                    .all()
                )
            }
            | {
                m.student_id
                for m in (
                    db.query(ManualPayment)
                    .join(Student, ManualPayment.student_id == Student.id)
                    .filter(
                        ManualPayment.academic_year == academic_year,
                        ManualPayment.term == term,
                        Student.form == form_name,
                    )
                    .filter(*([Student.track == track_enum] if track_enum is not None else []))
                    .all()
                )
            }
        )
        online_amounts = [
            row[0]
            for row in (
                _term_payment_filters(db, academic_year, term)
                .join(Student, Payment.student_id == Student.id)
                .filter(Student.form == form_name)
                .filter(*([Student.track == track_enum] if track_enum is not None else []))
                .with_entities(Payment.amount_ghs)
                .all()
            )
        ]
        manual_amounts = [
            row[0]
            for row in (
                db.query(ManualPayment)
                .join(Student, ManualPayment.student_id == Student.id)
                .filter(
                    ManualPayment.academic_year == academic_year,
                    ManualPayment.term == term,
                    Student.form == form_name,
                )
                .filter(*([Student.track == track_enum] if track_enum is not None else []))
                .with_entities(ManualPayment.amount_ghs)
                .all()
            )
        ]
        total_form_collected = sum(online_amounts + manual_amounts, Decimal(0))
        by_form.append(
            {
                "form": form_name,
                "total": students_in_form,
                "paid": paid_in_form,
                "payment_rate_percent": round(paid_in_form / students_in_form * 100, 1)
                if students_in_form
                else 0,
                "collected_ghs": str(total_form_collected),
            }
        )

    staff_records = (
        db.query(ManualPayment.recorded_by_user_id, User.name)
        .join(User, ManualPayment.recorded_by_user_id == User.id)
        .filter(ManualPayment.academic_year == academic_year, ManualPayment.term == term)
        .group_by(ManualPayment.recorded_by_user_id, User.name)
        .all()
    )
    by_staff = []
    for staff_id, staff_name in staff_records:
        count = (
            db.query(ManualPayment)
            .filter(
                ManualPayment.recorded_by_user_id == staff_id,
                ManualPayment.academic_year == academic_year,
                ManualPayment.term == term,
            )
            .count()
        )
        total = (
            db.query(ManualPayment)
            .filter(
                ManualPayment.recorded_by_user_id == staff_id,
                ManualPayment.academic_year == academic_year,
                ManualPayment.term == term,
            )
            .with_entities(ManualPayment.amount_ghs)
            .all()
        )
        total_sum = sum([t[0] for t in total], Decimal(0)) if total else Decimal(0)
        by_staff.append(
            {
                "staff_id": staff_id,
                "staff_name": staff_name,
                "manual_payments_count": count,
                "manual_total_ghs": str(total_sum),
            }
        )

    return {
        "success": True,
        "data": {
            "academic_year": academic_year,
            "term": term,
            "track": track_enum.value if track_enum else None,
            "dues_configured": dues is not None,
            "dues_amount_ghs": str(dues_amount),
            "total_students": total_students,
            "expected_total_ghs": str(expected_total),
            "total_collected_ghs": str(total_collected),
            "online_collected_ghs": str(online_collected),
            "manual_collected_ghs": str(manual_collected),
            "paid_count": paid_count,
            "unpaid_count": unpaid_count,
            "payment_rate_percent": round(paid_count / total_students * 100, 1)
            if total_students
            else 0,
            "by_form": by_form,
            "by_staff": [
                {
                    "staff_name": row["staff_name"],
                    "count": row["manual_payments_count"],
                    "total_ghs": row["manual_total_ghs"],
                }
                for row in by_staff
            ],
        },
    }


@router.get("/defaulters")
async def list_defaulters(
    academic_year: str,
    term: str,
    form: Optional[str] = None,
    stream: Optional[str] = None,
    format: str = "json",
    db: Session = Depends(get_db),
    staff=Depends(require_permission("reports")),
):
    dues = (
        db.query(DuesConfig)
        .filter(DuesConfig.academic_year == academic_year, DuesConfig.term == term)
        .first()
    )
    if not dues:
        raise HTTPException(status_code=404, detail="Dues not configured")
    paid_online_ids = [
        p.student_id
        for p in db.query(Payment)
        .filter(Payment.dues_config_id == dues.id, Payment.status == PaymentStatus.COMPLETED)
        .all()
    ]
    paid_manual_ids = [
        m.student_id
        for m in db.query(ManualPayment)
        .filter(ManualPayment.academic_year == academic_year, ManualPayment.term == term)
        .all()
    ]
    paid_student_ids = set(paid_online_ids + paid_manual_ids)

    query = db.query(Student).filter(
        Student.academic_year == academic_year, Student.is_active == True
    )
    if form:
        query = query.filter(Student.form == form)
    if stream:
        query = query.filter(Student.stream == stream)
    defaulters = [s for s in query.all() if s.id not in paid_student_ids]

    if format == "csv":
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["index_number", "full_name", "form", "stream", "parent_phone"])
        for s in defaulters:
            writer.writerow([s.index_number, s.full_name, s.form, s.stream, s.parent_phone_1])
        return StreamingResponse(iter([output.getvalue()]), media_type="text/csv")
    return {"success": True, "data": {"defaulters": defaulters}}


@router.get("/export")
async def export_financial_report(
    academic_year: str,
    term: str,
    format: str = "excel",
    db: Session = Depends(get_db),
    staff=Depends(require_permission("reports")),
):
    excel_data = generate_financial_report_excel(db, academic_year, term)
    return StreamingResponse(
        excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=financial_{academic_year}_{term}.xlsx"},
    )


@router.post("/expenditures")
async def create_expenditure(
    req: ExpenditureCreate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("reports")),
):
    row = Expenditure(
        description=req.description,
        amount_ghs=req.amount_ghs,
        date=req.date or datetime.utcnow(),
        academic_year=req.academic_year,
        term=req.term,
        recorded_by_user_id=staff["id"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "success": True,
        "data": {
            "id": row.id,
            "description": row.description,
            "amount_ghs": str(row.amount_ghs),
            "date": row.date.isoformat(),
            "academic_year": row.academic_year,
            "term": row.term,
        },
    }


@router.get("/expenditures")
async def list_expenditures(
    academic_year: Optional[str] = None,
    term: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("reports")),
):
    query = db.query(Expenditure)
    if academic_year:
        query = query.filter(Expenditure.academic_year == academic_year)
    if term:
        query = query.filter(Expenditure.term == term)
    query = query.order_by(Expenditure.date.desc())
    total = query.count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "success": True,
        "data": {
            "expenditures": [
                {
                    "id": row.id,
                    "description": row.description,
                    "amount_ghs": str(row.amount_ghs),
                    "date": row.date.isoformat(),
                    "academic_year": row.academic_year,
                    "term": row.term,
                }
                for row in rows
            ],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit if total else 0,
            },
        },
    }

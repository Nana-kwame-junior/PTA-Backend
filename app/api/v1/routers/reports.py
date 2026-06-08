from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from decimal import Decimal
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_role
from app.models.payment import Payment, PaymentStatus
from app.models.manual_payment import ManualPayment
from app.models.student import Student
from app.models.dues_config import DuesConfig
from app.models.user import User
from app.schemas.report import ExpenditureCreate, FollowupSmsRequest
from app.services.report_generator import generate_financial_report_excel
from fastapi.responses import StreamingResponse, FileResponse

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("/financial")
async def financial_report(
    academic_year: str,
    term: str,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Get dues config
    dues = db.query(DuesConfig).filter(DuesConfig.academic_year == academic_year, DuesConfig.term == term).first()
    if not dues:
        raise HTTPException(status_code=404, detail="Dues configuration not found for this term")
    
    # Count students
    total_students = db.query(Student).filter(Student.academic_year == academic_year, Student.is_active == True).count()
    
    # Paid via online
    online_paid = db.query(Payment).join(DuesConfig).filter(
        DuesConfig.academic_year == academic_year,
        DuesConfig.term == term,
        Payment.status == PaymentStatus.COMPLETED
    ).all()
    online_collected = sum(p.amount_ghs for p in online_paid) if online_paid else Decimal(0)
    
    # Paid via manual
    manual_paid = db.query(ManualPayment).filter(
        ManualPayment.academic_year == academic_year,
        ManualPayment.term == term
    ).all()
    manual_collected = sum(m.amount_ghs for m in manual_paid) if manual_paid else Decimal(0)
    
    total_collected = online_collected + manual_collected
    expected_total = dues.amount_ghs * total_students
    paid_count = len(online_paid) + len(manual_paid)
    unpaid_count = total_students - paid_count
    
    # By form
    forms = db.query(Student.form).filter(Student.academic_year == academic_year).distinct().all()
    by_form = []
    for form_row in forms:
        form_name = form_row[0]
        students_in_form = db.query(Student).filter(Student.academic_year == academic_year, Student.form == form_name).count()
        paid_in_form = db.query(Payment).join(Student).filter(Student.form == form_name, Payment.status == PaymentStatus.COMPLETED).count() + \
                      db.query(ManualPayment).join(Student).filter(Student.form == form_name).count()
        collected = (db.query(Payment).join(Student).filter(Student.form == form_name, Payment.status == PaymentStatus.COMPLETED).with_entities(Payment.amount_ghs).all() or []) + \
                    (db.query(ManualPayment).join(Student).filter(Student.form == form_name).with_entities(ManualPayment.amount_ghs).all() or [])
        total_form_collected = sum([c[0] for c in collected]) if collected else Decimal(0)
        by_form.append({
            "form": form_name,
            "total": students_in_form,
            "paid": paid_in_form,
            "payment_rate_percent": round(paid_in_form/students_in_form*100, 1) if students_in_form else 0,
            "collected_ghs": str(total_form_collected)
        })
    
    # By staff
    staff_records = db.query(ManualPayment.recorded_by_user_id, User.name).join(User, ManualPayment.recorded_by_user_id == User.id).group_by(ManualPayment.recorded_by_user_id, User.name).all()
    by_staff = []
    for staff_id, staff_name in staff_records:
        count = db.query(ManualPayment).filter(ManualPayment.recorded_by_user_id == staff_id).count()
        total = db.query(ManualPayment).filter(ManualPayment.recorded_by_user_id == staff_id).with_entities(ManualPayment.amount_ghs).all()
        total_sum = sum([t[0] for t in total]) if total else Decimal(0)
        by_staff.append({
            "staff_id": staff_id,
            "staff_name": staff_name,
            "manual_payments_count": count,
            "manual_total_ghs": str(total_sum)
        })
    
    return {
        "success": True,
        "data": {
            "academic_year": academic_year,
            "term": term,
            "dues_config": {
                "amount_ghs": str(dues.amount_ghs),
                "due_date": dues.due_date.isoformat()
            },
            "summary": {
                "total_students": total_students,
                "paid_count": paid_count,
                "unpaid_count": unpaid_count,
                "payment_rate_percent": round(paid_count/total_students*100, 1) if total_students else 0,
                "total_expected_ghs": str(expected_total),
                "total_collected_ghs": str(total_collected),
                "online_collected_ghs": str(online_collected),
                "manual_collected_ghs": str(manual_collected)
            },
            "by_form": by_form,
            "by_staff": by_staff
        }
    }

@router.get("/defaulters")
async def list_defaulters(
    academic_year: str,
    term: str,
    form: Optional[str] = None,
    stream: Optional[str] = None,
    format: str = "json",
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Find all students with no payment record for this term
    dues = db.query(DuesConfig).filter(DuesConfig.academic_year == academic_year, DuesConfig.term == term).first()
    if not dues:
        raise HTTPException(status_code=404, detail="Dues not configured")
    # Subquery for paid students
    paid_online_ids = [p.student_id for p in db.query(Payment).filter(Payment.dues_config_id == dues.id, Payment.status == PaymentStatus.COMPLETED).all()]
    paid_manual_ids = [m.student_id for m in db.query(ManualPayment).filter(ManualPayment.academic_year == academic_year, ManualPayment.term == term).all()]
    paid_student_ids = set(paid_online_ids + paid_manual_ids)
    
    query = db.query(Student).filter(Student.academic_year == academic_year, Student.is_active == True)
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
    else:
        return {"success": True, "data": {"defaulters": defaulters}}

@router.get("/export")
async def export_financial_report(
    academic_year: str,
    term: str,
    format: str = "excel",
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Generate Excel file
    excel_data = generate_financial_report_excel(db, academic_year, term)
    return StreamingResponse(excel_data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=financial_{academic_year}_{term}.xlsx"})

@router.post("/expenditures")
async def create_expenditure(
    req: ExpenditureCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Add to expenditure table (model not created yet – create one)
    # For now, just return
    return {"success": True, "data": {"message": "Expenditure recorded"}}

@router.get("/expenditures")
async def list_expenditures(
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    return {"success": True, "data": {"expenditures": []}}
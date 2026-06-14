from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from datetime import timedelta

from app.core.database import get_db
from app.core.security import require_permission
from app.models.dues_config import DuesConfig
from app.models.academic import AcademicTerm
from app.schemas.dues import DuesConfigCreate, DuesConfigUpdate
from app.services.activity_log import log_staff_activity
from app.workers.sms_tasks import send_dues_reminder

router = APIRouter(prefix="/dues", tags=["Dues Configuration"])


def _serialize_dues(row: DuesConfig) -> dict:
    return {
        "id": str(row.id),
        "academic_year": row.academic_year,
        "term": row.term,
        "amount_ghs": str(row.amount_ghs),
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "grace_period_days": row.grace_period_days,
        "late_fee_ghs": str(row.late_fee_ghs) if row.late_fee_ghs is not None else None,
        "is_active": row.is_active,
    }


@router.post("")
async def create_dues_config(
    req: DuesConfigCreate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.dues")),
):
    existing = db.query(DuesConfig).filter(
        DuesConfig.academic_year == req.academic_year,
        DuesConfig.term == req.term,
        DuesConfig.is_active == True,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Dues configuration already exists for this term/year")
    dues = DuesConfig(**req.dict())
    db.add(dues)
    db.commit()
    db.refresh(dues)

    send_dues_reminder.apply_async(args=[str(dues.id), "D3"], eta=dues.due_date - timedelta(days=3))
    send_dues_reminder.apply_async(args=[str(dues.id), "D1"], eta=dues.due_date - timedelta(days=1))
    send_dues_reminder.apply_async(args=[str(dues.id), "OVERDUE"], eta=dues.due_date + timedelta(days=1))

    log_staff_activity(
        db,
        staff,
        page_label="Dues Configuration",
        action_label=f"Created dues for {dues.term} {dues.academic_year}",
        details=f"GH₵{dues.amount_ghs}",
    )
    return {"success": True, "data": _serialize_dues(dues)}


@router.get("")
async def list_dues_configs(
    academic_year: Optional[str] = None,
    term: Optional[str] = None,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.dues")),
):
    query = db.query(DuesConfig).filter(DuesConfig.is_active == True)
    if academic_year:
        query = query.filter(DuesConfig.academic_year == academic_year)
    if term:
        query = query.filter(DuesConfig.term == term)
    configs = query.all()
    return {"success": True, "data": [_serialize_dues(c) for c in configs]}


@router.get("/current")
async def get_current_dues(db: Session = Depends(get_db)):
    """Public — current dues for the active academic term."""
    current_term = db.query(AcademicTerm).filter(AcademicTerm.is_current == True).first()
    query = db.query(DuesConfig).filter(DuesConfig.is_active == True)
    if current_term:
        query = query.filter(
            DuesConfig.academic_year == current_term.academic_year,
            DuesConfig.term == current_term.name,
        )
    config = query.order_by(DuesConfig.due_date.desc()).first()
    if not config:
        return {"success": True, "data": None}
    return {"success": True, "data": _serialize_dues(config)}


@router.patch("/{config_id}")
async def update_dues_config(
    config_id: UUID,
    req: DuesConfigUpdate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.dues")),
):
    dues = db.query(DuesConfig).filter(DuesConfig.id == str(config_id), DuesConfig.is_active == True).first()
    if not dues:
        raise HTTPException(status_code=404)
    old_due_date = dues.due_date
    for key, value in req.dict(exclude_unset=True).items():
        setattr(dues, key, value)
    db.commit()
    if req.due_date and req.due_date != old_due_date:
        send_dues_reminder.apply_async(args=[str(dues.id), "D3"], eta=dues.due_date - timedelta(days=3))
        send_dues_reminder.apply_async(args=[str(dues.id), "D1"], eta=dues.due_date - timedelta(days=1))
        send_dues_reminder.apply_async(args=[str(dues.id), "OVERDUE"], eta=dues.due_date + timedelta(days=1))
    log_staff_activity(
        db,
        staff,
        page_label="Dues Configuration",
        action_label=f"Updated dues for {dues.term} {dues.academic_year}",
    )
    return {"success": True, "data": {"id": str(config_id), "updated": True}}


@router.delete("/{config_id}")
async def deactivate_dues_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("payments.dues")),
):
    dues = db.query(DuesConfig).filter(DuesConfig.id == str(config_id)).first()
    if not dues:
        raise HTTPException(status_code=404)
    label = f"{dues.term} {dues.academic_year}"
    dues.is_active = False
    db.commit()
    log_staff_activity(
        db,
        staff,
        page_label="Dues Configuration",
        action_label=f"Removed dues config: {label}",
        details="Soft deleted",
    )
    return {"success": True, "data": {"message": "Dues configuration removed"}}

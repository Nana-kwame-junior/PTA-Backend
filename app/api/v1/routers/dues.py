from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from datetime import timedelta

from app.core.database import get_db
from app.core.security import require_role, get_current_user
from app.models.dues_config import DuesConfig
from app.schemas.dues import DuesConfigCreate, DuesConfigUpdate
from app.workers.sms_tasks import send_dues_reminder

router = APIRouter(prefix="/dues", tags=["Dues Configuration"])

@router.post("")
async def create_dues_config(
    req: DuesConfigCreate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Check if already exists
    existing = db.query(DuesConfig).filter(
        DuesConfig.academic_year == req.academic_year,
        DuesConfig.term == req.term
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Dues configuration already exists for this term/year")
    dues = DuesConfig(**req.dict())
    db.add(dues)
    db.commit()
    db.refresh(dues)

    # Schedule reminder jobs
    # D3
    send_dues_reminder.apply_async(
        args=[str(dues.id), "D3"],
        eta=dues.due_date - timedelta(days=3)
    )
    # D1
    send_dues_reminder.apply_async(
        args=[str(dues.id), "D1"],
        eta=dues.due_date - timedelta(days=1)
    )
    # OVERDUE (next day)
    send_dues_reminder.apply_async(
        args=[str(dues.id), "OVERDUE"],
        eta=dues.due_date + timedelta(days=1)
    )

    return {"success": True, "data": {"id": str(dues.id), **req.dict()}}

@router.get("")
async def list_dues_configs(
    academic_year: Optional[str] = None,
    term: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("FINANCIAL_STAFF"))
):
    query = db.query(DuesConfig)
    if academic_year:
        query = query.filter(DuesConfig.academic_year == academic_year)
    if term:
        query = query.filter(DuesConfig.term == term)
    configs = query.all()
    return {"success": True, "data": configs}

@router.get("/current")
async def get_current_dues(
    db: Session = Depends(get_db),
):
    """Public — current dues amount is not sensitive."""
    config = db.query(DuesConfig).order_by(DuesConfig.due_date.desc()).first()
    if not config:
        return {"success": True, "data": None}
    return {
        "success": True,
        "data": {
            "id": str(config.id),
            "academic_year": config.academic_year,
            "term": config.term,
            "amount_ghs": str(config.amount_ghs),
            "due_date": config.due_date.isoformat() if config.due_date else None,
            "grace_period_days": config.grace_period_days,
        },
    }

@router.patch("/{config_id}")
async def update_dues_config(
    config_id: UUID,
    req: DuesConfigUpdate,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    dues = db.query(DuesConfig).filter(DuesConfig.id == str(config_id)).first()
    if not dues:
        raise HTTPException(status_code=404)
    old_due_date = dues.due_date
    for key, value in req.dict(exclude_unset=True).items():
        setattr(dues, key, value)
    db.commit()
    if req.due_date and req.due_date != old_due_date:
        # Cancel old jobs and reschedule (similar to create)
        # Since we don't store Celery task IDs, we simply schedule new ones.
        # In production, you would cancel specific tasks.
        send_dues_reminder.apply_async(
            args=[str(dues.id), "D3"],
            eta=dues.due_date - timedelta(days=3)
        )
        send_dues_reminder.apply_async(
            args=[str(dues.id), "D1"],
            eta=dues.due_date - timedelta(days=1)
        )
        send_dues_reminder.apply_async(
            args=[str(dues.id), "OVERDUE"],
            eta=dues.due_date + timedelta(days=1)
        )
    return {"success": True, "data": {"id": str(config_id), "updated": True}}
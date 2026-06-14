from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.core.database import get_db
from app.core.security import require_role
from app.models.academic import AcademicYear, AcademicTerm, TermStatus
from app.services.promotion import promote_students_for_year

router = APIRouter(prefix="/admin/academic", tags=["Academic Calendar"])


def _serialize_year(row: AcademicYear) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_term(row: AcademicTerm) -> dict:
    return {
        "id": row.id,
        "academic_year_id": row.academic_year_id,
        "academic_year": row.academic_year,
        "name": row.name,
        "sequence": row.sequence,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status.value,
        "is_current": row.is_current,
        "auto_promote_on_close": row.auto_promote_on_close,
    }


@router.post("/years")
async def create_academic_year(
    body: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label is required (e.g. 2024/2025)")
    existing = db.query(AcademicYear).filter(AcademicYear.label == label).first()
    if existing:
        raise HTTPException(status_code=409, detail="Academic year already exists")
    row = AcademicYear(label=label, is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "data": _serialize_year(row)}


@router.get("/years")
async def list_academic_years(
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    rows = db.query(AcademicYear).order_by(AcademicYear.label.desc()).all()
    return {"success": True, "data": {"years": [_serialize_year(r) for r in rows]}}


@router.post("/years/{year_id}/terms")
async def create_academic_term(
    year_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    year = db.query(AcademicYear).filter(AcademicYear.id == str(year_id)).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")

    name = (body.get("name") or "").strip()
    sequence = body.get("sequence")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    if not name or sequence is None or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="name, sequence, start_date, end_date are required")

    exists = (
        db.query(AcademicTerm)
        .filter(AcademicTerm.academic_year_id == year.id, AcademicTerm.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail=f"{name} already exists for {year.label}")

    term = AcademicTerm(
        academic_year_id=year.id,
        academic_year=year.label,
        name=name,
        sequence=int(sequence),
        start_date=datetime.fromisoformat(start_date.replace("Z", "+00:00")),
        end_date=datetime.fromisoformat(end_date.replace("Z", "+00:00")),
        status=TermStatus.PLANNED,
        is_current=False,
        auto_promote_on_close=body.get("auto_promote_on_close", True),
    )
    db.add(term)
    db.commit()
    db.refresh(term)
    return {"success": True, "data": _serialize_term(term)}


@router.get("/years/{year_id}/terms")
async def list_terms_for_year(
    year_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    rows = (
        db.query(AcademicTerm)
        .filter(AcademicTerm.academic_year_id == str(year_id))
        .order_by(AcademicTerm.sequence.asc())
        .all()
    )
    return {"success": True, "data": {"terms": [_serialize_term(r) for r in rows]}}


@router.get("/terms")
async def list_all_terms(
    academic_year: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("FINANCIAL_STAFF")),
):
    query = db.query(AcademicTerm)
    if academic_year:
        query = query.filter(AcademicTerm.academic_year == academic_year)
    rows = query.order_by(AcademicTerm.academic_year.desc(), AcademicTerm.sequence.asc()).all()
    return {"success": True, "data": {"terms": [_serialize_term(r) for r in rows]}}


@router.get("/current")
async def get_current_term(db: Session = Depends(get_db)):
    term = db.query(AcademicTerm).filter(AcademicTerm.is_current == True).first()
    if not term:
        return {"success": True, "data": None}
    return {"success": True, "data": _serialize_term(term)}


@router.post("/terms/{term_id}/activate")
async def activate_term(
    term_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    term = db.query(AcademicTerm).filter(AcademicTerm.id == str(term_id)).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.status == TermStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Cannot activate a closed term")

    db.query(AcademicTerm).filter(AcademicTerm.is_current == True).update({"is_current": False})
    term.is_current = True
    term.status = TermStatus.ACTIVE
    db.commit()
    db.refresh(term)
    return {"success": True, "data": _serialize_term(term)}


@router.post("/terms/{term_id}/close")
async def close_term(
    term_id: UUID,
    body: dict | None = None,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN")),
):
    term = db.query(AcademicTerm).filter(AcademicTerm.id == str(term_id)).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.status == TermStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Term is already closed")

    promote = body.get("promote_students") if body else None
    if promote is None:
        promote = term.auto_promote_on_close

    term.status = TermStatus.CLOSED
    if term.is_current:
        term.is_current = False

    promotion_result = None
    if promote:
        promotion_result = promote_students_for_year(db, term.academic_year)
    db.commit()
    db.refresh(term)
    return {
        "success": True,
        "data": {
            "term": _serialize_term(term),
            "promotion": promotion_result,
        },
    }

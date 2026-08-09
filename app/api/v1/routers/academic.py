from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.core.database import get_db
from app.core.security import require_permission, get_current_user
from app.models.academic import AcademicYear, AcademicTerm, TermStatus
from app.models.class_level import Track
from app.services.promotion import promote_students_for_year

router = APIRouter(prefix="/admin/academic", tags=["Academic Calendar"])


def _serialize_year(row: AcademicYear) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "track": str(row.track.value) if hasattr(row.track, 'value') else str(row.track) if row.track else None,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_term(row: AcademicTerm) -> dict:
    return {
        "id": row.id,
        "academic_year_id": row.academic_year_id,
        "academic_year": row.academic_year,
        "track": str(row.track.value) if hasattr(row.track, 'value') else str(row.track) if row.track else None,
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
    admin=Depends(require_permission("academic")),
):
    label = (body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="label is required (e.g. 2024/2025)")
    track_raw = body.get("track")
    if track_raw is None:
        track_value = Track.BASIC
    else:
        track_str = str(track_raw).strip().upper()
        if track_str not in {"BASIC", "SHS"}:
            raise HTTPException(status_code=400, detail="track must be one of: BASIC, SHS")
        track_value = Track.BASIC if track_str == "BASIC" else Track.SHS
    existing = db.query(AcademicYear).filter(AcademicYear.label == label).first()
    if existing:
        raise HTTPException(status_code=409, detail="Academic year already exists")
    row = AcademicYear(label=label, track=track_value, is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "data": _serialize_year(row)}


@router.get("/years")
async def list_academic_years(
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    rows = db.query(AcademicYear).order_by(AcademicYear.label.desc()).all()
    return {"success": True, "data": {"years": [_serialize_year(r) for r in rows]}}


@router.post("/years/{year_id}/terms")
async def create_academic_term(
    year_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    year = db.query(AcademicYear).filter(AcademicYear.id == str(year_id)).first()
    if not year:
        raise HTTPException(status_code=404, detail="Academic year not found")

    year_track = year.track

    name = (body.get("name") or "").strip()
    sequence = body.get("sequence")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    if not name or sequence is None or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="name, sequence, start_date, end_date are required")

    sequence = int(sequence)
    if year_track == Track.BASIC:
        if sequence not in (1, 2, 3):
            raise HTTPException(status_code=400, detail="BASIC track terms must be sequence 1, 2, or 3 (Term 1, Term 2, Term 3).")
    else:
        if sequence not in (1, 2):
            raise HTTPException(status_code=400, detail="SHS track terms must be sequence 1 or 2 (Semester 1, Semester 2).")

    exists = (
        db.query(AcademicTerm)
        .filter(AcademicTerm.academic_year_id == year.id, AcademicTerm.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail=f"{name} already exists for {year.label}")

    seq_exists = (
        db.query(AcademicTerm)
        .filter(AcademicTerm.academic_year_id == year.id, AcademicTerm.sequence == sequence)
        .first()
    )
    if seq_exists:
        raise HTTPException(status_code=409, detail=f"A term with sequence {sequence} already exists for {year.label}")

    term = AcademicTerm(
        academic_year_id=year.id,
        academic_year=year.label,
        track=year.track,
        name=name,
        sequence=sequence,
        start_date=datetime.fromisoformat(start_date.replace("Z", "+00:00")),
        end_date=datetime.fromisoformat(end_date.replace("Z", "+00:00")),
        status=TermStatus.PLANNED,
        is_current=False,
        auto_promote_on_close=body.get("auto_promote_on_close", True),
    )
    db.add(term)
    db.commit()
    db.refresh(term)

    has_current = db.query(AcademicTerm).filter(AcademicTerm.is_current == True, AcademicTerm.track == year.track).first()
    if not has_current:
        term.is_current = True
        term.status = TermStatus.ACTIVE
        db.commit()
        db.refresh(term)

    return {"success": True, "data": _serialize_term(term)}


@router.get("/years/{year_id}/terms")
async def list_terms_for_year(
    year_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
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
    track: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user["role"] not in ("ADMIN", "FINANCIAL_STAFF"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    query = db.query(AcademicTerm)
    if academic_year:
        query = query.filter(AcademicTerm.academic_year == academic_year)
    if track:
        track_str = str(track).strip().upper()
        if track_str not in {"BASIC", "SHS"}:
            raise HTTPException(status_code=400, detail="track must be one of: BASIC, SHS")
        track_enum = Track.BASIC if track_str == "BASIC" else Track.SHS
        query = query.filter(AcademicTerm.track == track_enum)
    rows = query.order_by(AcademicTerm.academic_year.desc(), AcademicTerm.sequence.asc()).all()
    return {"success": True, "data": {"terms": [_serialize_term(r) for r in rows]}}


@router.get("/current")
async def get_current_term(track: str = Query(..., description="BASIC or SHS"), db: Session = Depends(get_db)):
    track_str = str(track).strip().upper()
    if track_str not in {"BASIC", "SHS"}:
        raise HTTPException(status_code=400, detail="track must be one of: BASIC, SHS")
    track_enum = Track.BASIC if track_str == "BASIC" else Track.SHS
    term = db.query(AcademicTerm).filter(AcademicTerm.is_current == True, AcademicTerm.track == track_enum).first()
    if not term:
        return {"success": True, "data": None}
    return {"success": True, "data": _serialize_term(term)}


@router.post("/terms/{term_id}/activate")
async def activate_term(
    term_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    term = db.query(AcademicTerm).filter(AcademicTerm.id == str(term_id)).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.status == TermStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Cannot activate a closed term")

    db.query(AcademicTerm).filter(AcademicTerm.is_current == True, AcademicTerm.track == term.track).update({"is_current": False})
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
    admin=Depends(require_permission("academic")),
):
    term = db.query(AcademicTerm).filter(AcademicTerm.id == str(term_id)).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    if term.status == TermStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Term is already closed")

    promote = body.get("promote_students") if body else None
    if promote is None:
        promote = term.auto_promote_on_close

    max_seq = 3 if term.track == Track.BASIC else 2
    if promote and int(term.sequence) != max_seq:
        raise HTTPException(status_code=400, detail=f"Promotion is only allowed when closing the final term of the track. {term.name!r} is sequence {term.sequence} out of {max_seq} for track={term.track.value}. There {'is' if (max_seq - term.sequence) == 1 else 'are'} {max_seq - term.sequence} term(s) remaining.")

    term.status = TermStatus.CLOSED
    if term.is_current:
        term.is_current = False

    promotion_result = None
    if promote:
        promotion_result = promote_students_for_year(db, term.academic_year, term.track)
    db.commit()
    db.refresh(term)
    return {
        "success": True,
        "data": {
            "term": _serialize_term(term),
            "promotion": promotion_result,
        },
    }

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.core.database import get_db
from app.core.security import require_permission, get_current_user
from app.models.academic import AcademicYear, AcademicTerm, TermStatus
from app.models.class_level import Track
from app.services.activity_log import log_staff_activity
from app.services.promotion import promote_students_for_year, stamp_active_students_academic_year

router = APIRouter(prefix="/admin/academic", tags=["School Calendar"])


def _serialize_year(row: AcademicYear, term_count: int = 0, closed_count: int = 0) -> dict:
    track = str(row.track.value) if hasattr(row.track, "value") else str(row.track) if row.track else None
    max_periods = 2 if track == "SHS" else 3
    terms = int(term_count or 0)
    closed = int(closed_count or 0)
    is_complete = terms >= max_periods and closed >= max_periods
    if is_complete:
        status = "ended"
    elif terms:
        status = "in_progress"
    else:
        status = "setup"
    return {
        "id": row.id,
        "label": row.label,
        "track": track,
        "is_active": row.is_active,
        "term_count": terms,
        "closed_count": closed,
        "max_periods": max_periods,
        "is_complete": is_complete,
        "status": status,
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


def _track_max_sequence(track: Track) -> int:
    return 3 if track == Track.BASIC else 2


def _is_final_term(term: AcademicTerm) -> bool:
    return int(term.sequence) == _track_max_sequence(term.track)


def _maybe_stamp_new_year(db: Session, term: AcademicTerm) -> int:
    if int(term.sequence) != 1:
        return 0
    return stamp_active_students_academic_year(db, term.track, term.academic_year)


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
    existing = (
        db.query(AcademicYear)
        .filter(AcademicYear.label == label, AcademicYear.track == track_value)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Academic year {label} already exists for {track_value.value}",
        )
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
    rows = (
        db.query(AcademicYear)
        .order_by(AcademicYear.label.desc(), AcademicYear.track.asc())
        .all()
    )
    counts = {
        str(year_id): int(n)
        for year_id, n in (
            db.query(AcademicTerm.academic_year_id, func.count(AcademicTerm.id))
            .group_by(AcademicTerm.academic_year_id)
            .all()
        )
    }
    closed_counts = {
        str(year_id): int(n)
        for year_id, n in (
            db.query(AcademicTerm.academic_year_id, func.count(AcademicTerm.id))
            .filter(AcademicTerm.status == TermStatus.CLOSED)
            .group_by(AcademicTerm.academic_year_id)
            .all()
        )
    }
    return {
        "success": True,
        "data": {
            "years": [
                _serialize_year(r, counts.get(str(r.id), 0), closed_counts.get(str(r.id), 0))
                for r in rows
            ]
        },
    }


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
        _maybe_stamp_new_year(db, term)
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
    rows = query.order_by(
        AcademicTerm.academic_year.desc(),
        AcademicTerm.track.asc(),
        AcademicTerm.sequence.asc(),
    ).all()
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
    _maybe_stamp_new_year(db, term)
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

    requested = body.get("promote_students") if body else None
    is_final = _is_final_term(term)
    if not is_final:
        promote = False
    elif requested is None:
        promote = bool(term.auto_promote_on_close)
    else:
        promote = bool(requested)

    term.status = TermStatus.CLOSED
    if term.is_current:
        term.is_current = False

    promotion_result = None
    if promote:
        promotion_result = promote_students_for_year(db, term.academic_year, term.track)

    db.flush()

    year_ended = False
    year_row = db.query(AcademicYear).filter(AcademicYear.id == term.academic_year_id).first()
    if year_row:
        remaining_open = (
            db.query(AcademicTerm)
            .filter(
                AcademicTerm.academic_year_id == year_row.id,
                AcademicTerm.status != TermStatus.CLOSED,
            )
            .count()
        )
        total_terms = (
            db.query(AcademicTerm)
            .filter(AcademicTerm.academic_year_id == year_row.id)
            .count()
        )
        if remaining_open == 0 and total_terms >= _track_max_sequence(year_row.track):
            year_row.is_active = False
            year_ended = True

    db.commit()
    db.refresh(term)

    track_label = term.track.value if hasattr(term.track, "value") else str(term.track)
    try:
        if promotion_result:
            log_staff_activity(
                db,
                admin,
                page_label="Academic",
                action_label=f"Closed {term.name} {term.academic_year} ({track_label}) with promotion",
                details=(
                    f"promoted={promotion_result.get('promoted', 0)}, "
                    f"graduated_basic={promotion_result.get('graduated_basic', 0)}, "
                    f"graduated_shs={promotion_result.get('graduated_shs', 0)}, "
                    f"unchanged={promotion_result.get('unchanged', 0)}"
                ),
            )
        else:
            log_staff_activity(
                db,
                admin,
                page_label="Academic",
                action_label=f"Closed {term.name} {term.academic_year} ({track_label})",
                details="Classes unchanged",
            )
    except Exception:
        pass

    return {
        "success": True,
        "data": {
            "term": _serialize_term(term),
            "promotion": promotion_result,
            "year_ended": year_ended,
        },
    }

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_permission
from app.models.class_level import ClassLevel
from app.services.class_level_names import (
    assert_secondary_naming_allowed,
    display_class_level_name,
    infer_track_from_name,
    normalize_class_level_name,
)
from app.services.school_options import GENDERS, SHS_PROGRAMMES

router = APIRouter(prefix="/admin/class-levels", tags=["Class Levels"])


def _serialize(row: ClassLevel) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "display_name": display_class_level_name(row.name),
        "sequence": row.sequence,
        "track": row.track.value if hasattr(row.track, "value") else str(row.track),
        "is_terminal": row.is_terminal,
        "requires_index_number": row.requires_index_number,
        "requires_stream": row.requires_stream,
        "is_active": row.is_active,
    }


def _prepare_level_name(db: Session, raw_name: str, *, exclude_id: str | None = None) -> str:
    try:
        name = normalize_class_level_name(raw_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        assert_secondary_naming_allowed(db, name, exclude_id=exclude_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return name


@router.get("")
async def list_class_levels(
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("academic")),
):
    rows = (
        db.query(ClassLevel)
        .filter(ClassLevel.is_active == True)
        .order_by(ClassLevel.sequence.asc())
        .all()
    )
    return {
        "success": True,
        "data": {
            "levels": [_serialize(r) for r in rows],
            "genders": GENDERS,
            "programmes": SHS_PROGRAMMES,
        },
    }


@router.post("")
async def create_class_level(
    body: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    sequence = body.get("sequence")
    if sequence is None:
        raise HTTPException(status_code=400, detail="name and sequence are required")

    name = _prepare_level_name(db, body.get("name") or "")

    if db.query(ClassLevel).filter(ClassLevel.name == name).first():
        raise HTTPException(status_code=409, detail="Level name already exists")
    if db.query(ClassLevel).filter(ClassLevel.sequence == int(sequence)).first():
        raise HTTPException(status_code=409, detail="Sequence number already used")

    row = ClassLevel(
        name=name,
        sequence=int(sequence),
        track=infer_track_from_name(name),
        is_terminal=bool(body.get("is_terminal", False)),
        requires_index_number=bool(body.get("requires_index_number", False)),
        requires_stream=bool(body.get("requires_stream", False)),
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"success": True, "data": _serialize(row)}


@router.patch("/{level_id}")
async def update_class_level(
    level_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    row = db.query(ClassLevel).filter(ClassLevel.id == str(level_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Class level not found")

    if "name" in body:
        name = _prepare_level_name(db, body["name"], exclude_id=row.id)
        exists = (
            db.query(ClassLevel)
            .filter(ClassLevel.name == name, ClassLevel.id != row.id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Level name already exists")
        row.name = name
        row.track = infer_track_from_name(name)

    if "sequence" in body:
        seq = int(body["sequence"])
        exists = (
            db.query(ClassLevel)
            .filter(ClassLevel.sequence == seq, ClassLevel.id != row.id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Sequence number already used")
        row.sequence = seq

    if "is_terminal" in body:
        row.is_terminal = bool(body["is_terminal"])
    if "requires_index_number" in body:
        row.requires_index_number = bool(body["requires_index_number"])
    if "requires_stream" in body:
        row.requires_stream = bool(body["requires_stream"])
    if "is_active" in body:
        row.is_active = bool(body["is_active"])

    db.commit()
    db.refresh(row)
    return {"success": True, "data": _serialize(row)}


@router.delete("/{level_id}")
async def deactivate_class_level(
    level_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_permission("academic")),
):
    row = db.query(ClassLevel).filter(ClassLevel.id == str(level_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Class level not found")
    row.is_active = False
    db.commit()
    return {"success": True, "data": {"message": "Class level deactivated"}}

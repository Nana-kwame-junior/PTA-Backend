from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from uuid import UUID



from app.core.database import get_db

from app.core.security import require_permission

from app.models.class_level import ClassLevel



router = APIRouter(prefix="/admin/class-levels", tags=["Class Levels"])





def _serialize(row: ClassLevel) -> dict:

    return {

        "id": row.id,

        "name": row.name,

        "sequence": row.sequence,

        "is_terminal": row.is_terminal,

        "requires_index_number": row.requires_index_number,

        "requires_stream": row.requires_stream,

        "is_active": row.is_active,

    }





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

    return {"success": True, "data": {"levels": [_serialize(r) for r in rows]}}





@router.post("")

async def create_class_level(

    body: dict,

    db: Session = Depends(get_db),

    admin=Depends(require_permission("academic")),

):

    name = (body.get("name") or "").strip()

    sequence = body.get("sequence")

    if not name or sequence is None:

        raise HTTPException(status_code=400, detail="name and sequence are required")



    if db.query(ClassLevel).filter(ClassLevel.name == name).first():

        raise HTTPException(status_code=409, detail="Level name already exists")

    if db.query(ClassLevel).filter(ClassLevel.sequence == int(sequence)).first():

        raise HTTPException(status_code=409, detail="Sequence number already used")



    row = ClassLevel(

        name=name,

        sequence=int(sequence),

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

        name = body["name"].strip()

        exists = (

            db.query(ClassLevel)

            .filter(ClassLevel.name == name, ClassLevel.id != row.id)

            .first()

        )

        if exists:

            raise HTTPException(status_code=409, detail="Level name already exists")

        row.name = name

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



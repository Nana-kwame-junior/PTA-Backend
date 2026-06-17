from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from pydantic import BaseModel

from sqlalchemy.orm import Session

from uuid import UUID

from typing import Optional

import json



from app.core.database import get_db

from app.core.security import require_permission

from app.models.parent import Parent, MatchStatus

from app.models.pending_match import PendingMatch

from app.models.student import Student

from app.models.parent_student_link import ParentStudentLink

from app.models.sms_log import SmsLog

from app.services.sms import send_sms_background

from app.services.parent_directory import (

    linked_students_for_parent,

    serialize_registered_parent,

)



router = APIRouter(prefix="/admin/pending-matches", tags=["Parent Matching"])





class ParentUpdateRequest(BaseModel):

    full_name: Optional[str] = None

    phone: Optional[str] = None

    relationship: Optional[str] = None





def _parse_candidates(raw: str | None) -> list:

    if not raw:

        return []

    try:

        parsed = json.loads(raw)

        return parsed if isinstance(parsed, list) else []

    except json.JSONDecodeError:

        return []





def _serialize_pending(db: Session, row: PendingMatch) -> dict:

    parent = db.query(Parent).filter(Parent.id == row.parent_id).first()

    return {

        "pending_id": str(row.id),

        "parent_id": str(row.parent_id),

        "parent_name": (parent.full_name if parent else "") or "",

        "phone": parent.phone if parent else "",

        "relationship": parent.relationship if parent else "",

        "entered_ward_name": row.entered_ward_name,

        "entered_ward_form": row.entered_ward_form,

        "entered_index_number": row.entered_index_number,

        "registered_at": row.registered_at.isoformat() if row.registered_at else None,

        "top_algorithm_candidates": _parse_candidates(row.top_candidates),

    }





@router.get("/parents-overview")

async def parents_overview(

    db: Session = Depends(get_db),

    staff=Depends(require_permission("parents")),

):

    """Registered parents plus pending ward-match approvals (works on existing deploy)."""

    pending_rows = (

        db.query(PendingMatch)

        .filter(PendingMatch.status == "PENDING")

        .order_by(PendingMatch.registered_at.desc())

        .all()

    )

    pending_matches = [_serialize_pending(db, row) for row in pending_rows]



    parent_rows = (

        db.query(Parent)

        .filter(Parent.full_name.isnot(None), Parent.full_name != "")

        .order_by(Parent.created_at.desc())

        .all()

    )

    parents = [serialize_registered_parent(db, parent) for parent in parent_rows]



    return {

        "success": True,

        "data": {

            "pending_matches": pending_matches,

            "pending_total": len(pending_matches),

            "parents": parents,

            "total_parents": len(parents),

        },

    }





@router.patch("/parents/{parent_id}")

async def update_parent(

    parent_id: UUID,

    req: ParentUpdateRequest,

    db: Session = Depends(get_db),

    staff=Depends(require_permission("parents")),

):

    parent = db.query(Parent).filter(Parent.id == str(parent_id)).first()

    if not parent:

        raise HTTPException(status_code=404, detail="Parent not found")



    payload = req.dict(exclude_unset=True)

    if "full_name" in payload and payload["full_name"] is not None:

        parent.full_name = payload["full_name"].strip()

    if "relationship" in payload and payload["relationship"] is not None:

        parent.relationship = payload["relationship"].strip()

    if "phone" in payload and payload["phone"] is not None:

        from app.utils.phone import normalize_ghana_phone, PhoneValidationError



        try:

            parent.phone = normalize_ghana_phone(payload["phone"])

        except PhoneValidationError as exc:

            raise HTTPException(status_code=422, detail=str(exc)) from exc



    db.commit()

    db.refresh(parent)

    return {"success": True, "data": serialize_registered_parent(db, parent)}





@router.get("")

async def list_pending_matches(

    db: Session = Depends(get_db),

    staff=Depends(require_permission("parents")),

):

    pending = (

        db.query(PendingMatch)

        .filter(PendingMatch.status == "PENDING")

        .order_by(PendingMatch.registered_at.desc())

        .all()

    )

    result = [_serialize_pending(db, row) for row in pending]

    return {"success": True, "data": {"pending": result, "total": len(result)}}





@router.post("/{pending_id}/approve")

async def approve_pending_match(

    pending_id: UUID,

    req: dict,

    background_tasks: BackgroundTasks,

    db: Session = Depends(get_db),

    staff=Depends(require_permission("parents")),

):

    pending = db.query(PendingMatch).filter(PendingMatch.id == str(pending_id)).first()

    if not pending:

        raise HTTPException(status_code=404)

    student = db.query(Student).filter(Student.id == req.get("student_id")).first()

    if not student:

        raise HTTPException(status_code=404, detail="Student not found")



    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()

    if not parent:

        raise HTTPException(status_code=404, detail="Parent not found")



    existing_link = (

        db.query(ParentStudentLink)

        .filter(

            ParentStudentLink.parent_id == pending.parent_id,

            ParentStudentLink.student_id == student.id,

        )

        .first()

    )

    if not existing_link:

        db.add(

            ParentStudentLink(

                parent_id=pending.parent_id,

                student_id=student.id,

                relationship=parent.relationship,

                confidence_score=100,

            )

        )



    parent.match_status = MatchStatus.MATCHED

    pending.status = "APPROVED"

    db.commit()



    if parent.phone:

        linked = linked_students_for_parent(db, parent.id)

        ward_names = ", ".join(s.full_name for s in linked[:3]) or student.full_name

        message = (

            f"YourSchoolPulse account is verified. Linked ward(s): {ward_names}. "

            "Open the app to view details. —SchoolPulse"

        )

        background_tasks.add_task(send_sms_background, parent.phone, message)

        db.add(

            SmsLog(

                message_type="MATCH_APPROVED",

                recipient_phone=parent.phone,

                content=message,

                status="QUEUED",

            )

        )

        db.commit()



    return {"success": True, "data": {"message": "Match approved"}}





@router.post("/{pending_id}/reject")

async def reject_pending_match(

    pending_id: UUID,

    req: dict,

    background_tasks: BackgroundTasks,

    db: Session = Depends(get_db),

    staff=Depends(require_permission("parents")),

):

    pending = db.query(PendingMatch).filter(PendingMatch.id == str(pending_id)).first()

    if not pending:

        raise HTTPException(status_code=404)

    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()

    pending.status = "REJECTED"

    db.commit()



    if parent and parent.phone:

        reason = req.get("reason", "No reason provided")

        message = (

            f"Your parent account could not be verified: {reason}. "

            "Please contact the school for assistance. —SchoolPulse"

        )

        background_tasks.add_task(send_sms_background, parent.phone, message)

        db.add(

            SmsLog(

                message_type="MATCH_REJECTED",

                recipient_phone=parent.phone,

                content=message,

                status="QUEUED",

            )

        )

        db.commit()



    return {"success": True, "data": {"message": "Match rejected"}}



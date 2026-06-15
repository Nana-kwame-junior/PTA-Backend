import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_permission
from app.models.parent import Parent, MatchStatus
from app.models.pending_match import PendingMatch
from app.models.student import Student
from app.models.parent_student_link import ParentStudentLink
from app.models.sms_log import SmsLog
from app.services.sms import send_sms_background

router = APIRouter(prefix="/admin/parents", tags=["Parents Admin"])


def _parse_candidates(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _linked_students(db: Session, parent_id: str) -> list[dict]:
    links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent_id).all()
    students = []
    for link in links:
        student = db.query(Student).filter(Student.id == link.student_id).first()
        if student:
            students.append(
                {
                    "id": str(student.id),
                    "full_name": student.full_name,
                    "index_number": student.index_number,
                    "form": student.form,
                    "stream": student.stream,
                }
            )
    return students


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


@router.get("")
async def list_parents_overview(
    db: Session = Depends(get_db),
    staff=Depends(require_permission("parents")),
):
    """All registered parents plus pending ward-match approvals."""
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
    parents = []
    for parent in parent_rows:
        linked = _linked_students(db, parent.id)
        parents.append(
            {
                "id": str(parent.id),
                "full_name": parent.full_name,
                "phone": parent.phone,
                "relationship": parent.relationship,
                "match_status": parent.match_status.value if parent.match_status else "PENDING",
                "registered_at": parent.created_at.isoformat() if parent.created_at else None,
                "linked_students": linked,
                "link_count": len(linked),
            }
        )

    return {
        "success": True,
        "data": {
            "pending_matches": pending_matches,
            "pending_total": len(pending_matches),
            "parents": parents,
            "total_parents": len(parents),
        },
    }


@router.post("/pending/{pending_id}/approve")
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

    link = ParentStudentLink(
        parent_id=pending.parent_id,
        student_id=student.id,
        relationship=db.query(Parent).filter(Parent.id == pending.parent_id).first().relationship,
        confidence_score=100,
    )
    db.add(link)
    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()
    if parent:
        parent.match_status = MatchStatus.MATCHED
    pending.status = "APPROVED"
    db.commit()

    if parent and parent.phone:
        message = (
            "Your Mawuli SHS PTA account has been verified. "
            "You can now log in to view your ward's details. — Mawuli SHS PTA"
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


@router.post("/pending/{pending_id}/reject")
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
            "Please contact the school for assistance. — Mawuli SHS PTA"
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

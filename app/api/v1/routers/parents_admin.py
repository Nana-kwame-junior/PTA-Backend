import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
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
            link_status = getattr(link, "status", "ACTIVE") or "ACTIVE"
            students.append(
                {
                    "id": str(student.id),
                    "full_name": student.full_name,
                    "index_number": student.index_number,
                    "form": student.form,
                    "stream": student.stream,
                    "status": link_status,
                    "unlink_pending": link_status == "PENDING_UNLINK",
                    "unlink_rejected": link_status == "UNLINK_REJECTED",
                }
            )
    return students


def _serialize_pending(db: Session, row: PendingMatch) -> dict:
    parent = db.query(Parent).filter(Parent.id == row.parent_id).first()
    request_type = getattr(row, "request_type", "MATCH") or "MATCH"
    target_student_id = getattr(row, "student_id", None)
    target_student_name = row.entered_ward_name
    if target_student_id:
        st = db.query(Student).filter(Student.id == target_student_id).first()
        if st:
            target_student_name = st.full_name

    return {
        "pending_id": str(row.id),
        "parent_id": str(row.parent_id),
        "parent_name": (parent.full_name if parent else "") or "",
        "phone": parent.phone if parent else "",
        "relationship": parent.relationship if parent else "",
        "request_type": request_type,
        "student_id": target_student_id,
        "entered_ward_name": target_student_name or row.entered_ward_name,
        "entered_ward_form": row.entered_ward_form,
        "entered_index_number": row.entered_index_number,
        "registered_at": row.registered_at.isoformat() if row.registered_at else None,
        "top_algorithm_candidates": _parse_candidates(row.top_candidates),
    }


@router.get("")
async def list_parents_overview(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("parents")),
):
    """Registered parents (paginated) plus pending ward-match approvals."""
    pending_rows = (
        db.query(PendingMatch)
        .filter(PendingMatch.status == "PENDING")
        .order_by(PendingMatch.registered_at.desc())
        .all()
    )
    pending_matches = [_serialize_pending(db, row) for row in pending_rows]

    parents_query = (
        db.query(Parent)
        .filter(Parent.full_name.isnot(None), Parent.full_name != "")
        .order_by(Parent.created_at.desc())
    )
    total_parents = parents_query.count()
    linked_parents_count = (
        db.query(Parent.id)
        .join(ParentStudentLink, ParentStudentLink.parent_id == Parent.id)
        .filter(Parent.full_name.isnot(None), Parent.full_name != "")
        .distinct()
        .count()
    )
    parent_rows = parents_query.offset((page - 1) * limit).limit(limit).all()
    parents = []
    for parent in parent_rows:
        linked = _linked_students(db, parent.id)
        pending_unlink = (
            db.query(PendingMatch)
            .filter(
                PendingMatch.parent_id == parent.id,
                PendingMatch.request_type == "UNLINK",
                PendingMatch.status == "PENDING",
            )
            .first()
        )
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
                "pending_unlink_id": str(pending_unlink.id) if pending_unlink else None,
                "pending_unlink_student_id": pending_unlink.student_id if pending_unlink else None,
                "pending_unlink_student_name": pending_unlink.entered_ward_name if pending_unlink else None,
            }
        )

    return {
        "success": True,
        "data": {
            "pending_matches": pending_matches,
            "pending_total": len(pending_matches),
            "parents": parents,
            "total_parents": total_parents,
            "linked_parents_count": linked_parents_count,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_parents,
                "total_pages": (total_parents + limit - 1) // limit if total_parents else 0,
            },
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
        raise HTTPException(status_code=404, detail="Pending record not found")

    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()
    request_type = getattr(pending, "request_type", "MATCH") or "MATCH"

    if request_type == "UNLINK":
        student_id_target = getattr(pending, "student_id", None) or req.get("student_id")
        if not student_id_target:
            raise HTTPException(status_code=400, detail="Target student ID missing")

        student = db.query(Student).filter(Student.id == student_id_target).first()
        student_name = student.full_name if student else pending.entered_ward_name or "ward"

        link = (
            db.query(ParentStudentLink)
            .filter(
                ParentStudentLink.parent_id == pending.parent_id,
                ParentStudentLink.student_id == str(student_id_target),
            )
            .first()
        )
        if link:
            db.delete(link)

        pending.status = "APPROVED"

        # Check remaining links
        remaining = (
            db.query(ParentStudentLink)
            .filter(ParentStudentLink.parent_id == pending.parent_id)
            .all()
        )
        if not remaining and parent:
            parent.match_status = MatchStatus.PENDING

        db.commit()

        if parent and parent.phone:
            message = (
                f"Your request to unlink ward '{student_name}' has been approved by the admin. —SchoolPulse"
            )
            background_tasks.add_task(send_sms_background, parent.phone, message)
            db.add(
                SmsLog(
                    message_type="UNLINK_APPROVED",
                    recipient_phone=parent.phone,
                    content=message,
                    status="QUEUED",
                )
            )
            db.commit()

        return {"success": True, "data": {"message": "Unlink request approved"}}

    # Standard Match approval
    student = db.query(Student).filter(Student.id == req.get("student_id")).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    link = ParentStudentLink(
        parent_id=pending.parent_id,
        student_id=student.id,
        relationship=parent.relationship if parent else None,
        confidence_score=100,
        status="ACTIVE",
    )
    db.add(link)
    if parent:
        parent.match_status = MatchStatus.MATCHED
    pending.status = "APPROVED"
    db.commit()

    if parent and parent.phone:
        message = (
            "Your SchoolPulse account has been verified. "
            "You can now log in to view your ward's details. —SchoolPulse"
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
        raise HTTPException(status_code=404, detail="Pending record not found")

    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()
    request_type = getattr(pending, "request_type", "MATCH") or "MATCH"
    reason = req.get("reason", "No reason provided")

    if request_type == "UNLINK":
        student_id_target = getattr(pending, "student_id", None) or req.get("student_id")
        student = db.query(Student).filter(Student.id == student_id_target).first() if student_id_target else None
        student_name = student.full_name if student else pending.entered_ward_name or "ward"

        links_to_update = (
            db.query(ParentStudentLink)
            .filter(
                ParentStudentLink.parent_id == pending.parent_id,
                or_(
                    ParentStudentLink.status == "PENDING_UNLINK",
                    ParentStudentLink.student_id == str(student_id_target) if student_id_target else False,
                )
            )
            .all()
        )
        for link in links_to_update:
            link.status = "UNLINK_REJECTED"

        pending.status = "REJECTED"
        db.commit()

        if parent and parent.phone:
            message = (
                f"Your request to unlink ward '{student_name}' was reviewed: {reason}. "
                "The ward link remains active. —SchoolPulse"
            )
            background_tasks.add_task(send_sms_background, parent.phone, message)
            db.add(
                SmsLog(
                    message_type="UNLINK_REJECTED",
                    recipient_phone=parent.phone,
                    content=message,
                    status="QUEUED",
                )
            )
            db.commit()

        return {"success": True, "data": {"message": "Unlink request rejected"}}

    pending.status = "REJECTED"
    db.commit()

    if parent and parent.phone:
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

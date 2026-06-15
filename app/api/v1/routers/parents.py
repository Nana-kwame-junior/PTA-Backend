from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.security import require_permission
from app.models.parent import Parent, MatchStatus
from app.models.pending_match import PendingMatch
from app.models.student import Student
from app.models.parent_student_link import ParentStudentLink
from app.models.sms_log import SmsLog
from app.services.sms import send_sms_background

router = APIRouter(prefix="/admin/pending-matches", tags=["Parent Matching"])

@router.get("")
async def list_pending_matches(
    db: Session = Depends(get_db),
    staff=Depends(require_permission("parents")),
):
    pending = db.query(PendingMatch).filter(PendingMatch.status == "PENDING").all()
    result = []
    for p in pending:
        parent = db.query(Parent).filter(Parent.id == p.parent_id).first()
        # Fetch top algorithm candidates (stored as JSON)
        import json
        candidates = json.loads(p.top_candidates) if p.top_candidates else []
        result.append({
            "pending_id": p.id,
            "parent_id": p.parent_id,
            "parent_name": parent.full_name if parent else "",
            "phone": parent.phone if parent else "",
            "relationship": parent.relationship if parent else "",
            "entered_ward_name": p.entered_ward_name,
            "entered_ward_form": p.entered_ward_form,
            "registered_at": p.registered_at,
            "top_algorithm_candidates": candidates
        })
    return {"success": True, "data": {"pending": result, "total": len(result)}}

@router.post("/{pending_id}/approve")
async def approve_pending_match(
    pending_id: UUID,
    req: dict,  # {"student_id": "..."}
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
    
    # Create link
    link = ParentStudentLink(
        parent_id=pending.parent_id,
        student_id=student.id,
        relationship=db.query(Parent).filter(Parent.id == pending.parent_id).first().relationship,
        confidence_score=100
    )
    db.add(link)
    # Update parent match status
    parent = db.query(Parent).filter(Parent.id == pending.parent_id).first()
    if parent:
        parent.match_status = MatchStatus.MATCHED
    pending.status = "APPROVED"
    db.commit()
    
    # Send SMS to parent
    if parent and parent.phone:
        message = f"Your Mawuli SHS PTA account has been verified. You can now log in to view your ward's details. — Mawuli SHS PTA"
        background_tasks.add_task(send_sms_background, parent.phone, message)
        sms_log = SmsLog(message_type="MATCH_APPROVED", recipient_phone=parent.phone, content=message, status="QUEUED")
        db.add(sms_log)
        db.commit()
    
    return {"success": True, "data": {"message": "Match approved"}}

@router.post("/{pending_id}/reject")
async def reject_pending_match(
    pending_id: UUID,
    req: dict,  # {"reason": "..."}
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
        message = f"Your parent account could not be verified: {reason}. Please contact the school for assistance. — Mawuli SHS PTA"
        background_tasks.add_task(send_sms_background, parent.phone, message)
        sms_log = SmsLog(message_type="MATCH_REJECTED", recipient_phone=parent.phone, content=message, status="QUEUED")
        db.add(sms_log)
        db.commit()
    
    return {"success": True, "data": {"message": "Match rejected"}}
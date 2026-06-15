from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.security import require_role
from app.models.sms_log import SmsLog
from app.models.job_record import JobRecord
from app.services.sms import send_sms_background, check_sms_balance

router = APIRouter(prefix="/sms", tags=["SMS"])


@router.get("/balance")
async def sms_balance(admin=Depends(require_role("ADMIN"))):
    """Check mNotify SMS credit balance (admin debug)."""
    try:
        data = await check_sms_balance()
        return {"success": True, "data": data}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/logs")
async def sms_logs(
    message_type: Optional[str] = None,
    status: Optional[str] = None,
    recipient_phone: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    query = db.query(SmsLog)
    if message_type:
        query = query.filter(SmsLog.message_type == message_type)
    if status:
        query = query.filter(SmsLog.status == status)
    if recipient_phone:
        query = query.filter(SmsLog.recipient_phone == recipient_phone)
    if date_from:
        query = query.filter(SmsLog.sent_at >= date_from)
    if date_to:
        query = query.filter(SmsLog.sent_at <= date_to)
    total = query.count()
    logs = query.order_by(SmsLog.sent_at.desc()).offset((page-1)*limit).limit(limit).all()
    return {"success": True, "data": {"logs": logs, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": (total+limit-1)//limit}}}

@router.get("/jobs")
async def list_sms_jobs(
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    jobs = db.query(JobRecord).filter(JobRecord.job_type.like("%REMINDER%")).all()
    return {"success": True, "data": {"jobs": jobs}}

@router.post("/resend-failed")
async def resend_failed_sms(
    req: dict,  # { "log_batch_id": "uuid" }
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # In a real implementation, you would fetch failed logs by batch ID
    # Here we just resend all failed logs
    failed_logs = db.query(SmsLog).filter(SmsLog.status == "FAILED").all()
    for log in failed_logs:
        background_tasks.add_task(send_sms_background, log.recipient_phone, log.content)
        log.status = "QUEUED"
    db.commit()
    return {"success": True, "data": {"message": f"Resend queued for {len(failed_logs)} messages"}}
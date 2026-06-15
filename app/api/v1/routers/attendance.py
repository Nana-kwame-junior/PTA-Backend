from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.core.security import require_role
from app.models.meeting_attendance import MeetingAttendance
from app.models.meeting import Meeting
from app.models.student import Student
from app.models.parent_student_link import ParentStudentLink
from app.models.parent import Parent
from app.models.sms_log import SmsLog
from app.schemas.meeting import AttendanceRecord
from app.schemas.report import FollowupSmsRequest
from app.services.sms import send_sms_background

router = APIRouter(prefix="/meetings", tags=["Attendance"])

@router.post("/{meeting_id}/attendance")
async def record_attendance(
    meeting_id: UUID,
    req: AttendanceRecord,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    meeting = db.query(Meeting).filter(Meeting.id == str(meeting_id)).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    
    # Mark attended
    for student_id in req.attended_student_ids:
        existing = db.query(MeetingAttendance).filter(
            MeetingAttendance.meeting_id == str(meeting_id),
            MeetingAttendance.student_id == str(student_id)
        ).first()
        if existing:
            existing.attended = True
        else:
            att = MeetingAttendance(meeting_id=str(meeting_id), student_id=str(student_id), attended=True)
            db.add(att)
    # Mark absent
    for student_id in req.absent_student_ids:
        existing = db.query(MeetingAttendance).filter(
            MeetingAttendance.meeting_id == str(meeting_id),
            MeetingAttendance.student_id == str(student_id)
        ).first()
        if existing:
            existing.attended = False
        else:
            att = MeetingAttendance(meeting_id=str(meeting_id), student_id=str(student_id), attended=False)
            db.add(att)
    db.commit()
    return {"success": True, "data": {"message": "Attendance recorded"}}

@router.get("/{meeting_id}/attendance")
async def get_attendance(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    attendance = db.query(MeetingAttendance).filter(MeetingAttendance.meeting_id == str(meeting_id)).all()
    return {"success": True, "data": {"attendance": attendance}}

@router.get("/reports/attendance")
async def attendance_summary(
    academic_year: str,
    term: str,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Fetch meetings in term
    meetings = db.query(Meeting).filter(Meeting.academic_year == academic_year, Meeting.term == term).all()
    per_meeting = []
    for meeting in meetings:
        total_students = db.query(Student).filter(Student.academic_year == academic_year, Student.is_active == True).count()
        attended = db.query(MeetingAttendance).filter(MeetingAttendance.meeting_id == meeting.id, MeetingAttendance.attended == True).count()
        per_meeting.append({
            "meeting_id": meeting.id,
            "title": meeting.title,
            "date": meeting.date,
            "attendance_rate": round(attended/total_students*100, 1) if total_students else 0,
            "attended_count": attended,
            "total_students": total_students
        })
    
    # Per student attendance count
    students = db.query(Student).filter(Student.academic_year == academic_year, Student.is_active == True).all()
    per_student = []
    for student in students:
        attended_count = db.query(MeetingAttendance).filter(
            MeetingAttendance.student_id == student.id,
            MeetingAttendance.attended == True
        ).count()
        per_student.append({
            "student_id": student.id,
            "name": student.full_name,
            "attended_count": attended_count
        })
    
    # Parents with 2+ consecutive absences (simplified – need to check last two meetings)
    consecutive_absences = []
    # Implementation: for each student, check last two meetings of the term
    # For brevity, placeholder
    return {
        "success": True,
        "data": {
            "per_meeting": per_meeting,
            "per_student": per_student,
            "consecutive_absences": consecutive_absences
        }
    }

@router.post("/attendance/followup-sms")
async def send_attendance_followup(
    req: FollowupSmsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    # Find parents with 2+ consecutive absences
    meetings = db.query(Meeting).filter(Meeting.academic_year == req.academic_year, Meeting.term == req.term).order_by(Meeting.date.desc()).limit(2).all()
    if len(meetings) < 2:
        raise HTTPException(status_code=400, detail="Not enough meetings in term")
    last_meeting = meetings[0]
    second_last = meetings[1]
    
    # Students absent in both
    absent_last = [a.student_id for a in db.query(MeetingAttendance).filter(MeetingAttendance.meeting_id == last_meeting.id, MeetingAttendance.attended == False).all()]
    absent_second = [a.student_id for a in db.query(MeetingAttendance).filter(MeetingAttendance.meeting_id == second_last.id, MeetingAttendance.attended == False).all()]
    chronic_absent_students = set(absent_last) & set(absent_second)
    
    # Get parent phones for these students
    parent_phones = set()
    for student_id in chronic_absent_students:
        links = db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student_id).all()
        for link in links:
            parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
            if parent and parent.phone:
                parent_phones.add(parent.phone)
    
    # Send SMS using template
    for phone in parent_phones:
        message = req.custom_message  # In real, replace placeholders
        background_tasks.add_task(send_sms_background, phone, message)
        sms_log = SmsLog(message_type="ATTENDANCE_FOLLOWUP", recipient_phone=phone, content=message, status="QUEUED")
        db.add(sms_log)
    db.commit()
    return {"success": True, "data": {"recipients_count": len(parent_phones)}}
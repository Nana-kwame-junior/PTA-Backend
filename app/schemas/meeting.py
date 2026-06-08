from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from uuid import UUID

class MeetingCreate(BaseModel):
    title: str
    date: datetime
    time: str
    venue: str
    agenda: str
    term: str
    academic_year: str

class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[datetime] = None
    time: Optional[str] = None
    venue: Optional[str] = None
    agenda: Optional[str] = None
    term: Optional[str] = None
    academic_year: Optional[str] = None

class MeetingCancel(BaseModel):
    reason: str

class AttendanceRecord(BaseModel):
    attended_student_ids: list[UUID]
    absent_student_ids: list[UUID]
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

MeetingStatusLiteral = Literal["SCHEDULED", "COMPLETED", "CANCELLED"]
MeetingCategoryLiteral = Literal["GENERAL", "URGENT", "FINANCIAL", "EVENT"]

class MeetingCreate(BaseModel):
    title: str
    date: datetime
    time: str
    venue: str
    agenda: str
    term: str
    academic_year: str
    category: MeetingCategoryLiteral = "GENERAL"
    status: MeetingStatusLiteral = "SCHEDULED"

class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[datetime] = None
    time: Optional[str] = None
    venue: Optional[str] = None
    agenda: Optional[str] = None
    term: Optional[str] = None
    academic_year: Optional[str] = None
    category: Optional[MeetingCategoryLiteral] = None

class MeetingCancel(BaseModel):
    reason: str

class AttendanceRecord(BaseModel):
    attended_student_ids: list[UUID]
    absent_student_ids: list[UUID]
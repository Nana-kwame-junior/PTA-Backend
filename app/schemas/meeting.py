from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

MeetingStatusLiteral = Literal["SCHEDULED", "COMPLETED", "CANCELLED"]
MeetingCategoryLiteral = Literal["GENERAL", "URGENT", "FINANCIAL", "EVENT"]
MeetingAudienceLiteral = Literal["BOTH", "BASIC", "SHS"]


class MeetingCreate(BaseModel):
    title: str
    date: datetime
    time: str
    end_date: Optional[datetime] = None
    end_time: Optional[str] = None
    venue: str
    agenda: str
    term: str
    academic_year: str
    audience_track: MeetingAudienceLiteral = "BOTH"
    category: MeetingCategoryLiteral = "GENERAL"
    status: MeetingStatusLiteral = "SCHEDULED"


class MeetingUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[datetime] = None
    time: Optional[str] = None
    end_date: Optional[datetime] = None
    end_time: Optional[str] = None
    venue: Optional[str] = None
    agenda: Optional[str] = None
    term: Optional[str] = None
    academic_year: Optional[str] = None
    audience_track: Optional[MeetingAudienceLiteral] = None
    category: Optional[MeetingCategoryLiteral] = None


class MeetingCancel(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


class AttendanceRecord(BaseModel):
    attended_student_ids: list[UUID]
    absent_student_ids: list[UUID]

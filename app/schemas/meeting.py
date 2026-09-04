import re
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

MeetingStatusLiteral = Literal["SCHEDULED", "COMPLETED", "CANCELLED"]
MeetingCategoryLiteral = Literal["GENERAL", "URGENT", "FINANCIAL", "EVENT"]
MeetingAudienceLiteral = Literal["BOTH", "BASIC", "SHS"]

_LETTERS_TEXT = re.compile(r"^[^\d]+$")


def _require_letters_only(value: str, field: str) -> str:
    text = " ".join((value or "").split())
    if len(text) < 3:
        raise ValueError(f"{field} must be at least 3 characters")
    if not _LETTERS_TEXT.match(text):
        raise ValueError(f"{field} cannot contain numbers")
    return text


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

    @field_validator("title")
    @classmethod
    def title_letters(cls, v: str) -> str:
        return _require_letters_only(v, "Title")

    @field_validator("agenda")
    @classmethod
    def agenda_letters(cls, v: str) -> str:
        return _require_letters_only(v, "Agenda")

    @field_validator("status")
    @classmethod
    def scheduled_only(cls, v: str) -> str:
        return "SCHEDULED"


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

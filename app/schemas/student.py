from pydantic import BaseModel, field_validator
from typing import Optional
from uuid import UUID


class StudentCreate(BaseModel):
    index_number: Optional[str] = None
    full_name: str
    gender: Optional[str] = None
    form: str
    stream: Optional[str] = None
    academic_year: str
    parent_phone_1: Optional[str] = None
    parent_phone_2: Optional[str] = None


class StudentUpdate(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    form: Optional[str] = None
    stream: Optional[str] = None
    index_number: Optional[str] = None
    is_active: Optional[bool] = None
    parent_phone_1: Optional[str] = None
    parent_phone_2: Optional[str] = None


class LinkParentRequest(BaseModel):
    parent_id: UUID
    relationship: str

from pydantic import BaseModel
from typing import Optional
from uuid import UUID

class StudentCreate(BaseModel):
    index_number: str
    full_name: str
    form: str
    stream: str
    academic_year: str
    parent_phone_1: Optional[str] = None
    parent_phone_2: Optional[str] = None

class StudentUpdate(BaseModel):
    full_name: Optional[str] = None
    form: Optional[str] = None
    stream: Optional[str] = None
    is_active: Optional[bool] = None
    parent_phone_1: Optional[str] = None
    parent_phone_2: Optional[str] = None

class LinkParentRequest(BaseModel):
    parent_id: UUID
    relationship: str
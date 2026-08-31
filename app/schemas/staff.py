from pydantic import BaseModel, EmailStr
from enum import Enum
from typing import Optional


class StaffRole(str, Enum):
    FINANCIAL_STAFF = "FINANCIAL_STAFF"
    # ADMIN not allowed to be created via this endpoint


class StaffCreate(BaseModel):
    name: str
    email: EmailStr
    job_title: str
    role: StaffRole = StaffRole.FINANCIAL_STAFF
    permissions: list[str] | None = None


class StaffUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    job_title: Optional[str] = None
    permissions: Optional[list[str]] = None

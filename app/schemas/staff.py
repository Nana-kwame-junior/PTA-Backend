from pydantic import BaseModel, EmailStr
from enum import Enum

class StaffRole(str, Enum):
    FINANCIAL_STAFF = "FINANCIAL_STAFF"
    # ADMIN not allowed to be created via this endpoint

class StaffCreate(BaseModel):
    name: str
    email: EmailStr
    role: StaffRole = StaffRole.FINANCIAL_STAFF
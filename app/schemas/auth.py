from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class WebLoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None

class OtpRequest(BaseModel):
    phone: str = Field(..., pattern=r"^\+\d{10,15}$")

class OtpVerifyRequest(BaseModel):
    phone: str
    otp: str

class ParentRegisterRequest(BaseModel):
    full_name: str
    relationship: str
    ward_name: str
    ward_form: str
    ward_index_number: Optional[str] = None

class SelectCandidateRequest(BaseModel):
    student_id: UUID

class RefreshTokenRequest(BaseModel):
    refresh_token: str
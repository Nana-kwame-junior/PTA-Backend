from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, Literal, List

from uuid import UUID

from datetime import datetime



from app.utils.phone import normalize_ghana_phone, PhoneValidationError



class WebLoginRequest(BaseModel):

    email: EmailStr

    password: str

    totp_code: Optional[str] = None



class OtpRequest(BaseModel):

    phone: str = Field(..., min_length=9, max_length=20)
    purpose: Literal["login", "register"] = "register"


    @field_validator("phone")

    @classmethod

    def validate_phone(cls, v: str) -> str:

        try:

            return normalize_ghana_phone(v)

        except PhoneValidationError as exc:

            raise ValueError(str(exc)) from exc



class ParentPhoneRequest(BaseModel):

    phone: str = Field(..., min_length=9, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            return normalize_ghana_phone(v)
        except PhoneValidationError as exc:
            raise ValueError(str(exc)) from exc



class OtpVerifyRequest(BaseModel):

    phone: str

    otp: str



    @field_validator("phone")

    @classmethod

    def validate_phone(cls, v: str) -> str:

        try:

            return normalize_ghana_phone(v)

        except PhoneValidationError as exc:

            raise ValueError(str(exc)) from exc



class WardRegisterEntry(BaseModel):
    ward_name: str
    ward_form: str
    ward_index_number: Optional[str] = None
    ward_stream: Optional[str] = None


class ParentRegisterRequest(BaseModel):
    full_name: str
    relationship: str
    ward_name: Optional[str] = None
    ward_form: Optional[str] = None
    ward_index_number: Optional[str] = None
    ward_stream: Optional[str] = None
    wards: Optional[List[WardRegisterEntry]] = None


class LinkWardRequest(BaseModel):
    ward_name: str
    ward_form: str
    ward_index_number: Optional[str] = None
    ward_stream: Optional[str] = None


class SelectCandidateRequest(BaseModel):

    student_id: UUID



class RefreshTokenRequest(BaseModel):

    refresh_token: str



class ForgotPasswordRequest(BaseModel):

    email: EmailStr



class ResetPasswordTokenRequest(BaseModel):

    token: str

    new_password: str



class StaffProfileUpdate(BaseModel):

    name: Optional[str] = None

    email: Optional[EmailStr] = None


class UnlinkWardRequest(BaseModel):

    student_id: UUID



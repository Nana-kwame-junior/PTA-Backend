from pydantic import BaseModel, model_validator
from typing import Optional
from uuid import UUID
from decimal import Decimal
from datetime import datetime
from enum import Enum

class PaymentMode(str, Enum):
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    BANK_DEPOSIT = "BANK_DEPOSIT"

class InitiatePaymentRequest(BaseModel):
    student_id: UUID
    dues_config_id: UUID

class ManualPaymentRequest(BaseModel):
    student_index_number: Optional[str] = None
    student_id: Optional[UUID] = None
    dues_config_id: UUID
    amount_ghs: Decimal
    payment_mode: PaymentMode
    payment_date: datetime
    notes: Optional[str] = None

    @model_validator(mode="after")
    def require_student_ref(self):
        if not self.student_index_number and not self.student_id:
            raise ValueError("student_index_number or student_id is required")
        return self

class ManualPaymentUpdate(BaseModel):
    amount_ghs: Optional[Decimal] = None
    payment_mode: Optional[PaymentMode] = None
    payment_date: Optional[datetime] = None
    notes: Optional[str] = None

class AmendmentRequest(BaseModel):
    reason: str
    corrected_amount_ghs: Decimal
    corrected_payment_mode: PaymentMode
    corrected_payment_date: datetime

class FlagPaymentRequest(BaseModel):
    reason: str
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Optional
from decimal import Decimal


class DuesConfigCreate(BaseModel):
    academic_year: str
    term: str
    amount_ghs: Decimal
    due_date: datetime
    grace_period_days: int = 7
    late_fee_ghs: Decimal = 0

    @field_validator("due_date")
    @classmethod
    def due_date_required(cls, value: datetime) -> datetime:
        if value is None:
            raise ValueError("Due date is required")
        return value

class DuesConfigUpdate(BaseModel):
    amount_ghs: Optional[Decimal] = None
    due_date: Optional[datetime] = None
    grace_period_days: Optional[int] = None
    late_fee_ghs: Optional[Decimal] = None
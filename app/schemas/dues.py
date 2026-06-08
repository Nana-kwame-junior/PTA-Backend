from pydantic import BaseModel
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

class DuesConfigUpdate(BaseModel):
    amount_ghs: Optional[Decimal] = None
    due_date: Optional[datetime] = None
    grace_period_days: Optional[int] = None
    late_fee_ghs: Optional[Decimal] = None
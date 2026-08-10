from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime
from typing import Optional

class ExpenditureCreate(BaseModel):
    description: str
    amount_ghs: Decimal
    academic_year: str
    term: str
    date: Optional[datetime] = Field(default=None, description="Defaults to now if omitted")

class FollowupSmsRequest(BaseModel):
    academic_year: str
    term: str
    custom_message: str
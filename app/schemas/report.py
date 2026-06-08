from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime

class ExpenditureCreate(BaseModel):
    description: str
    amount_ghs: Decimal
    date: datetime
    academic_year: str
    term: str

class FollowupSmsRequest(BaseModel):
    academic_year: str
    term: str
    custom_message: str
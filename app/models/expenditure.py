from sqlalchemy import Column, String, DateTime, Numeric, Text
from app.core.database import Base
import uuid
from datetime import datetime


class Expenditure(Base):
    __tablename__ = "expenditures"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    description = Column(Text, nullable=False)
    amount_ghs = Column(Numeric(10, 2), nullable=False)
    date = Column(DateTime, nullable=False)
    academic_year = Column(String(20), nullable=False)
    term = Column(String(20), nullable=False)
    recorded_by_user_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

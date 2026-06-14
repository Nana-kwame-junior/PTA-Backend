from sqlalchemy import Column, String, DateTime, Numeric, Integer, Boolean
from app.core.database import Base
import uuid
from datetime import datetime

class DuesConfig(Base):
    __tablename__ = "dues_configs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year = Column(String(20), nullable=False)
    term = Column(String(20), nullable=False)
    amount_ghs = Column(Numeric(10,2), nullable=False)
    due_date = Column(DateTime, nullable=False)
    grace_period_days = Column(Integer, default=7)
    late_fee_ghs = Column(Numeric(10,2), default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
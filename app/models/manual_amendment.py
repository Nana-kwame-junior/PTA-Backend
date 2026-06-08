from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base
import uuid
from datetime import datetime

class ManualAmendment(Base):
    __tablename__ = "manual_amendments"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    manual_payment_id = Column(String(36), nullable=False)
    original_values = Column(Text)  # JSON
    corrected_values = Column(Text)  # JSON
    reason = Column(Text)
    amended_by_user_id = Column(String(36))
    amended_at = Column(DateTime, default=datetime.utcnow)
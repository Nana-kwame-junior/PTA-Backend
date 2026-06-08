from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base
import uuid
from datetime import datetime

class JobRecord(Base):
    __tablename__ = "job_records"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String(255))  # BullMQ job ID
    job_type = Column(String(50))  # MEETING_REMINDER_D7, DUES_REMINDER_D3, etc.
    reference_id = Column(String(36))  # meeting_id or dues_config_id
    scheduled_for = Column(DateTime)
    status = Column(String(20))  # WAITING, COMPLETED, FAILED, CANCELLED
    created_at = Column(DateTime, default=datetime.utcnow)
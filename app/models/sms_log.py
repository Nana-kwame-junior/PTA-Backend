from sqlalchemy import Column, String, DateTime, Text, Integer
from app.core.database import Base
import uuid
from datetime import datetime

class SmsLog(Base):
    __tablename__ = "sms_logs"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_type = Column(String(50))  # OTP, MEETING_REMINDER, DUES_REMINDER, etc.
    recipient_phone = Column(String(20))
    content = Column(Text)
    status = Column(String(20))  # SENT, DELIVERED, FAILED
    provider_reference = Column(String(255))
    sent_at = Column(DateTime, default=datetime.utcnow)
    delivered_at = Column(DateTime)
    retry_count = Column(Integer, default=0)
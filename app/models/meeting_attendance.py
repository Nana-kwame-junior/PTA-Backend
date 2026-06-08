from sqlalchemy import Column, String, DateTime, Boolean
from app.core.database import Base
import uuid
from datetime import datetime

class MeetingAttendance(Base):
    __tablename__ = "meeting_attendance"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    meeting_id = Column(String(36), nullable=False)
    student_id = Column(String(36), nullable=False)
    attended = Column(Boolean, default=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)
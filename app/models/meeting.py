from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum, Boolean
from app.core.database import Base
from app.models.announcement import AnnouncementType
import uuid
from datetime import datetime
import enum

class MeetingStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    date = Column(DateTime, nullable=False)
    time = Column(String(10))
    venue = Column(String(255))
    agenda = Column(Text)
    term = Column(String(20))
    academic_year = Column(String(20))
    category = Column(SQLEnum(AnnouncementType), default=AnnouncementType.GENERAL)
    status = Column(SQLEnum(MeetingStatus), default=MeetingStatus.SCHEDULED)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
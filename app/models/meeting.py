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


class MeetingAudience(str, enum.Enum):
    """Which track's parents receive meeting SMS / see the meeting."""
    BOTH = "BOTH"
    BASIC = "BASIC"
    SHS = "SHS"


class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    date = Column(DateTime, nullable=False)
    time = Column(String(10))
    end_date = Column(DateTime, nullable=True)
    end_time = Column(String(10), nullable=True)
    venue = Column(String(255))
    agenda = Column(Text)
    term = Column(String(80))
    academic_year = Column(String(20))
    audience_track = Column(
        SQLEnum(MeetingAudience),
        default=MeetingAudience.BOTH,
        nullable=False,
    )
    category = Column(SQLEnum(AnnouncementType), default=AnnouncementType.GENERAL)
    status = Column(SQLEnum(MeetingStatus), default=MeetingStatus.SCHEDULED)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

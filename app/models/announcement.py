from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum, Boolean
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class AnnouncementType(str, enum.Enum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    FINANCIAL = "FINANCIAL"
    EVENT = "EVENT"

class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    body = Column(Text)
    type = Column(SQLEnum(AnnouncementType), default=AnnouncementType.GENERAL)
    is_active = Column(Boolean, default=True)
    published_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
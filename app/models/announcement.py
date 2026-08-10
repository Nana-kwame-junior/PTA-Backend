from sqlalchemy import Column, String, DateTime, Text, Enum as SQLEnum, Boolean, JSON
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class AnnouncementType(str, enum.Enum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    FINANCIAL = "FINANCIAL"
    EVENT = "EVENT"


class AnnouncementAudience(str, enum.Enum):
    """Who should receive / see this announcement."""
    BOTH = "BOTH"    # KG–JHS + SHS
    BASIC = "BASIC"  # KG–JHS only
    SHS = "SHS"      # SHS only


class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    body = Column(Text)
    type = Column(SQLEnum(AnnouncementType), default=AnnouncementType.GENERAL)
    audience_track = Column(
        SQLEnum(AnnouncementAudience),
        default=AnnouncementAudience.BOTH,
        nullable=False,
    )
    image_urls = Column(JSON, nullable=False, default=list)
    is_active = Column(Boolean, default=True)
    published_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

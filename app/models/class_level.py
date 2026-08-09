from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum as SQLEnum
from app.core.database import Base
import uuid
import enum
from datetime import datetime


class Track(str, enum.Enum):
    BASIC = "BASIC"  # KG, Primary 1–6, JHS 1–3
    SHS = "SHS"      # Form 1–3


class ClassLevel(Base):
    """
    PTA class levels split across two tracks.
    Track=BASIC — KG through JHS 3. JHS 3 is the unconditional terminal.
    Track=SHS   — Form 1–3. Form 3 is the unconditional terminal.
    """

    __tablename__ = "class_levels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    sequence = Column(Integer, unique=True, nullable=False)
    track = Column(SQLEnum(Track, name="classleveltrack"), nullable=False, default=Track.BASIC)
    is_terminal = Column(Boolean, default=False)
    requires_index_number = Column(Boolean, default=False)
    requires_stream = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

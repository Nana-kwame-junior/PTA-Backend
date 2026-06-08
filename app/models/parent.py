from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class MatchStatus(str, enum.Enum):
    MATCHED = "MATCHED"
    PENDING = "PENDING"

class Parent(Base):
    __tablename__ = "parents"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    phone = Column(String(20), unique=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    relationship = Column(String(50))  # FATHER, MOTHER, GUARDIAN
    match_status = Column(SQLEnum(MatchStatus), default=MatchStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from app.core.database import Base
import uuid
from datetime import datetime


class ClassLevel(Base):
    """School class/level labels used on student records (Nursery, KG, Form 1, etc.)."""

    __tablename__ = "class_levels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    sequence = Column(Integer, unique=True, nullable=False)
    is_terminal = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

from sqlalchemy import Column, String, Integer, Boolean, DateTime
from app.core.database import Base
import uuid
from datetime import datetime


class ClassLevel(Base):
    """
    PTA class levels (KG through SHS).
    KG–Primary: no BECE index, no single programme.
    JHS: BECE index required, no programme.
    SHS (Form 1–3): BECE index + programme/stream required.
    """

    __tablename__ = "class_levels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    sequence = Column(Integer, unique=True, nullable=False)
    is_terminal = Column(Boolean, default=False)
    requires_index_number = Column(Boolean, default=False)
    requires_stream = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

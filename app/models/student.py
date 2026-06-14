from sqlalchemy import Column, String, Boolean, DateTime
from app.core.database import Base
import uuid
from datetime import datetime


class Student(Base):
    __tablename__ = "students"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    index_number = Column(String(50), unique=True, nullable=True)
    full_name = Column(String(255), nullable=False)
    gender = Column(String(1), nullable=True)
    form = Column(String(50))
    stream = Column(String(100), nullable=True)
    parent_phone_1 = Column(String(20))
    parent_phone_2 = Column(String(20))
    is_active = Column(Boolean, default=True)
    academic_year = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

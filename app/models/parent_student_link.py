from sqlalchemy import Column, String, DateTime, Integer
from app.core.database import Base
import uuid
from datetime import datetime

class ParentStudentLink(Base):
    __tablename__ = "parent_student_links"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id = Column(String(36), nullable=False)
    student_id = Column(String(36), nullable=False)
    relationship = Column(String(50))
    confidence_score = Column(Integer)
    status = Column(String(20), default="ACTIVE")  # ACTIVE, PENDING_UNLINK
    created_at = Column(DateTime, default=datetime.utcnow)
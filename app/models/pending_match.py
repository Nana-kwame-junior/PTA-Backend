from sqlalchemy import Column, String, DateTime, Text, Integer
from app.core.database import Base
import uuid
from datetime import datetime

class PendingMatch(Base):
    __tablename__ = "pending_matches"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    parent_id = Column(String(36), nullable=False)
    entered_ward_name = Column(String(255))
    entered_ward_form = Column(String(50))
    entered_index_number = Column(String(50), nullable=True)
    top_candidates = Column(Text)  # JSON string of candidates
    registered_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="PENDING")  # PENDING, APPROVED, REJECTED
from sqlalchemy import Column, String, DateTime, Text
from app.core.database import Base
import uuid
from datetime import datetime


class StaffActivityLog(Base):
    """Human-readable audit trail of staff actions in the dashboard."""

    __tablename__ = "staff_activity_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), nullable=False, index=True)
    user_name = Column(String(255), nullable=False)
    user_email = Column(String(255), nullable=False)
    page_label = Column(String(120), nullable=False)
    action_label = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

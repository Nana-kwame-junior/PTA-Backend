from sqlalchemy import Column, String, DateTime, Numeric, Enum as SQLEnum
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Payment(Base):
    __tablename__ = "payments"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = Column(String(36), nullable=False)
    dues_config_id = Column(String(36), nullable=False)
    parent_id = Column(String(36), nullable=False)
    amount_ghs = Column(Numeric(10,2), nullable=False)
    paystack_reference = Column(String(255), unique=True)
    status = Column(SQLEnum(PaymentStatus), default=PaymentStatus.PENDING)
    receipt_number = Column(String(50), unique=True, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
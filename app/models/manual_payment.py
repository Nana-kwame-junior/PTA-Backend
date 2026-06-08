from sqlalchemy import Column, String, DateTime, Numeric, Boolean, Text, Enum as SQLEnum
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class ManualPaymentMode(str, enum.Enum):
    CASH = "CASH"
    CHEQUE = "CHEQUE"
    BANK_DEPOSIT = "BANK_DEPOSIT"

class ManualPayment(Base):
    __tablename__ = "manual_payments"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    receipt_number = Column(String(50), unique=True, nullable=False)
    student_id = Column(String(36), nullable=False)
    student_index_no = Column(String(50))
    student_name = Column(String(255))
    parent_phone = Column(String(20))
    term = Column(String(20))
    academic_year = Column(String(20))
    amount_ghs = Column(Numeric(10,2), nullable=False)
    payment_mode = Column(SQLEnum(ManualPaymentMode))
    payment_date = Column(DateTime, nullable=False)
    recorded_by_user_id = Column(String(36), nullable=False)
    recorded_by_name = Column(String(255))
    recorded_at = Column(DateTime, default=datetime.utcnow)
    ip_address = Column(String(45))
    notes = Column(Text)
    sms_sent = Column(Boolean, default=False)
    sms_sent_at = Column(DateTime, nullable=True)
    is_flagged = Column(Boolean, default=False)
    flag_reason = Column(Text)
    is_locked = Column(Boolean, default=False)
    amendment_id = Column(String(36), nullable=True)
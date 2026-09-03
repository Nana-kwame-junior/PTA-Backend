from sqlalchemy import Column, String, Boolean, DateTime, Enum as SQLEnum, JSON
from app.core.database import Base
import uuid
from datetime import datetime
import enum

class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    FINANCIAL_STAFF = "FINANCIAL_STAFF"

class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)
    job_title = Column(String(64), nullable=True, default="Other")
    phone = Column(String(32), nullable=True)
    is_active = Column(Boolean, default=True)
    is_first_login = Column(Boolean, default=True)
    permissions = Column(JSON, nullable=True)
    totp_secret = Column(String(255), nullable=True)  # optional 2FA, not used yet
    reset_token = Column(String(255), nullable=True)  # password reset token
    reset_token_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
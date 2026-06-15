from sqlalchemy import Column, DateTime, String

from app.core.database import Base


class OtpSession(Base):
    __tablename__ = "otp_sessions"

    phone = Column(String(20), primary_key=True)
    code = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False)

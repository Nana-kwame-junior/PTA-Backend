"""OTP storage in PostgreSQL (no Redis required)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.otp_session import OtpSession

logger = logging.getLogger(__name__)


def store_otp(db: Session, phone: str, otp: str) -> None:
    ttl = settings.otp_expiry_seconds
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    try:
        row = db.query(OtpSession).filter(OtpSession.phone == phone).first()
        if row:
            row.code = otp
            row.expires_at = expires_at
        else:
            db.add(OtpSession(phone=phone, code=otp, expires_at=expires_at))
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("OTP storage failed — run `alembic upgrade head`: %s", exc)
        raise


def fetch_otp(db: Session, phone: str) -> str | None:
    row = db.query(OtpSession).filter(OtpSession.phone == phone).first()
    if not row:
        return None
    if row.expires_at < datetime.utcnow():
        db.delete(row)
        db.commit()
        return None
    return row.code


def delete_otp(db: Session, phone: str) -> None:
    row = db.query(OtpSession).filter(OtpSession.phone == phone).first()
    if row:
        db.delete(row)
        db.commit()

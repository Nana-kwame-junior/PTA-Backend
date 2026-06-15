"""OTP storage with Redis primary and PostgreSQL fallback when Redis is unavailable."""

import logging
from datetime import datetime, timedelta

import redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.otp_session import OtpSession

logger = logging.getLogger(__name__)

_redis_client = None
_redis_available = True


def _get_redis():
    global _redis_client, _redis_available
    if not _redis_available:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
            _redis_client.ping()
        except redis.RedisError as exc:
            logger.warning("Redis unavailable for OTP storage, using database fallback: %s", exc)
            _redis_available = False
            _redis_client = None
    return _redis_client


def store_otp(db: Session, phone: str, otp: str) -> None:
    ttl = settings.otp_expiry_seconds
    client = _get_redis()
    if client:
        try:
            client.setex(f"otp:{phone}", ttl, otp)
            return
        except redis.RedisError as exc:
            logger.warning("Redis OTP write failed, using database fallback: %s", exc)

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
        logger.error("Database OTP storage failed (run alembic upgrade head): %s", exc)
        raise


def fetch_otp(db: Session, phone: str) -> str | None:
    client = _get_redis()
    if client:
        try:
            stored = client.get(f"otp:{phone}")
            if stored:
                return stored.decode()
        except redis.RedisError as exc:
            logger.warning("Redis OTP read failed, using database fallback: %s", exc)

    row = db.query(OtpSession).filter(OtpSession.phone == phone).first()
    if not row:
        return None
    if row.expires_at < datetime.utcnow():
        db.delete(row)
        db.commit()
        return None
    return row.code


def delete_otp(db: Session, phone: str) -> None:
    client = _get_redis()
    if client:
        try:
            client.delete(f"otp:{phone}")
        except redis.RedisError:
            pass

    row = db.query(OtpSession).filter(OtpSession.phone == phone).first()
    if row:
        db.delete(row)
        db.commit()

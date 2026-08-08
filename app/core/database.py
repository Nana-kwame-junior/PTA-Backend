from sqlalchemy import create_engine, make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_raw = settings.database_url_sync
# Ensure the psycopg (v3) driver is used for Neon/Postgres sync connections.
if _raw.startswith("postgresql+"):
    _url_str = _raw
else:
    _url_str = _raw.replace("postgresql://", "postgresql+psycopg://", 1)

try:
    _url = make_url(_url_str)
except Exception:
    _url = _url_str  # fall back; create_engine will raise a clearer error later
else:
    # Log just host/db, never the password, for deploy debugging.
    try:
        logger.info(
            "DB engine configured: host=%s db=%s driver=%s",
            getattr(_url, "host", None),
            getattr(_url, "database", None),
            getattr(_url, "drivername", None),
        )
    except Exception:
        pass

engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_recycle=280,
    pool_size=5,
    max_overflow=10,
    connect_args={
        # Neon pooler requires SSL + channel binding. Let the engine honour the
        # URL query params; keep an explicit fallback just in case.
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

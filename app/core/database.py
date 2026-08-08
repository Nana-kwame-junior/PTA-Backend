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

_host = None
_dbname = None
_driver = None
_is_localhost = False
try:
    _url = make_url(_url_str)
except Exception:
    _url = _url_str  # fall back; create_engine will raise a clearer error later
else:
    _host = getattr(_url, "host", None)
    _dbname = getattr(_url, "database", None)
    _driver = getattr(_url, "drivername", None)
    _is_localhost = _host in (
        "localhost",
        "127.0.0.1",
        "::1",
        "",
        None,
    )

if _is_localhost:
    logger.warning(
        "DB engine is targeting localhost (host=%r, db=%r, driver=%r). "
        "If this is production check that DATABASE_URL / DATABASE_URL_SYNC "
        "env vars are injected correctly.",
        _host,
        _dbname,
        _driver,
    )
else:
    # Log just host/db, never the password, for deploy debugging.
    logger.info(
        "DB engine configured: host=%s db=%s driver=%s",
        _host,
        _dbname,
        _driver,
    )

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

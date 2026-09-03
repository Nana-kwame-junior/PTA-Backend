from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app import models  # noqa: F401 — register SQLAlchemy models on Base.metadata
from app.api.v1.routers import (
    auth, students, dues, payments_online, payments_manual, payments_parent,
    payments_history, meetings, announcements, sms, reports, attendance, staff,
    parents, parents_admin, academic, class_levels,
)
import logging

logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description=settings.description,
)


@app.on_event("startup")
def _startup_verify_db() -> None:
    from app.core.database import engine
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
            # Auto-migrate columns for PostgreSQL / SQLite if missing
            try:
                conn.execute(text("ALTER TABLE pending_matches ADD COLUMN IF NOT EXISTS request_type VARCHAR(20) DEFAULT 'MATCH';"))
                conn.execute(text("ALTER TABLE pending_matches ADD COLUMN IF NOT EXISTS student_id VARCHAR(36);"))
                conn.execute(text("ALTER TABLE parent_student_links ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'ACTIVE';"))
            except Exception as mig_exc:
                logger.warning("Auto-migration notice (ignoring if dialect unsupported): %s", mig_exc)
        logger.info("Database connection and schema verified on startup")
    except Exception as exc:
        logger.error("Database connection failed on startup: %s", exc)
        raise

# Security and rate limit middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS middleware added LAST so it executes FIRST on all incoming requests
raw_origins = [
    o.strip()
    for o in (*settings.cors_origins.split(","), settings.dashboard_url)
    if o.strip()
]
has_wildcard = "*" in raw_origins or any("*" in o for o in raw_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if has_wildcard else raw_origins,
    allow_origin_regex=r".*" if has_wildcard else None,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(dues.router, prefix="/api/v1")
app.include_router(payments_online.router, prefix="/api/v1")
app.include_router(payments_manual.router, prefix="/api/v1")
app.include_router(payments_parent.router, prefix="/api/v1")
app.include_router(payments_history.router, prefix="/api/v1")
app.include_router(meetings.router, prefix="/api/v1")
app.include_router(announcements.router, prefix="/api/v1")
app.include_router(sms.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(attendance.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(parents.router, prefix="/api/v1")
app.include_router(parents_admin.router, prefix="/api/v1")
app.include_router(academic.router, prefix="/api/v1")
app.include_router(class_levels.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.project_name}",
        "version": settings.version,
        "paystack_webhook": "/api/v1/payments/online/webhook",
    }

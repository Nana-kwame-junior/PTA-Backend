from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app import models  # noqa: F401 — register SQLAlchemy models on Base.metadata
from app.api.v1.routers import (
    auth, students, dues, payments_online, payments_manual, payments_parent,
    meetings, announcements, sms, reports, attendance, staff, parents, parents_admin, academic, class_levels
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
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified on startup")
    except Exception as exc:
        logger.error("Database connection failed on startup: %s", exc)
        raise

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.cors_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(dues.router, prefix="/api/v1")
app.include_router(payments_online.router, prefix="/api/v1")
app.include_router(payments_manual.router, prefix="/api/v1")
app.include_router(payments_parent.router, prefix="/api/v1")
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
        "version": settings.version
    }
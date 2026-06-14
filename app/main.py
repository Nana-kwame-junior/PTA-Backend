from fastapi import FastAPI
from app.core.config import settings
from app import models  # noqa: F401 — register SQLAlchemy models before create_all
from app.core.database import engine, Base
from app.api.v1.routers import (
    auth, students, dues, payments_online, payments_manual,
    meetings, announcements, sms, reports, attendance, staff, parents
)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description=settings.description,
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(students.router, prefix="/api/v1")
app.include_router(dues.router, prefix="/api/v1")
app.include_router(payments_online.router, prefix="/api/v1")
app.include_router(payments_manual.router, prefix="/api/v1")
app.include_router(meetings.router, prefix="/api/v1")
app.include_router(announcements.router, prefix="/api/v1")
app.include_router(sms.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(attendance.router, prefix="/api/v1")
app.include_router(staff.router, prefix="/api/v1")
app.include_router(parents.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.project_name}",
        "version": settings.version
    }
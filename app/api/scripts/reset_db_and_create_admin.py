"""Wipe application data and create a single admin. Keeps alembic_version."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from app import models  # noqa: F401 — register tables
from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.staff_job_titles import ADMIN_JOB_TITLE

ADMIN_EMAIL = "Isaiahdogah81@gmail.com"
ADMIN_PASSWORD = "password"
ADMIN_NAME = "Isaiah Dogah"


def _target() -> tuple[str, str]:
    url = make_url(settings.database_url_sync)
    return str(url.host or ""), str(url.database or "")


def truncate_data_tables() -> list[str]:
    inspector = inspect(engine)
    tables = [
        name
        for name in inspector.get_table_names()
        if name != "alembic_version"
    ]
    if not tables:
        return []

    quoted = ", ".join(f'"{name}"' for name in tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    return tables


def create_admin() -> None:
    db = SessionLocal()
    try:
        admin = User(
            name=ADMIN_NAME,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            job_title=ADMIN_JOB_TITLE,
            is_active=True,
            is_first_login=False,
        )
        db.add(admin)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    host, dbname = _target()
    print(f"Target database: host={host} db={dbname}")
    truncated = truncate_data_tables()
    print(f"Truncated {len(truncated)} tables (alembic_version kept).")
    create_admin()
    print(f"Admin ready: {ADMIN_EMAIL}")

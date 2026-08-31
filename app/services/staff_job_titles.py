"""Job titles (human role) vs UserRole (auth) for staff accounts."""

from app.models.user import UserRole
from app.services.permissions import DEFAULT_FINANCIAL_PERMISSIONS

STAFF_JOB_TITLES = [
    "Teacher",
    "Assistant Teacher",
    "Finance Officer",
    "PTA Executive",
    "Secretary",
    "Head of Department",
    "Other",
]

ADMIN_JOB_TITLE = "Administrator"

DEFAULT_PERMISSIONS_BY_JOB_TITLE: dict[str, list[str]] = {
    "Teacher": [
        "dashboard",
        "students",
        "meetings",
        "announcements",
    ],
    "Assistant Teacher": [
        "dashboard",
        "students",
        "meetings",
        "announcements",
    ],
    "Finance Officer": [
        "dashboard",
        "payments.record",
        "payments.history",
        "payments.online",
        "payments.dues",
        "reports",
    ],
    "PTA Executive": [
        "dashboard",
        "reports",
        "meetings",
        "announcements",
        "parents",
    ],
    "Secretary": [
        "dashboard",
        "students",
        "parents",
        "announcements",
        "meetings",
    ],
    "Head of Department": [
        "dashboard",
        "students",
        "meetings",
        "announcements",
    ],
    "Other": list(DEFAULT_FINANCIAL_PERMISSIONS),
}


def sanitize_job_title(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return "Other"
    title = str(raw).strip()
    if title in STAFF_JOB_TITLES:
        return title
    if title == ADMIN_JOB_TITLE:
        return ADMIN_JOB_TITLE
    return "Other"


def suggested_permissions_for_job_title(job_title: str | None) -> list[str]:
    title = sanitize_job_title(job_title)
    if title == ADMIN_JOB_TITLE:
        return []
    return list(DEFAULT_PERMISSIONS_BY_JOB_TITLE.get(title, DEFAULT_FINANCIAL_PERMISSIONS))


def display_job_title(user) -> str:
    if user.role == UserRole.ADMIN:
        return user.job_title or ADMIN_JOB_TITLE
    return sanitize_job_title(getattr(user, "job_title", None))

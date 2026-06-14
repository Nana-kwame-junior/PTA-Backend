"""Dashboard page permissions assignable to financial staff."""

from app.models.user import UserRole

ALL_STAFF_PERMISSIONS = [
    "dashboard",
    "students",
    "parents",
    "payments.record",
    "payments.history",
    "payments.online",
    "payments.dues",
    "reports",
    "meetings",
    "academic",
    "settings",
]

DEFAULT_FINANCIAL_PERMISSIONS = [
    "dashboard",
    "payments.record",
    "payments.history",
    "reports",
]


def default_permissions_for_role(role: UserRole) -> list[str]:
    if role == UserRole.ADMIN:
        return list(ALL_STAFF_PERMISSIONS) + ["users.manage"]
    return list(DEFAULT_FINANCIAL_PERMISSIONS)


def resolve_user_permissions(user) -> list[str]:
    if user.role == UserRole.ADMIN:
        return default_permissions_for_role(UserRole.ADMIN)
    stored = user.permissions if hasattr(user, "permissions") and user.permissions else None
    if stored and isinstance(stored, list) and len(stored) > 0:
        return [p for p in stored if p in ALL_STAFF_PERMISSIONS]
    return default_permissions_for_role(UserRole.FINANCIAL_STAFF)


def sanitize_permissions(raw: list | None) -> list[str]:
    if not raw:
        return list(DEFAULT_FINANCIAL_PERMISSIONS)
    cleaned = [p for p in raw if p in ALL_STAFF_PERMISSIONS]
    return cleaned or list(DEFAULT_FINANCIAL_PERMISSIONS)

from sqlalchemy.orm import Session

from app.models.staff_activity import StaffActivityLog


def log_staff_activity(
    db: Session,
    user: dict,
    *,
    page_label: str,
    action_label: str,
    details: str | None = None,
) -> None:
    if not user or user.get("role") not in ("ADMIN", "FINANCIAL_STAFF"):
        return
    db.add(
        StaffActivityLog(
            user_id=str(user["id"]),
            user_name=user.get("name") or "Staff",
            user_email=user.get("email") or "",
            page_label=page_label,
            action_label=action_label,
            details=details,
        )
    )
    db.commit()

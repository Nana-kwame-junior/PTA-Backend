"""Validate student fields against PTA class-level rules (Ghana KG–JHS)."""

import re

from sqlalchemy.orm import Session

from app.models.class_level import ClassLevel
from app.services.class_level_names import find_class_level, normalize_student_form_name

BECE_INDEX_PATTERN = re.compile(r"^\d{10}$")


def normalize_gender(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    v = str(value).strip().upper()
    if v in ("M", "MALE", "BOY"):
        return "M"
    if v in ("F", "FEMALE", "GIRL"):
        return "F"
    raise ValueError(f"Invalid gender '{value}' — use M/F or Male/Female")


def normalize_form_name(form: str) -> str:
    """Backward-compatible alias used by student import."""
    return normalize_student_form_name(form)


def get_class_level(db: Session, form: str) -> ClassLevel:
    level = find_class_level(db, form)
    if not level:
        raise ValueError(f"Unknown class level '{form}'. Configure it under Academic Calendar first.")
    return level


def validate_student_fields(
    db: Session,
    form: str,
    index_number: str | None,
    stream: str | None,
    gender: str | None = None,
    *,
    require_index: bool | None = None,
    require_stream: bool | None = None,
) -> tuple[str | None, str | None, str | None]:
    """
    Returns normalized (index_number, stream, gender).
    KG–Primary: no index, no stream.
    JHS 1–2: no index required.
    JHS 3: 10-digit BECE index when required by class level config.

    Parent registration may pass require_index=False so index is optional even for JHS 3.
    """
    level = get_class_level(db, form)

    idx = (index_number or "").strip() or None
    index_required = level.requires_index_number if require_index is None else require_index
    stream_required = level.requires_stream if require_stream is None else require_stream

    if index_required:
        if not idx:
            raise ValueError(
                f"Index number is required for {form} (10 digits, e.g. 0111025007)"
            )
        if not BECE_INDEX_PATTERN.match(idx):
            raise ValueError("Index number must be exactly 10 digits (e.g. 0111025007)")
    elif idx and not BECE_INDEX_PATTERN.match(idx):
        raise ValueError("If provided, index number must be exactly 10 digits (e.g. 0111025007)")

    strm = (stream or "").strip() or None
    if strm and len(strm) > 25:
        raise ValueError("Programme must be at most 25 characters")
    if stream_required:
        if not strm:
            raise ValueError(
                f"Programme/stream is required for {form} (e.g. General Arts, Science, Business)"
            )
    else:
        strm = None

    g = normalize_gender(gender)
    return idx, strm, g

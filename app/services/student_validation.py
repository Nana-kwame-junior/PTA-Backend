"""Validate student fields against PTA class-level rules (Ghana KG–JHS–SHS)."""

import re

from sqlalchemy.orm import Session

from app.models.class_level import ClassLevel

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


def get_class_level(db: Session, form: str) -> ClassLevel:
    level = (
        db.query(ClassLevel)
        .filter(ClassLevel.name == form.strip(), ClassLevel.is_active == True)
        .first()
    )
    if not level:
        raise ValueError(f"Unknown class level '{form}'. Configure it under Academic Calendar first.")
    return level


def validate_student_fields(
    db: Session,
    form: str,
    index_number: str | None,
    stream: str | None,
    gender: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """
    Returns normalized (index_number, stream, gender).
    KG–Primary: no index, no stream.
    JHS: 10-digit BECE index, no stream.
    SHS (Form 1–3): 10-digit index + programme/stream.
    """
    level = get_class_level(db, form)

    idx = (index_number or "").strip() or None

    if level.requires_index_number:
        if not idx:
            raise ValueError(
                f"Index number is required for {form} (10 digits, e.g. 0111025007)"
            )
        if not BECE_INDEX_PATTERN.match(idx):
            raise ValueError("Index number must be exactly 10 digits (e.g. 0111025007)")
    elif idx:
        raise ValueError(
            f"Index number is not used for {form} — leave the index field blank"
        )

    strm = (stream or "").strip() or None
    if level.requires_stream:
        if not strm:
            raise ValueError(
                f"Programme/stream is required for {form} (e.g. General Arts, Science, Business)"
            )
    else:
        strm = None

    g = normalize_gender(gender)
    return idx, strm, g

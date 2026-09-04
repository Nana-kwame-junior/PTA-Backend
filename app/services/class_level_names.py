"""Canonical class level names for Ghana PTA (KG 1–2 → Primary → JHS → SHS)."""

import re

from sqlalchemy.orm import Session

from app.models.class_level import ClassLevel, Track

JHS_NUMBERED = re.compile(r"^JHS [123]$")
SHS_NUMBERED = re.compile(r"^SHS [123]$")


def infer_track_from_name(normalized_name: str) -> Track:
    if normalized_name.startswith("SHS "):
        return Track.SHS
    return Track.BASIC


def display_class_level_name(raw: str) -> str:
    """User-facing class label. Maps legacy Form 1–3 / KG to SHS / KG 1."""
    try:
        return normalize_class_level_name(raw)
    except ValueError:
        return " ".join((raw or "").strip().split())


def normalize_class_level_name(raw: str) -> str:
    """Normalize user input (any case) to a canonical level name."""
    name = " ".join(raw.strip().split())
    if not name:
        raise ValueError("Level name is required")

    lower = name.lower()
    if lower in ("kg", "kindergarten", "kg 1", "kg1"):
        return "KG 1"
    if lower in ("kg 2", "kg2"):
        return "KG 2"

    primary = re.match(r"^primary\s*(\d+)$", lower)
    if primary:
        n = int(primary.group(1))
        if n < 1 or n > 6:
            raise ValueError("Primary levels must be Primary 1 through Primary 6")
        return f"Primary {n}"

    jhs = re.match(r"^jhs\s*(\d+)$", lower)
    if jhs:
        n = int(jhs.group(1))
        if n < 1 or n > 3:
            raise ValueError("JHS levels must be JHS 1, JHS 2, or JHS 3")
        return f"JHS {n}"

    form = re.match(r"^form\s*(\d+)$", lower)
    if form:
        n = int(form.group(1))
        if n < 1 or n > 3:
            raise ValueError("SHS levels must be SHS 1, SHS 2, or SHS 3")
        return f"SHS {n}"

    shs = re.match(r"^shs\s*(\d+)$", lower)
    if shs:
        n = int(shs.group(1))
        if n < 1 or n > 3:
            raise ValueError("SHS levels must be SHS 1, SHS 2, or SHS 3")
        return f"SHS {n}"

    raise ValueError(
        "Use KG 1, KG 2, Primary 1–6, JHS 1–3, or SHS 1–3 "
        "(e.g. kg 1, jhs 1, shs 2, primary 3)"
    )


def normalize_student_form_name(form: str) -> str:
    """Normalize a student class field before lookup."""
    return normalize_class_level_name(form)


def assert_secondary_naming_allowed(
    db: Session,
    normalized_name: str,
    *,
    exclude_id: str | None = None,
) -> None:
    """Reserved for future constraints."""
    _ = (db, normalized_name, exclude_id)


def find_class_level(db: Session, form: str) -> ClassLevel | None:
    try:
        canonical = normalize_student_form_name(form)
    except ValueError:
        return None

    level = (
        db.query(ClassLevel)
        .filter(ClassLevel.name == canonical, ClassLevel.is_active == True)
        .first()
    )
    if level:
        return level

    for row in db.query(ClassLevel).filter(ClassLevel.is_active == True).all():
        try:
            if normalize_class_level_name(row.name) == canonical:
                return row
        except ValueError:
            continue
    return None

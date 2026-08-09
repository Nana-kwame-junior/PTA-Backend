"""Canonical class level names for Ghana PTA (KG → Primary → JHS → SHS Form)."""

import re

from sqlalchemy.orm import Session

from app.models.class_level import ClassLevel

JHS_NUMBERED = re.compile(r"^JHS [123]$")
FORM_NUMBERED = re.compile(r"^Form [123]$")

STUDENT_FORM_ALIASES = {
    "kg 1": "KG",
    "kg 2": "KG",
    "kg1": "KG",
    "kg2": "KG",
    "kindergarten": "KG",
}


def normalize_class_level_name(raw: str) -> str:
    """Normalize user input (any case) to a canonical level name."""
    name = " ".join(raw.strip().split())
    if not name:
        raise ValueError("Level name is required")

    lower = name.lower()
    if lower in STUDENT_FORM_ALIASES:
        return STUDENT_FORM_ALIASES[lower]
    if lower == "kg":
        return "KG"

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

    # SHS levels (Form 1–3); also accept "SHS 1" style input.
    form = re.match(r"^form\s*(\d+)$", lower)
    if form:
        n = int(form.group(1))
        if n < 1 or n > 3:
            raise ValueError("SHS Form levels must be Form 1, Form 2, or Form 3")
        return f"Form {n}"

    shs = re.match(r"^shs\s*(\d+)$", lower)
    if shs:
        n = int(shs.group(1))
        if n < 1 or n > 3:
            raise ValueError("SHS levels must be SHS 1, SHS 2, or SHS 3 (maps to Form 1–3)")
        return f"Form {n}"

    raise ValueError(
        "Use KG, Primary 1–6, JHS 1–3, or Form 1–3 "
        "(e.g. jhs 1, form 2, primary 3, kg)"
    )


def normalize_student_form_name(form: str) -> str:
    """Normalize a student class field before lookup."""
    name = " ".join(form.strip().split())
    lower = name.lower()
    if lower in STUDENT_FORM_ALIASES:
        return STUDENT_FORM_ALIASES[lower]
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

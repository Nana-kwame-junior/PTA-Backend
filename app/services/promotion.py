"""Promote students using admin-configured class levels."""

from sqlalchemy.orm import Session
from app.models.student import Student
from app.models.class_level import ClassLevel


def _promotion_map(db: Session) -> dict[str, str | None]:
    """
    Returns mapping of current level name -> next level name.
    Terminal levels map to None (graduate).
    """
    levels = (
        db.query(ClassLevel)
        .filter(ClassLevel.is_active == True)
        .order_by(ClassLevel.sequence.asc())
        .all()
    )
    mapping: dict[str, str | None] = {}
    for index, level in enumerate(levels):
        if level.is_terminal:
            mapping[level.name] = None
        elif index + 1 < len(levels):
            mapping[level.name] = levels[index + 1].name
        else:
            mapping[level.name] = None
    return mapping


def promote_students_for_year(db: Session, academic_year: str) -> dict:
    """
    Move each active student to the next configured class level.
    Payment/history records are not modified.
    """
    ladder = _promotion_map(db)
    if not ladder:
        return {
            "promoted": 0,
            "graduated": 0,
            "unchanged": 0,
            "total_processed": 0,
            "message": "No class levels configured — add levels in admin settings first.",
        }

    students = (
        db.query(Student)
        .filter(Student.is_active == True, Student.academic_year == academic_year)
        .all()
    )
    promoted = 0
    graduated = 0
    unchanged = 0

    for student in students:
        form = (student.form or "").strip()
        if not form or form not in ladder:
            unchanged += 1
            continue
        next_form = ladder[form]
        if next_form:
            student.form = next_form
            promoted += 1
        else:
            student.form = "Graduated"
            student.is_active = False
            graduated += 1

    return {
        "promoted": promoted,
        "graduated": graduated,
        "unchanged": unchanged,
        "total_processed": len(students),
    }

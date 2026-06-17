"""Promote students using admin-configured class levels."""

from sqlalchemy.orm import Session

from app.models.student import Student
from app.models.class_level import ClassLevel
from app.services.class_level_names import find_class_level, normalize_class_level_name


def _promotion_map(db: Session) -> dict[str, str | None]:
    """
    Returns mapping of canonical level name -> next level name.
    Terminal levels map to None (graduate). Non-terminal last levels stay unchanged.
    """
    levels = (
        db.query(ClassLevel)
        .filter(ClassLevel.is_active == True)
        .order_by(ClassLevel.sequence.asc())
        .all()
    )
    mapping: dict[str, str | None] = {}
    for index, level in enumerate(levels):
        try:
            key = normalize_class_level_name(level.name)
        except ValueError:
            continue

        if level.is_terminal:
            mapping[key] = None
        elif index + 1 < len(levels):
            next_level = levels[index + 1]
            try:
                mapping[key] = normalize_class_level_name(next_level.name)
            except ValueError:
                mapping[key] = next_level.name
        # Non-terminal last level: no mapping entry → student stays unchanged

    return mapping


def _level_requires_index(db: Session, level_name: str) -> bool:
    level = find_class_level(db, level_name)
    return bool(level and level.requires_index_number)


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
            "needs_index": [],
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
    needs_index: list[dict] = []

    for student in students:
        form = (student.form or "").strip()
        if not form:
            unchanged += 1
            continue

        level = find_class_level(db, form)
        if not level:
            unchanged += 1
            continue

        canonical = level.name
        if canonical not in ladder:
            unchanged += 1
            continue

        next_form = ladder[canonical]
        if next_form:
            student.form = next_form
            promoted += 1
            if _level_requires_index(db, next_form) and not (student.index_number or "").strip():
                needs_index.append(
                    {
                        "student_id": str(student.id),
                        "full_name": student.full_name,
                        "form": next_form,
                    }
                )
        else:
            student.form = "Graduated"
            student.is_active = False
            graduated += 1

    return {
        "promoted": promoted,
        "graduated": graduated,
        "unchanged": unchanged,
        "total_processed": len(students),
        "needs_index": needs_index,
    }

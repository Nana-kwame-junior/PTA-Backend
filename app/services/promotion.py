"""Promote students to the next form when an academic term closes."""

from sqlalchemy.orm import Session
from app.models.student import Student

FORM_LADDER = {
    "Form 1": "Form 2",
    "Form 2": "Form 3",
}


def promote_students_for_year(db: Session, academic_year: str) -> dict:
    """
    Move active students up one form. Form 3 students are marked graduated (inactive).
    Payment and historical records are untouched — they remain tied to their term/year.
    """
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
        next_form = FORM_LADDER.get(form)
        if next_form:
            student.form = next_form
            promoted += 1
        elif form == "Form 3":
            student.form = "Graduated"
            student.is_active = False
            graduated += 1
        else:
            unchanged += 1

    return {
        "promoted": promoted,
        "graduated": graduated,
        "unchanged": unchanged,
        "total_processed": len(students),
    }

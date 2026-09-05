from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models.parent import Parent
from app.models.parent_student_link import ParentStudentLink
from app.models.student import Student
from app.services.parent_directory import occupied_student_ids


def _already_linked_student_ids(db: Session, parent_id: str) -> set[str]:
    links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent_id).all()
    return {str(link.student_id) for link in links if link.student_id}


def match_parent_to_student(
    parent: Parent,
    student: Student,
    entered_ward_name: str,
    entered_ward_form: str,
    entered_index_number: str | None = None,
    entered_stream: str | None = None,
) -> int:
    if entered_index_number and student.index_number:
        if entered_index_number.strip() == student.index_number:
            if entered_stream and student.stream:
                if entered_stream.strip().lower() != student.stream.strip().lower():
                    return 85
            return 100

    score = 0
    name_score = fuzz.token_sort_ratio(entered_ward_name, student.full_name)
    score += min(name_score, 60)
    if entered_ward_form.strip().lower() == (student.form or "").strip().lower():
        score += 20
    if entered_stream and student.stream:
        if entered_stream.strip().lower() == student.stream.strip().lower():
            score += 15
    parent_last = entered_ward_name.split()[-1] if entered_ward_name else ""
    student_last = student.full_name.split()[-1] if student.full_name else ""
    if parent_last and student_last and parent_last.lower() == student_last.lower():
        score += 20
    if parent.phone in [student.parent_phone_1, student.parent_phone_2]:
        score += 15
    return min(score, 100)


def find_matches(
    parent: Parent,
    db: Session,
    entered_ward_name: str,
    entered_ward_form: str,
    entered_index_number: str | None = None,
    entered_stream: str | None = None,
):
    """Find ward candidates. Skips students already linked to any parent."""
    linked_ids = occupied_student_ids(db) | _already_linked_student_ids(db, parent.id)
    candidates = []
    students = db.query(Student).filter(Student.is_active == True).all()

    if entered_index_number:
        exact = [
            s
            for s in students
            if s.index_number
            and s.index_number == entered_index_number.strip()
            and s.id not in linked_ids
        ]
        if len(exact) == 1:
            return [{"student": exact[0], "score": 100}]
        if len(exact) > 1:
            return [{"student": s, "score": 95} for s in exact[:5]]

    for student in students:
        if student.id in linked_ids:
            continue
        score = match_parent_to_student(
            parent,
            student,
            entered_ward_name,
            entered_ward_form,
            entered_index_number,
            entered_stream,
        )
        if score >= 40:
            candidates.append({"student": student, "score": score})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]

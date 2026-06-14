from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.student import Student
from app.models.parent import Parent


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
        return 0

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
        score += 10
    return min(score, 100)


def find_matches(
    parent: Parent,
    db: Session,
    entered_ward_name: str,
    entered_ward_form: str,
    entered_index_number: str = None,
    entered_stream: str = None,
):
    candidates = []
    students = db.query(Student).filter(Student.is_active == True).all()
    for student in students:
        if entered_index_number and student.index_number:
            if student.index_number == entered_index_number.strip():
                return [{"student": student, "score": 100}]
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

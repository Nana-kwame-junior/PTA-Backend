from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.student import Student
from app.models.parent import Parent
import re

def normalize_name(name: str) -> str:
    return re.sub(r'[^a-zA-Z]', '', name).lower()

def match_parent_to_student(parent: Parent, student: Student, entered_ward_name: str, entered_ward_form: str) -> int:
    score = 0
    # Index number exact match
    if hasattr(parent, 'entered_index_number') and parent.entered_index_number == student.index_number:
        return 100
    # Fuzzy name match
    name_score = fuzz.token_sort_ratio(entered_ward_name, student.full_name)
    score += min(name_score, 60)
    # Form/class match
    if entered_ward_form == student.form:
        score += 20
    # Shared surname (last token)
    parent_last = entered_ward_name.split()[-1] if entered_ward_name else ""
    student_last = student.full_name.split()[-1] if student.full_name else ""
    if parent_last and student_last and parent_last.lower() == student_last.lower():
        score += 20
    # Phone match (bonus)
    if parent.phone in [student.parent_phone_1, student.parent_phone_2]:
        score += 10
    return min(score, 100)

def find_matches(parent: Parent, db: Session, entered_ward_name: str, entered_ward_form: str, entered_index_number: str = None):
    candidates = []
    students = db.query(Student).filter(Student.is_active == True).all()
    for student in students:
        if entered_index_number and student.index_number == entered_index_number:
            return [{"student": student, "score": 100}]
        score = match_parent_to_student(parent, student, entered_ward_name, entered_ward_form)
        if score >= 40:
            candidates.append({"student": student, "score": score})
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:5]  # top 5
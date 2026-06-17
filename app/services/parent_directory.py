"""Shared helpers for admin parent listings and meeting SMS recipients."""

from sqlalchemy.orm import Session

from app.models.parent import MatchStatus, Parent
from app.models.parent_student_link import ParentStudentLink
from app.models.student import Student
from app.utils.phone import normalize_ghana_phone, PhoneValidationError


def linked_students_for_parent(db: Session, parent_id: str) -> list[dict]:
    links = db.query(ParentStudentLink).filter(ParentStudentLink.parent_id == parent_id).all()
    students: list[dict] = []
    for link in links:
        student = db.query(Student).filter(Student.id == link.student_id).first()
        if student:
            students.append(
                {
                    "id": str(student.id),
                    "full_name": student.full_name,
                    "index_number": student.index_number,
                    "form": student.form,
                    "stream": student.stream,
                }
            )
    return students


def linked_parents_for_student(db: Session, student_id: str) -> list[dict]:
    links = db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student_id).all()
    parents: list[dict] = []
    for link in links:
        parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
        if parent:
            parents.append(
                {
                    "id": str(parent.id),
                    "full_name": parent.full_name,
                    "phone": parent.phone,
                    "relationship": link.relationship or parent.relationship,
                    "match_status": parent.match_status.value if parent.match_status else "PENDING",
                }
            )
    return parents


def serialize_registered_parent(db: Session, parent: Parent) -> dict:
    linked = linked_students_for_parent(db, parent.id)
    return {
        "id": str(parent.id),
        "full_name": parent.full_name,
        "phone": parent.phone,
        "relationship": parent.relationship,
        "match_status": parent.match_status.value if parent.match_status else "PENDING",
        "registered_at": parent.created_at.isoformat() if parent.created_at else None,
        "linked_students": linked,
        "link_count": len(linked),
    }


def meeting_recipient_phones(db: Session) -> list[str]:
    """Matched app parents plus phone numbers stored on student records."""
    phones: set[str] = set()
    for parent in db.query(Parent).filter(Parent.match_status == MatchStatus.MATCHED).all():
        if parent.phone:
            try:
                phones.add(normalize_ghana_phone(parent.phone))
            except PhoneValidationError:
                phones.add(parent.phone.strip())
    for student in db.query(Student).filter(Student.is_active == True).all():
        for raw in (student.parent_phone_1, student.parent_phone_2):
            if not raw:
                continue
            try:
                phones.add(normalize_ghana_phone(raw))
            except PhoneValidationError:
                phones.add(raw.strip())
    return sorted(phones)


def student_recipient_phones(db: Session, student_id: str) -> list[str]:
    """
    All SMS numbers for a ward: parent_phone_1/2 on the student record plus any
    registered parent app numbers linked to that student. Duplicates removed.
    """
    phones: set[str] = set()
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        return []

    for raw in (student.parent_phone_1, student.parent_phone_2):
        if not raw:
            continue
        try:
            phones.add(normalize_ghana_phone(raw))
        except PhoneValidationError:
            phones.add(raw.strip())

    for link in db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student_id).all():
        parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
        if parent and parent.phone:
            try:
                phones.add(normalize_ghana_phone(parent.phone))
            except PhoneValidationError:
                phones.add(parent.phone.strip())

    return sorted(phones)

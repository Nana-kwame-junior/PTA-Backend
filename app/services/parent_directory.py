"""Shared helpers for admin parent listings and meeting SMS recipients."""

import logging

from sqlalchemy.orm import Session

from app.models.parent import MatchStatus, Parent
from app.models.parent_student_link import ParentStudentLink
from app.models.student import Student
from app.utils.phone import normalize_ghana_phone, PhoneValidationError

logger = logging.getLogger(__name__)


def _phone_for_sms(raw: str | None, *, context: str) -> str | None:
    """Normalize to +233… for SMS; adds country code when only local digits are stored."""
    if not (raw or "").strip():
        return None
    try:
        return normalize_ghana_phone(raw)
    except PhoneValidationError:
        logger.warning("Skipping invalid phone for %s: %s", context, raw)
        return None


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


def meeting_recipient_phones(db: Session, audience_track: str | None = "BOTH") -> list[str]:
    """
    Matched app parents plus phone numbers stored on student records.
    audience_track: BOTH | BASIC | SHS — filters student-linked phones by track.
    """
    from app.models.class_level import Track

    track_filter = (audience_track or "BOTH").strip().upper()
    phones: set[str] = set()

    student_query = db.query(Student).filter(Student.is_active == True)
    if track_filter == "BASIC":
        student_query = student_query.filter(Student.track == Track.BASIC)
    elif track_filter == "SHS":
        student_query = student_query.filter(Student.track == Track.SHS)
    students = student_query.all()
    student_ids = {str(s.id) for s in students}

    if track_filter == "BOTH":
        for parent in db.query(Parent).filter(Parent.match_status == MatchStatus.MATCHED).all():
            normalized = _phone_for_sms(parent.phone, context="meeting SMS parent")
            if normalized:
                phones.add(normalized)
    else:
        # Parents who have at least one linked ward on the selected track
        parent_ids: set[str] = set()
        if student_ids:
            links = (
                db.query(ParentStudentLink)
                .filter(ParentStudentLink.student_id.in_(student_ids))
                .all()
            )
            parent_ids = {str(link.parent_id) for link in links}
        if parent_ids:
            for parent in (
                db.query(Parent)
                .filter(Parent.id.in_(parent_ids), Parent.match_status == MatchStatus.MATCHED)
                .all()
            ):
                normalized = _phone_for_sms(parent.phone, context="meeting SMS parent")
                if normalized:
                    phones.add(normalized)

    for student in students:
        for raw in (student.parent_phone_1, student.parent_phone_2):
            normalized = _phone_for_sms(raw, context=f"meeting SMS student {student.id}")
            if normalized:
                phones.add(normalized)
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
        normalized = _phone_for_sms(raw, context=f"dues SMS student {student_id}")
        if normalized:
            phones.add(normalized)

    for link in db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student_id).all():
        parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
        if not parent:
            continue
        normalized = _phone_for_sms(parent.phone, context=f"dues SMS parent {parent.id}")
        if normalized:
            phones.add(normalized)

    return sorted(phones)

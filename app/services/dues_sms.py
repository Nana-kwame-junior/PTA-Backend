"""Build and send personalized PTA dues SMS grouped by parent phone.

Each parent/contact number receives ONE SMS listing every owing ward
linked to that number (name + amount), so they know who the debt is for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging

from sqlalchemy.orm import Session

from app.models.academic import AcademicTerm
from app.models.class_level import Track
from app.models.dues_config import DuesConfig
from app.models.sms_log import SmsLog
from app.models.student import Student
from app.services.dues_balance import student_outstanding_summary, student_term_dues_balance
from app.services.parent_directory import student_recipient_phones
from app.services.sms import send_sms_sync

logger = logging.getLogger(__name__)


@dataclass
class WardDebt:
    student_id: str
    full_name: str
    form: str
    amount: Decimal


@dataclass
class ParentDebtBucket:
    phone: str
    wards: list[WardDebt] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((w.amount for w in self.wards), Decimal("0"))


def _term_for_dues(db: Session, dues: DuesConfig) -> AcademicTerm | None:
    return (
        db.query(AcademicTerm)
        .filter(
            AcademicTerm.academic_year == dues.academic_year,
            AcademicTerm.name == dues.term,
        )
        .first()
    )


def students_with_outstanding_for_dues(db: Session, dues: DuesConfig) -> list[tuple[Student, dict]]:
    """Active students with a positive balance for this dues year/term (incl. arrears when term exists)."""
    term_row = _term_for_dues(db, dues)
    rows: list[tuple[Student, dict]] = []
    students = (
        db.query(Student)
        .filter(Student.academic_year == dues.academic_year, Student.is_active == True)
        .all()
    )
    for student in students:
        if term_row:
            track = student.track if student.track is not None else Track.BASIC
            summary = student_outstanding_summary(
                db,
                student_id=student.id,
                track=track,
                current_term=term_row,
            )
            amount = Decimal(summary["total_due_ghs"])
        else:
            bal = student_term_dues_balance(
                db,
                student_id=student.id,
                academic_year=dues.academic_year,
                term=dues.term,
            )
            amount = bal["remaining_ghs"]
            summary = {"total_due_ghs": str(amount)}
        if amount > 0:
            rows.append((student, summary))
    return rows


def group_outstanding_by_phone(
    db: Session,
    dues: DuesConfig,
) -> list[ParentDebtBucket]:
    """Map each parent phone → list of owing wards (deduped by student)."""
    buckets: dict[str, ParentDebtBucket] = {}
    seen_phone_student: set[tuple[str, str]] = set()

    for student, summary in students_with_outstanding_for_dues(db, dues):
        amount = Decimal(summary["total_due_ghs"])
        ward = WardDebt(
            student_id=str(student.id),
            full_name=student.full_name,
            form=student.form or "",
            amount=amount,
        )
        phones = student_recipient_phones(db, student.id)
        if not phones:
            logger.info("No parent phones for student %s — dues SMS skipped", student.full_name)
            continue
        for phone in phones:
            key = (phone, str(student.id))
            if key in seen_phone_student:
                continue
            seen_phone_student.add(key)
            if phone not in buckets:
                buckets[phone] = ParentDebtBucket(phone=phone)
            buckets[phone].wards.append(ward)

    return list(buckets.values())


def build_personalized_parent_dues_message(
    *,
    dues: DuesConfig,
    wards: list[WardDebt],
    reminder_type: str,
) -> str:
    """One SMS for a parent covering all their owing wards by name."""
    due_str = dues.due_date.strftime("%d %b %Y") if dues.due_date else ""
    total = sum((w.amount for w in wards), Decimal("0"))

    ward_bits: list[str] = []
    for w in wards:
        label = w.full_name
        if w.form:
            label = f"{w.full_name} ({w.form})"
        ward_bits.append(f"{label}: GH₵{w.amount:.2f}")
    ward_list = "; ".join(ward_bits)

    if reminder_type == "NEW":
        head = (
            f"SchoolPulse dues ({dues.term} · {dues.academic_year}). "
            f"You owe GH₵{total:.2f} for your ward(s): {ward_list}. Due {due_str}."
        )
        return head + " Pay via the SchoolPulse app or school office."

    if reminder_type == "OVERDUE":
        head = (
            f"PTA Dues OVERDUE ({dues.term} · {dues.academic_year}). "
            f"Outstanding GH₵{total:.2f} for: {ward_list}. Was due {due_str}."
        )
        return head + " Please pay immediately via the app or school office."

    days = "3 days" if reminder_type == "D3" else "1 day" if reminder_type == "D1" else "soon"
    head = (
        f"PTA Dues Reminder — due in {days} ({due_str}). "
        f"You owe GH₵{total:.2f} for: {ward_list}."
    )
    return head + " Pay via the SchoolPulse app or school office."


def build_dues_sms_message(
    *,
    student: Student,
    dues: DuesConfig,
    summary: dict,
    reminder_type: str,
) -> str:
    """Legacy single-ward message (kept for compatibility). Prefer personalized parent SMS."""
    ward = WardDebt(
        student_id=str(student.id),
        full_name=student.full_name,
        form=student.form or "",
        amount=Decimal(summary["total_due_ghs"]),
    )
    return build_personalized_parent_dues_message(
        dues=dues,
        wards=[ward],
        reminder_type=reminder_type,
    )


def send_dues_sms_for_config(db: Session, dues_config_id: str, reminder_type: str) -> int:
    """
    Send ONE personalized SMS per parent phone for all owing wards.
    Ward names + amounts are included so parents know who the balance is for.
    Returns count of SMS send attempts.
    """
    dues = (
        db.query(DuesConfig)
        .filter(DuesConfig.id == dues_config_id, DuesConfig.is_active == True)
        .first()
    )
    if not dues:
        logger.warning("Dues config %s not found/inactive — SMS skipped", dues_config_id)
        return 0

    buckets = group_outstanding_by_phone(db, dues)
    if not buckets:
        logger.info("No outstanding dues recipients for config %s", dues_config_id)
        return 0

    sent = 0
    message_type = f"DUES_{reminder_type}"

    for bucket in buckets:
        message = build_personalized_parent_dues_message(
            dues=dues,
            wards=bucket.wards,
            reminder_type=reminder_type,
        )
        # Keep SMS within practical length for multi-ward parents
        if len(message) > 480:
            names = ", ".join(w.full_name for w in bucket.wards)
            total = bucket.total
            due_str = dues.due_date.strftime("%d %b %Y") if dues.due_date else ""
            message = (
                f"SchoolPulse: You owe GH₵{total:.2f} for {names} "
                f"({dues.term} · {dues.academic_year}, due {due_str}). "
                f"See the SchoolPulse app for breakdown. Pay via app or school office."
            )

        try:
            send_sms_sync(bucket.phone, message)
            db.add(
                SmsLog(
                    message_type=message_type,
                    recipient_phone=bucket.phone,
                    content=message,
                    status="SENT",
                )
            )
            sent += 1
            logger.info(
                "Personalized dues SMS (%s) → %s wards=%s total=%s",
                reminder_type,
                bucket.phone,
                [w.full_name for w in bucket.wards],
                bucket.total,
            )
        except Exception as exc:
            logger.error("Dues SMS failed to %s: %s", bucket.phone, exc)
            db.add(
                SmsLog(
                    message_type=message_type,
                    recipient_phone=bucket.phone,
                    content=message,
                    status="FAILED",
                )
            )

    db.commit()
    return sent


def send_personalized_outstanding_dues(db: Session, dues_config_id: str, reminder_type: str = "NEW") -> int:
    """Alias used by Celery task name for clarity."""
    return send_dues_sms_for_config(db, dues_config_id, reminder_type)

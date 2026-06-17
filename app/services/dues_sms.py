"""Build and send PTA dues SMS to all parent contact numbers for a student."""

from decimal import Decimal
import logging

from sqlalchemy.orm import Session

from app.models.academic import AcademicTerm
from app.models.dues_config import DuesConfig
from app.models.sms_log import SmsLog
from app.models.student import Student
from app.services.dues_balance import student_outstanding_summary
from app.services.parent_directory import student_recipient_phones
from app.services.sms import send_sms_sync

logger = logging.getLogger(__name__)


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
    term_row = _term_for_dues(db, dues)
    if not term_row:
        return []

    rows: list[tuple[Student, dict]] = []
    students = (
        db.query(Student)
        .filter(Student.academic_year == dues.academic_year, Student.is_active == True)
        .all()
    )
    for student in students:
        summary = student_outstanding_summary(
            db,
            student_id=student.id,
            current_term=term_row,
        )
        if Decimal(summary["total_due_ghs"]) > 0:
            rows.append((student, summary))
    return rows


def build_dues_sms_message(
    *,
    student: Student,
    dues: DuesConfig,
    summary: dict,
    reminder_type: str,
) -> str:
    total = Decimal(summary["total_due_ghs"])
    arrears = Decimal(summary["arrears_ghs"])
    ward = student.full_name
    form = student.form or ""
    due_str = dues.due_date.strftime("%d %b %Y") if dues.due_date else ""

    if reminder_type == "NEW":
        base = (
            f"Mawuli PTA: GH₵{total:.2f} due for {ward}"
            f"{f' ({form})' if form else ''}. {dues.term} · {dues.academic_year}. Due {due_str}."
        )
        if arrears > 0:
            base += f" Includes GH₵{arrears:.2f} unpaid from previous term(s)."
        return base + " Pay at the school office or via the Mawuli PTA app."

    if reminder_type == "OVERDUE":
        base = (
            f"PTA Dues OVERDUE: GH₵{total:.2f} for {ward}"
            f"{f' ({form})' if form else ''}. {dues.term} · {dues.academic_year} was due {due_str}."
        )
        if arrears > 0:
            base += f" Includes GH₵{arrears:.2f} arrears."
        return base + " Please pay immediately at the school office or via the app."

    days = "3 days" if reminder_type == "D3" else "1 day"
    base = (
        f"PTA Dues Reminder: GH₵{total:.2f} for {ward}"
        f"{f' ({form})' if form else ''}. {dues.term} · {dues.academic_year} due in {days} ({due_str})."
    )
    if arrears > 0:
        base += f" Total includes GH₵{arrears:.2f} from previous term(s)."
    return base + " Pay via the Mawuli PTA app or school office."


def send_dues_sms_for_config(db: Session, dues_config_id: str, reminder_type: str) -> int:
    """
    Send dues SMS to every contact number for each student with outstanding balance.
    Returns count of SMS send attempts.
    """
    dues = db.query(DuesConfig).filter(DuesConfig.id == dues_config_id, DuesConfig.is_active == True).first()
    if not dues:
        return 0

    sent = 0
    for student, summary in students_with_outstanding_for_dues(db, dues):
        phones = student_recipient_phones(db, student.id)
        if not phones:
            logger.info("No parent phones for student %s — dues SMS skipped", student.full_name)
            continue

        message = build_dues_sms_message(
            student=student,
            dues=dues,
            summary=summary,
            reminder_type=reminder_type,
        )
        message_type = f"DUES_{reminder_type}"

        for phone in phones:
            try:
                send_sms_sync(phone, message)
                db.add(
                    SmsLog(
                        message_type=message_type,
                        recipient_phone=phone,
                        content=message,
                        status="SENT",
                    )
                )
                sent += 1
            except Exception as exc:
                logger.error("Dues SMS failed to %s for %s: %s", phone, student.full_name, exc)
                db.add(
                    SmsLog(
                        message_type=message_type,
                        recipient_phone=phone,
                        content=message,
                        status="FAILED",
                    )
                )

    db.commit()
    return sent

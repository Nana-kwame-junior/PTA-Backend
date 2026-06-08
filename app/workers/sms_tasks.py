import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.meeting import Meeting
from app.models.dues_config import DuesConfig
from app.models.student import Student
from app.models.parent import Parent
from app.models.parent_student_link import ParentStudentLink
from app.models.payment import Payment
from app.models.manual_payment import ManualPayment
from app.models.sms_log import SmsLog
from app.services.sms import send_sms
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

def get_distinct_parent_phones(db: Session) -> list:
    parents = db.query(Parent).filter(Parent.match_status == "MATCHED").all()
    return [p.phone for p in parents if p.phone]

def get_parents_for_student(db: Session, student_id: str) -> list:
    links = db.query(ParentStudentLink).filter(ParentStudentLink.student_id == student_id).all()
    phones = []
    for link in links:
        parent = db.query(Parent).filter(Parent.id == link.parent_id).first()
        if parent and parent.phone:
            phones.append(parent.phone)
    return phones

@celery_app.task(bind=True, max_retries=3)
def send_meeting_reminder(self, meeting_id: str, reminder_type: str):
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting or meeting.status != "SCHEDULED":
            return
        message = (f"PTA Meeting Reminder: {meeting.title} on {meeting.date.strftime('%d %b %Y')} at {meeting.time}, "
                   f"{meeting.venue}. Agenda available on the app. — Mawuli SHS PTA")
        phones = get_distinct_parent_phones(db)
        for phone in phones:
            try:
                send_sms(phone, message)
                sms_log = SmsLog(
                    message_type=f"MEETING_REMINDER_{reminder_type}",
                    recipient_phone=phone,
                    content=message,
                    status="SENT",
                    sent_at=datetime.utcnow()
                )
                db.add(sms_log)
            except Exception as e:
                logger.error(f"Meeting reminder failed to {phone}: {e}")
                sms_log = SmsLog(
                    message_type=f"MEETING_REMINDER_{reminder_type}",
                    recipient_phone=phone,
                    content=message,
                    status="FAILED",
                    sent_at=datetime.utcnow()
                )
                db.add(sms_log)
        db.commit()
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()

@celery_app.task(bind=True, max_retries=3)
def send_dues_reminder(self, dues_config_id: str, reminder_type: str):
    db = SessionLocal()
    try:
        dues = db.query(DuesConfig).filter(DuesConfig.id == dues_config_id).first()
        if not dues:
            return
        students = db.query(Student).filter(Student.academic_year == dues.academic_year, Student.is_active == True).all()
        unpaid_students = []
        for student in students:
            online_paid = db.query(Payment).filter(
                Payment.student_id == student.id,
                Payment.dues_config_id == dues_config_id,
                Payment.status == "COMPLETED"
            ).first()
            manual_paid = db.query(ManualPayment).filter(
                ManualPayment.student_id == student.id,
                ManualPayment.academic_year == dues.academic_year,
                ManualPayment.term == dues.term
            ).first()
            if not online_paid and not manual_paid:
                unpaid_students.append(student)
        if not unpaid_students:
            return
        if reminder_type == "OVERDUE":
            message = (f"PTA Dues OVERDUE: GHS {dues.amount_ghs} for {dues.term} {dues.academic_year} was due on "
                       f"{dues.due_date.strftime('%d %b %Y')}. Please pay immediately via the app or school office. Late fee applies.")
        else:
            days = "3 days" if reminder_type == "D3" else "1 day"
            message = (f"PTA Dues Reminder: GHS {dues.amount_ghs} for {dues.term} {dues.academic_year} is due in {days} "
                       f"({dues.due_date.strftime('%d %b %Y')}). Pay via the Mawuli PTA app.")
        for student in unpaid_students:
            phones = get_parents_for_student(db, student.id)
            for phone in phones:
                try:
                    send_sms(phone, message)
                    sms_log = SmsLog(
                        message_type=f"DUES_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="SENT",
                        sent_at=datetime.utcnow()
                    )
                    db.add(sms_log)
                except Exception as e:
                    logger.error(f"Dues SMS failed to {phone}: {e}")
                    sms_log = SmsLog(
                        message_type=f"DUES_REMINDER_{reminder_type}",
                        recipient_phone=phone,
                        content=message,
                        status="FAILED",
                        sent_at=datetime.utcnow()
                    )
                    db.add(sms_log)
        db.commit()
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=60)
    finally:
        db.close()
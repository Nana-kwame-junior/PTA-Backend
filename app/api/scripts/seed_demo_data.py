"""Seed demo students, dues, announcements, and meetings."""

from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.student import Student
from app.models.dues_config import DuesConfig
from app.models.announcement import Announcement, AnnouncementType
from app.models.meeting import Meeting, MeetingStatus
from app.models.academic import AcademicYear, AcademicTerm, TermStatus

ACADEMIC_YEAR = "2024/2025"

STUDENTS = [
    {
        "index_number": "MWL/2024/001",
        "full_name": "Kofi Mensah Ansah",
        "form": "Form 2",
        "stream": "Science A",
        "parent_phone_1": "+233241234567",
    },
    {
        "index_number": "MWL/2024/002",
        "full_name": "Ama Serwaa Ofori",
        "form": "Form 1",
        "stream": "General Arts B",
        "parent_phone_1": "+233244567890",
    },
    {
        "index_number": "MWL/2024/003",
        "full_name": "Kwame Boateng",
        "form": "Form 3",
        "stream": "Business C",
        "parent_phone_1": "+233201234567",
    },
    {
        "index_number": "MWL/2024/004",
        "full_name": "Akosua Mensah",
        "form": "Form 2",
        "stream": "Science A",
        "parent_phone_1": "+233551234567",
    },
    {
        "index_number": "MWL/2024/005",
        "full_name": "Yaw Darko",
        "form": "Form 1",
        "stream": "Visual Arts A",
        "parent_phone_1": "+233501234567",
    },
]


def seed():
    db = SessionLocal()
    try:
        year = db.query(AcademicYear).filter(AcademicYear.label == ACADEMIC_YEAR).first()
        if not year:
            year = AcademicYear(label=ACADEMIC_YEAR, is_active=True)
            db.add(year)
            db.commit()
            db.refresh(year)
            print(f"Academic year: created {ACADEMIC_YEAR}")
        else:
            print(f"Academic year: {ACADEMIC_YEAR} already exists")

        term_row = (
            db.query(AcademicTerm)
            .filter(AcademicTerm.academic_year_id == year.id, AcademicTerm.name == "Term 1")
            .first()
        )
        if not term_row:
            now = datetime.utcnow()
            db.query(AcademicTerm).filter(AcademicTerm.is_current == True).update({"is_current": False})
            term_row = AcademicTerm(
                academic_year_id=year.id,
                academic_year=ACADEMIC_YEAR,
                name="Term 1",
                sequence=1,
                start_date=now - timedelta(days=30),
                end_date=now + timedelta(days=60),
                status=TermStatus.ACTIVE,
                is_current=True,
                auto_promote_on_close=True,
            )
            db.add(term_row)
            db.commit()
            print("Academic term: created Term 1 (current)")
        else:
            print("Academic term: Term 1 already exists")

        # Students
        student_count = 0
        for row in STUDENTS:
            existing = db.query(Student).filter(Student.index_number == row["index_number"]).first()
            if existing:
                continue
            db.add(
                Student(
                    index_number=row["index_number"],
                    full_name=row["full_name"],
                    form=row["form"],
                    stream=row["stream"],
                    academic_year=ACADEMIC_YEAR,
                    parent_phone_1=row["parent_phone_1"],
                    is_active=True,
                )
            )
            student_count += 1
        db.commit()
        print(f"Students: added {student_count} new (total sample set: {len(STUDENTS)})")

        # Dues
        dues = (
            db.query(DuesConfig)
            .filter(DuesConfig.academic_year == ACADEMIC_YEAR, DuesConfig.term == "Term 1")
            .first()
        )
        if not dues:
            dues = DuesConfig(
                academic_year=ACADEMIC_YEAR,
                term="Term 1",
                amount_ghs=150.00,
                due_date=datetime.utcnow() + timedelta(days=30),
                grace_period_days=7,
                late_fee_ghs=10.00,
            )
            db.add(dues)
            db.commit()
            print("Dues: created Term 1 2024/2025 — GHS 150.00")
        else:
            print("Dues: Term 1 config already exists")

        # Announcements
        announcements = [
            {
                "title": "Term 1 PTA Dues Now Open",
                "body": "Parents are reminded to pay Term 1 PTA dues of GHS 150 by the due date. Pay online via the app or at the finance office.",
                "type": AnnouncementType.FINANCIAL,
            },
            {
                "title": "General PTA Assembly — November",
                "body": "All parents are invited to the General PTA Assembly. Venue: Assembly Hall. Agenda will be shared via SMS.",
                "type": AnnouncementType.GENERAL,
            },
            {
                "title": "Inter-House Sports Day",
                "body": "Inter-house sports competition next month. Parents are welcome to attend and support their wards.",
                "type": AnnouncementType.EVENT,
            },
        ]
        ann_added = 0
        for item in announcements:
            exists = db.query(Announcement).filter(Announcement.title == item["title"]).first()
            if exists:
                continue
            db.add(Announcement(title=item["title"], body=item["body"], type=item["type"]))
            ann_added += 1
        db.commit()
        print(f"Announcements: added {ann_added} new")

        # Meetings
        now = datetime.utcnow()
        meetings = [
            {
                "title": "General PTA Assembly",
                "date": now + timedelta(days=14),
                "time": "10:00",
                "venue": "Assembly Hall",
                "agenda": "Term 1 review, dues update, and prefect elections.",
                "status": MeetingStatus.SCHEDULED,
            },
            {
                "title": "Finance Committee Meeting",
                "date": now + timedelta(days=7),
                "time": "14:00",
                "venue": "Admin Block",
                "agenda": "Review collections and expenditure report.",
                "status": MeetingStatus.SCHEDULED,
            },
            {
                "title": "Term 1 Opening Briefing",
                "date": now - timedelta(days=30),
                "time": "09:00",
                "venue": "Main Hall",
                "agenda": "Welcome address and academic calendar.",
                "status": MeetingStatus.COMPLETED,
            },
        ]
        mtg_added = 0
        for item in meetings:
            exists = db.query(Meeting).filter(Meeting.title == item["title"]).first()
            if exists:
                continue
            db.add(
                Meeting(
                    title=item["title"],
                    date=item["date"],
                    time=item["time"],
                    venue=item["venue"],
                    agenda=item["agenda"],
                    term="Term 1",
                    academic_year=ACADEMIC_YEAR,
                    status=item["status"],
                )
            )
            mtg_added += 1
        db.commit()
        print(f"Meetings: added {mtg_added} new")

        total_students = db.query(Student).count()
        total_dues = db.query(DuesConfig).count()
        total_ann = db.query(Announcement).count()
        total_mtg = db.query(Meeting).count()
        print(
            f"\nTable counts — students: {total_students}, dues: {total_dues}, "
            f"announcements: {total_ann}, meetings: {total_mtg}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()

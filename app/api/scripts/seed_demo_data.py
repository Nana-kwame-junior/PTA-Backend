"""Seed demo students, dues, announcements, and meetings."""

from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.student import Student
from app.models.dues_config import DuesConfig
from app.models.announcement import Announcement, AnnouncementType
from app.models.meeting import Meeting, MeetingStatus
from app.models.academic import AcademicYear, AcademicTerm, TermStatus
from app.models.class_level import ClassLevel

ACADEMIC_YEAR = "2024/2025"

# PTA ladder: KG → Primary → JHS → SHS Form (programme required for Form levels).
DEFAULT_CLASS_LEVELS = [
    {"name": "KG", "sequence": 1, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 1", "sequence": 2, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 2", "sequence": 3, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 3", "sequence": 4, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 4", "sequence": 5, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 5", "sequence": 6, "requires_index_number": False, "requires_stream": False},
    {"name": "Primary 6", "sequence": 7, "requires_index_number": False, "requires_stream": False},
    {"name": "JHS 1", "sequence": 8, "requires_index_number": False, "requires_stream": False},
    {"name": "JHS 2", "sequence": 9, "requires_index_number": False, "requires_stream": False},
    {"name": "JHS 3", "sequence": 10, "is_terminal": True, "requires_index_number": True, "requires_stream": False},
    {"name": "Form 1", "sequence": 11, "requires_index_number": True, "requires_stream": True},
    {"name": "Form 2", "sequence": 12, "requires_index_number": True, "requires_stream": True},
    {"name": "Form 3", "sequence": 13, "is_terminal": True, "requires_index_number": True, "requires_stream": True},
]

SHS_PROGRAMMES = [
    "General Science",
    "General Arts",
    "Business",
    "Visual Arts",
    "Home Economics",
    "Agricultural Science",
]

FIRST_NAMES_M = [
    "Kwame", "Kofi", "Yaw", "Kojo", "Kwesi", "Fiifi", "Kwabena", "Ato",
    "Nana", "Mensah", "Ebo", "Papa", "Kobina", "Kweku", "Adom",
]
FIRST_NAMES_F = [
    "Ama", "Akosua", "Abena", "Adwoa", "Afua", "Akua", "Yaa", "Efua",
    "Esi", "Maame", "Serwaa", "Adjoa", "Pokua", "Afi", "Naana",
]
SURNAMES = [
    "Mensah", "Owusu", "Asante", "Boateng", "Osei", "Adjei", "Darko",
    "Ofori", "Appiah", "Amoah", "Frimpong", "Agyeman", "Nkrumah", "Addo",
    "Sarpong", "Gyasi", "Amponsah", "Tetteh", "Quaye", "Annan", "Baah",
    "Acheampong", "Opoku", "Danso", "Kusi",
]


def _phone(n: int) -> str:
    # Stable fake Ghana numbers in +23324xxxxxxx range
    return f"+23324{1000000 + n:07d}"


def _bece_index(n: int) -> str:
    return f"01110{25000 + n:05d}"


def build_students() -> list[dict]:
    """Build ~50 demo students across KG–Primary–JHS–SHS."""
    students: list[dict] = []
    counter = 1

    # ── Hand-picked mobile test wards (kept for registration scenarios) ──
    students.extend(
        [
            {
                "index_number": None,
                "full_name": "Ama Adjei",
                "gender": "F",
                "form": "KG",
                "stream": None,
                "parent_phone_1": "+233241234567",
            },
            {
                "index_number": None,
                "full_name": "Kwame Adjei",
                "gender": "M",
                "form": "Primary 2",
                "stream": None,
                "parent_phone_1": "+233241234567",
            },
            {
                "index_number": "0111025007",
                "full_name": "Yaw Ofori",
                "gender": "M",
                "form": "JHS 2",
                "stream": None,
                "parent_phone_1": "+233551234567",
            },
            {
                "index_number": "0111025099",
                "full_name": "Efua Darko",
                "gender": "F",
                "form": "JHS 3",
                "stream": None,
                "parent_phone_1": "+233501234567",
            },
            {
                "index_number": None,
                "full_name": "Kofi Mensah",
                "gender": "M",
                "form": "JHS 1",
                "stream": None,
                "parent_phone_1": "+233244567890",
            },
        ]
    )

    # ── Extra lower-school students (10) ──
    lower_levels = [
        "KG", "Primary 1", "Primary 2", "Primary 3", "Primary 4",
        "Primary 5", "Primary 6", "JHS 1", "JHS 2", "JHS 3",
    ]
    for i, form in enumerate(lower_levels):
        gender = "F" if i % 2 == 0 else "M"
        first = FIRST_NAMES_F[i % len(FIRST_NAMES_F)] if gender == "F" else FIRST_NAMES_M[i % len(FIRST_NAMES_M)]
        surname = SURNAMES[i % len(SURNAMES)]
        needs_index = form == "JHS 3"
        students.append(
            {
                "index_number": _bece_index(counter) if needs_index else None,
                "full_name": f"{first} {surname}",
                "gender": gender,
                "form": form,
                "stream": None,
                "parent_phone_1": _phone(counter),
            }
        )
        counter += 1

    # ── SHS Form students with programmes (~35 → total ≈ 50) ──
    shs_targets = (
        [("Form 1", 12)]
        + [("Form 2", 12)]
        + [("Form 3", 11)]
    )
    name_i = 0
    for form, count in shs_targets:
        for _ in range(count):
            gender = "F" if name_i % 2 == 0 else "M"
            firsts = FIRST_NAMES_F if gender == "F" else FIRST_NAMES_M
            first = firsts[name_i % len(firsts)]
            surname = SURNAMES[(name_i * 3) % len(SURNAMES)]
            programme = SHS_PROGRAMMES[name_i % len(SHS_PROGRAMMES)]
            students.append(
                {
                    "index_number": _bece_index(100 + counter),
                    "full_name": f"{first} {surname}",
                    "gender": gender,
                    "form": form,
                    "stream": programme,
                    "parent_phone_1": _phone(200 + counter),
                }
            )
            counter += 1
            name_i += 1

    return students


STUDENTS = build_students()

MOBILE_TEST_GUIDE = """
Mobile parent registration test data
------------------------------------
Scenario A — KG ward (no index number):
  Phone: +233241234567
  Parent name: (any, e.g. Grace Adjei)
  Ward name: Ama Adjei
  Ward class: KG
  Index: leave blank

Scenario B — JHS ward (10-digit BECE index):
  Phone: +233551234567
  Ward name: Yaw Ofori
  Ward class: JHS 2
  Index: 0111025007

Scenario C — JHS 3 ward (10-digit BECE index):
  Phone: +233501234567
  Ward name: Efua Darko
  Ward class: JHS 3
  Index: 0111025099

SHS wards use Form 1–3 and must include a programme
(General Science, General Arts, Business, Visual Arts,
Home Economics, or Agricultural Science).

Use OTP from SMS (or Redis in dev) after POST /auth/parent/request-otp.
"""


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

        # Only one terminal level allowed in practice; keep Form 3 as SHS terminal
        # and clear is_terminal on JHS 3 when Form 3 exists.
        level_count = 0
        for row in DEFAULT_CLASS_LEVELS:
            existing = db.query(ClassLevel).filter(ClassLevel.name == row["name"]).first()
            if existing:
                for key in ("requires_index_number", "requires_stream", "is_terminal", "sequence"):
                    if key in row:
                        setattr(existing, key, row[key])
                existing.is_active = True
                continue
            db.add(ClassLevel(**row, is_active=True))
            level_count += 1
        # Prefer a single terminal flag: Form 3 for SHS schools.
        jhs3 = db.query(ClassLevel).filter(ClassLevel.name == "JHS 3").first()
        if jhs3:
            jhs3.is_terminal = False
        db.commit()
        if level_count:
            print(f"Class levels: created {level_count}")
        else:
            print("Class levels: updated/seeded (incl. Form 1–3)")

        student_count = 0
        for row in STUDENTS:
            if row.get("index_number"):
                existing = (
                    db.query(Student)
                    .filter(Student.index_number == row["index_number"])
                    .first()
                )
            else:
                existing = (
                    db.query(Student)
                    .filter(
                        Student.full_name == row["full_name"],
                        Student.form == row["form"],
                        Student.index_number.is_(None),
                    )
                    .first()
                )
            if existing:
                # Keep SHS programme in sync if re-run.
                if row.get("stream") and existing.stream != row["stream"]:
                    existing.stream = row["stream"]
                    existing.form = row["form"]
                continue
            db.add(
                Student(
                    index_number=row.get("index_number"),
                    full_name=row["full_name"],
                    gender=row.get("gender"),
                    form=row["form"],
                    stream=row.get("stream"),
                    academic_year=ACADEMIC_YEAR,
                    parent_phone_1=row["parent_phone_1"],
                    is_active=True,
                )
            )
            student_count += 1
        db.commit()
        print(f"Students: added {student_count} new (sample set: {len(STUDENTS)})")

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
        shs_students = (
            db.query(Student)
            .filter(Student.form.in_(["Form 1", "Form 2", "Form 3"]))
            .count()
        )
        with_programme = (
            db.query(Student)
            .filter(Student.stream.isnot(None), Student.stream != "")
            .count()
        )
        total_dues = db.query(DuesConfig).count()
        total_ann = db.query(Announcement).count()
        total_mtg = db.query(Meeting).count()
        print(
            f"\nTable counts — students: {total_students} "
            f"(SHS/Form: {shs_students}, with programme: {with_programme}), "
            f"dues: {total_dues}, announcements: {total_ann}, meetings: {total_mtg}"
        )
        print(MOBILE_TEST_GUIDE)
    finally:
        db.close()


if __name__ == "__main__":
    seed()

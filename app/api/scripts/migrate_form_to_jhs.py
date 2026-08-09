"""One-time migration: Form 1–3 → JHS 1–3, fix class level flags, update all students."""

import re

from app.api.scripts.seed_demo_data import DEFAULT_CLASS_LEVELS
from app.core.database import SessionLocal
from app.models.class_level import ClassLevel, Track
from app.models.student import Student
from app.services.class_level_names import normalize_student_form_name

FORM_RE = re.compile(r"^Form ([123])$", re.IGNORECASE)
JHS_RE = re.compile(r"^JHS ([123])$", re.IGNORECASE)


def ensure_jhs_class_levels(db) -> int:
    """Create or update the KG–JHS ladder when missing or outdated."""
    created = 0
    for row in DEFAULT_CLASS_LEVELS:
        existing = db.query(ClassLevel).filter(ClassLevel.name == row["name"]).first()
        if existing:
            existing.is_active = True
            for key in ("track", "requires_index_number", "requires_stream", "is_terminal", "sequence"):
                if key in row:
                    setattr(existing, key, row[key])
            continue
        db.add(ClassLevel(**row, is_active=True))
        created += 1
    return created


def migrate_form_to_jhs() -> None:
    db = SessionLocal()
    try:
        levels_created = ensure_jhs_class_levels(db)
        if levels_created:
            print(f"Class levels: created {levels_created} (KG through JHS 3)")
        else:
            print("Class levels: updated existing KG–JHS ladder")

        levels_renamed = 0
        levels_deactivated = 0
        students_form_updated = 0
        students_normalized = 0
        streams_cleared = 0

        for row in db.query(ClassLevel).filter(ClassLevel.is_active == True).all():
            match = FORM_RE.match(row.name.strip())
            if not match:
                continue

            jhs_name = f"JHS {match.group(1)}"
            existing_jhs = (
                db.query(ClassLevel)
                .filter(ClassLevel.name == jhs_name, ClassLevel.is_active == True)
                .first()
            )

            if existing_jhs:
                row.is_active = False
                levels_deactivated += 1
                print(f"Deactivated duplicate Form level: {row.name} (JHS level already exists)")
            else:
                row.name = jhs_name
                row.requires_stream = False
                if jhs_name == "JHS 3":
                    row.requires_index_number = True
                    row.is_terminal = True
                else:
                    row.requires_index_number = False
                    row.is_terminal = False
                levels_renamed += 1
                print(f"Renamed class level: Form {match.group(1)} → {jhs_name}")

        for row in db.query(ClassLevel).filter(ClassLevel.is_active == True).all():
            match = JHS_RE.match(row.name.strip())
            if not match:
                continue
            n = int(match.group(1))
            if n == 3:
                row.requires_index_number = True
                row.is_terminal = True
                row.requires_stream = False
            else:
                row.requires_index_number = False
                row.is_terminal = False
                row.requires_stream = False

        for student in db.query(Student).all():
            raw_form = (student.form or "").strip()
            if not raw_form or raw_form.lower() == "graduated":
                continue

            try:
                canonical = normalize_student_form_name(raw_form)
            except ValueError as e:
                print(f"  Skip student {student.full_name!r}: {e} (form={raw_form!r})")
                continue

            if canonical != raw_form:
                if FORM_RE.match(raw_form):
                    students_form_updated += 1
                    print(f"  Student {student.full_name}: {raw_form} -> {canonical}")
                else:
                    students_normalized += 1
                    print(f"  Student {student.full_name}: normalized {raw_form!r} → {canonical}")
                student.form = canonical

            if student.stream:
                level = (
                    db.query(ClassLevel)
                    .filter(ClassLevel.name == student.form, ClassLevel.is_active == True)
                    .first()
                )
                if level and not level.requires_stream:
                    student.stream = None
                    streams_cleared += 1

        db.commit()

        total_students = db.query(Student).count()
        print("\nMigration summary")
        print(f"  Class levels created:     {levels_created}")
        print(f"  Class levels renamed:     {levels_renamed}")
        print(f"  Class levels deactivated: {levels_deactivated}")
        print(f"  Students Form to JHS:       {students_form_updated}")
        print(f"  Students normalized:      {students_normalized}")
        print(f"  Streams cleared:          {streams_cleared}")
        print(f"  Total students in DB:     {total_students}")
    finally:
        db.close()


if __name__ == "__main__":
    migrate_form_to_jhs()

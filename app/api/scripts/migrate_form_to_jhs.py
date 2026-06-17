"""One-time migration: Form 1–3 → JHS 1–3, fix class level flags."""

import re

from app.core.database import SessionLocal
from app.models.class_level import ClassLevel
from app.models.student import Student

FORM_RE = re.compile(r"^Form ([123])$")
JHS_RE = re.compile(r"^JHS ([123])$")


def migrate_form_to_jhs() -> None:
    db = SessionLocal()
    try:
        levels_renamed = 0
        levels_deactivated = 0
        students_updated = 0
        streams_cleared = 0

        for row in db.query(ClassLevel).filter(ClassLevel.is_active == True).all():
            match = FORM_RE.match(row.name)
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

        for student in db.query(Student).all():
            form = (student.form or "").strip()
            match = FORM_RE.match(form)
            if match:
                student.form = f"JHS {match.group(1)}"
                students_updated += 1

            if student.stream and student.form:
                level = (
                    db.query(ClassLevel)
                    .filter(ClassLevel.name == student.form, ClassLevel.is_active == True)
                    .first()
                )
                if level and not level.requires_stream:
                    student.stream = None
                    streams_cleared += 1

        for row in db.query(ClassLevel).filter(ClassLevel.is_active == True).all():
            match = JHS_RE.match(row.name)
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

        db.commit()

        print("\nMigration summary")
        print(f"  Class levels renamed:    {levels_renamed}")
        print(f"  Class levels deactivated:{levels_deactivated}")
        print(f"  Students updated:        {students_updated}")
        print(f"  Streams cleared:         {streams_cleared}")
    finally:
        db.close()


if __name__ == "__main__":
    migrate_form_to_jhs()

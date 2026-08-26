"""Promote students using admin-configured class levels (two independent tracks)."""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.class_level import ClassLevel, Track
from app.models.student import Student
from app.services.class_level_names import find_class_level, normalize_class_level_name


_utc_now = lambda: datetime.now(timezone.utc).replace(tzinfo=None)


def _promotion_map(db: Session) -> dict[str, dict]:
    """
    Returns mapping of canonical level name -> dict describing what happens next.

    Built per track so a BASIC level never promotes into SHS (and vice versa).
    Entry shape:
      {"kind": "promote", "next": "Form 2"}  or
      {"kind": "graduate_basic"}             (BASIC terminal -> JHS 3)          or
      {"kind": "graduate_shs"}               (SHS   terminal -> Form 3)

    Non-terminal tail levels (no successor and not terminal) are omitted from
    the map so the student stays unchanged.
    """
    levels = (
        db.query(ClassLevel)
        .filter(ClassLevel.is_active == True)
        .order_by(ClassLevel.sequence.asc())
        .all()
    )
    by_track: dict[Track, list[ClassLevel]] = defaultdict(list)
    for level in levels:
        by_track[level.track].append(level)

    mapping: dict[str, dict] = {}
    for track_levels in by_track.values():
        track_levels.sort(key=lambda row: row.sequence)
        for index, level in enumerate(track_levels):
            try:
                key = normalize_class_level_name(level.name)
            except ValueError:
                continue

            if level.is_terminal:
                if level.track == Track.SHS:
                    mapping[key] = {"kind": "graduate_shs"}
                else:
                    mapping[key] = {"kind": "graduate_basic"}
            elif index + 1 < len(track_levels):
                next_level = track_levels[index + 1]
                try:
                    next_name = normalize_class_level_name(next_level.name)
                except ValueError:
                    next_name = next_level.name
                mapping[key] = {"kind": "promote", "next": next_name}

    return mapping


def _level_requires_index(db: Session, level_name: str) -> bool:
    level = find_class_level(db, level_name)
    return bool(level and level.requires_index_number)


def stamp_active_students_academic_year(db: Session, track: Track, academic_year: str) -> int:
    """Mark every active student on this track as belonging to the new academic year."""
    return (
        db.query(Student)
        .filter(Student.is_active == True, Student.track == track)
        .update({Student.academic_year: academic_year}, synchronize_session=False)
    )


def promote_students_for_year(db: Session, academic_year: str, track: Track) -> dict:
    """
    Move each active student to the next configured class level WITHIN THEIR TRACK.

    Includes students whose academic_year is the closed year or earlier (lagged
    records from a previous year that never got restamped). Students already
    stamped with a later year (e.g. new Form 1 intake) are left alone.

    Terminal level behavior:
      * JHS 3 (BASIC terminal)  -> graduated_basic_at = now(), is_active=False.
        form/academic_year are preserved as permanent historical record.
      * Form 3 (SHS terminal)   -> graduated_shs_at   = now(), is_active=False.
        form/academic_year are preserved as permanent historical record.
    """
    ladder = _promotion_map(db)
    if not ladder:
        return {
            "promoted": 0,
            "graduated_basic": 0,
            "graduated_shs": 0,
            "unchanged": 0,
            "total_processed": 0,
            "needs_index": [],
            "message": "No class levels configured — add levels in admin settings first.",
        }

    students = (
        db.query(Student)
        .filter(
            Student.is_active == True,
            Student.track == track,
            or_(
                Student.academic_year.is_(None),
                Student.academic_year == "",
                Student.academic_year <= academic_year,
            ),
        )
        .all()
    )
    promoted = 0
    graduated_basic = 0
    graduated_shs = 0
    unchanged = 0
    needs_index: list[dict] = []

    for student in students:
        form = (student.form or "").strip()
        if not form:
            unchanged += 1
            continue

        level = find_class_level(db, form)
        if not level:
            unchanged += 1
            continue

        try:
            canonical = normalize_class_level_name(level.name)
        except ValueError:
            unchanged += 1
            continue
        if canonical not in ladder:
            unchanged += 1
            continue

        step = ladder[canonical]
        kind = step["kind"]

        if kind == "promote":
            next_form = step["next"]
            student.form = next_form
            student.academic_year = academic_year
            next_level = find_class_level(db, next_form)
            if next_level:
                student.track = next_level.track
            promoted += 1
            if _level_requires_index(db, next_form) and not (student.index_number or "").strip():
                needs_index.append(
                    {
                        "student_id": str(student.id),
                        "full_name": student.full_name,
                        "form": next_form,
                    }
                )
        elif kind == "graduate_basic":
            if student.graduated_basic_at is None:
                student.graduated_basic_at = _utc_now()
            student.is_active = False
            # form / academic_year intentionally left as-is for permanent history.
            graduated_basic += 1
        elif kind == "graduate_shs":
            if student.graduated_shs_at is None:
                student.graduated_shs_at = _utc_now()
            student.is_active = False
            # form / academic_year intentionally left as-is for permanent history.
            graduated_shs += 1

    return {
        "promoted": promoted,
        "graduated_basic": graduated_basic,
        "graduated_shs": graduated_shs,
        "unchanged": unchanged,
        "total_processed": len(students),
        "needs_index": needs_index,
    }

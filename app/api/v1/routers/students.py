from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.dependencies import require_permission
from app.models.student import Student
from app.models.academic import AcademicYear
from app.models.class_level import ClassLevel, Track
from app.schemas.student import StudentCreate, StudentUpdate, LinkParentRequest, EnrollShsRequest
from app.services.student_validation import validate_student_fields, normalize_gender, normalize_form_name
from app.services.class_level_names import find_class_level
from app.services.activity_log import log_staff_activity
import csv
import io
from uuid import UUID

router = APIRouter(prefix="/students", tags=["Students"])


def _serialize_student(student: Student) -> dict:
    return {
        "id": str(student.id),
        "index_number": student.index_number,
        "full_name": student.full_name,
        "gender": student.gender,
        "form": student.form,
        "stream": student.stream,
        "track": str(student.track.value) if hasattr(student.track, 'value') else str(student.track) if student.track else None,
        "academic_year": student.academic_year,
        "parent_phone_1": student.parent_phone_1,
        "parent_phone_2": student.parent_phone_2,
        "is_active": student.is_active,
        "graduated_basic_at": student.graduated_basic_at.isoformat() if student.graduated_basic_at else None,
        "graduated_shs_at": student.graduated_shs_at.isoformat() if student.graduated_shs_at else None,
    }


# Columns differ by stage. Import uses DictReader so unused columns can be omitted.
SAMPLE_CSV_PRIMARY = (
    "full_name,gender,form,parent_phone_1,parent_phone_2\n"
    "Ama Adjei,F,KG,+233241234567,\n"
    "Kwame Mensah,M,Primary 1,+233241234568,+233501111111\n"
    "Akosua Boateng,F,Primary 2,+233244567890,\n"
    "Yaw Asante,M,Primary 4,+233551234567,\n"
    "Efua Darko,F,Primary 6,+233501234567,+233242222333\n"
)

SAMPLE_CSV_JHS = (
    "index_number,full_name,gender,form,parent_phone_1,parent_phone_2\n"
    ",Kofi Owusu,M,JHS 1,+233241111222,\n"
    ",Abena Sarpong,F,JHS 1,+233242222333,\n"
    ",Kojo Boateng,M,JHS 2,+233244567890,\n"
    "0111025001,Yaw Ofori,M,JHS 3,+233551234567,\n"
    "0111025002,Efua Nkrumah,F,JHS 3,+233501234567,+233241000001\n"
)

SAMPLE_CSV_SHS = (
    "index_number,full_name,gender,form,stream,parent_phone_1,parent_phone_2\n"
    "0111025101,Ama Serwah,F,Form 1,General Arts,+233241111222,\n"
    "0111025102,Kojo Appiah,M,Form 1,General Science,+233242222333,\n"
    "0111025103,Esi Kwansah,F,Form 2,Business,+233503333444,\n"
    "0111025104,Kwaku Adjei,M,Form 2,Home Economics,+233244567890,\n"
    "0111025105,Akua Mensah,F,Form 3,Visual Arts,+233551234567,+233501000002\n"
)

_SAMPLE_BY_KIND = {
    "primary": ("students_import_primary.csv", SAMPLE_CSV_PRIMARY),
    "jhs": ("students_import_jhs.csv", SAMPLE_CSV_JHS),
    "shs": ("students_import_shs.csv", SAMPLE_CSV_SHS),
}


def _csv_cell(row: dict, *keys: str) -> str:
    for key in keys:
        value = (row.get(key) or "").strip()
        if value:
            return value
    return ""


@router.get("/import/sample")
async def download_import_sample(
    kind: str = Query(..., description="primary, jhs, or shs"),
    staff=Depends(require_permission("students")),
):
    key = (kind or "").strip().lower()
    sample = _SAMPLE_BY_KIND.get(key)
    if not sample:
        raise HTTPException(status_code=400, detail="kind must be one of: primary, jhs, shs")
    filename, body = sample
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import")
async def import_students(
    file: UploadFile = File(...),
    academic_year: str = Query(...),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    contents = await file.read()
    text = contents.decode("utf-8-sig")
    csv_reader = csv.DictReader(io.StringIO(text))
    imported = 0
    errors = []
    row_count = 0
    for i, row in enumerate(csv_reader):
        row_count = i + 1
        normalized_row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            form_raw = _csv_cell(normalized_row, "form", "class", "level")
            full_name = _csv_cell(normalized_row, "full_name", "name")
            form_name = normalize_form_name(form_raw)
            if not form_name:
                raise ValueError("form is required")
            if not full_name:
                raise ValueError("full_name is required")
            idx, strm, gender = validate_student_fields(
                db,
                form_name,
                _csv_cell(normalized_row, "index_number", "index") or None,
                _csv_cell(normalized_row, "stream", "programme", "program") or None,
                _csv_cell(normalized_row, "gender") or None,
            )
            if idx:
                dup = db.query(Student).filter(Student.index_number == idx).first()
                if dup:
                    raise ValueError(f"Duplicate index number {idx}")
            _level = find_class_level(db, form_name)
            _form_track = _level.track if _level else Track.BASIC
            student = Student(
                index_number=idx,
                full_name=full_name,
                gender=gender,
                form=form_name,
                stream=strm,
                track=_form_track,
                academic_year=academic_year.strip(),
                parent_phone_1=_csv_cell(normalized_row, "parent_phone_1", "phone", "phone_1") or None,
                parent_phone_2=_csv_cell(normalized_row, "parent_phone_2", "phone_2") or None,
            )
            db.add(student)
            imported += 1
        except Exception as e:
            errors.append({"row": i + 2, "reason": str(e)})
    if imported:
        db.commit()
    return {
        "success": True,
        "data": {
            "total_rows": row_count,
            "imported": imported,
            "skipped_duplicates": len(errors),
            "errors": errors,
        },
    }


@router.get("")
async def list_students(
    page: int = 1,
    limit: int = 20,
    search: str = None,
    form: str = None,
    stream: str = None,
    academic_year: str = None,
    is_active: bool = None,
    track: str = None,
    graduation: str = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("students")),
):
    query = db.query(Student)
    if search:
        query = query.filter(
            Student.full_name.ilike(f"%{search}%")
            | Student.index_number.ilike(f"%{search}%")
        )
    if form:
        query = query.filter(Student.form == form)
    if stream:
        query = query.filter(Student.stream == stream)
    if academic_year:
        query = query.filter(Student.academic_year == academic_year)
    if track:
        track_enum = Track.BASIC if str(track).strip().upper() == "BASIC" else Track.SHS
        query = query.filter(Student.track == track_enum)

    graduation_key = (graduation or "").strip().lower()
    if graduation_key:
        if graduation_key not in {"jhs", "shs"}:
            raise HTTPException(status_code=400, detail="graduation must be one of: jhs, shs")
        if graduation_key == "jhs":
            query = query.filter(
                Student.graduated_basic_at.isnot(None),
                Student.graduated_shs_at.is_(None),
                Student.is_active == False,
            ).order_by(Student.graduated_basic_at.desc())
        else:
            query = query.filter(Student.graduated_shs_at.isnot(None)).order_by(
                Student.graduated_shs_at.desc()
            )
    elif is_active is not None:
        query = query.filter(Student.is_active == is_active)

    total = query.count()
    students = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "success": True,
        "data": {
            "students": [_serialize_student(s) for s in students],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": (total + limit - 1) // limit,
            },
        },
    }


@router.get("/detail/{student_id}")
async def get_student_detail(
    student_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    from app.services.parent_directory import linked_parents_for_student

    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    data = _serialize_student(student)
    data["linked_parents"] = linked_parents_for_student(db, student.id)
    return {"success": True, "data": data}


@router.get("/{index_number}")
async def get_student_by_index(
    index_number: str,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    student = db.query(Student).filter(Student.index_number == index_number).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return {"success": True, "data": _serialize_student(student)}


@router.post("")
async def create_student(
    data: StudentCreate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    try:
        form_name = normalize_form_name(data.form)
        idx, strm, gender = validate_student_fields(
            db, form_name, data.index_number, data.stream, data.gender
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _level = find_class_level(db, form_name)
    _form_track = _level.track if _level else Track.BASIC
    student = Student(
        index_number=idx,
        full_name=data.full_name.strip(),
        gender=gender,
        form=form_name,
        stream=strm,
        track=_form_track,
        academic_year=data.academic_year,
        parent_phone_1=data.parent_phone_1,
        parent_phone_2=data.parent_phone_2,
    )
    db.add(student)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student record already exists") from e
    db.refresh(student)
    log_staff_activity(
        db,
        staff,
        page_label="Students",
        action_label=f"Added student {student.full_name}",
        details=student.index_number or student.form,
    )
    return {"success": True, "data": _serialize_student(student)}


@router.patch("/{student_id}")
async def update_student(
    student_id: UUID,
    data: StudentUpdate,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404)
    payload = data.dict(exclude_unset=True)
    form = payload.get("form", student.form)
    index_number = payload.get("index_number", student.index_number)
    stream = payload.get("stream", student.stream)
    gender = payload.get("gender", student.gender)
    try:
        idx, strm, g = validate_student_fields(db, form, index_number, stream, gender)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    payload["index_number"] = idx
    payload["stream"] = strm
    payload["gender"] = g
    for key, value in payload.items():
        setattr(student, key, value)
    if "form" in payload:
        lvl = find_class_level(db, form)
        if lvl:
            student.track = lvl.track
    db.commit()
    log_staff_activity(
        db,
        staff,
        page_label="Students",
        action_label=f"Updated student {student.full_name}",
        details=student.index_number or student.form,
    )
    return {"success": True, "data": _serialize_student(student)}


@router.delete("/{student_id}")
async def delete_student(
    student_id: UUID,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404)
    name = student.full_name
    student.is_active = False
    db.commit()
    log_staff_activity(
        db,
        staff,
        page_label="Students",
        action_label=f"Removed student {name}",
        details="Soft deleted — record kept inactive",
    )
    return {"success": True, "data": {"message": "Student deactivated"}}


@router.post("/{student_id}/enroll-shs")
async def enroll_student_in_shs(
    student_id: UUID,
    data: EnrollShsRequest,
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    if student.graduated_basic_at is None:
        raise HTTPException(status_code=400, detail="Student must have graduated JHS 3 / Basic education first (graduated_basic_at missing)")
    if student.graduated_shs_at is not None:
        raise HTTPException(status_code=400, detail="Student has already completed SHS — cannot re-enroll")
    if student.is_active:
        raise HTTPException(status_code=400, detail="Student is still active in Basic track — close the term and let Basic graduation deactivate first")

    year = db.query(AcademicYear).filter(AcademicYear.id == str(data.academic_year_id)).first()
    if not year:
        raise HTTPException(status_code=400, detail="academic_year_id not found")
    if year.track != Track.SHS:
        raise HTTPException(status_code=400, detail=f"Target academic year {year.label!r} is not marked track=SHS")

    level = db.query(ClassLevel).filter(ClassLevel.id == str(data.class_level_id)).first()
    if not level:
        raise HTTPException(status_code=400, detail="class_level_id not found")
    if level.track != Track.SHS or level.name.strip() != "Form 1":
        raise HTTPException(status_code=400, detail="SHS enrollment must target the Form 1 (SHS track) class level")

    if level.requires_stream:
        stream_val = (data.stream or "").strip() or None
        if not stream_val:
            raise HTTPException(status_code=400, detail=f"Programme/stream is required for {level.name} (e.g. General Arts, General Science, Business)")
    else:
        stream_val = None

    student.is_active = True
    student.form = "Form 1"
    student.track = Track.SHS
    student.stream = stream_val
    student.academic_year = year.label

    db.commit()
    db.refresh(student)

    try:
        from app.services.activity_log import log_staff_activity
        log_staff_activity(
            db, staff,
            page_label="Students",
            action_label=f"Enrolled {student.full_name} into SHS Form 1",
            details=f"year={year.label}, stream={stream_val or 'N/A'}"
        )
    except Exception:
        pass

    return {"success": True, "data": _serialize_student(student)}

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.dependencies import require_permission
from app.models.student import Student
from app.schemas.student import StudentCreate, StudentUpdate, LinkParentRequest
from app.services.student_validation import validate_student_fields, normalize_gender
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
        "academic_year": student.academic_year,
        "parent_phone_1": student.parent_phone_1,
        "parent_phone_2": student.parent_phone_2,
        "is_active": student.is_active,
    }


SAMPLE_CSV = (
    "index_number,full_name,gender,form,stream,parent_phone_1,parent_phone_2\n"
    ",Ama Adjei,F,KG,,+233241234567,\n"
    ",Kwame Adjei,M,Primary 2,,+233241234567,\n"
    "0111025007,Yaw Ofori,M,JHS 2,,+233551234567,\n"
    "0111025099,Efua Darko,F,Form 2,General Arts,+233501234567,\n"
)


@router.get("/import/sample")
async def download_import_sample(staff=Depends(require_permission("students"))):
    return StreamingResponse(
        iter([SAMPLE_CSV]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_import_sample.csv"},
    )


@router.post("/import")
async def import_students(
    file: UploadFile = File(...),
    academic_year: str = Query(...),
    db: Session = Depends(get_db),
    staff=Depends(require_permission("students")),
):
    contents = await file.read()
    csv_reader = csv.DictReader(io.StringIO(contents.decode("utf-8")))
    imported = 0
    errors = []
    row_count = 0
    for i, row in enumerate(csv_reader):
        row_count = i + 1
        try:
            idx, strm, gender = validate_student_fields(
                db,
                row["form"],
                row.get("index_number"),
                row.get("stream"),
                row.get("gender"),
            )
            if idx:
                dup = db.query(Student).filter(Student.index_number == idx).first()
                if dup:
                    raise ValueError(f"Duplicate index number {idx}")
            student = Student(
                index_number=idx,
                full_name=row["full_name"].strip(),
                gender=gender,
                form=row["form"].strip(),
                stream=strm,
                academic_year=academic_year,
                parent_phone_1=row.get("parent_phone_1") or None,
                parent_phone_2=row.get("parent_phone_2") or None,
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
    limit: int = 50,
    search: str = None,
    form: str = None,
    stream: str = None,
    academic_year: str = None,
    is_active: bool = None,
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
    if is_active is not None:
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
        idx, strm, gender = validate_student_fields(
            db, data.form, data.index_number, data.stream, data.gender
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    student = Student(
        index_number=idx,
        full_name=data.full_name.strip(),
        gender=gender,
        form=data.form.strip(),
        stream=strm,
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

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.dependencies import require_role
from app.models.student import Student
from app.schemas.student import StudentCreate, StudentUpdate, LinkParentRequest
import csv
import io
from uuid import UUID

router = APIRouter(prefix="/students", tags=["Students"])

@router.post("/import")
async def import_students(
    file: UploadFile = File(...),
    academic_year: str = Query(...),
    db: Session = Depends(get_db),
    admin=Depends(require_role("ADMIN"))
):
    contents = await file.read()
    csv_reader = csv.DictReader(io.StringIO(contents.decode('utf-8')))
    imported = 0
    errors = []
    for i, row in enumerate(csv_reader):
        try:
            student = Student(
                index_number=row['index_number'],
                full_name=row['full_name'],
                form=row['form'],
                stream=row['stream'],
                academic_year=academic_year,
                parent_phone_1=row.get('parent_phone_1'),
                parent_phone_2=row.get('parent_phone_2')
            )
            db.add(student)
            imported += 1
        except Exception as e:
            errors.append({"row": i+2, "reason": str(e)})
    db.commit()
    return {"success": True, "data": {"total_rows": i+1, "imported": imported, "skipped_duplicates": len(errors), "errors": errors}}

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
    current_user=Depends(require_role("FINANCIAL_STAFF"))
):
    query = db.query(Student)
    if search:
        query = query.filter(Student.full_name.ilike(f"%{search}%") | Student.index_number.ilike(f"%{search}%"))
    if form:
        query = query.filter(Student.form == form)
    if stream:
        query = query.filter(Student.stream == stream)
    if academic_year:
        query = query.filter(Student.academic_year == academic_year)
    if is_active is not None:
        query = query.filter(Student.is_active == is_active)
    total = query.count()
    students = query.offset((page-1)*limit).limit(limit).all()
    return {"success": True, "data": {"students": students, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": (total+limit-1)//limit}}}

@router.get("/{index_number}")
async def get_student_by_index(index_number: str, db: Session = Depends(get_db), staff=Depends(require_role("FINANCIAL_STAFF"))):
    student = db.query(Student).filter(Student.index_number == index_number).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return {"success": True, "data": student}

@router.post("")
async def create_student(data: StudentCreate, db: Session = Depends(get_db), admin=Depends(require_role("ADMIN"))):
    student = Student(**data.dict())
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"success": True, "data": student}

@router.patch("/{student_id}")
async def update_student(student_id: UUID, data: StudentUpdate, db: Session = Depends(get_db), admin=Depends(require_role("ADMIN"))):
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404)
    for key, value in data.dict(exclude_unset=True).items():
        setattr(student, key, value)
    db.commit()
    return {"success": True, "data": student}

@router.delete("/{student_id}")
async def delete_student(student_id: UUID, db: Session = Depends(get_db), admin=Depends(require_role("ADMIN"))):
    
    student = db.query(Student).filter(Student.id == str(student_id)).first()
    if not student:
        raise HTTPException(status_code=404)
    student.is_active = False
    db.commit()
    return {"success": True, "data": {"message": "Student deactivated"}}
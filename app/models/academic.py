from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey, Enum as SQLEnum, UniqueConstraint
from app.core.database import Base
import uuid
from datetime import datetime
import enum


class TermStatus(str, enum.Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    label = Column(String(20), unique=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AcademicTerm(Base):
    __tablename__ = "academic_terms"
    __table_args__ = (UniqueConstraint("academic_year_id", "name", name="uq_year_term_name"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = Column(String(36), ForeignKey("academic_years.id"), nullable=False)
    academic_year = Column(String(20), nullable=False)
    name = Column(String(20), nullable=False)
    sequence = Column(Integer, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(SQLEnum(TermStatus), default=TermStatus.PLANNED)
    is_current = Column(Boolean, default=False)
    auto_promote_on_close = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

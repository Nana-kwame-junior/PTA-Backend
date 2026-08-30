"""Calculate student PTA dues balance for SMS and reporting."""

from decimal import Decimal

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.academic import AcademicTerm
from app.models.class_level import Track
from app.models.dues_config import DuesConfig
from app.models.manual_payment import ManualPayment, ManualPaymentMode
from app.models.payment import Payment, PaymentStatus
from app.models.student import Student


def _term_sort_key(term: AcademicTerm) -> tuple[str, int]:
    return (term.academic_year, term.sequence)


def _terms_up_to_current(db: Session, track: Track, current_term: AcademicTerm) -> list[AcademicTerm]:
    """All academic terms on this track up to and including the current term (cross-year)."""
    current_key = _term_sort_key(current_term)
    terms = (
        db.query(AcademicTerm)
        .filter(AcademicTerm.track == track)
        .order_by(AcademicTerm.academic_year.asc(), AcademicTerm.sequence.asc())
        .all()
    )
    return [term for term in terms if _term_sort_key(term) <= current_key]


def _online_allocated_for_reference(db: Session, student_id: str, paystack_reference: str) -> Decimal:
    total = (
        db.query(func.coalesce(func.sum(ManualPayment.amount_ghs), 0))
        .filter(
            ManualPayment.student_id == student_id,
            ManualPayment.notes.like(f"%Online:{paystack_reference}%"),
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def student_term_dues_balance(
    db: Session,
    *,
    student_id: str,
    academic_year: str,
    term: str,
    exclude_manual_payment_id: str | None = None,
) -> dict:
    dues = (
        db.query(DuesConfig)
        .filter(
            DuesConfig.academic_year == academic_year,
            DuesConfig.term == term,
            DuesConfig.is_active == True,
        )
        .first()
    )
    expected = Decimal(str(dues.amount_ghs)) if dues else Decimal("0")

    manual_query = db.query(func.coalesce(func.sum(ManualPayment.amount_ghs), 0)).filter(
        ManualPayment.student_id == student_id,
        ManualPayment.academic_year == academic_year,
        ManualPayment.term == term,
    )
    if exclude_manual_payment_id:
        manual_query = manual_query.filter(ManualPayment.id != exclude_manual_payment_id)
    manual_paid = Decimal(str(manual_query.scalar() or 0))

    online_paid = Decimal("0")
    if dues:
        online_rows = (
            db.query(Payment)
            .filter(
                Payment.student_id == student_id,
                Payment.dues_config_id == dues.id,
                Payment.status == PaymentStatus.COMPLETED,
            )
            .all()
        )
        for payment in online_rows:
            allocated = _online_allocated_for_reference(db, student_id, payment.paystack_reference)
            if allocated > 0:
                current_part = Decimal(str(payment.amount_ghs)) - allocated
                online_paid += max(current_part, Decimal("0"))
            else:
                online_paid += Decimal(str(payment.amount_ghs))

    total_paid = manual_paid + online_paid
    remaining = max(expected - total_paid, Decimal("0"))
    return {
        "expected_ghs": expected,
        "paid_ghs": total_paid,
        "remaining_ghs": remaining,
    }


def get_current_academic_term(db: Session, track: Track) -> AcademicTerm | None:
    return db.query(AcademicTerm).filter(AcademicTerm.is_current == True, AcademicTerm.track == track).first()


def student_outstanding_summary(
    db: Session,
    *,
    student_id: str,
    track: Track,
    current_term: AcademicTerm | None = None,
) -> dict:
    """Outstanding dues for a student: current term + unpaid prior terms in the same year."""
    current_term = current_term or get_current_academic_term(db, track)
    if not current_term:
        return {
            "student_id": student_id,
            "current_term": None,
            "academic_year": None,
            "dues_config_id": None,
            "due_date": None,
            "current_term_amount_ghs": "0",
            "arrears_ghs": "0",
            "total_due_ghs": "0",
            "breakdown": [],
        }

    terms = _terms_up_to_current(db, track, current_term)

    breakdown: list[dict] = []
    arrears = Decimal("0")
    current_amount = Decimal("0")
    total_due = Decimal("0")

    for term in terms:
        bal = student_term_dues_balance(
            db,
            student_id=student_id,
            academic_year=term.academic_year,
            term=term.name,
        )
        remaining = bal["remaining_ghs"]
        expected = bal["expected_ghs"]
        if expected <= 0 and remaining <= 0:
            continue

        is_current = term.id == current_term.id
        is_arrear = not is_current and remaining > 0
        is_prior_year_arrear = is_arrear and term.academic_year != current_term.academic_year
        breakdown.append(
            {
                "academic_year": term.academic_year,
                "term": term.name,
                "sequence": term.sequence,
                "expected_ghs": str(expected),
                "paid_ghs": str(bal["paid_ghs"]),
                "remaining_ghs": str(remaining),
                "is_current": is_current,
                "is_arrear": is_arrear,
                "is_prior_year_arrear": is_prior_year_arrear,
            }
        )
        total_due += remaining
        if is_arrear:
            arrears += remaining
        if is_current:
            current_amount = expected

    current_dues = (
        db.query(DuesConfig)
        .filter(
            DuesConfig.academic_year == current_term.academic_year,
            DuesConfig.term == current_term.name,
            DuesConfig.is_active == True,
        )
        .first()
    )

    return {
        "student_id": student_id,
        "current_term": current_term.name,
        "academic_year": current_term.academic_year,
        "dues_config_id": str(current_dues.id) if current_dues else None,
        "due_date": current_dues.due_date.isoformat() if current_dues and current_dues.due_date else None,
        "current_term_amount_ghs": str(current_amount),
        "arrears_ghs": str(arrears),
        "total_due_ghs": str(total_due),
        "breakdown": breakdown,
    }


def apply_payment_fifo(
    db: Session,
    *,
    student_id: str,
    track: Track,
    amount,
    payment_date,
    recorded_by_user_id: str,
    recorded_by_name: str,
    payment_mode,
    receipt_number: str,
    parent_phone: str | None,
    student_name: str,
    student_index_no: str | None,
    allocation_note: str,
    exclude_manual_payment_id: str | None = None,
) -> tuple[list[ManualPayment], Decimal]:
    """
    Apply a payment oldest-term-first across outstanding balances in the current academic year.
    Returns manual payment rows created for arrear terms and the portion left for the current term.
    """
    current_term = get_current_academic_term(db, track)
    if not current_term:
        return [], Decimal(str(amount))

    terms = _terms_up_to_current(db, track, current_term)

    remaining = Decimal(str(amount))
    created: list[ManualPayment] = []
    current_portion = Decimal("0")

    for term in terms:
        if remaining <= 0:
            break
        bal = student_term_dues_balance(
            db,
            student_id=student_id,
            academic_year=term.academic_year,
            term=term.name,
            exclude_manual_payment_id=exclude_manual_payment_id,
        )
        owed = bal["remaining_ghs"]
        if owed <= 0:
            continue

        portion = min(owed, remaining)
        if portion <= 0:
            continue

        if term.id == current_term.id:
            current_portion = portion
            remaining -= portion
            continue

        manual = ManualPayment(
            receipt_number=f"{receipt_number}-AR{term.sequence}",
            student_id=student_id,
            student_index_no=student_index_no,
            student_name=student_name,
            parent_phone=parent_phone,
            term=term.name,
            academic_year=term.academic_year,
            amount_ghs=portion,
            payment_mode=payment_mode,
            payment_date=payment_date,
            recorded_by_user_id=recorded_by_user_id,
            recorded_by_name=recorded_by_name,
            notes=f"{allocation_note} · {term.name} · {term.academic_year}",
        )
        db.add(manual)
        created.append(manual)
        remaining -= portion

    if remaining > 0 and current_portion <= 0:
        bal = student_term_dues_balance(
            db,
            student_id=student_id,
            academic_year=current_term.academic_year,
            term=current_term.name,
            exclude_manual_payment_id=exclude_manual_payment_id,
        )
        current_portion = min(bal["remaining_ghs"], remaining)

    return created, current_portion


def apply_online_payment_allocations(
    db: Session,
    *,
    payment: Payment,
    student: Student | None,
    parent_phone: str | None,
) -> None:
    """Split a completed online payment across arrear terms; current term uses the Payment row."""
    student = student or db.query(Student).filter(Student.id == payment.student_id).first()
    if not student:
        return
    track = student.track if student.track else Track.BASIC

    note_prefix = f"Online:{payment.paystack_reference}"
    existing = (
        db.query(ManualPayment)
        .filter(ManualPayment.notes.like(f"%{note_prefix}%"))
        .count()
    )
    if existing:
        return

    apply_payment_fifo(
        db,
        student_id=student.id,
        track=track,
        amount=payment.amount_ghs,
        payment_date=payment.paid_at or payment.created_at,
        recorded_by_user_id="online",
        recorded_by_name="Online Payment",
        payment_mode=ManualPaymentMode.BANK_DEPOSIT,
        receipt_number=payment.receipt_number or payment.paystack_reference,
        parent_phone=parent_phone,
        student_name=student.full_name,
        student_index_no=student.index_number,
        allocation_note=note_prefix,
    )


def format_payment_sms(
    *,
    student_name: str,
    amount_ghs,
    term: str,
    academic_year: str,
    receipt_number: str,
    balance_before,
    balance_after,
    channel: str = "Payment",
) -> str:
    amt = Decimal(str(amount_ghs))
    before = Decimal(str(balance_before))
    after = Decimal(str(balance_after))
    return (
        f"{channel} received: GH₵{amt:.2f} for {student_name}, {term} · {academic_year}. "
        f"Previous balance owed: GH₵{before:.2f}. "
        f"Remaining balance: GH₵{after:.2f}. "
        f"Receipt: {receipt_number}. —SchoolPulse"
    )

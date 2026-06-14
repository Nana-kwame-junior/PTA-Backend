"""Calculate student PTA dues balance for SMS and reporting."""

from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.dues_config import DuesConfig
from app.models.manual_payment import ManualPayment
from app.models.payment import Payment, PaymentStatus


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

    online_paid = Decimal(
        str(
            db.query(func.coalesce(func.sum(Payment.amount_ghs), 0))
            .join(DuesConfig, Payment.dues_config_id == DuesConfig.id)
            .filter(
                Payment.student_id == student_id,
                Payment.status == PaymentStatus.COMPLETED,
                DuesConfig.academic_year == academic_year,
                DuesConfig.term == term,
            )
            .scalar()
            or 0
        )
    )

    total_paid = manual_paid + online_paid
    remaining = max(expected - total_paid, Decimal("0"))
    return {
        "expected_ghs": expected,
        "paid_ghs": total_paid,
        "remaining_ghs": remaining,
    }


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
        f"Receipt: {receipt_number}. — Mawuli SHS PTA"
    )

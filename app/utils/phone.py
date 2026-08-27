"""Ghana phone normalization for storage (E.164) and mNotify (233XXXXXXXXX)."""

import re
from decimal import Decimal, InvalidOperation

GHANA_LOCAL_RE = re.compile(r"^[235]\d{8}$")
SCI_NOTATION_RE = re.compile(r"^\d*\.?\d+[eE][+\-]?\d+$")

_EXCEL_TRUNCATION_MSG = (
    "Phone was saved as Excel scientific notation (e.g. 2.3353E+11) and lost digits. "
    "Format the phone column as Text in Excel (prefix with ' ) and export the CSV again."
)


class PhoneValidationError(ValueError):
    pass


def _scientific_significant_digits(text: str) -> int:
    mantissa = re.split(r"[eE]", text.strip(), maxsplit=1)[0]
    digits = re.sub(r"\D", "", mantissa).lstrip("0")
    return len(digits) if digits else 0


def _extract_digits(raw: str) -> str:
    """Pull digits from text; expand Excel scientific notation when all digits survived."""
    text = (raw or "").strip().lstrip("'").strip()
    if not text:
        return ""
    if SCI_NOTATION_RE.match(text):
        if _scientific_significant_digits(text) < 9:
            raise PhoneValidationError(_EXCEL_TRUNCATION_MSG)
        try:
            return format(Decimal(text), "f").split(".")[0]
        except (InvalidOperation, ValueError, OverflowError) as exc:
            raise PhoneValidationError(_EXCEL_TRUNCATION_MSG) from exc
    return re.sub(r"\D", "", text)


def _local_subscriber_digits(digits: str) -> str:
    """Strip +233 / 233 / leading 0 until a 9-digit local mobile remains."""
    local = digits
    while local.startswith("233") and len(local) > 9:
        local = local[3:]
    while local.startswith("0") and len(local) > 9:
        local = local[1:]
    return local


def normalize_ghana_phone(raw: str) -> str:
    """
    Normalize any Ghana input to E.164 (+233XXXXXXXXX).
    Adds country code +233 when only the 9-digit local mobile is present.
    """
    digits = _extract_digits(raw)
    if not digits:
        raise PhoneValidationError("Phone number is required")

    local = _local_subscriber_digits(digits)

    if len(local) != 9:
        raise PhoneValidationError("Phone number must be 9 digits after the country code (+233)")
    if not GHANA_LOCAL_RE.match(local):
        raise PhoneValidationError("Enter a valid Ghana mobile number")
    return f"+233{local}"


def parse_optional_ghana_phone(raw: str | None) -> str | None:
    """Empty → None. Otherwise E.164, or PhoneValidationError if invalid / truncated Excel value."""
    if raw is None or not str(raw).strip():
        return None
    return normalize_ghana_phone(str(raw))


def coerce_stored_phone(raw: str | None) -> str | None:
    """Best-effort E.164 for values already in the DB (including recoverable Excel notation)."""
    if raw is None or not str(raw).strip():
        return None
    try:
        return normalize_ghana_phone(str(raw))
    except PhoneValidationError:
        return None


def safe_normalize_ghana_phone(raw: str) -> str | None:
    """Return E.164 phone for SMS/storage, adding +233 when missing; None if invalid."""
    if not (raw or "").strip():
        return None
    try:
        return normalize_ghana_phone(raw)
    except PhoneValidationError:
        return None


def to_mnotify_recipient(phone: str) -> str:
    """
    Format phone for mNotify API: 233XXXXXXXXX (12 digits, no + or leading 0).
    Adds country code 233 when the stored number is local-only.
    """
    e164 = normalize_ghana_phone(phone)
    return e164.lstrip("+")

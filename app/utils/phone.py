"""Ghana phone normalization for storage (E.164) and mNotify (233XXXXXXXXX)."""

import re

GHANA_LOCAL_RE = re.compile(r"^[235]\d{8}$")


class PhoneValidationError(ValueError):
    pass


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
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        raise PhoneValidationError("Phone number is required")

    local = _local_subscriber_digits(digits)

    if len(local) != 9:
        raise PhoneValidationError("Phone number must be 9 digits after the country code (+233)")
    if not GHANA_LOCAL_RE.match(local):
        raise PhoneValidationError("Enter a valid Ghana mobile number")
    return f"+233{local}"


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

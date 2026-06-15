"""Ghana phone normalization for storage (E.164) and mNotify (local 0XXXXXXXXX)."""

import re

GHANA_LOCAL_RE = re.compile(r"^[235]\d{8}$")


class PhoneValidationError(ValueError):
    pass


def normalize_ghana_phone(raw: str) -> str:
    """Normalize any Ghana input to E.164 (+233XXXXXXXXX)."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("233"):
        digits = digits[3:]
    if digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 9:
        raise PhoneValidationError("Phone number must be 9 digits after the country code (+233)")
    if not GHANA_LOCAL_RE.match(digits):
        raise PhoneValidationError("Enter a valid Ghana mobile number")
    return f"+233{digits}"


def to_mnotify_recipient(phone: str) -> str:
    """Format phone for mNotify API (0XXXXXXXXX)."""
    e164 = normalize_ghana_phone(phone)
    return "0" + e164[4:]

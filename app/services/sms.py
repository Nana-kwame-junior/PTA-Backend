import asyncio
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.services.sms_errors import SmsDeliveryError, mnotify_error_message
from app.utils.phone import to_mnotify_recipient

logger = logging.getLogger(__name__)

# https://developer.mnotify.com/#tag/SMS/operation/campaign/sms_quick
# All messages (including login codes) use SMS credits — never sms_type=otp (main wallet).
MNOTIFY_QUICK_URL = "https://api.mnotify.com/api/sms/quick"


def _api_key() -> str:
    return (settings.mnotify_api_key or "").strip().strip('"').strip("'")


def _build_payload(
    recipients: list[str],
    message: str,
    *,
    schedule_date: Optional[str] = None,
) -> dict[str, Any]:
    scheduled = bool(schedule_date)
    return {
        "recipient": recipients,
        "sender": (settings.mnotify_sender_id or "MawuliPTA")[:11],
        "message": message,
        "is_schedule": scheduled,
        "schedule_date": schedule_date or "",
    }


def _parse_mnotify_response(response: httpx.Response) -> dict:
    if response.status_code != 200:
        logger.error("mNotify HTTP %s: %s", response.status_code, response.text)
        raise mnotify_error_message(response.status_code, response.text)

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("mNotify returned non-JSON: %s", response.text[:500])
        raise SmsDeliveryError(
            "SMS provider returned an invalid response. Try again shortly.",
            status_code=503,
        ) from exc

    if isinstance(data, dict) and data.get("status") not in (None, "success"):
        code = str(data.get("code", ""))
        msg = data.get("message") or data.get("error") or "SMS send failed"
        logger.error("mNotify API rejected request: %s", data)
        if "insufficient" in str(msg).lower() or code == "402":
            raise mnotify_error_message(402, str(msg))
        raise SmsDeliveryError(str(msg), status_code=503)

    return data


async def _post_mnotify(payload: dict) -> dict:
    if settings.sms_dry_run:
        recipients = payload.get("recipient", [])
        logger.warning(
            "SMS_DRY_RUN — skipped mNotify to %s: %s",
            recipients,
            str(payload.get("message", ""))[:80],
        )
        return {"status": "dry_run", "recipient": recipients}

    key = _api_key()
    if not key:
        raise SmsDeliveryError(
            "SMS service is not configured (MNOTIFY_API_KEY missing). Contact the school admin.",
            status_code=503,
        )

    url = f"{MNOTIFY_QUICK_URL}?key={key}"
    logger.info(
        "mNotify SMS credit send → %s recipient(s), sender=%s",
        len(payload.get("recipient", [])),
        payload.get("sender"),
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30.0,
        )

    data = _parse_mnotify_response(response)
    summary = data.get("summary") or {}
    logger.info(
        "mNotify OK: sent=%s credits_used=%s credit_left=%s",
        summary.get("total_sent"),
        summary.get("credit_used"),
        summary.get("credit_left"),
    )
    return data


async def send_sms(
    phone: str,
    message: str,
    *,
    schedule_date: Optional[str] = None,
) -> dict:
    """Send one SMS using mNotify SMS credits."""
    recipient = to_mnotify_recipient(phone)
    payload = _build_payload([recipient], message, schedule_date=schedule_date)
    return await _post_mnotify(payload)


async def send_verification_code_sms(phone: str, code: str) -> dict:
    """Send parent login verification code via regular SMS credits (not mNotify OTP wallet)."""
    minutes = max(1, settings.otp_expiry_seconds // 60)
    message = (
        f"Your Mawuli PTA verification code is {code}. "
        f"Valid for {minutes} minutes. Do not share this code."
    )
    if settings.sms_dry_run:
        logger.warning("SMS_DRY_RUN verification code for %s: %s", phone, code)
        return {"status": "dry_run", "code": code}
    return await send_sms(phone, message)


# Backward-compatible alias
send_otp_sms = send_verification_code_sms


async def send_bulk_sms(
    phones: list[str],
    message: str,
    *,
    schedule_date: Optional[str] = None,
    batch_size: int = 100,
) -> list[dict]:
    results = []
    for i in range(0, len(phones), batch_size):
        batch = phones[i : i + batch_size]
        recipients = [to_mnotify_recipient(p) for p in batch]
        payload = _build_payload(recipients, message, schedule_date=schedule_date)
        results.append(await _post_mnotify(payload))
    return results


async def schedule_sms(phones: list[str], message: str, schedule_date: str) -> list[dict]:
    """Schedule SMS (schedule_date format: YYYY-MM-DD hh:mm per mNotify docs)."""
    return await send_bulk_sms(phones, message, schedule_date=schedule_date)


async def check_sms_balance() -> dict:
    """GET /api/balance/sms — admin health check."""
    key = _api_key()
    if not key:
        return {"status": "skipped", "message": "MNOTIFY_API_KEY not set"}
    url = f"https://api.mnotify.com/api/balance/sms?key={key}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=15.0)
    return _parse_mnotify_response(response)


def send_sms_sync(phone: str, message: str, **kwargs) -> dict:
    return asyncio.run(send_sms(phone, message, **kwargs))


def send_sms_background(phone: str, message: str, **kwargs) -> None:
    try:
        send_sms_sync(phone, message, **kwargs)
    except Exception as exc:
        logger.error("Background SMS to %s failed: %s", phone, exc)

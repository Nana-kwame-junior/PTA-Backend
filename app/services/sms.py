import asyncio
import logging
from typing import Optional

import httpx

from app.core.config import settings
from app.utils.phone import to_mnotify_recipient

logger = logging.getLogger(__name__)

MNOTIFY_QUICK_URL = "https://api.mnotify.com/api/sms/quick"


def _mnotify_headers() -> dict:
    return {"Content-Type": "application/json"}


async def _post_mnotify(payload: dict) -> dict:
    if not settings.mnotify_api_key:
        logger.warning("mNotify API key not configured — SMS skipped")
        return {"status": "skipped", "message": "SMS provider not configured"}

    url = f"{MNOTIFY_QUICK_URL}?key={settings.mnotify_api_key}"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=_mnotify_headers(),
            json=payload,
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error("mNotify API error: %s - %s", response.status_code, response.text)
            response.raise_for_status()
        return response.json()


async def send_sms(
    phone: str,
    message: str,
    *,
    sms_type: Optional[str] = None,
    schedule_date: Optional[str] = None,
) -> dict:
    """
    Send SMS via mNotify quick API.
    Docs: https://developer.mnotify.com/
    """
    payload = {
        "recipient": [to_mnotify_recipient(phone)],
        "sender": settings.mnotify_sender_id[:11],
        "message": message,
        "is_schedule": bool(schedule_date),
        "schedule_date": schedule_date or "",
    }
    if sms_type:
        payload["sms_type"] = sms_type
    return await _post_mnotify(payload)


async def send_otp_sms(phone: str, otp: str) -> dict:
    message = f"Your Mawuli PTA OTP is {otp}. Valid for 10 minutes."
    return await send_sms(phone, message, sms_type="otp")


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
        payload = {
            "recipient": recipients,
            "sender": settings.mnotify_sender_id[:11],
            "message": message,
            "is_schedule": bool(schedule_date),
            "schedule_date": schedule_date or "",
        }
        results.append(await _post_mnotify(payload))
    return results


async def schedule_sms(phones: list[str], message: str, schedule_date: str) -> list[dict]:
    """Schedule SMS for a future date/time (YYYY-MM-DD hh:mm)."""
    return await send_bulk_sms(phones, message, schedule_date=schedule_date)


def send_sms_sync(phone: str, message: str, **kwargs) -> dict:
    return asyncio.run(send_sms(phone, message, **kwargs))

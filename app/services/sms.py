import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_sms(phone: str, message: str) -> dict:
    """
    Send an SMS using mNotify API.
    """
    async with httpx.AsyncClient() as client:
        clean_phone = phone.lstrip('+')
        response = await client.post(
            "https://apps.mnotify.net/api/campaign/sms/quick",
            headers={
                "Authorization": f"Bearer {settings.mnotify_api_key}",
                "Content-Type": "application/json"
            },
            json={
                "recipient": [clean_phone],
                "sender": settings.mnotify_sender_id,
                "message": message
            },
            timeout=30.0
        )
        if response.status_code != 200:
            logger.error(f"mNotify API error: {response.status_code} - {response.text}")
            response.raise_for_status()
        return response.json()

async def send_bulk_sms(phones: list[str], message: str, batch_size: int = 100) -> list[dict]:
    results = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(phones), batch_size):
            batch = phones[i:i + batch_size]
            clean_batch = [p.lstrip('+') for p in batch]
            response = await client.post(
                "https://apps.mnotify.net/api/campaign/sms/quick",
                headers={
                    "Authorization": f"Bearer {settings.mnotify_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "recipient": clean_batch,
                    "sender": settings.mnotify_sender_id,
                    "message": message
                },
                timeout=60.0
            )
            results.append(response.json())
    return results
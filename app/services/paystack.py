import httpx
import json
from app.core.config import settings


def paystack_callback_url() -> str:
    base = settings.api_base_url.rstrip("/")
    if base.endswith("/api/v1"):
        return f"{base}/payments/online/callback"
    return f"{base}/api/v1/payments/online/callback"


def paystack_is_configured() -> bool:
    secret = settings.paystack_secret_key or ""
    public = settings.paystack_public_key or ""
    placeholders = ("sk_test_xxxxxxxxxxxx", "pk_test_xxxxxxxxxxxx", "sk_test_1234567890")
    return (
        secret.startswith("sk_")
        and public.startswith("pk_")
        and secret not in placeholders
        and public not in placeholders
    )


async def initialize_transaction(email: str, amount: int, reference: str, metadata: dict):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.paystack_base_url}/transaction/initialize",
            headers={"Authorization": f"Bearer {settings.paystack_secret_key}"},
            json={
                "email": email,
                "amount": amount,
                "reference": reference,
                "metadata": metadata,
                "callback_url": paystack_callback_url(),
            },
        )
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"status": False, "message": response.text or "Invalid Paystack response"}


async def verify_transaction(reference: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.paystack_base_url}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.paystack_secret_key}"},
        )
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"status": False, "message": response.text or "Invalid Paystack response"}


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Paystack signs webhooks with the secret key (HMAC SHA512)."""
    import hmac
    import hashlib

    candidates: list[str] = []
    secret_key = (settings.paystack_secret_key or "").strip()
    webhook_secret = (settings.paystack_webhook_secret or "").strip()
    if secret_key:
        candidates.append(secret_key)
    # Keep webhook secret as a fallback for custom/proxy setups.
    if webhook_secret and webhook_secret not in candidates and "your-webhook" not in webhook_secret:
        candidates.append(webhook_secret)

    for secret in candidates:
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()
        if hmac.compare_digest(expected, signature):
            return True
    return False

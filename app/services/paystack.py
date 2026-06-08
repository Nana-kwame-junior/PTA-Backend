import httpx
from app.core.config import settings

async def initialize_transaction(email: str, amount: int, reference: str, metadata: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.paystack_base_url}/transaction/initialize",
            headers={"Authorization": f"Bearer {settings.paystack_secret_key}"},
            json={
                "email": email,
                "amount": amount,
                "reference": reference,
                "metadata": metadata,
                "callback_url": f"{settings.api_base_url}/api/v1/payments/online/callback"
            }
        )
        return response.json()

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    import hmac
    import hashlib
    expected = hmac.new(
        settings.paystack_webhook_secret.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
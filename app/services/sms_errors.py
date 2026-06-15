"""SMS delivery errors with user-facing messages."""


class SmsDeliveryError(Exception):
    def __init__(self, user_message: str, status_code: int = 503, provider_status: int | None = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code
        self.provider_status = provider_status


def mnotify_error_message(http_status: int, body: str) -> SmsDeliveryError:
    text = body.lower()
    if http_status == 402 or "insufficient wallet balance" in text:
        return SmsDeliveryError(
            "SMS could not be sent — mNotify SMS credits are too low. "
            "Top up SMS credits in your mNotify dashboard, then try again.",
            status_code=402,
            provider_status=402,
        )
    if http_status == 401 or "invalid" in text and "key" in text:
        return SmsDeliveryError(
            "SMS service is misconfigured (invalid API key). Contact the school admin.",
            status_code=503,
            provider_status=401,
        )
    if http_status == 400:
        return SmsDeliveryError(
            "SMS could not be sent (invalid phone or sender ID). Check the number and try again.",
            status_code=400,
            provider_status=400,
        )
    return SmsDeliveryError(
        "Could not send SMS right now. Please try again in a few minutes.",
        status_code=503,
        provider_status=http_status,
    )

"""Normalize Redis URLs for Celery/kombu (Upstash rediss:// requires ssl_cert_reqs)."""


def ensure_rediss_ssl(url: str) -> str:
    if not url or not url.startswith("rediss://"):
        return url
    if "ssl_cert_reqs=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}ssl_cert_reqs=CERT_REQUIRED"

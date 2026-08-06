from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional
from pydantic import model_validator

from app.core.redis_url import ensure_rediss_ssl


class Settings(BaseSettings):
    # ── App ────────────────────────────────────────────────────────
    project_name: str = "PTA SaaS"
    version: str = "1.0.0"
    description: str = "PTA SaaS"
    debug: bool = False
    api_prefix: str = "/api/v1"
    api_base_url: str = "http://localhost:8000"
    dashboard_url: str = "http://localhost:5173"

    # ── Database ───────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/pta"
    database_url_sync: str = "postgresql://postgres:password@localhost:5432/pta"

    # ── Redis ──────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── JWT ────────────────────────────────────────────────────────
    jwt_secret: str = "256"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 480
    jwt_refresh_expire_days: int = 30
    jwt_registration_expire_minutes: int = 1440
    jwt_selection_expire_minutes: int = 5

    # ── OTP ────────────────────────────────────────────────────────
    otp_expiry_seconds: int = 180
    otp_max_attempts: int = 3
    otp_lockout_minutes: int = 15

    # ── Paystack ───────────────────────────────────────────────────
    paystack_secret_key: str = "sk_test_xxxxxxxxxxxx"
    paystack_public_key: str = "pk_test_xxxxxxxxxxxx"
    paystack_webhook_secret: str = "your-webhook-secret"
    paystack_base_url: str = "https://api.paystack.co"

    # ── SMS Provider (mNotify) ─────────────────────────────────────
    sms_provider: str = "MNOTIFY"
    mnotify_api_key: str = ""
    mnotify_sender_id: str = "MawuliPTA"
    # Staging only: log verification codes in server logs instead of sending SMS
    sms_dry_run: bool = False

    # ── Email (Brevo transactional API — staff invite / password reset) ─
    pta_chairperson_email: str = "chairperson@mawulishs.edu.gh"
    brevo_api_key: str = ""
    # Prefer BREVO_SENDER_EMAIL / BREVO_SENDER_NAME, or BREVO_FROM_EMAIL as "Name <email>"
    brevo_sender_email: str = ""
    brevo_sender_name: str = "SchoolPulse"
    brevo_from_email: str = ""
    # Optional legacy aliases (MAIL_FROM / MAIL_FROM_NAME still work as fallbacks)
    mail_from: Optional[str] = None
    mail_from_name: Optional[str] = None

    # ── CORS ───────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://localhost:8081,http://localhost:3000"
    cors_allow_credentials: bool = True

    # ── File Storage ───────────────────────────────────────────────
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    # ── Matching thresholds ────────────────────────────────────────
    match_auto_threshold: int = 80
    match_candidate_threshold: int = 40

    # ── School constants ───────────────────────────────────────────
    school_name: str = "Mawuli Senior High School"
    school_index_prefix: str = "MWL"
    sms_sender_id: str = "MawuliPTA"
    current_academic_year: str = "2024/2025"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _normalize_redis_urls(self):
        self.redis_url = ensure_rediss_ssl(self.redis_url)
        self.celery_broker_url = ensure_rediss_ssl(self.celery_broker_url)
        self.celery_result_backend = ensure_rediss_ssl(self.celery_result_backend)
        return self

    def resolved_brevo_sender(self) -> tuple[str, str]:
        """Return (email, display_name) for Brevo sender."""
        raw = (self.brevo_from_email or "").strip()
        if raw:
            # Support "Display Name <addr@domain>" or bare email
            if "<" in raw and raw.endswith(">"):
                name_part, _, email_part = raw.partition("<")
                email = email_part[:-1].strip()
                name = name_part.strip().strip('"') or self.brevo_sender_name
                return email, name
            return raw, self.brevo_sender_name

        email = (self.brevo_sender_email or self.mail_from or "").strip()
        name = (self.brevo_sender_name or self.mail_from_name or "SchoolPulse").strip()
        return email, name

@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

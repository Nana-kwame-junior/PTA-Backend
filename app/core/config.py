from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    # ── App ────────────────────────────────────────────────────────
    project_name: str = "PTA SaaS"
    version: str = "1.0.0"
    description: str = "PTA SaaS"
    debug: bool = False
    api_prefix: str = "/api/v1"
    api_base_url: str = "http://localhost:8000"

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
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30
    jwt_registration_expire_minutes: int = 10
    jwt_selection_expire_minutes: int = 5

    # ── OTP ────────────────────────────────────────────────────────
    otp_expiry_seconds: int = 600
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

    # ── Email (admin alerts & staff invitations) ───────────────────
    pta_chairperson_email: str = "chairperson@mawulishs.edu.gh"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""

    # Additional email fields that may be in .env (optional)
    mail_username: Optional[str] = None
    mail_password: Optional[str] = None
    mail_from: Optional[str] = None
    mail_port: Optional[int] = None
    mail_server: Optional[str] = None
    mail_from_name: Optional[str] = None
    mail_starttls: Optional[bool] = False
    mail_ssl_tls: Optional[bool] = False
    use_credentials: Optional[bool] = False

    # ── CORS (optional) ────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
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

    # Allow extra env vars (so they don't break the app)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

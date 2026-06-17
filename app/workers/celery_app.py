import ssl

from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "pta_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.sms_tasks",
        "app.workers.lock_tasks"
    ]
)

_ssl_opts = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
if settings.celery_broker_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = _ssl_opts
    celery_app.conf.redis_backend_use_ssl = _ssl_opts

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Africa/Accra",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=20 * 60,
)
"""Safe Celery task scheduling when Redis/broker is unavailable (e.g. Koyeb without Redis)."""

import logging

logger = logging.getLogger(__name__)


def safe_apply_async(task, *args, **kwargs):
    try:
        return task.apply_async(*args, **kwargs)
    except Exception as exc:
        logger.warning("Background task skipped (broker unavailable): %s", exc)
        return None

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.manual_payment import ManualPayment
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=2)
def lock_manual_payment(self, manual_payment_id: str):
    db = SessionLocal()
    try:
        payment = db.query(ManualPayment).filter(ManualPayment.id == manual_payment_id).first()
        if not payment:
            logger.warning(f"Manual payment {manual_payment_id} not found")
            return
        if payment.is_locked:
            return
        if payment.recorded_at <= datetime.utcnow() - timedelta(hours=24):
            payment.is_locked = True
            db.commit()
            logger.info(f"Locked manual payment {manual_payment_id}")
    except Exception as e:
        db.rollback()
        raise self.retry(exc=e, countdown=300)
    finally:
        db.close()
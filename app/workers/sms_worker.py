from redis import Redis
from rq import Queue, Worker
from app.services.sms import send_sms
from app.core.config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)
queue = Queue("sms", connection=redis_conn)

def process_sms_job(phone: str, message: str):
    # This runs in a worker process
    result = asyncio.run(send_sms(phone, message))
    # Log result to DB
    return result

if __name__ == "__main__":
    worker = Worker([queue], connection=redis_conn)
    worker.work()
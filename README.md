app/
├── __init__.py
├── main.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   └── security.py
├── models/                     # (already defined – keep as is)
├── schemas/                    # (already defined – keep as is)
├── services/
│   ├── __init__.py
│   ├── sms.py                  # UPDATED with mNotify
│   ├── paystack.py
│   ├── pdf.py
│   └── email.py
├── workers/
│   ├── __init__.py
│   ├── celery_app.py
│   ├── sms_tasks.py
│   └── lock_tasks.py
└── api/v1/routers/
    ├── __init__.py
    ├── auth.py
    ├── students.py
    ├── dues.py                 # UPDATED (schedule dues reminders)
    ├── payments_online.py
    ├── payments_manual.py      # UPDATED (schedule lock)
    ├── meetings.py             # UPDATED (schedule meeting reminders)
    ├── announcements.py
    ├── sms.py
    ├── reports.py
    ├── attendance.py
    ├── staff.py
    └── parents.py

    


# PTA Backend

A FastAPI backend scaffold for the PTA project.

## Quick start

1. Create a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/Scripts/activate  # Windows
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   uvicorn app.main:app --reload
   ```

4. Open the docs:

   - http://127.0.0.1:8000/docs
   - http://127.0.0.1:8000/redoc

## Test

```bash
pytest
```



# Terminal 1: FastAPI server
uvicorn app.main:app --reload

# Terminal 2: Celery worker (for scheduled SMS jobs and manual payment lock)
celery -A app.workers.celery_app worker --loglevel=info
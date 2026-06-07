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

from fastapi import FastAPI

from app.api.v1.endpoints import router as api_router
from app.core.config import settings

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    description=settings.description,
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def read_root():
    return {"message": "Welcome to PTA Backend", "version": settings.version}

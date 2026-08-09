"""Upload announcement images to Cloudinary."""

from __future__ import annotations

import io
from typing import Iterable

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, UploadFile

from app.core.config import settings

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)
MAX_IMAGES = 5
MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def _configured() -> bool:
    return bool(
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    )


def _ensure_configured() -> None:
    if not _configured():
        raise HTTPException(
            status_code=503,
            detail="Image uploads are not configured. Set CLOUDINARY_URL on the server.",
        )
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


async def upload_announcement_images(
    files: Iterable[UploadFile],
    *,
    folder: str = "pta/announcements",
) -> list[str]:
    """Validate and upload image files; return secure HTTPS URLs."""
    file_list = [f for f in files if f is not None and getattr(f, "filename", None)]
    if not file_list:
        return []
    if len(file_list) > MAX_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"You can attach at most {MAX_IMAGES} images per announcement.",
        )

    _ensure_configured()
    urls: list[str] = []

    for upload in file_list:
        content_type = (upload.content_type or "").lower().strip()
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image type '{content_type or 'unknown'}'. Use JPEG, PNG, WebP, or GIF.",
            )
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail="One of the uploaded images is empty.")
        if len(data) > MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Each image must be {MAX_BYTES // (1024 * 1024)}MB or smaller.",
            )
        try:
            result = cloudinary.uploader.upload(
                io.BytesIO(data),
                folder=folder,
                resource_type="image",
                overwrite=False,
            )
        except Exception:
            raise HTTPException(
                status_code=502,
                detail="Failed to upload image. Please try again.",
            ) from None
        url = result.get("secure_url") or result.get("url")
        if not url:
            raise HTTPException(status_code=502, detail="Image upload did not return a URL.")
        urls.append(str(url))

    return urls

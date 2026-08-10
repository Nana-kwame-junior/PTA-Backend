from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class AnnouncementType(str, Enum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    FINANCIAL = "FINANCIAL"
    EVENT = "EVENT"


class AnnouncementCreate(BaseModel):
    title: str
    body: str
    type: AnnouncementType
    send_sms: bool = False
    image_urls: list[str] = Field(default_factory=list)


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[AnnouncementType] = None
    image_urls: Optional[list[str]] = None


class AnnouncementOut(BaseModel):
    id: str
    title: str
    body: str = ""
    type: AnnouncementType
    published_at: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)

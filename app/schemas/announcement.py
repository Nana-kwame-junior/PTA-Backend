from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class AnnouncementType(str, Enum):
    GENERAL = "GENERAL"
    URGENT = "URGENT"
    FINANCIAL = "FINANCIAL"
    EVENT = "EVENT"


class AnnouncementAudience(str, Enum):
    BOTH = "BOTH"
    BASIC = "BASIC"
    SHS = "SHS"


class AnnouncementCreate(BaseModel):
    title: str
    body: str
    type: AnnouncementType
    send_sms: bool = False
    audience_track: AnnouncementAudience = AnnouncementAudience.BOTH
    image_urls: list[str] = Field(default_factory=list)


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[AnnouncementType] = None
    audience_track: Optional[AnnouncementAudience] = None
    image_urls: Optional[list[str]] = None


class AnnouncementOut(BaseModel):
    id: str
    title: str
    body: str = ""
    type: AnnouncementType
    audience_track: AnnouncementAudience = AnnouncementAudience.BOTH
    published_at: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)

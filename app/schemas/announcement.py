from pydantic import BaseModel
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
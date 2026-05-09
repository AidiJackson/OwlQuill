"""Pydantic schemas for candidate slot replacement."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator

VALID_SLOTS = ("front", "three_quarter", "torso", "full_body")


class CandidateSlotCreate(BaseModel):
    slot: str
    image_url: str

    @field_validator("slot")
    @classmethod
    def slot_must_be_valid(cls, v: str) -> str:
        if v not in VALID_SLOTS:
            raise ValueError(f"slot must be one of {VALID_SLOTS}")
        return v

    @field_validator("image_url")
    @classmethod
    def image_url_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("image_url must not be empty")
        return v.strip()


class CandidateSlotRead(BaseModel):
    id: int
    character_id: int
    slot: str
    image_url: str
    status: str
    validation_status: str
    validation_notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

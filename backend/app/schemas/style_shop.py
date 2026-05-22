"""Pydantic schemas for Style Shops."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.style_shop import AttachmentModeEnum, PlacementEnum, ShopTypeEnum, StyleElementStatusEnum


class StylePresetRead(BaseModel):
    id: int
    shop_type: ShopTypeEnum
    name: str
    slug: str
    description: str
    attachment_mode: AttachmentModeEnum
    placement: PlacementEnum
    prompt_token: str
    preview_image_url: Optional[str] = None
    is_active: bool
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class StyleElementRead(BaseModel):
    id: int
    character_id: int
    preset_id: int
    placement: PlacementEnum
    status: StyleElementStatusEnum
    created_at: datetime
    updated_at: datetime
    preset: StylePresetRead

    model_config = {"from_attributes": True}


class ApplyStyleElementRequest(BaseModel):
    preset_id: int
    placement: Optional[PlacementEnum] = None


class StyleElementsResponse(BaseModel):
    character_id: int
    elements: list[StyleElementRead]

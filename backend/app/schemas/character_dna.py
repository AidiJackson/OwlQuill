"""Character DNA schemas."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class CharacterDNACreate(BaseModel):
    """Schema for creating / fully replacing character DNA."""
    species: Optional[str] = None
    gender_presentation: Optional[str] = None
    visual_traits_json: Optional[dict[str, Any]] = None
    structural_profile_json: Optional[dict[str, Any]] = None
    style_permissions_json: Optional[dict[str, Any]] = None


class CharacterDNAUpdate(BaseModel):
    """Schema for partial DNA updates."""
    species: Optional[str] = None
    gender_presentation: Optional[str] = None
    visual_traits_json: Optional[dict[str, Any]] = None
    structural_profile_json: Optional[dict[str, Any]] = None
    style_permissions_json: Optional[dict[str, Any]] = None


class CharacterDNARead(BaseModel):
    """Schema returned when reading character DNA."""
    id: int
    character_id: int
    species: Optional[str] = None
    gender_presentation: Optional[str] = None
    visual_traits_json: Optional[dict[str, Any]] = None
    structural_profile_json: Optional[dict[str, Any]] = None
    style_permissions_json: Optional[dict[str, Any]] = None
    anchor_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

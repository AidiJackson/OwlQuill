"""Character Image schemas."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, computed_field

from app.models.character_image import ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum


class CharacterImageCreate(BaseModel):
    """Schema for recording a new character image."""
    kind: ImageKindEnum
    file_path: str
    status: ImageStatusEnum = ImageStatusEnum.ACTIVE
    visibility: ImageVisibilityEnum = ImageVisibilityEnum.PRIVATE
    provider: Optional[str] = None
    prompt_summary: Optional[str] = None
    seed: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None


class CharacterImageRead(BaseModel):
    """Schema returned when reading a character image."""
    id: int
    character_id: int
    kind: ImageKindEnum
    status: ImageStatusEnum
    visibility: ImageVisibilityEnum
    provider: Optional[str] = None
    prompt_summary: Optional[str] = None
    seed: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    file_path: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        """Derive a servable URL from the stored file_path."""
        # file_path is stored as e.g. "static/generated/<uuid>.png"
        path = self.file_path.lstrip("/")
        if not path.startswith("static/"):
            return f"/static/{path}"
        return f"/{path}"

    model_config = {"from_attributes": True}

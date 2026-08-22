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


#: Kinds that belong in a character's PUBLIC gallery.
#:
#: The ``visibility`` column is NOT usable as the gallery signal: it defaults to
#: PRIVATE and nothing in the codebase has ever written PUBLIC, so every stored
#: image is 'private'. Filtering on it would empty every gallery in production.
#: Kind is therefore the safest existing definition — it distinguishes finished,
#: shareable output from the identity/anchor working references used to build a
#: character. Documented limitation, not invented behaviour.
#:
#: ``UPLOADED`` (founder/seeder device uploads) is deliberately NOT here. An
#: uploaded image is a private working reference: the founder supplied it to
#: steer generation, not to publish it, and Ficshon has no provenance for it. It
#: is likewise absent from ``POST_ATTACHABLE_IMAGE_KINDS``. Adding it to either
#: list is a product decision that must be taken explicitly, never as a
#: side effect of adding the upload feature.
PUBLIC_GALLERY_KINDS = frozenset({
    ImageKindEnum.GENERATED,
    ImageKindEnum.COVER,
    ImageKindEnum.SCENE_ONLY,
})


class CharacterImagePublic(BaseModel):
    """A character image as seen by the PUBLIC — Wanderers, other owners,
    anonymous visitors.

    Deliberately narrow. Everything a viewer has no business seeing is absent
    from the schema rather than merely unset, so it cannot leak by accident:
    ``prompt_summary``, ``provider``, ``seed``, ``metadata_json`` (raw provider
    payloads, costs, storage internals), ``user_id`` (account identity),
    ``status`` and ``visibility``.
    """
    id: int
    character_id: int
    kind: ImageKindEnum
    created_at: datetime
    url: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_image(cls, image) -> "CharacterImagePublic":
        """Build from a CharacterImage ORM row, deriving the servable URL."""
        return cls(
            id=image.id,
            character_id=image.character_id,
            kind=image.kind,
            created_at=image.created_at,
            url=_file_path_to_url(image.file_path),
        )


def _file_path_to_url(file_path: str) -> str:
    """Derive a servable URL from a stored file_path.

    Shared by CharacterImageRead.url and CharacterImagePublic so the two can
    never disagree about how an image is addressed.
    """
    if file_path.startswith(("http://", "https://")):
        return file_path
    path = file_path.lstrip("/")
    if not path.startswith("static/"):
        return f"/static/{path}"
    return f"/{path}"


def is_public_gallery_image(image) -> bool:
    """True when *image* belongs in the character's public gallery.

    Requires an allowlisted kind, ACTIVE status, and that the image is not a
    temporary pack preview that was never accepted.
    """
    if image.kind not in PUBLIC_GALLERY_KINDS:
        return False
    if image.status != ImageStatusEnum.ACTIVE:
        return False
    return not (image.metadata_json or {}).get("is_temp", False)


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
        return _file_path_to_url(self.file_path)

    model_config = {"from_attributes": True}

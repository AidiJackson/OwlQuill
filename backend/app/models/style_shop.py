"""Style Shop models — StylePreset and CharacterStyleElement."""
import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum as SQLEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ShopTypeEnum(str, enum.Enum):
    BARBER = "barber"
    TATTOO = "tattoo"
    MASK = "mask"
    JEWELLERY = "jewellery"
    WEAPON = "weapon"


class AttachmentModeEnum(str, enum.Enum):
    PERMANENT = "permanent"
    REMOVABLE = "removable"


class PlacementEnum(str, enum.Enum):
    HAIR = "hair"
    FACE = "face"
    LOWER_FACE = "lower_face"
    RIGHT_ARM = "right_arm"
    LEFT_ARM = "left_arm"
    CHEST = "chest"
    BACK = "back"
    NECK = "neck"
    HAND = "hand"
    CUSTOM = "custom"


class StyleElementStatusEnum(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


# PostgreSQL native enums use .name by default in SQLAlchemy 2.x.
# values_callable forces use of .value (lowercase) to match the migration-created enum types.
def _enum_values(obj):
    return [e.value for e in obj]


class StylePreset(Base):
    """Curated preset item available in a Style Shop."""

    __tablename__ = "style_presets"

    id = Column(Integer, primary_key=True, index=True)
    shop_type = Column(SQLEnum(ShopTypeEnum, values_callable=_enum_values), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)
    attachment_mode = Column(SQLEnum(AttachmentModeEnum, values_callable=_enum_values), nullable=False)
    placement = Column(SQLEnum(PlacementEnum, values_callable=_enum_values), nullable=False)
    prompt_token = Column(Text, nullable=False)
    preview_image_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")
    sort_order = Column(Integer, default=0, nullable=False, server_default="0")
    # JSON dict of identity_spec fields to patch when applied (hair presets)
    spec_patch_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    elements = relationship("CharacterStyleElement", back_populates="preset")


class CharacterStyleElement(Base):
    """A style preset applied to a character."""

    __tablename__ = "character_style_elements"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)
    preset_id = Column(Integer, ForeignKey("style_presets.id", ondelete="CASCADE"), nullable=False)
    placement = Column(SQLEnum(PlacementEnum, values_callable=_enum_values), nullable=False)
    status = Column(SQLEnum(StyleElementStatusEnum, values_callable=_enum_values), default=StyleElementStatusEnum.ACTIVE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    character = relationship("Character", back_populates="style_elements")
    preset = relationship("StylePreset", back_populates="elements")

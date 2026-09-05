"""Character model."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Float, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class VisibilityEnum(str, enum.Enum):
    """Character visibility options."""
    PUBLIC = "public"
    FRIENDS = "friends"
    PRIVATE = "private"


class Character(Base):
    """Character/OC model for roleplay."""

    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    alias = Column(String, nullable=True)
    age = Column(String, nullable=True)
    species = Column(String, nullable=True)
    role = Column(String, nullable=True)  # e.g., "assassin", "healer", "detective"
    era = Column(String, nullable=True)  # e.g., "modern", "medieval", "sci-fi future"
    short_bio = Column(Text, nullable=True)
    long_bio = Column(Text, nullable=True)
    avatar_url = Column(String, nullable=True)
    cover_url = Column(String, nullable=True)       # Character cover/banner image
    cover_position_y = Column(Float, nullable=True, default=0.5)  # 0.0=top, 0.5=center, 1.0=bottom
    cover_position_x = Column(Float, nullable=True, default=0.5)  # 0.0=left, 0.5=center, 1.0=right
    cover_scale = Column(Float, nullable=True, default=1.0)     # zoom factor, 1.0=no zoom
    avatar_position_x = Column(Float, nullable=True, default=0.5)  # 0.0=left, 0.5=center, 1.0=right
    avatar_position_y = Column(Float, nullable=True, default=0.5)  # 0.0=top, 0.5=center, 1.0=bottom
    avatar_scale = Column(Float, nullable=True, default=1.0)     # zoom factor, 1.0=no zoom
    portrait_url = Column(String, nullable=True)  # Character portrait for RP sheets
    tags = Column(String, nullable=True)  # Stored as comma-separated for MVP
    visibility = Column(SQLEnum(VisibilityEnum), default=VisibilityEnum.PUBLIC, nullable=False)
    visual_locked = Column(Boolean, default=False, nullable=False, server_default="false")
    # Founder-granted permission for this character to have an anonymous public
    # Character Home. Permission only — it never overrides ``visibility``; a
    # Character Home is publishable only when BOTH this flag and PUBLIC
    # visibility hold. See app.services.character_publication.
    public_home_enabled = Column(Boolean, default=False, nullable=False, server_default="false")
    identity_spec_json = Column(Text, nullable=True)      # Structured identity spec (JSON string)
    identity_spec_version = Column(Integer, default=0, nullable=False, server_default="0")
    identity_anchor_json = Column(Text, nullable=True)    # Compact anchor snapshot saved on lock
    body_canon_json = Column(Text, nullable=True)         # Persistent body markings (tattoos, scars, burns, birthmarks)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User", back_populates="characters", foreign_keys=[owner_id])
    posts = relationship("Post", back_populates="character")
    comments = relationship("Comment", back_populates="character")
    dna = relationship("CharacterDNA", back_populates="character", uselist=False, cascade="all, delete-orphan")
    #: Phase 4C: ``delete`` and ``delete-orphan`` are deliberately ABSENT.
    #:
    #: Deleting a character must not delete the images it was associated with.
    #: They belong to an account (``CharacterImage.user_id``, NOT NULL since
    #: 4B2), they carry a safety decision, provenance, lineage and a pointer to
    #: bytes in a bucket, and none of that stops mattering because a character
    #: was removed. The association is dropped instead — ``character_id``
    #: becomes NULL — and the asset stays in its owner's library.
    #:
    #: ``save-update, merge`` is SQLAlchemy's default cascade. It is spelled out
    #: rather than omitted so that the absence of ``delete`` reads as a decision
    #: instead of an oversight.
    #:
    #: ``passive_deletes`` is deliberately left unset (False). With it False the
    #: ORM issues an explicit ``UPDATE character_images SET character_id=NULL``
    #: before deleting the character, which behaves identically on PostgreSQL
    #: and on SQLite regardless of ``PRAGMA foreign_keys``. Setting it True
    #: would delegate the nulling entirely to the database FK — correct on DEV,
    #: but the shared test fixture does not enable SQLite foreign keys, so the
    #: whole suite would silently leave ``character_id`` pointing at a deleted
    #: character and prove nothing about the invariant this exists to create.
    #: The database still carries ``ON DELETE SET NULL`` as well, for the paths
    #: that never touch the ORM.
    #:
    #: This is also what makes account deletion reach
    #: ``character_images_user_id_fkey``. While this cascade deleted the image
    #: rows first, ``DELETE FROM users`` found nothing referencing the account
    #: and the RESTRICT was never asked. ``User.characters`` is unchanged and
    #: still ``all, delete-orphan``; it did not need to change, because the
    #: bypass was always this hop.
    images = relationship(
        "CharacterImage",
        back_populates="character",
        cascade="save-update, merge",
    )
    style_elements = relationship("CharacterStyleElement", back_populates="character", cascade="all, delete-orphan")
    identity_canon = relationship("CharacterIdentityCanon", back_populates="character", uselist=False, cascade="all, delete-orphan")

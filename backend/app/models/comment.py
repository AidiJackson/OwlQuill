"""Comment model."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.provenance import ProvenanceMixin


class Comment(ProvenanceMixin, Base):
    """Comment model for posts."""

    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)
    # Authorship provenance, written once at creation and never cleared, so it
    # survives ``character_id`` being SET NULL by a character deletion.
    # "character" | "wanderer" | NULL (unknown → never shows account
    # identity). See app.models.authorship.
    author_kind = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    post = relationship("Post", back_populates="comments")
    author_user = relationship("User", back_populates="comments")
    character = relationship("Character", back_populates="comments")

    @property
    def author_username(self) -> str | None:
        if self.author_user:
            return self.author_user.username
        return None

    @property
    def author_avatar_url(self) -> str | None:
        """The account sigil, used for Wanderer attribution.

        Only ever serialized for characterless (Wanderer) comments — the
        serialization layer strips it, along with the username, from
        character-attributed comments so a Writer's public output carries the
        character and nothing else.
        """
        if self.author_user:
            return self.author_user.avatar_url
        return None

    @property
    def character_name(self) -> str | None:
        if self.character:
            return self.character.name
        return None

    @property
    def character_avatar_url(self) -> str | None:
        if self.character:
            return self.character.avatar_url
        return None

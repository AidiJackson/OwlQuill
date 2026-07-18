"""PostMention model — tracks @mentions within post content."""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class PostMention(Base):
    """Stores each resolved @mention found in a post."""

    __tablename__ = "post_mentions"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    mention_text = Column(String(100), nullable=False)   # e.g. "@alice"
    mentioned_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    mentioned_character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships for display_name / url property helpers
    mentioned_user = relationship("User", foreign_keys=[mentioned_user_id])
    mentioned_character = relationship("Character", foreign_keys=[mentioned_character_id])

    # ── Computed properties (used by PostMentionRead schema) ─────────────────

    @property
    def target_type(self) -> str:
        if self.mentioned_user_id:
            return "user"
        if self.mentioned_character_id:
            return "character"
        return "unresolved"

    @property
    def target_id(self) -> Optional[int]:
        return self.mentioned_user_id or self.mentioned_character_id

    @property
    def display_name(self) -> str:
        # Identity-first: never surface an account username, even on legacy
        # rows that resolved to a user before Sprint 33.
        if self.mentioned_character and self.mentioned_character.name:
            return self.mentioned_character.name
        return self.mention_text.lstrip("@")

    @property
    def url(self) -> str:
        # Identity-first: only characters are linkable identities. Legacy
        # user-mention rows render unlinked.
        if self.mentioned_character:
            return f"/characters/{self.mentioned_character.id}"
        return ""

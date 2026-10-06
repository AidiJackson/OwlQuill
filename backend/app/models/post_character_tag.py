"""PostCharacterTag — a character deliberately tagged on a post by its author (W-10A).

TAGGED, NOT AUTHORED. A tag says "the author associated this post with that
character". It never makes the tagged character an author or co-author:
authorship stays ``posts.character_id`` / ``posts.author_kind`` and nothing
here is read by the authored Timeline or the anonymous Character Home.

IDS ONLY. The row carries no character name and no account id. Names are read
live from ``characters`` at projection time, so a rename needs no rewrite, and
the owning account is reached through the character only where a server-side
rule needs it (notifications, blocks) — it is never serialised.

DELETION. Both foreign keys are ``ON DELETE CASCADE``: a tag with no post, or
with no character, says nothing worth keeping. The ORM relationships on
``Post`` and ``Character`` carry ``delete-orphan`` cascades as well, because the
SQLite test fixture does not enforce foreign keys and the invariant has to hold
there too (see the note on ``Character.images``).

VISIBILITY is not stored. A tag on a character that later becomes PRIVATE keeps
its row and is hidden at projection time (``app.services.character_tags``), so
it reappears if the character becomes PUBLIC again.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class PostCharacterTag(Base):
    """One (post, tagged character) association."""

    __tablename__ = "post_character_tags"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(
        Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Loaded with the tag so a page of posts resolves every tagged character in
    # one extra statement (Post.character_tags -> PostCharacterTag.character).
    character = relationship("Character", back_populates="post_tags", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("post_id", "character_id", name="uq_post_character_tag"),
    )

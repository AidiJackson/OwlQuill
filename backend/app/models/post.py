"""Post model for story snippets/scenes."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base
from app.models.provenance import ProvenanceMixin


class ContentTypeEnum(str, enum.Enum):
    """Post content type."""
    IC = "ic"  # In-character
    OOC = "ooc"  # Out-of-character
    NARRATION = "narration"


class PostKindEnum(str, enum.Enum):
    """Post kind / purpose."""
    GENERAL = "general"
    OPEN_STARTER = "open_starter"
    FINISHED_PIECE = "finished_piece"


class SourceTypeEnum(str, enum.Enum):
    """RETIRED — superseded by ``app.models.provenance.Provenance``.

    The old badge vocabulary. It was client-settable and defaulted to ``USER``,
    so it asserted authorship it had no evidence for. Kept only so the retired
    column below still maps; nothing writes it.
    """
    USER = "user"
    AI_ASSISTED = "ai_assisted"
    AI_GENERATED = "ai_generated"


class Post(ProvenanceMixin, Base):
    """Post model for story snippets and scenes."""

    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="CASCADE"), nullable=True)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    content_type = Column(SQLEnum(ContentTypeEnum), default=ContentTypeEnum.IC, nullable=False)
    post_kind = Column(String, default="general", nullable=False)
    # RETIRED — read by nothing, written by nothing. Left in place so the
    # existing column still maps; dropped in a follow-up once no deployment
    # is rolling back across the provenance migration.
    source_type = Column(String(20), nullable=True)
    image_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    realm = relationship("Realm", back_populates="posts")
    author_user = relationship("User", back_populates="posts")
    character = relationship("Character", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    reactions = relationship("Reaction", back_populates="post", cascade="all, delete-orphan")
    mentions = relationship("PostMention", cascade="all, delete-orphan", lazy="selectin")

    @property
    def author_username(self) -> str | None:
        """Return the author's username for OOC attribution."""
        if self.author_user:
            return self.author_user.username
        return None

    @property
    def character_name(self) -> str | None:
        """Return the associated character's name, if any."""
        if self.character:
            return self.character.name
        return None

    @property
    def character_avatar_url(self) -> str | None:
        """Return the associated character's avatar URL, if any."""
        if self.character:
            return self.character.avatar_url
        return None


# ``comment_count`` is attached after the class body because it references the
# Comment mapper, which cannot be imported at class-definition time.
#
# It is a correlated scalar subquery rather than ``len(self.comments)`` on
# purpose: a feed renders many posts, and the relationship form would emit one
# extra SELECT per post. This form travels inside the post query itself, so the
# collapsed "Comments (n)" affordance costs nothing extra per post.
def _attach_comment_count() -> None:
    from sqlalchemy import func, select
    from sqlalchemy.orm import column_property

    from app.models.comment import Comment

    Post.comment_count = column_property(
        select(func.count(Comment.id))
        .where(Comment.post_id == Post.id)
        .correlate_except(Comment)
        .scalar_subquery(),
        deferred=False,
    )


_attach_comment_count()

"""User model."""
from datetime import datetime
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    cover_url = Column(String, nullable=True)
    next_character_allowed_at = Column(DateTime, nullable=True)
    # When the account last changed its public username. NULL = never changed.
    # Drives the change cooldown in app/core/usernames.py.
    username_changed_at = Column(DateTime, nullable=True)
    # When the paid Writer Unlock was granted. NULL = Wanderer (a complete,
    # permanent account type — not an unfinished Writer). Set only by a real
    # grant path; see app/core/entitlements.py::has_writer_unlock.
    writer_unlocked_at = Column(DateTime, nullable=True)
    # When the account asked to be told the Writer Unlock had launched.
    # NULL = not waiting. Deliberately a separate column from
    # ``writer_unlocked_at``: interest is not entitlement, and nothing reads
    # this to decide what an account may do. A timestamp rather than a boolean
    # so the operator readout can answer "how many joined this week".
    writer_waitlist_joined_at = Column(DateTime, nullable=True)
    # The owner's currently selected character — their visible Ficshon identity.
    # NULL = no explicit selection; the API falls back to the account's single
    # character when exactly one exists. SET NULL on character delete.
    active_character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Role + moderation
    is_admin = Column(Boolean, default=False, nullable=False, server_default="false")
    # Dedicated seeder flag — exempt from the one-character-per-account limit
    # (so founder/seeding accounts can hold multiple characters) without granting
    # full admin powers. See app/services/seeding.py::is_seeder_account.
    is_seeder = Column(Boolean, default=False, nullable=False, server_default="false")
    is_banned = Column(Boolean, default=False, nullable=False, server_default="false")
    banned_at = Column(DateTime, nullable=True)
    ban_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    # foreign_keys pinned: users↔characters now has two FK paths
    # (characters.owner_id and users.active_character_id).
    characters = relationship(
        "Character",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Character.owner_id",
    )
    active_character = relationship(
        "Character",
        foreign_keys=[active_character_id],
        post_update=True,
    )
    owned_realms = relationship("Realm", back_populates="owner", cascade="all, delete-orphan")
    realm_memberships = relationship("RealmMembership", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="author_user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="author_user", cascade="all, delete-orphan")
    reactions = relationship("Reaction", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    images = relationship("UserImage", back_populates="user", cascade="all, delete-orphan")

"""User model."""
from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, DateTime
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
    characters = relationship("Character", back_populates="owner", cascade="all, delete-orphan")
    owned_realms = relationship("Realm", back_populates="owner", cascade="all, delete-orphan")
    realm_memberships = relationship("RealmMembership", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="author_user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="author_user", cascade="all, delete-orphan")
    reactions = relationship("Reaction", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    images = relationship("UserImage", back_populates="user", cascade="all, delete-orphan")

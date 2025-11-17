"""Realm model for RP groups/worlds."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class Realm(Base):
    """Realm (RP group/world) model."""

    __tablename__ = "realms"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    tagline = Column(String, nullable=True)  # Short catchy description
    description = Column(Text, nullable=True)
    genre = Column(String, nullable=True)
    banner_url = Column(String, nullable=True)  # Header/banner image URL
    is_public = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    owner = relationship("User", back_populates="owned_realms")
    memberships = relationship("RealmMembership", back_populates="realm", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="realm", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="realm", cascade="all, delete-orphan")


class RealmMembership(Base):
    """Realm membership model."""

    __tablename__ = "realm_memberships"

    id = Column(Integer, primary_key=True, index=True)
    realm_id = Column(Integer, ForeignKey("realms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, default="member", nullable=False)  # owner, admin, member
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    realm = relationship("Realm", back_populates="memberships")
    user = relationship("User", back_populates="realm_memberships")

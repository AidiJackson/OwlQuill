"""Pydantic schemas for the messaging feature."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CharacterSummary(BaseModel):
    """Minimal character info embedded in conversation responses."""

    id: int
    name: str
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class MessageRead(BaseModel):
    """A single message returned from the API."""

    id: int
    sender_character_id: int
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationRead(BaseModel):
    """A conversation returned from the API."""

    id: int
    character_a: CharacterSummary
    character_b: CharacterSummary
    last_message: Optional[MessageRead] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    """Body for creating / fetching a conversation."""

    from_character_id: int
    to_character_id: int


class MessageCreate(BaseModel):
    """Body for sending a message."""

    sender_character_id: int
    body: str = Field(..., min_length=1, max_length=5000)

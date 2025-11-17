"""Direct messaging schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


# Base schemas
class MessageBase(BaseModel):
    """Base message schema."""
    content: str


class MessageCreate(MessageBase):
    """Schema for creating a message."""
    pass


class MessageRead(MessageBase):
    """Schema for reading a message."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    sender_id: int
    created_at: datetime
    edited_at: Optional[datetime] = None


class ConversationParticipantBase(BaseModel):
    """Base conversation participant schema."""
    user_id: int


class ConversationParticipantRead(ConversationParticipantBase):
    """Schema for reading a conversation participant."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    joined_at: datetime
    last_read_at: Optional[datetime] = None


# Minimal user info for conversation display
class ConversationUserInfo(BaseModel):
    """Minimal user info for conversation display."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None


# Conversation schemas
class ConversationBase(BaseModel):
    """Base conversation schema."""
    pass


class ConversationCreate(BaseModel):
    """Schema for creating/starting a conversation."""
    target_user_id: Optional[int] = None
    target_username: Optional[str] = None


class ConversationSummary(BaseModel):
    """Summary of a conversation for list view."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    other_participant: ConversationUserInfo
    last_message: Optional[MessageRead] = None
    last_message_at: Optional[datetime] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    """Detailed conversation with messages."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    participants: list[ConversationUserInfo]
    messages: list[MessageRead]
    created_at: datetime
    updated_at: datetime


class MarkReadRequest(BaseModel):
    """Request to mark messages as read."""
    last_read_message_id: Optional[int] = None
    read_up_to: Optional[datetime] = None

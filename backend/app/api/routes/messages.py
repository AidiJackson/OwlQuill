"""Messaging routes — 1:1 conversations between characters."""
from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.messaging import (
    CharacterSummary,
    ConversationCreate,
    ConversationRead,
    MessageCreate,
    MessageRead,
)
from app.services.messaging import (
    get_conversation,
    get_last_message,
    get_or_create_conversation,
    list_conversations_for_owner,
    list_messages,
    send_message,
)

router = APIRouter()


def _conversation_to_read(db: Session, conv) -> ConversationRead:
    """Map a Conversation ORM object to ConversationRead."""
    last = get_last_message(db, conv.id)
    return ConversationRead(
        id=conv.id,
        character_a=CharacterSummary.model_validate(conv.character_a),
        character_b=CharacterSummary.model_validate(conv.character_b),
        last_message=MessageRead.model_validate(last) if last else None,
        updated_at=conv.updated_at,
    )


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_200_OK,
)
def create_or_get_conversation(
    body: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create or return an existing conversation between two characters."""
    conv = get_or_create_conversation(
        db,
        my_character_id=body.from_character_id,
        other_character_id=body.to_character_id,
        user_id=current_user.id,
    )
    return _conversation_to_read(db, conv)


@router.get("/conversations", response_model=List[ConversationRead])
def list_my_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all conversations for the logged-in user, newest first."""
    convs = list_conversations_for_owner(db, current_user.id)
    return [_conversation_to_read(db, c) for c in convs]


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=List[MessageRead],
)
def get_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List messages in a conversation, oldest first."""
    return list_messages(db, conversation_id, current_user.id)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def post_message(
    conversation_id: int,
    body: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a message in a conversation."""
    return send_message(
        db,
        conversation_id=conversation_id,
        sender_character_id=body.sender_character_id,
        user_id=current_user.id,
        body=body.body,
    )

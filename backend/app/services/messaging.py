"""Service helpers for the messaging feature."""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.message import Message


def _user_owns_character(db: Session, user_id: int, character_id: int) -> bool:
    """Return True if the user owns the given character."""
    return (
        db.query(Character.id)
        .filter(Character.id == character_id, Character.owner_id == user_id)
        .first()
        is not None
    )


def _user_character_ids(db: Session, user_id: int) -> list[int]:
    """Return all character IDs owned by a user."""
    rows = (
        db.query(Character.id).filter(Character.owner_id == user_id).all()
    )
    return [r[0] for r in rows]


def get_or_create_conversation(
    db: Session, my_character_id: int, other_character_id: int, user_id: int
) -> Conversation:
    """Get or create a conversation between two characters.

    Normalizes order so character_a_id < character_b_id.
    Validates that the caller owns my_character_id.
    """
    if my_character_id == other_character_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a conversation with the same character.",
        )

    if not _user_owns_character(db, user_id, my_character_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own the sender character.",
        )

    # Verify other character exists
    other = db.query(Character.id).filter(Character.id == other_character_id).first()
    if not other:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target character not found.",
        )

    # Normalize pair
    a_id, b_id = sorted([my_character_id, other_character_id])

    conv = (
        db.query(Conversation)
        .filter(
            Conversation.character_a_id == a_id,
            Conversation.character_b_id == b_id,
        )
        .first()
    )
    if conv:
        return conv

    conv = Conversation(character_a_id=a_id, character_b_id=b_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def list_conversations_for_owner(db: Session, user_id: int) -> list[Conversation]:
    """Return all conversations that involve any character owned by user_id."""
    char_ids = _user_character_ids(db, user_id)
    if not char_ids:
        return []

    return (
        db.query(Conversation)
        .filter(
            or_(
                Conversation.character_a_id.in_(char_ids),
                Conversation.character_b_id.in_(char_ids),
            )
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )


def _user_has_access(db: Session, conversation: Conversation, user_id: int) -> bool:
    """Check if user owns at least one character in the conversation."""
    char_ids = _user_character_ids(db, user_id)
    return (
        conversation.character_a_id in char_ids
        or conversation.character_b_id in char_ids
    )


def get_conversation(
    db: Session, conversation_id: int, user_id: int
) -> Conversation:
    """Fetch a single conversation, enforcing access."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    if not _user_has_access(db, conv, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this conversation.",
        )
    return conv


def list_messages(
    db: Session, conversation_id: int, user_id: int
) -> list[Message]:
    """Return messages in a conversation, oldest first. Enforces access."""
    conv = get_conversation(db, conversation_id, user_id)
    return (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
        .all()
    )


def send_message(
    db: Session,
    conversation_id: int,
    sender_character_id: int,
    user_id: int,
    body: str,
) -> Message:
    """Send a message in a conversation. Enforces ownership + participation."""
    conv = get_conversation(db, conversation_id, user_id)

    # Sender must be a participant
    if sender_character_id not in (conv.character_a_id, conv.character_b_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sender character is not part of this conversation.",
        )

    # Sender must be owned by caller
    if not _user_owns_character(db, user_id, sender_character_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own the sender character.",
        )

    msg = Message(
        conversation_id=conv.id,
        sender_character_id=sender_character_id,
        body=body,
    )
    db.add(msg)

    # Touch conversation updated_at
    conv.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(msg)
    return msg


def get_last_message(db: Session, conversation_id: int) -> Optional[Message]:
    """Return the most recent message in a conversation, or None."""
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .first()
    )

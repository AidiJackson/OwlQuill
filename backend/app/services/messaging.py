"""Service helpers for the messaging feature."""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.safety import blocked_user_ids


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


def _other_owner_id(conv: Conversation, user_id: int) -> Optional[int]:
    """Return the owner_id of the other character in a conversation, or None.

    Uses lazy-loaded relationships; safe to call within an open session.
    """
    char_a = conv.character_a
    char_b = conv.character_b
    if char_a and char_a.owner_id == user_id:
        return char_b.owner_id if char_b else None
    if char_b and char_b.owner_id == user_id:
        return char_a.owner_id if char_a else None
    return None


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

    # Verify other character exists (need full object for owner check)
    other_char = db.query(Character).filter(Character.id == other_character_id).first()
    if not other_char:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target character not found.",
        )

    # Block check: 403 if either party has blocked the other
    blocked = blocked_user_ids(db, user_id)
    if other_char.owner_id in blocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "blocked"},
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
    """Return all conversations that involve any character owned by user_id,
    excluding conversations where the other participant is blocked."""
    char_ids = _user_character_ids(db, user_id)
    if not char_ids:
        return []

    convs = (
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

    blocked = blocked_user_ids(db, user_id)
    if not blocked:
        return convs

    return [c for c in convs if _other_owner_id(c, user_id) not in blocked]


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
    """Fetch a single conversation, enforcing access and block rules."""
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
    # Block check → 404 (treat as not found for privacy)
    other_owner = _other_owner_id(conv, user_id)
    if other_owner is not None and other_owner in blocked_user_ids(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
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
    """Send a message in a conversation. Enforces ownership + participation.

    Returns 403 (not 404) when a block relationship exists so the caller
    receives a clear "blocked" signal rather than a silent not-found.
    """
    # Block check before the full access check so the status code is 403
    conv_peek = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv_peek is not None:
        other_owner = _other_owner_id(conv_peek, user_id)
        if other_owner is not None and other_owner in blocked_user_ids(db, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": "blocked"},
            )

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

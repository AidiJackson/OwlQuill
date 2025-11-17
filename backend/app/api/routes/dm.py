"""Direct messaging routes."""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.dm import Conversation, ConversationParticipant, Message
from app.models.notification import Notification
from app.schemas.dm import (
    ConversationCreate,
    ConversationSummary,
    ConversationDetail,
    MessageCreate,
    MessageRead,
    MarkReadRequest,
    ConversationUserInfo,
)

router = APIRouter()


def get_other_participant(conversation: Conversation, current_user_id: int, db: Session) -> Optional[User]:
    """Get the other participant in a 1:1 conversation."""
    for participant in conversation.participants:
        if participant.user_id != current_user_id:
            user = db.query(User).filter(User.id == participant.user_id).first()
            return user
    return None


def get_unread_count(conversation_id: int, user_id: int, db: Session) -> int:
    """Get the count of unread messages for a user in a conversation."""
    participant = db.query(ConversationParticipant).filter(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id
        )
    ).first()

    if not participant:
        return 0

    # Count messages created after last_read_at
    query = db.query(func.count(Message.id)).filter(
        and_(
            Message.conversation_id == conversation_id,
            Message.sender_id != user_id  # Don't count own messages
        )
    )

    if participant.last_read_at:
        query = query.filter(Message.created_at > participant.last_read_at)

    return query.scalar() or 0


@router.get("/conversations", response_model=List[ConversationSummary])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[ConversationSummary]:
    """List all conversations for the current user."""
    # Get all conversation IDs where user is a participant
    participant_records = db.query(ConversationParticipant).filter(
        ConversationParticipant.user_id == current_user.id
    ).all()

    conversation_ids = [p.conversation_id for p in participant_records]

    if not conversation_ids:
        return []

    # Get all conversations
    conversations = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids)
    ).order_by(Conversation.updated_at.desc()).all()

    result = []
    for conversation in conversations:
        # Get other participant (for 1:1 conversations)
        other_user = get_other_participant(conversation, current_user.id, db)
        if not other_user:
            continue  # Skip if no other participant found

        # Get last message
        last_message = db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at.desc()).first()

        # Get unread count
        unread_count = get_unread_count(conversation.id, current_user.id, db)

        summary = ConversationSummary(
            id=conversation.id,
            other_participant=ConversationUserInfo(
                id=other_user.id,
                username=other_user.username,
                display_name=other_user.display_name,
                avatar_url=other_user.avatar_url
            ),
            last_message=MessageRead.model_validate(last_message) if last_message else None,
            last_message_at=last_message.created_at if last_message else None,
            unread_count=unread_count,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at
        )
        result.append(summary)

    return result


@router.post("/start", response_model=ConversationDetail, status_code=status.HTTP_200_OK)
def start_conversation(
    conversation_data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ConversationDetail:
    """Start a new conversation or return existing one."""
    # Find target user
    target_user = None
    if conversation_data.target_user_id:
        target_user = db.query(User).filter(User.id == conversation_data.target_user_id).first()
    elif conversation_data.target_username:
        target_user = db.query(User).filter(User.username == conversation_data.target_username).first()

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found"
        )

    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start a conversation with yourself"
        )

    # Check if conversation already exists between these two users
    # Get all conversations where current user is a participant
    current_user_conversations = db.query(ConversationParticipant.conversation_id).filter(
        ConversationParticipant.user_id == current_user.id
    ).subquery()

    # Get all conversations where target user is a participant
    target_user_conversations = db.query(ConversationParticipant.conversation_id).filter(
        ConversationParticipant.user_id == target_user.id
    ).subquery()

    # Find conversations where both are participants
    existing_conversation_id = db.query(Conversation.id).filter(
        and_(
            Conversation.id.in_(current_user_conversations),
            Conversation.id.in_(target_user_conversations)
        )
    ).first()

    if existing_conversation_id:
        # Return existing conversation
        return get_conversation_detail(existing_conversation_id[0], current_user, db)

    # Create new conversation
    conversation = Conversation()
    db.add(conversation)
    db.flush()  # Get the conversation ID

    # Add participants
    current_participant = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=current_user.id
    )
    target_participant = ConversationParticipant(
        conversation_id=conversation.id,
        user_id=target_user.id
    )
    db.add(current_participant)
    db.add(target_participant)
    db.commit()
    db.refresh(conversation)

    return get_conversation_detail(conversation.id, current_user, db)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation_detail(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
) -> ConversationDetail:
    """Get conversation details with messages."""
    # Check if conversation exists
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    # Check if current user is a participant
    is_participant = db.query(ConversationParticipant).filter(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == current_user.id
        )
    ).first()

    if not is_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation"
        )

    # Get all participants with user info
    participants_data = []
    for participant in conversation.participants:
        user = db.query(User).filter(User.id == participant.user_id).first()
        if user:
            participants_data.append(ConversationUserInfo(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                avatar_url=user.avatar_url
            ))

    # Get messages (paginated, newest first for display but we'll reverse)
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.desc()).offset(skip).limit(limit).all()

    # Reverse to get chronological order
    messages = list(reversed(messages))

    return ConversationDetail(
        id=conversation.id,
        participants=participants_data,
        messages=[MessageRead.model_validate(m) for m in messages],
        created_at=conversation.created_at,
        updated_at=conversation.updated_at
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def send_message(
    conversation_id: int,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> MessageRead:
    """Send a message in a conversation."""
    # Check if conversation exists
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )

    # Check if current user is a participant
    current_participant = db.query(ConversationParticipant).filter(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == current_user.id
        )
    ).first()

    if not current_participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation"
        )

    # Create message
    message = Message(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=message_data.content
    )
    db.add(message)

    # Update conversation updated_at
    conversation.updated_at = datetime.utcnow()

    # Update sender's last_read_at (they've read up to their own message)
    current_participant.last_read_at = datetime.utcnow()

    db.commit()
    db.refresh(message)

    # Create notifications for other participants
    other_participants = db.query(ConversationParticipant).filter(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id != current_user.id
        )
    ).all()

    for participant in other_participants:
        notification = Notification(
            user_id=participant.user_id,
            type="dm_message",
            payload=f'{{"conversation_id": {conversation_id}, "message_id": {message.id}, "sender": "{current_user.username}"}}',
            is_read=False
        )
        db.add(notification)

    db.commit()

    return MessageRead.model_validate(message)


@router.post("/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_messages_read(
    conversation_id: int,
    mark_read_data: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> None:
    """Mark messages as read in a conversation."""
    # Check if user is a participant
    participant = db.query(ConversationParticipant).filter(
        and_(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == current_user.id
        )
    ).first()

    if not participant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant in this conversation"
        )

    # Update last_read_at
    if mark_read_data.read_up_to:
        participant.last_read_at = mark_read_data.read_up_to
    elif mark_read_data.last_read_message_id:
        # Get the timestamp of the specified message
        message = db.query(Message).filter(
            and_(
                Message.id == mark_read_data.last_read_message_id,
                Message.conversation_id == conversation_id
            )
        ).first()
        if message:
            participant.last_read_at = message.created_at
    else:
        # If no specific time/message, mark all as read up to now
        participant.last_read_at = datetime.utcnow()

    db.commit()
    return None

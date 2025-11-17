"""Analytics event logging routes."""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.models.user import User as UserModel
from app.models.analytics import AnalyticsEvent as AnalyticsEventModel
from app.schemas.analytics import AnalyticsEventCreate, AnalyticsEvent

router = APIRouter()

# Whitelist of allowed event types
ALLOWED_EVENT_TYPES = {
    "profile_view",
    "character_view",
    "realm_view",
    "post_view",
    "search",
}


@router.post("/events", response_model=AnalyticsEvent, status_code=201)
def log_event(
    event_create: AnalyticsEventCreate,
    db: Session = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional)
) -> AnalyticsEvent:
    """
    Log an analytics event.

    Only whitelisted event types are allowed for security.
    """
    # Validate event type
    if event_create.event_type not in ALLOWED_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event type. Allowed types: {', '.join(ALLOWED_EVENT_TYPES)}"
        )

    # Serialize payload to JSON string
    payload_str = None
    if event_create.payload:
        payload_str = json.dumps(event_create.payload)

    # Create event
    event = AnalyticsEventModel(
        user_id=current_user.id if current_user else None,
        event_type=event_create.event_type,
        payload=payload_str
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    return event

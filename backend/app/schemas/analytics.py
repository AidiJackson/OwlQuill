"""Analytics event schemas."""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class AnalyticsEventCreate(BaseModel):
    """Analytics event creation schema."""
    event_type: str = Field(..., min_length=1, max_length=100)
    payload: Optional[Dict[str, Any]] = None


class AnalyticsEvent(BaseModel):
    """Analytics event response schema."""
    id: int
    user_id: Optional[int] = None
    event_type: str
    payload: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}

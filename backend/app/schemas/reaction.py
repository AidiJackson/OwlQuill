"""Reaction schemas."""
from datetime import datetime
from pydantic import BaseModel, Field


class ReactionBase(BaseModel):
    """Base reaction schema."""
    type: str = Field(..., min_length=1, max_length=50)


class ReactionCreate(ReactionBase):
    """Reaction creation schema."""
    pass


class Reaction(ReactionBase):
    """Reaction schema."""
    id: int
    post_id: int
    user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}

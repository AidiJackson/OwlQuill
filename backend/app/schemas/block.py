"""Block schemas for API requests and responses."""
from datetime import datetime
from pydantic import BaseModel


class BlockCreate(BaseModel):
    """Block creation schema."""
    blocked_id: int


class Block(BaseModel):
    """Block response schema."""
    id: int
    blocker_id: int
    blocked_id: int
    created_at: datetime

    model_config = {"from_attributes": True}

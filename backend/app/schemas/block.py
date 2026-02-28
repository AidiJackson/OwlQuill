"""Pydantic schemas for the blocks feature."""
from datetime import datetime

from pydantic import BaseModel


class BlockedUserSummary(BaseModel):
    """Minimal public info about a blocked user."""

    id: int
    username: str

    model_config = {"from_attributes": True}


class BlockRead(BaseModel):
    """A block relationship returned from the API."""

    id: int
    blocked: BlockedUserSummary
    created_at: datetime

    model_config = {"from_attributes": True}

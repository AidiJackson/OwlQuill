"""User connection (follow) schemas."""
from datetime import datetime
from pydantic import BaseModel


class ConnectionBase(BaseModel):
    """Base connection schema."""
    pass


class ConnectionCreate(BaseModel):
    """Connection creation schema."""
    following_id: int


class Connection(ConnectionBase):
    """Connection schema."""
    id: int
    follower_id: int
    following_id: int
    created_at: datetime

    model_config = {"from_attributes": True}

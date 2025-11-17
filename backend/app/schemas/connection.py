"""Connection schemas."""
from datetime import datetime
from pydantic import BaseModel


class ConnectionBase(BaseModel):
    """Base connection schema."""
    pass


class ConnectionCreate(ConnectionBase):
    """Connection creation schema."""
    pass


class Connection(ConnectionBase):
    """Connection schema."""
    id: int
    follower_id: int
    followee_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectionUser(BaseModel):
    """User info for connection list."""
    id: int
    username: str
    display_name: str | None
    avatar_url: str | None

    model_config = {"from_attributes": True}

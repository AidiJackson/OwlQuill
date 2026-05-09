"""Schemas for identity snapshot read/list."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class IdentitySnapshotRead(BaseModel):
    id: int
    character_id: int
    snapshot_version: int
    anchor_version: int
    reason: Optional[str] = None
    created_at: datetime
    # Anchor and spec JSON are intentionally omitted from the read schema —
    # they are large blobs consumed only by the rollback endpoint internally.

    model_config = {"from_attributes": True}

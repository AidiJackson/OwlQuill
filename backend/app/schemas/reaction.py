"""Reaction schemas."""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel

# The product's whole reaction vocabulary. Enforced on write so a reaction can
# never carry a user-controlled label, and on read so a row stored before the
# allowlist (or written straight to the column) is dropped rather than served.
REACTION_TYPES = ("heart", "star", "eyes")
ReactionType = Literal["heart", "star", "eyes"]


class ReactionCreate(BaseModel):
    """Reaction creation schema."""
    type: ReactionType


class Reaction(BaseModel):
    """Reaction schema.

    Reactions are ACCOUNT-owned, so ``user_id`` is account infrastructure: it is
    only ever filled in with the viewer's own id, on the viewer's own reaction —
    enough for a client to find and toggle it off. Every other reaction carries
    ``None``, and an anonymous reader receives ``None`` throughout, so a list of
    reactions cannot link one account's activity across posts. See
    ``app.api.routes.reactions.project_reaction``.
    """
    id: int
    post_id: int
    type: str
    user_id: Optional[int] = None
    created_at: datetime

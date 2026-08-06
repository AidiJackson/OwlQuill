"""Composition session schemas.

Note what is absent: there is no field anywhere in this module that carries
text. The client reports counts about its editing session and nothing else —
clipboard contents are never read, hashed, sampled or transmitted.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CompositionMetrics(BaseModel):
    """Counters describing an editing session. Integers only, by design."""

    #: Characters that arrived one or two at a time — keystrokes and IME commits.
    typed_chars: int = Field(0, ge=0)
    #: Characters that arrived by paste or drop, of any origin.
    inserted_chars: int = Field(0, ge=0)
    #: Of ``inserted_chars``, how many the client attributes to a Ficshon
    #: internal transfer (WriteSpace → composer). Credited only up to what the
    #: parent session was independently observed to have typed.
    internal_insert_chars: int = Field(0, ge=0)
    largest_insertion: int = Field(0, ge=0)
    insertion_count: int = Field(0, ge=0)
    edit_duration_ms: int = Field(0, ge=0)


class SessionOpenRequest(BaseModel):
    surface: str = Field(..., max_length=32)
    target_kind: Optional[str] = Field(None, max_length=32)
    target_ref: Optional[str] = Field(None, max_length=64)
    #: The session this one continues, for an internal draft handoff.
    continues_session_id: Optional[str] = Field(None, max_length=36)


class SessionUpdateRequest(BaseModel):
    metrics: CompositionMetrics


class SessionRead(BaseModel):
    id: str
    surface: str
    status: str
    target_kind: Optional[str] = None
    target_ref: Optional[str] = None
    parent_session_id: Optional[str] = None
    created_at: datetime
    last_active_at: datetime

    model_config = {"from_attributes": True}

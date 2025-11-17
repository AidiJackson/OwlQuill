"""Report schemas for API requests and responses."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models.report import ReportReasonEnum, ReportStatusEnum


class ReportCreate(BaseModel):
    """Report creation schema."""
    target_type: str = Field(..., pattern="^(post|scene_post)$")
    target_id: int
    reason: ReportReasonEnum
    details: Optional[str] = Field(None, max_length=1000)


class Report(BaseModel):
    """Report response schema."""
    id: int
    reporter_id: int
    target_type: str
    target_id: int
    reason: ReportReasonEnum
    details: Optional[str]
    status: ReportStatusEnum
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

"""Report submission endpoint — authenticated users can report content."""
from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.report import Report, ReportTargetTypeEnum, ReportStatusEnum
from app.models.user import User

router = APIRouter()


class ReportCreate(BaseModel):
    target_type: ReportTargetTypeEnum
    target_id: str = Field(..., min_length=1, max_length=128)
    reason: str = Field(..., min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=2000)


class ReportRead(BaseModel):
    id: int
    target_type: ReportTargetTypeEnum
    target_id: str
    reason: str
    detail: str | None
    status: ReportStatusEnum
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def submit_report(
    body: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReportRead:
    """Submit a report against content or a user."""
    report = Report(
        reporter_id=current_user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        reason=body.reason,
        detail=body.detail,
        status=ReportStatusEnum.OPEN,
        created_at=datetime.utcnow(),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report

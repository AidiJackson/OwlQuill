"""Admin-only endpoints: report review + user ban/unban."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, user_is_admin
from app.models.report import Report, ReportStatusEnum, ReportTargetTypeEnum
from app.models.user import User

router = APIRouter()


# ── Admin guard ───────────────────────────────────────────────────────────────

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the caller is an admin. Returns the user if so."""
    is_admin = user_is_admin(current_user)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "detail": "Admin access required."},
        )
    return current_user


# ── Schemas ───────────────────────────────────────────────────────────────────

class ReportAdminRead(BaseModel):
    id: int
    reporter_id: int
    target_type: ReportTargetTypeEnum
    target_id: str
    reason: str
    detail: Optional[str]
    status: ReportStatusEnum
    resolved_by_id: Optional[int]
    resolved_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class BanRequest(BaseModel):
    reason: Optional[str] = None


# ── Report endpoints ──────────────────────────────────────────────────────────

@router.get("/reports", response_model=list[ReportAdminRead])
def list_reports(
    status: Optional[str] = Query(default=None, description="Filter by status: open|resolved"),
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[ReportAdminRead]:
    """List reports, optionally filtered by status."""
    query = db.query(Report)
    if status in ("open", "resolved"):
        query = query.filter(Report.status == status)
    return query.order_by(Report.created_at.desc()).limit(limit).all()


@router.post("/reports/{report_id}/resolve", response_model=ReportAdminRead)
def resolve_report(
    report_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReportAdminRead:
    """Mark a report as resolved."""
    report = db.query(Report).filter(Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    report.status = ReportStatusEnum.RESOLVED
    report.resolved_by_id = admin.id
    report.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(report)
    return report


# ── Ban / unban endpoints ─────────────────────────────────────────────────────

@router.post("/ban/{user_id}", status_code=status.HTTP_200_OK)
def ban_user(
    user_id: int,
    body: BanRequest = BanRequest(),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Ban a user account."""
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if target.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_operation", "detail": "Cannot ban yourself."},
        )
    target.is_banned = True
    target.banned_at = datetime.utcnow()
    target.ban_reason = body.reason or "Banned by admin."
    db.commit()
    return {"user_id": user_id, "is_banned": True, "ban_reason": target.ban_reason}


@router.post("/unban/{user_id}", status_code=status.HTTP_200_OK)
def unban_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Unban a user account."""
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    target.is_banned = False
    target.banned_at = None
    target.ban_reason = None
    db.commit()
    return {"user_id": user_id, "is_banned": False}

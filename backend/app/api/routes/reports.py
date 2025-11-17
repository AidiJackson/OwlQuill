"""Report routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.report import ContentReport as ContentReportModel
from app.models.post import Post
from app.models.scene import ScenePost
from app.schemas.report import Report, ReportCreate

router = APIRouter()


@router.post("/", response_model=Report, status_code=status.HTTP_201_CREATED)
def create_report(
    report_data: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Report:
    """Report content."""
    # Validate that target exists
    if report_data.target_type == "post":
        target = db.query(Post).filter(Post.id == report_data.target_id).first()
    elif report_data.target_type == "scene_post":
        target = db.query(ScenePost).filter(ScenePost.id == report_data.target_id).first()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target type"
        )

    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{report_data.target_type} not found"
        )

    # Create report
    db_report = ContentReportModel(
        reporter_id=current_user.id,
        **report_data.model_dump()
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report

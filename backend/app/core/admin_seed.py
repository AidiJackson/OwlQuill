"""Admin user seed on startup."""
import logging
import os

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User

logger = logging.getLogger(__name__)


def ensure_admin_user() -> None:
    """Ensure admin user exists based on environment variables.

    Env vars:
        ADMIN_EMAIL (required): Admin email address
        ADMIN_PASSWORD (required): Admin password (will be hashed)
        ADMIN_USERNAME (optional): Username, defaults to "admin"
        ADMIN_FORCE_RESET (optional): If "true", reset password even if user exists
    """
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    force_reset = os.environ.get("ADMIN_FORCE_RESET", "").lower() == "true"

    # Skip if no admin credentials configured
    if not admin_email or not admin_password:
        return

    db: Session = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == admin_email).first()

        if existing is None:
            # Create new admin user
            admin = User(
                email=admin_email,
                username=admin_username,
                hashed_password=get_password_hash(admin_password),
                display_name=admin_username,
            )
            db.add(admin)
            db.commit()
            logger.info(f"Admin user created: {admin_email}")
        elif force_reset:
            # Update password if force reset enabled
            existing.hashed_password = get_password_hash(admin_password)
            db.commit()
            logger.info(f"Admin password reset: {admin_email}")
        else:
            logger.info(f"Admin ensured: {admin_email}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to ensure admin user: {e}")
        raise
    finally:
        db.close()

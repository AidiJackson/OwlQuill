"""Admin user and Commons realm seed on startup."""
import logging
import os

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User
from app.models.realm import Realm as RealmModel, RealmMembership as RealmMembershipModel

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
    finally:
        db.close()


def ensure_commons_realm() -> None:
    """Ensure The Commons realm exists. Called on startup.

    Requires at least one user to exist (as owner). If no users exist,
    the realm will be created on first user registration instead.
    """
    db: Session = SessionLocal()
    try:
        existing = db.query(RealmModel).filter(RealmModel.is_commons == True).first()
        if existing:
            logger.info("The Commons realm ensured")
            return

        # Need an owner — use the first available user
        owner = db.query(User).first()
        if not owner:
            logger.info("No users yet — The Commons will be created on first registration")
            return

        commons = RealmModel(
            name="The Commons",
            slug="the-commons",
            tagline="Intros, plotting, and updates for the whole community",
            description="The global social space for all OwlQuill users. Post OOC updates, find RP partners, and connect with the community.",
            genre="Social",
            is_public=True,
            is_commons=True,
            owner_id=owner.id,
        )
        db.add(commons)
        db.flush()

        membership = RealmMembershipModel(
            realm_id=commons.id,
            user_id=owner.id,
            role="owner",
        )
        db.add(membership)
        db.commit()
        logger.info("The Commons realm created")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to ensure Commons realm: {e}")
    finally:
        db.close()


def auto_join_commons(user_id: int, db: Session) -> None:
    """Ensure a user is a member of The Commons. Creates Commons if needed.

    Safe to call multiple times (idempotent). Never raises — logs errors instead.
    """
    try:
        commons = db.query(RealmModel).filter(RealmModel.is_commons == True).first()

        if not commons:
            # Create The Commons with this user as owner
            commons = RealmModel(
                name="The Commons",
                slug="the-commons",
                tagline="Intros, plotting, and updates for the whole community",
                description="The global social space for all OwlQuill users. Post OOC updates, find RP partners, and connect with the community.",
                genre="Social",
                is_public=True,
                is_commons=True,
                owner_id=user_id,
            )
            db.add(commons)
            db.flush()

        existing = db.query(RealmMembershipModel).filter(
            RealmMembershipModel.realm_id == commons.id,
            RealmMembershipModel.user_id == user_id,
        ).first()

        if not existing:
            membership = RealmMembershipModel(
                realm_id=commons.id,
                user_id=user_id,
                role="member",
            )
            db.add(membership)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to auto-join Commons for user {user_id}: {e}")

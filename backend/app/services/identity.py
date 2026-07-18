"""Active-character identity helpers (Sprint 33).

On Ficshon, characters are the social identities; user accounts are private
infrastructure. These helpers resolve which character an account is currently
"being" and build the authenticated /me payload that carries that context.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character import Character
from app.models.user import User as UserModel
from app.schemas.user import ActiveCharacterSummary, User as UserSchema
from app.services.seeding import is_seeder_account


def resolve_active_character(db: Session, user: UserModel) -> Optional[Character]:
    """Return the user's active character.

    Explicit selection wins (ignored if the character no longer belongs to the
    account); otherwise fall back to the account's single character when exactly
    one exists. Multi-character accounts with no selection resolve to None.
    """
    if user.active_character_id:
        char = (
            db.query(Character)
            .filter(
                Character.id == user.active_character_id,
                Character.owner_id == user.id,
            )
            .first()
        )
        if char:
            return char

    owned = (
        db.query(Character)
        .filter(Character.owner_id == user.id)
        .order_by(Character.created_at.asc())
        .limit(2)
        .all()
    )
    if len(owned) == 1:
        return owned[0]
    return None


def build_user_out(db: Session, user: UserModel) -> UserSchema:
    """Serialize a User for authenticated /me responses with identity context:
    is_admin/is_seeder (config- and flag-aware), the resolved active character,
    and the owned-character count.
    """
    from app.core.config import settings

    out = UserSchema.model_validate(user)
    out.is_admin = bool(user.is_admin) or (user.email or "").lower() in settings.get_admin_emails()
    out.is_seeder = is_seeder_account(user)
    out.character_count = (
        db.query(Character).filter(Character.owner_id == user.id).count()
    )
    active = resolve_active_character(db, user)
    out.active_character = (
        ActiveCharacterSummary.model_validate(active) if active else None
    )
    return out

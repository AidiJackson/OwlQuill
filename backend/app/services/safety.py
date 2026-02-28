"""Safety service helpers — blocks and related filtering utilities."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.block import Block


def blocked_user_ids(db: Session, user_id: int) -> set[int]:
    """Return all user IDs in a block relationship with user_id (both directions).

    Includes:
    - Users that user_id has blocked (blocker_id == user_id)
    - Users that have blocked user_id (blocked_id == user_id)
    """
    rows = (
        db.query(Block)
        .filter(
            or_(Block.blocker_id == user_id, Block.blocked_id == user_id)
        )
        .all()
    )
    result: set[int] = set()
    for row in rows:
        if row.blocker_id == user_id:
            result.add(row.blocked_id)
        else:
            result.add(row.blocker_id)
    return result

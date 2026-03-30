"""Seed initial invite codes from BETA_INVITE_CODES env var at startup.

Format: comma-separated list of "CODE" or "CODE:N" entries.
  - "CODE"    → enabled, unlimited uses
  - "CODE:N"  → enabled, max N uses

Existing codes are never overwritten. Only missing ones are inserted.
"""
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.invite_code import InviteCode

logger = logging.getLogger(__name__)


def seed_invite_codes() -> None:
    """Create any invite codes from BETA_INVITE_CODES that don't yet exist in DB."""
    raw = settings.BETA_INVITE_CODES.strip()
    if not raw:
        return

    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not entries:
        return

    db = SessionLocal()
    try:
        created = 0
        for entry in entries:
            if ":" in entry:
                code_str, max_str = entry.rsplit(":", 1)
                try:
                    max_uses: int | None = int(max_str)
                except ValueError:
                    logger.warning("invite_seed: invalid max_uses %r in entry %r — skipping", max_str, entry)
                    continue
            else:
                code_str = entry
                max_uses = None

            code_str = code_str.strip().upper()
            if not code_str:
                continue

            existing = db.query(InviteCode).filter(InviteCode.code == code_str).first()
            if existing:
                continue  # Never overwrite

            db.add(InviteCode(
                code=code_str,
                is_enabled=True,
                max_uses=max_uses,
                use_count=0,
                note="seeded-from-env",
                created_at=datetime.utcnow(),
            ))
            created += 1

        if created:
            db.commit()
            logger.info("invite_seed: created %d invite code(s)", created)
        else:
            logger.debug("invite_seed: all codes already exist, nothing to create")
    except Exception:
        db.rollback()
        logger.exception("invite_seed: failed to seed invite codes")
    finally:
        db.close()

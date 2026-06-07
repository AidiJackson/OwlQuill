"""Finish Adult Studio backfill preparation for as03-migrated characters.

Run from the backend/ directory:
    python scripts/adult_studio_prepare_backfilled.py
    python scripts/adult_studio_prepare_backfilled.py --dry-run
    python scripts/adult_studio_prepare_backfilled.py --character-id 60

Context
-------
The ``as03`` migration performs a cheap SQL copy (legacy status + manifest) into
``adult_identity_models`` but leaves ``canon_fingerprint`` NULL and creates no
per-mark render plans. ``prepare_adult_identity()`` is what populates those:
canon fingerprint, per-mark render routes, and the settled ``prepared`` state.

This utility finds backfilled-but-unprepared identity models and runs
``prepare_adult_identity()`` for each. It is:

  * idempotent  — re-running prepares nothing already complete and never
                  duplicates rows (prepare upserts by character / mark id);
  * read-only on canon — it reads the locked Canon Pack as source of truth and
                  writes ONLY ``adult_identity_*`` tables;
  * provider-free — it NEVER constructs a provider, trains, or generates images.

Safe to run after ``as03`` in dev or prod.
"""
import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow running from backend/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import exists, or_

from app.core.database import SessionLocal
from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs
from app.services.adult_identity_preparation import (
    CanonNotReadyError,
    prepare_adult_identity,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BackfillPrepareSummary:
    """Outcome of a prepare-backfilled run (testable, no I/O)."""

    dry_run: bool = False
    processed: list[int] = field(default_factory=list)       # character_ids prepared
    would_process: list[int] = field(default_factory=list)   # dry-run candidates
    skipped: list[tuple[int, str]] = field(default_factory=list)
    failed: list[tuple[int, str]] = field(default_factory=list)

    @property
    def processed_count(self) -> int:
        return len(self.would_process if self.dry_run else self.processed)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        return len(self.failed)


def _render_count(db, model: AdultIdentityModel) -> int:
    return (
        db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .count()
    )


def _canon_mark_count(db, character_id: int) -> int:
    """Number of permanent canon marks for a character (read-only canon access)."""
    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == character_id)
        .first()
    )
    if canon is None:
        return 0
    body = cs.load_body_canon(canon)
    return len(list(getattr(body, "permanent_body_marks", []) or []))


def _needs_prep(db, model: AdultIdentityModel) -> bool:
    """A model needs preparation when it was backfilled but never prepared.

    - NULL canon_fingerprint → definitely unprepared (the as03 backfill state).
    - fingerprint present but no render rows → only when canon actually has marks
      (a markless character legitimately has zero renders and is already complete).
    """
    if model.canon_fingerprint is None:
        return True
    if _render_count(db, model) > 0:
        return False
    return _canon_mark_count(db, model.character_id) > 0


def prepare_backfilled(
    db, *, character_id: int | None = None, dry_run: bool = False
) -> BackfillPrepareSummary:
    """Prepare backfilled identity models. Returns a structured summary.

    With ``character_id`` only that character's model is considered; otherwise every
    candidate (NULL fingerprint OR missing render plan) is processed.
    """
    summary = BackfillPrepareSummary(dry_run=dry_run)

    q = db.query(AdultIdentityModel)
    if character_id is not None:
        q = q.filter(AdultIdentityModel.character_id == character_id)
    else:
        # Cheap candidate filter; _needs_prep refines (e.g. markless characters).
        render_exists = exists().where(
            AdultIdentityMarkRender.identity_id == AdultIdentityModel.id
        )
        q = q.filter(
            or_(AdultIdentityModel.canon_fingerprint.is_(None), ~render_exists)
        )
    models = q.order_by(AdultIdentityModel.character_id).all()

    if character_id is not None and not models:
        summary.failed.append((character_id, "no AdultIdentityModel row for character"))
        logger.warning("character_id=%s has no AdultIdentityModel row", character_id)
        return summary

    for model in models:
        cid = model.character_id
        if not _needs_prep(db, model):
            summary.skipped.append((cid, "already prepared"))
            print(f"SKIP  character_id={cid} — already prepared")
            continue

        if dry_run:
            summary.would_process.append(cid)
            print(f"DRY   character_id={cid} — would prepare (fingerprint/mark routes)")
            continue

        try:
            res = prepare_adult_identity(cid, db)
        except CanonNotReadyError as exc:
            db.rollback()
            summary.failed.append((cid, f"canon not ready: {exc}"))
            print(f"FAIL  character_id={cid} — canon not ready")
            continue
        except Exception as exc:  # noqa: BLE001 — never crash the batch on one row
            db.rollback()
            summary.failed.append((cid, f"error: {exc}"))
            print(f"FAIL  character_id={cid} — {exc}")
            continue

        summary.processed.append(cid)
        print(
            f"OK    character_id={cid} — status={res.model_status} "
            f"fingerprint={res.fingerprint[:12]}… marks={res.mark_count}"
        )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Finish Adult Studio backfill preparation (as03 → prepared)."
    )
    parser.add_argument("--character-id", type=int, help="Only this character ID")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report candidates; write nothing"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = prepare_backfilled(
            db, character_id=args.character_id, dry_run=args.dry_run
        )
    finally:
        db.close()

    verb = "would prepare" if summary.dry_run else "prepared"
    logger.info(
        "Done (%s): %s=%d skipped=%d failed=%d",
        "dry-run" if summary.dry_run else "live",
        verb,
        summary.processed_count,
        summary.skipped_count,
        summary.failed_count,
    )
    # Non-zero exit if anything failed, so CI/ops can detect partial completion.
    if summary.failed_count:
        sys.exit(1)


if __name__ == "__main__":
    main()

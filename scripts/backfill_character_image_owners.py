"""Backfill ``character_images.user_id`` from ``characters.owner_id``.

Phase 4B1. This is the data half of one change: ``CharacterImage.user_id``
stops meaning "which account generated this, for the weekly quota" and starts
meaning "which account OWNS this asset". The application half — the five
ownership reads that stop joining ``Character`` — ships in the same increment,
because a persistent state where the column has been backfilled but the code
still derives ownership from the character (or the reverse) is a state nobody
can reason about.

WHY A SCRIPT AND NOT A MIGRATION
--------------------------------
An Alembic data migration runs unattended, its dry-run is "read the SQL", and
its ``downgrade()`` cannot tell the 318 rows it wrote from the 1,111 rows that
were already correct — so reversing it would have to NULL all 1,429, destroying
data it never touched. This script writes a manifest of the exact ids it
changed BEFORE it commits, so the reversal is precise by construction. That
property is the whole reason for the file.

WHAT IT WILL NOT DO
-------------------
* It will not touch anything but ``character_images.user_id``, and only on rows
  where that column IS NULL.
* It will not run against anything but the DEV database. ``assert_dev_database``
  is called unconditionally in :func:`main`, and there is no override flag,
  no ``--force``, and no production mode. Production execution is a separate,
  reviewable design; adding a bypass here would pre-empt it.
* It will not change quota accounting behind anyone's back. If any row it would
  backfill falls inside the live seven-day quota window, it ABORTS — see
  :func:`quota_impact`.
* It will not print a connection string, hostname, role, email, file path,
  prompt or any other row content. Output is counts and image ids only, so a
  transcript is safe to paste into a ticket.
* There is no ORM session, no model import and no unit of work. Only literal
  SQL, so nothing can flush a stray change alongside the intended one.

INVOCATION
----------
Preview (the default — mutates nothing, and the connection is opened in a
server-enforced read-only transaction so it *cannot* mutate)::

    python scripts/backfill_character_image_owners.py --dry-run

Apply::

    python scripts/backfill_character_image_owners.py --confirm

``--dry-run --confirm`` together is refused as contradictory rather than
resolved in either direction.

IDEMPOTENCE
-----------
The update matches only ``user_id IS NULL``. A second confirmed run finds zero
eligible rows, writes no manifest and reports "nothing to do". Running it twice
is not an error and not a second mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence

# Repo root, derived from this file, so the sibling guard imports wherever the
# checkout lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from scripts.assert_dev_db import DEV, assert_dev_database

#: Length of the rolling image-allowance window, in days.
#:
#: MIRRORS ``app.services.image_quota._WINDOW_DAYS``. It is duplicated rather
#: than imported so this file stays free of application imports (importing the
#: quota service pulls in the models and the settings object, and with them a
#: configured engine — exactly what "no ORM session" is meant to exclude).
#:
#: A duplicated constant can drift, and a drifted constant would make the quota
#: guard below measure the wrong window while still reporting success. That is
#: why ``tests/test_ownership_backfill.py`` asserts the two are equal: the
#: duplication is checked by the suite, not by hope.
QUOTA_WINDOW_DAYS = 7

#: Version tag written into every manifest, so a future reader knows what shape
#: it is looking at before trusting the ``ids`` field.
MANIFEST_SCHEMA = "character_image_owner_backfill/1"

#: Where manifests are written. Git-ignored: a manifest describes one run
#: against one database at one moment, and a committed one would be mistaken
#: for a description of the current state.
DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parent / "ownership_backfill_manifests"

#: The reversal, recorded in the manifest so it does not have to be
#: reconstructed from memory. NEVER executed by this script.
ROLLBACK_SQL_TEMPLATE = (
    "UPDATE character_images SET user_id = NULL WHERE id IN (<manifest ids>);"
)


class BackfillAborted(RuntimeError):
    """A precondition or guard refused the run. Nothing was mutated.

    Carries the reasons as data rather than pre-formatted text so a caller (a
    test, or a future wrapper) can assert on them without parsing prose.
    """

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass
class QuotaImpact:
    """What the backfill would do to the live weekly image allowance."""

    #: Rows the backfill would write that fall inside the current window.
    #: Anything above zero is an abort: those rows would start counting against
    #: a real account's allowance the moment they gained an owner.
    rows_in_window: int
    #: owner_id -> images already counted against them inside the window.
    before: dict[int, int] = field(default_factory=dict)
    #: owner_id -> what that count would become after the backfill.
    after: dict[int, int] = field(default_factory=dict)

    @property
    def delta(self) -> int:
        """Total allowance movement across all accounts."""
        return sum(self.after.values()) - sum(self.before.values())


@dataclass
class BackfillResult:
    """Outcome of one run, in the shape the report needs."""

    eligible: int
    updated: int
    mutated: bool
    quota: QuotaImpact
    manifest_path: Path | None
    remaining_null: int
    disagreements: int


# ── Preconditions ────────────────────────────────────────────────────────────


def check_preconditions(conn: Connection) -> list[str]:
    """Return blocking reasons; an empty list means the rule is safe to apply.

    Each check is the negation of an assumption the backfill rule depends on.
    They are asserted at run time rather than trusted from an earlier
    inspection, because the inspection described a database as it was on one
    afternoon and this script mutates one as it is now.
    """
    reasons: list[str] = []

    disagreements = conn.execute(
        text(
            """
            SELECT count(*) FROM character_images ci
            JOIN characters c ON c.id = ci.character_id
            WHERE ci.user_id IS NOT NULL AND ci.user_id <> c.owner_id
            """
        )
    ).scalar_one()
    if disagreements:
        reasons.append(
            f"{disagreements} row(s) already carry a user_id that disagrees with "
            "characters.owner_id. The rule 'the owner of the character owns the "
            "image' is not lossless on this data — a human has to decide which "
            "of the two is right before anything is written."
        )

    orphans = conn.execute(
        text(
            """
            SELECT count(*) FROM character_images ci
            LEFT JOIN characters c ON c.id = ci.character_id
            WHERE c.id IS NULL
            """
        )
    ).scalar_one()
    if orphans:
        reasons.append(
            f"{orphans} row(s) point at a character that does not exist. Their "
            "owner cannot be derived, so the backfill would be partial and the "
            "postcondition 'zero NULL user_id' unreachable."
        )

    null_character = conn.execute(
        text("SELECT count(*) FROM character_images WHERE character_id IS NULL")
    ).scalar_one()
    if null_character:
        reasons.append(
            f"{null_character} row(s) have a NULL character_id. character_id is "
            "NOT NULL in this increment; a NULL means the schema is ahead of "
            "this script and the ownership rule needs revisiting first."
        )

    return reasons


def eligible_row_ids(conn: Connection) -> list[int]:
    """Ids of rows the backfill would write, in ascending order.

    Computed inside the same transaction as the update so the manifest cannot
    describe a different set of rows from the one that gets written.
    """
    rows = conn.execute(
        text(
            """
            SELECT ci.id
            FROM character_images ci
            JOIN characters c ON c.id = ci.character_id
            WHERE ci.user_id IS NULL
            ORDER BY ci.id
            """
        )
    ).all()
    return [int(r[0]) for r in rows]


# ── Quota guard ──────────────────────────────────────────────────────────────


def quota_impact(conn: Connection, *, now: datetime) -> QuotaImpact:
    """Measure what the backfill would do to the rolling image allowance.

    ``app.services.image_quota`` counts ``CharacterImage.user_id == user.id AND
    created_at >= now - 7 days``. Giving an owner-less row an owner therefore
    adds it to that account's used allowance — but only if it is inside the
    window. Outside the window a backfilled row is invisible to quota, which is
    why the guard measures the window rather than the whole table.

    The cutoff is computed from a naive UTC *now* and bound as a parameter,
    matching ``datetime.utcnow()`` in the service exactly. Using the database's
    ``now()`` would compare a timestamptz against the naive ``created_at``
    column and silently shift the boundary by the server's timezone.
    """
    cutoff = now - timedelta(days=QUOTA_WINDOW_DAYS)

    rows_in_window = conn.execute(
        text(
            """
            SELECT count(*)
            FROM character_images ci
            JOIN characters c ON c.id = ci.character_id
            WHERE ci.user_id IS NULL AND ci.created_at >= :cutoff
            """
        ),
        {"cutoff": cutoff},
    ).scalar_one()

    before = {
        int(owner): int(n)
        for owner, n in conn.execute(
            text(
                """
                SELECT user_id, count(*)
                FROM character_images
                WHERE user_id IS NOT NULL AND created_at >= :cutoff
                GROUP BY user_id
                """
            ),
            {"cutoff": cutoff},
        ).all()
    }

    added = {
        int(owner): int(n)
        for owner, n in conn.execute(
            text(
                """
                SELECT c.owner_id, count(*)
                FROM character_images ci
                JOIN characters c ON c.id = ci.character_id
                WHERE ci.user_id IS NULL AND ci.created_at >= :cutoff
                GROUP BY c.owner_id
                """
            ),
            {"cutoff": cutoff},
        ).all()
    }

    after = dict(before)
    for owner, n in added.items():
        after[owner] = after.get(owner, 0) + n

    return QuotaImpact(rows_in_window=int(rows_in_window), before=before, after=after)


# ── Manifest ─────────────────────────────────────────────────────────────────


def build_manifest(
    ids: Sequence[int], *, generated_at: datetime, classification: str
) -> dict:
    """The reversal record for one run.

    Contains only what reversing THIS backfill needs: the schema tag, when it
    ran, which database class it ran against, and the ids. No prompts, file
    paths, emails, usernames, connection strings or any other row content — a
    manifest is a rollback instrument, not an export.

    The target is recorded as a CLASSIFICATION ("DEV"), never a hostname, so a
    manifest is as safe to attach to a ticket as the console output is.
    """
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at.isoformat() + "Z",
        "database": classification,
        "operation": "character_images.user_id := characters.owner_id WHERE user_id IS NULL",
        "row_count": len(ids),
        "ids": list(ids),
        "rollback_sql": ROLLBACK_SQL_TEMPLATE,
        "rollback_note": (
            "Apply rollback_sql to EXACTLY the ids listed above and no others. "
            "Rows absent from this list either already had an owner before the "
            "run or were written afterwards; NULLing them would destroy data "
            "this backfill never touched."
        ),
    }


def write_manifest(manifest: dict, directory: Path, *, generated_at: datetime) -> Path:
    """Write *manifest* to *directory* and return the path.

    Called BEFORE the update is issued, so a crash between write and commit
    leaves a manifest describing rows that were never changed — harmless, since
    the reversal of an unapplied change is a no-op — rather than a mutation
    with no record of what it touched.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"backfill_character_image_owners_{stamp}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


# ── Mutation and postconditions ──────────────────────────────────────────────


def apply_backfill(conn: Connection) -> int:
    """Run the one statement this script exists for. Returns rows updated.

    ``user_id IS NULL`` in the WHERE clause is what makes the run idempotent
    and what stops it from overwriting an owner that is already recorded.
    """
    result = conn.execute(
        text(
            """
            UPDATE character_images AS ci
               SET user_id = c.owner_id
              FROM characters c
             WHERE c.id = ci.character_id
               AND ci.user_id IS NULL
            """
        )
    )
    return int(result.rowcount)


def check_postconditions(conn: Connection) -> tuple[int, int, list[str]]:
    """Return ``(remaining_null, disagreements, failures)`` after a write.

    Checked inside the transaction, so a failure rolls the update back rather
    than leaving a half-established invariant behind.
    """
    remaining_null = int(
        conn.execute(
            text("SELECT count(*) FROM character_images WHERE user_id IS NULL")
        ).scalar_one()
    )
    disagreements = int(
        conn.execute(
            text(
                """
                SELECT count(*) FROM character_images ci
                JOIN characters c ON c.id = ci.character_id
                WHERE ci.user_id IS NOT NULL AND ci.user_id <> c.owner_id
                """
            )
        ).scalar_one()
    )

    failures: list[str] = []
    if remaining_null:
        failures.append(
            f"{remaining_null} row(s) still have a NULL user_id after the update."
        )
    if disagreements:
        failures.append(
            f"{disagreements} row(s) disagree with characters.owner_id after the update."
        )
    return remaining_null, disagreements, failures


# ── Orchestration ────────────────────────────────────────────────────────────


def run(
    conn: Connection,
    *,
    mutate: bool,
    manifest_dir: Path,
    now: datetime,
    classification: str = DEV,
    emit: Callable[[str], None] = print,
) -> BackfillResult:
    """Preview or apply the backfill on *conn*. Raises on any refusal.

    Takes a connection rather than opening one, so the caller owns the
    transaction and the DEV guard sits in exactly one place (:func:`main`).
    """
    reasons = check_preconditions(conn)
    if reasons:
        raise BackfillAborted(reasons)

    ids = eligible_row_ids(conn)
    quota = quota_impact(conn, now=now)

    emit("── Ownership backfill ─────────────────────────")
    emit(f"  database                : {classification}")
    emit(f"  mode                    : {'APPLY' if mutate else 'DRY RUN'}")
    emit(f"  rows eligible           : {len(ids)}")
    emit("")
    emit("── Quota impact (rolling %d-day window) ────────" % QUOTA_WINDOW_DAYS)
    emit(f"  eligible rows in window : {quota.rows_in_window}")
    emit(f"  allowance delta         : {quota.delta}")
    _emit_quota_table(quota, emit)
    emit("")

    if quota.rows_in_window:
        raise BackfillAborted(
            [
                f"{quota.rows_in_window} eligible row(s) fall inside the live "
                f"{QUOTA_WINDOW_DAYS}-day quota window. Backfilling them would "
                "charge real accounts for generations they were never charged "
                "for, mid-week and without warning. That is a product decision, "
                "not a data fix — refusing rather than deciding it here."
            ]
        )

    if not ids:
        emit("Nothing to do — every row already carries an owner.")
        return BackfillResult(
            eligible=0,
            updated=0,
            mutated=False,
            quota=quota,
            manifest_path=None,
            remaining_null=0,
            disagreements=0,
        )

    if not mutate:
        emit("DRY RUN — no changes made. Re-run with --confirm to apply.")
        return BackfillResult(
            eligible=len(ids),
            updated=0,
            mutated=False,
            quota=quota,
            manifest_path=None,
            remaining_null=len(ids),
            disagreements=0,
        )

    # Manifest first: a record of what is about to change must exist before the
    # change does, or a failure between the two leaves an unreversible write.
    manifest_path = write_manifest(
        build_manifest(ids, generated_at=now, classification=classification),
        manifest_dir,
        generated_at=now,
    )
    emit(f"  rollback manifest       : {manifest_path}")

    updated = apply_backfill(conn)
    if updated != len(ids):
        raise BackfillAborted(
            [
                f"Update touched {updated} row(s) but {len(ids)} were eligible. "
                "The manifest would not describe the change. Rolling back."
            ]
        )

    remaining_null, disagreements, failures = check_postconditions(conn)
    if failures:
        raise BackfillAborted(failures)

    emit(f"  rows updated            : {updated}")
    emit(f"  user_id IS NULL         : {remaining_null}")
    emit(f"  owner disagreements     : {disagreements}")
    emit("✓ Backfill applied.")

    return BackfillResult(
        eligible=len(ids),
        updated=updated,
        mutated=True,
        quota=quota,
        manifest_path=manifest_path,
        remaining_null=remaining_null,
        disagreements=disagreements,
    )


def _emit_quota_table(quota: QuotaImpact, emit: Callable[[str], None]) -> None:
    """Per-owner before/after allowance counts. Account ids only, no identity."""
    owners: Iterable[int] = sorted(set(quota.before) | set(quota.after))
    if not owners:
        emit("  (no images inside the window for any account)")
        return
    emit("  owner_id    used now    used after")
    for owner in owners:
        emit(f"  {owner:<11} {quota.before.get(owner, 0):<11} {quota.after.get(owner, 0)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill character_images.user_id from characters.owner_id. "
            "DEV only. Preview by default."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only (default). Mutates nothing.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Apply the backfill. Required to mutate.",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=DEFAULT_MANIFEST_DIR,
        help="Where to write the rollback manifest (git-ignored).",
    )
    args = parser.parse_args(argv)

    if args.confirm and args.dry_run:
        print("REFUSED: pass either --dry-run or --confirm, not both.", file=sys.stderr)
        return 2
    mutate = args.confirm

    # Unconditional, and before anything opens a connection. There is no flag
    # that skips this and no production path that reuses it.
    url = assert_dev_database(
        purpose="to backfill character_images.user_id ownership"
    )

    # In preview mode the server itself refuses writes, so "dry run" is a
    # property of the connection rather than of an if-statement further down.
    connect_args = (
        {} if mutate else {"options": "-c default_transaction_read_only=on"}
    )
    engine = create_engine(
        url,
        future=True,
        connect_args=connect_args,
        # Names the connection in pg_stat_activity if it ever has to be found.
        pool_pre_ping=True,
    )

    now = datetime.utcnow()
    try:
        # One transaction: preconditions, eligibility, manifest, update and
        # postconditions all see the same snapshot, and any raise rolls the
        # whole thing back.
        with engine.begin() as conn:
            run(
                conn,
                mutate=mutate,
                manifest_dir=args.manifest_dir,
                now=now,
                classification=DEV,
            )
    except BackfillAborted as exc:
        print("── ABORTED — nothing was changed ──────────────", file=sys.stderr)
        for reason in exc.reasons:
            print(f"  ✗ {reason}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

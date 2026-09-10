"""Backfill ``character_images.user_id`` on a NON-DEV database.

The production counterpart to ``backfill_character_image_owners.py``, which
refuses every target that is not DEV and says so in its own docstring:

    Production execution is a separate, reviewable design; adding a bypass
    here would pre-empt it.

This file is that separate design. It exists because Phase 4B2 (``p4b02``)
cannot apply to a database that still holds pre-4B1 rows: ``f1a2b3c4d5e6``
added ``user_id`` nullable on 2026-02-28 and deliberately left every existing
row NULL, and nothing has attributed them since.

THE RULE IS NOT RE-DERIVED HERE
-------------------------------
:func:`apply_backfill` is IMPORTED from the DEV script rather than copied. It
is the one statement both paths exist to run::

    UPDATE character_images ci SET user_id = c.owner_id
      FROM characters c
     WHERE c.id = ci.character_id AND ci.user_id IS NULL

Copying it would create two ownership rules that agree today and diverge at the
first edit — the same failure ``scripts/assert_dev_db.py`` was written to
prevent for "which database is DEV?". The quota guard is imported for the same
reason. What this file adds is everything AROUND the statement: a richer
census, a target-bound acknowledgement, and a postflight that reconciles.

WHAT THIS FILE DOES NOT INHERIT, AND WHY
----------------------------------------
The DEV script's :func:`check_preconditions` aborts when ANY row carries a
``user_id`` that disagrees with ``characters.owner_id``. That is right for DEV,
where the column has only ever been written by current code. It is WRONG here.

Before Phase 4B1 the column meant "which account generated this, for the weekly
quota". A generation performed by an admin on someone else's character
therefore recorded the REQUESTER, and a production database a month old
legitimately contains such rows. They are real history, they are outside this
tool's mutation set (which touches ``user_id IS NULL`` only), and ``p4b02`` does
not care about them — it checks NULLs and nothing else.

So disagreements are COUNTED AND REPORTED here, never treated as a blocker.
Blocking on them would make production unbackfillable for a reason unrelated to
the migration it unblocks. The postflight instead asserts the count did not
MOVE: the backfill writes ``user_id := owner_id``, so it cannot manufacture a
disagreement, and any change in that number means something else wrote to the
table inside the transaction window.

FAIL CLOSED
-----------
* Preview is the default and opens a server-enforced read-only transaction.
* Mutation requires :data:`PRODUCTION_ACK_VAR` to hold a phrase that NAMES THE
  TARGET CLASSIFICATION. There is no ``--force``, no ``--yes``, and no flag that
  substitutes for it.
* Mutation is refused unless the census reconciles exactly AND every NULL row is
  deterministically attributable. A partial backfill is worse than none: it
  leaves ``p4b02`` still unappliable and the operator believing otherwise.
* An unclassifiable target is refused, not assumed safe.

INVOCATION
----------
Preview — mutates nothing, and the connection cannot mutate::

    python scripts/backfill_character_image_owners_production.py --dry-run

Apply — the acknowledgement is per-invocation and must not be exported::

    FICSHON_OWNERSHIP_BACKFILL_ACK='backfill-image-ownership-on-<CLASS>' \\
        python scripts/backfill_character_image_owners_production.py --apply

Run the preview first: it prints the classification, which is the half of the
phrase you cannot know in advance, and a refusal names the exact string.

IDEMPOTENCE
-----------
The update matches ``user_id IS NULL`` only. A second apply finds nothing
eligible, writes a receipt recording that, and reports "nothing to do".
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

# Repo root, derived from this file, so the sibling imports resolve wherever the
# checkout lives. Same convention as the DEV script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from scripts.assert_dev_db import DatabaseTargetError, classify_database_url

# THE OWNERSHIP RULE AND THE QUOTA GUARD, imported so the two paths cannot
# drift. See the module docstring.
from scripts.backfill_character_image_owners import (
    QUOTA_WINDOW_DAYS,
    BackfillAborted,
    QuotaImpact,
    apply_backfill,
    quota_impact,
)

#: Environment variable authorising MUTATION by this script.
#:
#: Distinct from ``FICSHON_MIGRATION_ACK`` and ``FICSHON_STARTUP_BOOTSTRAP_ACK``
#: in ``app.core.db_target``, and deliberately so: that module's own docstring
#: establishes the pattern — "a DIFFERENT variable and a DIFFERENT phrase
#: prefix, so the two cannot substitute for each other in either direction".
#: Authorising a migration must not also authorise a data rewrite.
PRODUCTION_ACK_VAR = "FICSHON_OWNERSHIP_BACKFILL_ACK"

#: Receipt schema tag. Distinct from the DEV manifest's
#: ``character_image_owner_backfill/1`` because the shape is a superset — a
#: reader must not mistake one for the other.
RECEIPT_SCHEMA = "character_image_owner_backfill_production/1"

#: Where receipts are written. Git-ignored, like the DEV manifests: a receipt
#: describes one run against one database at one moment, and a committed one
#: would be read as a description of the current state.
DEFAULT_RECEIPT_DIR = Path(__file__).resolve().parent / "ownership_backfill_manifests"

#: The reversal, recorded so it need not be reconstructed from memory. NEVER
#: executed by this script.
ROLLBACK_SQL_TEMPLATE = (
    "UPDATE character_images SET user_id = NULL WHERE id IN (<receipt ids>);"
)

_OPERATION = "character_images.user_id := characters.owner_id WHERE user_id IS NULL"


def ownership_backfill_ack_phrase(classification: str) -> str:
    """The exact value :data:`PRODUCTION_ACK_VAR` must hold for *classification*.

    The classification is EMBEDDED, so an acknowledgement minted for one target
    does not authorise another — a value left over from a run against a NEON
    target does not authorise a write to an UNKNOWN_EXTERNAL host that appeared
    afterwards.
    """
    return f"backfill-image-ownership-on-{classification}"


class AcknowledgementRequired(RuntimeError):
    """Mutation was requested without a valid target-bound acknowledgement.

    The message is safe to print, log and paste into a ticket: it names a
    classification, a variable and a phrase, never the URL, host, user or
    password.
    """


# ── Census ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OwnershipCensus:
    """Every number the go/no-go decision needs, taken in one snapshot.

    The four ``null_*``/``backfillable`` buckets are mutually exclusive and
    exhaustive over ``user_id IS NULL``, which is what makes
    :attr:`reconciles` a real check rather than a restatement.
    """

    #: Every row in the table. Pinned so the postflight can prove an UPDATE
    #: neither inserted nor deleted anything.
    total_rows: int
    #: Rows that already carry an owner.
    rows_with_owner: int
    #: Rows with no owner — the population this tool addresses.
    null_user_id_rows: int

    #: — the four buckets —
    #: No character to derive an owner from. Only reachable once ``p4c01`` has
    #: made ``character_id`` nullable; on a database awaiting ``p4b02`` this
    #: must be zero.
    also_null_character_id: int
    #: Points at a character id that no longer exists.
    missing_character: int
    #: Character exists but has no owner.
    character_missing_owner: int
    #: Character exists and has an owner — repairable by the rule.
    deterministically_backfillable: int

    #: Rows whose EXISTING owner disagrees with the character's owner. Reported,
    #: never a blocker — see the module docstring.
    owner_disagreements: int

    @property
    def unattributable(self) -> int:
        """NULL rows the rule cannot repair. Must be zero before any write."""
        return (
            self.also_null_character_id
            + self.missing_character
            + self.character_missing_owner
        )

    @property
    def reconciles(self) -> bool:
        """Do the four buckets account for every NULL row, exactly once?

        A False here means the buckets and the total were computed against
        different data — a concurrent write, or a bug in the SQL. Either way the
        census does not describe a database anybody should mutate.
        """
        return (
            self.unattributable + self.deterministically_backfillable
            == self.null_user_id_rows
        )

    @property
    def fully_attributable(self) -> bool:
        """Is every ownerless row repairable through ``characters.owner_id``?"""
        return self.reconciles and self.unattributable == 0


def take_census(conn: Connection) -> OwnershipCensus:
    """Measure the table. Reads only; safe inside a read-only transaction.

    One statement per number rather than one clever aggregate, because these
    counts are read by a human deciding whether to mutate production and each
    line has to be independently checkable against the query in the ticket.
    """

    def scalar(sql: str) -> int:
        return int(conn.execute(text(sql)).scalar_one())

    total_rows = scalar("SELECT count(*) FROM character_images")
    rows_with_owner = scalar(
        "SELECT count(*) FROM character_images WHERE user_id IS NOT NULL"
    )
    null_rows = scalar(
        "SELECT count(*) FROM character_images WHERE user_id IS NULL"
    )

    also_null_character_id = scalar(
        """
        SELECT count(*) FROM character_images
         WHERE user_id IS NULL AND character_id IS NULL
        """
    )
    missing_character = scalar(
        """
        SELECT count(*)
          FROM character_images ci
          LEFT JOIN characters c ON c.id = ci.character_id
         WHERE ci.user_id IS NULL
           AND ci.character_id IS NOT NULL
           AND c.id IS NULL
        """
    )
    character_missing_owner = scalar(
        """
        SELECT count(*)
          FROM character_images ci
          JOIN characters c ON c.id = ci.character_id
         WHERE ci.user_id IS NULL AND c.owner_id IS NULL
        """
    )
    backfillable = scalar(
        """
        SELECT count(*)
          FROM character_images ci
          JOIN characters c ON c.id = ci.character_id
         WHERE ci.user_id IS NULL AND c.owner_id IS NOT NULL
        """
    )
    disagreements = scalar(
        """
        SELECT count(*)
          FROM character_images ci
          JOIN characters c ON c.id = ci.character_id
         WHERE ci.user_id IS NOT NULL AND ci.user_id <> c.owner_id
        """
    )

    return OwnershipCensus(
        total_rows=total_rows,
        rows_with_owner=rows_with_owner,
        null_user_id_rows=null_rows,
        also_null_character_id=also_null_character_id,
        missing_character=missing_character,
        character_missing_owner=character_missing_owner,
        deterministically_backfillable=backfillable,
        owner_disagreements=disagreements,
    )


def eligible_row_ids(conn: Connection) -> list[int]:
    """Ids the rule will write, ascending.

    Computed in the same transaction as the update, so the receipt cannot
    describe a different row set from the one that gets written. The join
    condition mirrors :func:`apply_backfill` exactly — an id appears here if and
    only if that statement would touch it.
    """
    rows = conn.execute(
        text(
            """
            SELECT ci.id
              FROM character_images ci
              JOIN characters c ON c.id = ci.character_id
             WHERE ci.user_id IS NULL AND c.owner_id IS NOT NULL
             ORDER BY ci.id
            """
        )
    ).all()
    return [int(r[0]) for r in rows]


# ── Authorisation ────────────────────────────────────────────────────────────


def classify(url: Optional[str]) -> str:
    """Classification for *url*, or raise :class:`AcknowledgementRequired`.

    Fails CLOSED: a target the shared classifier cannot parse is not given a
    label that might later be matched by an acknowledgement phrase. It is
    refused outright, because a guard that cannot answer "which database is
    this?" must not answer "go ahead".
    """
    try:
        return classify_database_url(url)
    except DatabaseTargetError as exc:
        raise AcknowledgementRequired(
            f"Refusing to run: the database target could not be classified "
            f"({exc}). No acknowledgement can authorise an unidentified target."
        ) from None


def require_acknowledgement(
    classification: str, *, environ: Mapping[str, str]
) -> None:
    """Raise unless *environ* carries the phrase minted for *classification*.

    Read from the passed mapping — in production, ``os.environ`` — and never
    through ``app.core.config.Settings``, which is declared with
    ``env_file=".env"``. A value dropped in that dotenv file would silently
    authorise every future run on the checkout, which is precisely the
    "persists in the environment" failure the acknowledgement design exists to
    avoid. It must be supplied per invocation.

    NOTE that no classification is exempt, DEV included. This tool's whole
    purpose is writing to databases the DEV script refuses, so "safe target"
    is not a concept it should carry; the DEV script remains the right tool for
    DEV, and running this one there still requires saying so out loud.
    """
    expected = ownership_backfill_ack_phrase(classification)
    if environ.get(PRODUCTION_ACK_VAR) == expected:
        return
    raise AcknowledgementRequired(
        f"Refusing to mutate: database target classified {classification}. "
        f"To do this deliberately, set {PRODUCTION_ACK_VAR} to exactly "
        f"'{expected}' for this one invocation. Do not persist it in .env or a "
        f"shell profile. There is no --force. (Connection details withheld.)"
    )


# ── Receipt ──────────────────────────────────────────────────────────────────


def build_receipt(
    *,
    generated_at: datetime,
    classification: str,
    mode: str,
    state: str,
    preflight: OwnershipCensus,
    ids: Sequence[int] = (),
    rows_updated: Optional[int] = None,
    postflight: Optional[OwnershipCensus] = None,
    failure_reasons: Sequence[str] = (),
) -> dict:
    """The record of one run.

    Contains counts, ids, a classification and a state. It contains no
    connection string, hostname, role, email, username, file path, prompt or any
    other row content — a receipt is a rollback instrument and an audit note,
    not an export, and must be as safe to attach to a ticket as the console
    output is.
    """
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "generated_at": generated_at.isoformat() + "Z",
        "database": classification,
        "mode": mode,
        "state": state,
        "operation": _OPERATION,
        "preflight": asdict(preflight),
        "preflight_reconciles": preflight.reconciles,
        "preflight_unattributable": preflight.unattributable,
        "rows_updated": rows_updated,
        "row_count": len(ids),
        "ids": list(ids),
        "postflight": asdict(postflight) if postflight is not None else None,
        "failure_reasons": list(failure_reasons),
    }
    if ids:
        receipt["rollback_sql"] = ROLLBACK_SQL_TEMPLATE
        receipt["rollback_note"] = (
            "Apply rollback_sql to EXACTLY the ids listed above and no others. "
            "Rows absent from this list either already had an owner before the "
            "run or were written afterwards; NULLing them would destroy data "
            "this backfill never touched."
        )
    return receipt


def write_receipt(receipt: dict, directory: Path, *, generated_at: datetime) -> Path:
    """Write *receipt* into *directory*, returning the path.

    The filename is derived from *generated_at* alone, so the pending receipt
    written before the update and the final one written after the commit land on
    the SAME path — the second overwrites the first in place rather than
    leaving two files a reader has to reconcile.

    MICROSECONDS ARE IN THE STAMP, and they are not decoration. ``now`` is
    captured once per invocation, so pending and applied still agree; but two
    SEPARATE invocations inside the same second would otherwise collide, and the
    second one wins. That is not hypothetical — a re-run immediately after an
    apply is the normal way to confirm idempotence, and at second precision its
    "noop" receipt lands on the applied receipt's path and destroys the only
    record of which rows were written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%dT%H%M%S_%fZ")
    path = directory / f"production_backfill_character_image_owners_{stamp}.json"
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return path


# ── Postflight ───────────────────────────────────────────────────────────────


def check_postflight(
    before: OwnershipCensus, after: OwnershipCensus, updated: int
) -> list[str]:
    """Return failures; empty means the write is exactly what was promised.

    Run INSIDE the transaction, so any failure rolls the update back rather
    than leaving a half-established invariant behind. Five independent
    assertions, because each catches a different way for this to have gone
    wrong and a single aggregate check would let the others hide.
    """
    failures: list[str] = []

    if after.null_user_id_rows != 0:
        failures.append(
            f"{after.null_user_id_rows} row(s) still have a NULL user_id after "
            "the update. p4b02 would still refuse; rolling back."
        )

    if after.total_rows != before.total_rows:
        failures.append(
            f"character_images row count moved from {before.total_rows} to "
            f"{after.total_rows}. An UPDATE must neither insert nor delete; "
            "something else wrote to this table. Rolling back."
        )

    expected_owned = before.rows_with_owner + updated
    if after.rows_with_owner != expected_owned:
        failures.append(
            f"Rows with an owner went to {after.rows_with_owner}, expected "
            f"{expected_owned} ({before.rows_with_owner} + {updated} updated). "
            "Ownership counts do not reconcile; rolling back."
        )

    if updated != before.deterministically_backfillable:
        failures.append(
            f"Update touched {updated} row(s) but "
            f"{before.deterministically_backfillable} were attributable. The "
            "receipt would not describe the change; rolling back."
        )

    if after.owner_disagreements != before.owner_disagreements:
        failures.append(
            f"Owner disagreements moved from {before.owner_disagreements} to "
            f"{after.owner_disagreements}. This backfill writes "
            "user_id := owner_id and cannot create one, so the table changed "
            "underneath the transaction. Rolling back."
        )

    return failures


# ── Orchestration ────────────────────────────────────────────────────────────


@dataclass
class ProductionBackfillResult:
    """Outcome of one run, in the shape the report and the tests need."""

    classification: str
    mutated: bool
    census: OwnershipCensus
    eligible: int
    updated: int
    receipt_path: Optional[Path]
    postflight: Optional[OwnershipCensus]
    quota: QuotaImpact
    #: The rows this run wrote, ascending. Carried so ``main`` can promote the
    #: pending receipt to "applied" after the commit without re-querying a
    #: connection that is, by then, closed.
    ids: tuple[int, ...] = ()


def run(
    conn: Connection,
    *,
    mutate: bool,
    classification: str,
    receipt_dir: Path,
    now: datetime,
    environ: Mapping[str, str],
    emit: Callable[[str], None] = print,
) -> ProductionBackfillResult:
    """Preview or apply on *conn*. Raises on any refusal; never partially applies.

    Takes a connection rather than opening one, so the caller owns the
    transaction and the target guard sits in exactly one place (:func:`main`).
    """
    census = take_census(conn)
    quota = quota_impact(conn, now=now)

    emit("── Ownership backfill (production-capable) ─────")
    emit(f"  database                     : {classification}")
    emit(f"  mode                         : {'APPLY' if mutate else 'DRY RUN'}")
    emit("")
    emit("── Census ─────────────────────────────────────")
    emit(f"  total rows                   : {census.total_rows}")
    emit(f"  rows with an owner           : {census.rows_with_owner}")
    emit(f"  NULL user_id rows            : {census.null_user_id_rows}")
    emit(f"    ├─ NULL character_id       : {census.also_null_character_id}")
    emit(f"    ├─ character missing       : {census.missing_character}")
    emit(f"    ├─ character has no owner  : {census.character_missing_owner}")
    emit(f"    └─ backfillable            : {census.deterministically_backfillable}")
    emit(f"  unattributable               : {census.unattributable}")
    emit(f"  buckets reconcile            : {'yes' if census.reconciles else 'NO'}")
    emit(f"  owner disagreements (FYI)    : {census.owner_disagreements}")
    emit("")

    if census.owner_disagreements:
        emit(
            f"  NOTE: {census.owner_disagreements} row(s) already carry a "
            "user_id that differs from their character's owner. Those rows are "
            "NOT touched by this tool and do not block p4b02. Pre-4B1 the "
            "column recorded the generation requester, so this is expected "
            "history on an old database."
        )
        emit("")

    if not census.reconciles:
        raise BackfillAborted(
            [
                f"Census does not reconcile: {census.unattributable} "
                f"unattributable + {census.deterministically_backfillable} "
                f"backfillable != {census.null_user_id_rows} NULL rows. The "
                "counts were taken against a moving table or the SQL is wrong. "
                "Refusing to mutate on a census nobody can trust."
            ]
        )

    if census.unattributable:
        raise BackfillAborted(
            [
                f"{census.unattributable} ownerless row(s) cannot be attributed "
                "through characters.owner_id "
                f"(NULL character_id: {census.also_null_character_id}, "
                f"missing character: {census.missing_character}, "
                f"character without owner: {census.character_missing_owner}). "
                "A partial backfill leaves p4b02 unappliable while looking like "
                "progress. Who owns these rows is a product decision and has to "
                "be answered before anything is written."
            ]
        )

    # The same guard the DEV script applies, for the same reason — and this is
    # the database where it actually protects someone. Giving an ownerless row
    # an owner adds it to that account's rolling allowance; inside the window
    # that charges a real person for a generation they were never charged for.
    if quota.rows_in_window:
        raise BackfillAborted(
            [
                f"{quota.rows_in_window} eligible row(s) fall inside the live "
                f"{QUOTA_WINDOW_DAYS}-day quota window. Backfilling them would "
                "charge real accounts mid-week for generations they were never "
                "charged for. That is a product decision, not a data fix."
            ]
        )

    ids = eligible_row_ids(conn)
    if len(ids) != census.deterministically_backfillable:
        raise BackfillAborted(
            [
                f"Eligible id list holds {len(ids)} row(s) but the census "
                f"counted {census.deterministically_backfillable}. The two "
                "disagree, so the receipt could not describe the write."
            ]
        )

    if not mutate:
        emit("DRY RUN — no changes made, and the connection was read-only.")
        receipt_path = write_receipt(
            build_receipt(
                generated_at=now,
                classification=classification,
                mode="dry_run",
                state="preview",
                preflight=census,
                ids=ids,
            ),
            receipt_dir,
            generated_at=now,
        )
        emit(f"  receipt                      : {receipt_path}")
        return ProductionBackfillResult(
            classification=classification,
            mutated=False,
            census=census,
            eligible=len(ids),
            updated=0,
            receipt_path=receipt_path,
            postflight=None,
            quota=quota,
            ids=tuple(ids),
        )

    # Checked here rather than in main() so that no caller — including a future
    # wrapper or a test — can reach the update without passing it.
    require_acknowledgement(classification, environ=environ)

    if not ids:
        emit("Nothing to do — every row already carries an owner.")
        receipt_path = write_receipt(
            build_receipt(
                generated_at=now,
                classification=classification,
                mode="apply",
                state="noop",
                preflight=census,
                rows_updated=0,
                postflight=census,
            ),
            receipt_dir,
            generated_at=now,
        )
        emit(f"  receipt                      : {receipt_path}")
        return ProductionBackfillResult(
            classification=classification,
            mutated=False,
            census=census,
            eligible=0,
            updated=0,
            receipt_path=receipt_path,
            postflight=census,
            quota=quota,
            ids=(),
        )

    # Receipt first, state "pending": a record of what is about to change must
    # exist before the change does. A crash between this line and the commit
    # leaves a receipt describing rows that were never written — harmless, since
    # reversing an unapplied change is a no-op — rather than a mutation with no
    # record of what it touched.
    receipt_path = write_receipt(
        build_receipt(
            generated_at=now,
            classification=classification,
            mode="apply",
            state="pending",
            preflight=census,
            ids=ids,
        ),
        receipt_dir,
        generated_at=now,
    )
    emit(f"  receipt (pending)            : {receipt_path}")

    updated = apply_backfill(conn)
    after = take_census(conn)
    failures = check_postflight(census, after, updated)
    if failures:
        # Rewritten before the raise, so the file on disk records the refusal
        # even though the caller's context manager is about to roll back.
        write_receipt(
            build_receipt(
                generated_at=now,
                classification=classification,
                mode="apply",
                state="aborted",
                preflight=census,
                ids=ids,
                rows_updated=updated,
                postflight=after,
                failure_reasons=failures,
            ),
            receipt_dir,
            generated_at=now,
        )
        raise BackfillAborted(failures)

    emit(f"  rows updated                 : {updated}")
    emit(f"  user_id IS NULL (after)      : {after.null_user_id_rows}")
    emit(f"  rows with an owner (after)   : {after.rows_with_owner}")
    emit(f"  total rows (unchanged)       : {after.total_rows}")
    emit("✓ Backfill verified inside the transaction; committing.")

    return ProductionBackfillResult(
        classification=classification,
        mutated=True,
        census=census,
        eligible=len(ids),
        updated=updated,
        receipt_path=receipt_path,
        postflight=after,
        quota=quota,
        ids=tuple(ids),
    )


def _is_postgres(url: str) -> bool:
    """True when *url* names PostgreSQL, ``+driver`` suffixes included."""
    try:
        scheme = urlparse(url).scheme
    except ValueError:
        return False
    return scheme.split("+", 1)[0].lower() in {"postgres", "postgresql"}


def main(argv: Sequence[str] | None = None) -> int:
    import os

    parser = argparse.ArgumentParser(
        description=(
            "Backfill character_images.user_id from characters.owner_id on a "
            "non-DEV database. Preview by default; mutation requires a "
            "target-bound acknowledgement."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only (default). Mutates nothing.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply the backfill. Also requires "
            f"{PRODUCTION_ACK_VAR}=backfill-image-ownership-on-<CLASSIFICATION>."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Target URL. Defaults to DATABASE_URL. Supplied explicitly so the "
            "production run does not depend on whatever the environment names."
        ),
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=DEFAULT_RECEIPT_DIR,
        help="Where to write the run receipt (git-ignored).",
    )
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        print("REFUSED: pass either --dry-run or --apply, not both.", file=sys.stderr)
        return 2
    mutate = args.apply

    url = args.database_url or os.environ.get("DATABASE_URL")

    try:
        classification = classify(url)
    except AcknowledgementRequired as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    # Fail before opening a connection, so an unauthorised apply never reaches
    # the database at all.
    if mutate:
        try:
            require_acknowledgement(classification, environ=os.environ)
        except AcknowledgementRequired as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1

    # In preview the SERVER refuses writes, so "dry run" is a property of the
    # connection rather than of an if-statement further down. Postgres only:
    # the option is not valid on other backends, and this flag is the reason
    # the scheme is inspected at all.
    connect_args = {}
    if not mutate and _is_postgres(url or ""):
        connect_args = {"options": "-c default_transaction_read_only=on"}

    engine = create_engine(
        url, future=True, connect_args=connect_args, pool_pre_ping=True
    )

    now = datetime.utcnow()
    try:
        # One transaction: census, eligibility, receipt, update and postflight
        # all see the same snapshot, and any raise rolls the whole thing back.
        with engine.begin() as conn:
            result = run(
                conn,
                mutate=mutate,
                classification=classification,
                receipt_dir=args.receipt_dir,
                now=now,
                environ=os.environ,
            )

        # Reached only after the transaction COMMITTED. The receipt has said
        # "pending" since before the update; promoting it here is what makes the
        # difference between "we intended this" and "this is durable" visible on
        # disk. A crash between the commit and this line leaves "pending" — the
        # honest state to investigate, and never a file claiming a success that
        # did not happen.
        if result.mutated:
            final = write_receipt(
                build_receipt(
                    generated_at=now,
                    classification=classification,
                    mode="apply",
                    state="applied",
                    preflight=result.census,
                    ids=result.ids,
                    rows_updated=result.updated,
                    postflight=result.postflight,
                ),
                args.receipt_dir,
                generated_at=now,
            )
            print(f"  receipt (applied)            : {final}")
    except AcknowledgementRequired as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
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

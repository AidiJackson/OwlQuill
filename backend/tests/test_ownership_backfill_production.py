"""Tests for scripts/backfill_character_image_owners_production.py.

The production counterpart mutates a database the DEV script refuses to touch,
so the parts worth testing are the ones that decide WHETHER to mutate and the
ones that prove the mutation was exactly what was promised: the census and its
reconciliation, the target-bound acknowledgement, the attributability gate, the
postflight, the rollback, and the receipt.

The connection is passed in rather than opened, so every test here drives the
real code path with no patched-out guard — the only thing a test supplies that
production does not is the environment mapping holding the acknowledgement.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# The tools live in the repo-root scripts/ tree, beside the guard they call.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import backfill_character_image_owners as dev_backfill
from scripts import backfill_character_image_owners_production as prod
from scripts.assert_dev_db import DEV, NEON, UNKNOWN_EXTERNAL

from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User


NOW = datetime(2026, 9, 10, 12, 0, 0)

#: Old enough to sit outside the rolling quota window in every test. The
#: production rows this tool exists for are historical by construction.
ANCIENT = 400


@pytest.fixture()
def engine(tmp_path):
    """A throwaway database carrying the schema as it was BEFORE p4b02.

    ``character_images.user_id`` and ``characters.owner_id`` are both created
    nullable. The whole purpose of this tool is to fill in NULL owners and to
    REFUSE when a character has none, so its tests have to be able to create
    both states — NOT NULL is what the tool makes reachable, not what it runs
    against.

    Both model columns are restored immediately, so nothing outside this
    fixture sees the relaxed definitions.
    """
    eng = create_engine(f"sqlite:///{tmp_path / 'prod_backfill.db'}", future=True)
    image_user_id = CharacterImage.__table__.c.user_id
    character_owner_id = Character.__table__.c.owner_id
    image_user_id.nullable = True
    character_owner_id.nullable = True
    try:
        Base.metadata.create_all(bind=eng)
    finally:
        image_user_id.nullable = False
        character_owner_id.nullable = False
    yield eng
    eng.dispose()


def _seed(engine, images, *, characters=2, ownerless_character=False):
    """Create accounts, characters and images.

    ``images`` is a list of ``(character_index_or_None, user_id_or_None,
    age_days)``. A ``character_index`` of ``-1`` means "a character id that does
    not exist". Returns ``(user_ids, character_ids, image_ids)``.
    """
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    try:
        users, chars = [], []
        for i in range(characters):
            u = User(
                email=f"owner{i}@test.local",
                username=f"owner{i}",
                hashed_password="x",
            )
            db.add(u)
            db.flush()
            owner_id = None if (ownerless_character and i == 0) else u.id
            c = Character(owner_id=owner_id, name=f"Char {i}")
            db.add(c)
            db.flush()
            users.append(u.id)
            chars.append(c.id)

        image_ids = []
        for char_index, user_id, age_days in images:
            if char_index is None:
                character_id = None
            elif char_index == -1:
                character_id = 9_999_999  # deliberately dangling
            else:
                character_id = chars[char_index]
            img = CharacterImage(
                character_id=character_id,
                user_id=user_id,
                kind=ImageKindEnum.GENERATED,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                file_path=f"static/generated/{len(image_ids)}.png",
                created_at=NOW - timedelta(days=age_days),
            )
            db.add(img)
            db.flush()
            image_ids.append(img.id)
        db.commit()
        return users, chars, image_ids
    finally:
        db.close()


def _null_count(engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM character_images WHERE user_id IS NULL")
            ).scalar_one()
        )


def _run(engine, *, mutate, receipt_dir, environ=None, classification=UNKNOWN_EXTERNAL):
    """Drive ``run`` inside a real transaction, exactly as ``main`` does."""
    with engine.begin() as conn:
        return prod.run(
            conn,
            mutate=mutate,
            classification=classification,
            receipt_dir=receipt_dir,
            now=NOW,
            environ={} if environ is None else environ,
            emit=lambda _line: None,
        )


def _ack(classification=UNKNOWN_EXTERNAL):
    return {prod.PRODUCTION_ACK_VAR: prod.ownership_backfill_ack_phrase(classification)}


# ── The rule is shared, not copied ───────────────────────────────────────────


def test_ownership_rule_is_the_dev_script_s_own_statement():
    """The production path must not carry a second copy of the rule.

    Two ownership rules would agree today and diverge at the first edit. This
    asserts identity, not equivalence: the imported function IS the DEV one.
    """
    assert prod.apply_backfill is dev_backfill.apply_backfill
    assert prod.quota_impact is dev_backfill.quota_impact
    assert prod.QUOTA_WINDOW_DAYS == dev_backfill.QUOTA_WINDOW_DAYS


# ── Census and reconciliation ────────────────────────────────────────────────


def test_census_buckets_are_exclusive_and_exhaustive(engine):
    """Every NULL row lands in exactly one bucket, and they sum to the total."""
    _seed(
        engine,
        [
            (0, None, ANCIENT),   # backfillable
            (1, None, ANCIENT),   # backfillable
            (None, None, ANCIENT),  # NULL character_id
            (-1, None, ANCIENT),  # dangling character
            (0, 1, ANCIENT),      # already owned
        ],
    )
    with engine.connect() as conn:
        census = prod.take_census(conn)

    assert census.null_user_id_rows == 4
    assert census.deterministically_backfillable == 2
    assert census.also_null_character_id == 1
    assert census.missing_character == 1
    assert census.character_missing_owner == 0
    assert census.unattributable == 2
    assert census.reconciles is True
    assert census.fully_attributable is False
    assert census.total_rows == 5
    assert census.rows_with_owner == 1


def test_census_counts_a_character_without_an_owner(engine):
    """An ownerless character makes its images unattributable, not backfillable."""
    _seed(engine, [(0, None, ANCIENT), (1, None, ANCIENT)], ownerless_character=True)
    with engine.connect() as conn:
        census = prod.take_census(conn)

    assert census.character_missing_owner == 1
    assert census.deterministically_backfillable == 1
    assert census.reconciles is True
    assert census.fully_attributable is False


# ── Dry run ──────────────────────────────────────────────────────────────────


def test_dry_run_reports_and_writes_nothing(engine, tmp_path):
    """Preview succeeds on clean data, mutates nothing, and leaves a receipt."""
    _seed(engine, [(0, None, ANCIENT), (1, None, ANCIENT), (0, 1, ANCIENT)])

    result = _run(engine, mutate=False, receipt_dir=tmp_path)

    assert result.mutated is False
    assert result.eligible == 2
    assert result.updated == 0
    assert result.census.fully_attributable is True
    assert _null_count(engine) == 2  # untouched

    receipt = json.loads(result.receipt_path.read_text())
    assert receipt["mode"] == "dry_run"
    assert receipt["state"] == "preview"
    assert receipt["rows_updated"] is None


def test_dry_run_needs_no_acknowledgement(engine, tmp_path):
    """Reading is not mutating; an empty environment must still preview."""
    _seed(engine, [(0, None, ANCIENT)])
    result = _run(engine, mutate=False, receipt_dir=tmp_path, environ={})
    assert result.mutated is False


def test_dry_run_refuses_when_rows_are_unattributable(engine, tmp_path):
    """A partial backfill looks like progress and leaves p4b02 unappliable."""
    _seed(engine, [(0, None, ANCIENT), (-1, None, ANCIENT)])

    with pytest.raises(dev_backfill.BackfillAborted) as exc:
        _run(engine, mutate=False, receipt_dir=tmp_path)

    assert "cannot be attributed" in str(exc.value)
    assert _null_count(engine) == 2


def test_dry_run_refuses_on_a_null_character_id(engine, tmp_path):
    """Post-p4c01 rows with no character have no derivable owner."""
    _seed(engine, [(None, None, ANCIENT)])

    with pytest.raises(dev_backfill.BackfillAborted) as exc:
        _run(engine, mutate=False, receipt_dir=tmp_path)

    assert "NULL character_id: 1" in str(exc.value)


def test_dry_run_refuses_when_a_character_has_no_owner(engine, tmp_path):
    """Ownership cannot be invented for a character that has none."""
    _seed(engine, [(0, None, ANCIENT)], ownerless_character=True)

    with pytest.raises(dev_backfill.BackfillAborted) as exc:
        _run(engine, mutate=False, receipt_dir=tmp_path)

    assert "character without owner: 1" in str(exc.value)


def test_rows_inside_the_quota_window_abort_the_run(engine, tmp_path):
    """Backfilling a recent row charges a real account for it, mid-week."""
    _seed(engine, [(0, None, 1)])

    with pytest.raises(dev_backfill.BackfillAborted) as exc:
        _run(engine, mutate=False, receipt_dir=tmp_path)

    assert "quota window" in str(exc.value)


# ── Acknowledgement ──────────────────────────────────────────────────────────


def test_mutation_without_acknowledgement_is_refused(engine, tmp_path):
    """No environment variable, no write. There is no --force to fall back on."""
    _seed(engine, [(0, None, ANCIENT)])

    with pytest.raises(prod.AcknowledgementRequired) as exc:
        _run(engine, mutate=True, receipt_dir=tmp_path, environ={})

    assert prod.PRODUCTION_ACK_VAR in str(exc.value)
    assert _null_count(engine) == 1


def test_acknowledgement_for_another_target_does_not_authorise_this_one(
    engine, tmp_path
):
    """The phrase names its target, so a leftover value cannot be reused."""
    _seed(engine, [(0, None, ANCIENT)])

    with pytest.raises(prod.AcknowledgementRequired):
        _run(
            engine,
            mutate=True,
            receipt_dir=tmp_path,
            environ=_ack(DEV),
            classification=UNKNOWN_EXTERNAL,
        )

    assert _null_count(engine) == 1


def test_migration_acknowledgement_does_not_authorise_a_data_rewrite(engine, tmp_path):
    """Authorising a schema migration must not also authorise rewriting rows."""
    _seed(engine, [(0, None, ANCIENT)])

    with pytest.raises(prod.AcknowledgementRequired):
        _run(
            engine,
            mutate=True,
            receipt_dir=tmp_path,
            environ={"FICSHON_MIGRATION_ACK": f"run-migrations-on-{UNKNOWN_EXTERNAL}"},
        )

    assert _null_count(engine) == 1


def test_no_classification_is_exempt_from_the_acknowledgement(engine, tmp_path):
    """Even DEV must be named out loud — the DEV script is the tool for DEV."""
    _seed(engine, [(0, None, ANCIENT)])

    with pytest.raises(prod.AcknowledgementRequired):
        _run(engine, mutate=True, receipt_dir=tmp_path, environ={}, classification=DEV)


def test_acknowledgement_phrase_embeds_the_classification():
    phrases = {
        prod.ownership_backfill_ack_phrase(label)
        for label in (DEV, NEON, UNKNOWN_EXTERNAL)
    }
    assert len(phrases) == 3
    assert prod.ownership_backfill_ack_phrase(NEON) == "backfill-image-ownership-on-NEON"


# ── Target classification safeguards ─────────────────────────────────────────


def test_unclassifiable_target_is_refused_outright():
    """A guard that cannot say which database this is must not say 'go ahead'."""
    for url in (None, "", "not-a-url", "postgresql://"):
        with pytest.raises(prod.AcknowledgementRequired):
            prod.classify(url)


def test_classification_labels_come_from_the_shared_guard():
    """No second host classifier lives in this file."""
    assert prod.classify("postgresql://u:p@helium/app") == DEV
    assert prod.classify("postgresql://u:p@ep-x.neon.tech/app") == NEON
    assert prod.classify("postgresql://u:p@some-prod-host.example.com/app") == (
        UNKNOWN_EXTERNAL
    )


def test_the_ack_variable_is_distinct_from_the_migration_and_bootstrap_ones():
    from app.core import db_target

    assert prod.PRODUCTION_ACK_VAR != db_target.MIGRATION_ACK_VAR
    assert prod.PRODUCTION_ACK_VAR != db_target.STARTUP_BOOTSTRAP_ACK_VAR
    # And the phrases cannot collide either, in either direction.
    assert prod.ownership_backfill_ack_phrase(DEV) != db_target.migration_ack_phrase(DEV)
    assert prod.ownership_backfill_ack_phrase(
        DEV
    ) != db_target.startup_bootstrap_ack_phrase(DEV)


# ── The successful path ──────────────────────────────────────────────────────


def test_deterministic_backfill_applies_and_verifies(engine, tmp_path):
    """The whole point: every ownerless row gains its character's owner."""
    users, chars, image_ids = _seed(
        engine,
        [(0, None, ANCIENT), (1, None, ANCIENT), (0, None, ANCIENT), (1, 2, ANCIENT)],
    )

    result = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    assert result.mutated is True
    assert result.updated == 3
    assert _null_count(engine) == 0
    assert result.postflight.null_user_id_rows == 0
    assert result.postflight.total_rows == result.census.total_rows
    assert result.postflight.rows_with_owner == result.census.rows_with_owner + 3

    # Ownership actually follows the character, rather than merely being non-NULL.
    with engine.connect() as conn:
        pairs = conn.execute(
            text(
                "SELECT ci.user_id, c.owner_id FROM character_images ci "
                "JOIN characters c ON c.id = ci.character_id WHERE ci.id IN "
                f"({','.join(str(i) for i in image_ids[:3])})"
            )
        ).all()
    assert all(user_id == owner_id for user_id, owner_id in pairs)


def test_a_second_apply_is_a_no_op(engine, tmp_path):
    """Idempotence: the WHERE clause matches nothing the second time."""
    _seed(engine, [(0, None, ANCIENT)])
    _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    second = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())
    assert second.updated == 0
    assert second.mutated is False
    assert json.loads(second.receipt_path.read_text())["state"] == "noop"


def test_rows_that_already_have_an_owner_are_never_rewritten(engine, tmp_path):
    """A disagreeing owner is history, not a target. It must survive untouched."""
    users, chars, image_ids = _seed(engine, [(0, None, ANCIENT), (0, 2, ANCIENT)])

    _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    with engine.connect() as conn:
        preserved = conn.execute(
            text("SELECT user_id FROM character_images WHERE id = :i"),
            {"i": image_ids[1]},
        ).scalar_one()
    assert preserved == 2  # still the requester, not the character's owner


def test_pre_existing_disagreements_do_not_block_the_run(engine, tmp_path):
    """Unlike the DEV script, which is right to refuse them and wrong for prod."""
    _seed(engine, [(0, None, ANCIENT), (0, 2, ANCIENT)])

    with engine.connect() as conn:
        assert prod.take_census(conn).owner_disagreements == 1

    result = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())
    assert result.updated == 1
    assert _null_count(engine) == 0


# ── Postflight and rollback ──────────────────────────────────────────────────


def test_postflight_rejects_a_partial_update():
    before = prod.OwnershipCensus(
        total_rows=10,
        rows_with_owner=7,
        null_user_id_rows=3,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=3,
        owner_disagreements=0,
    )
    after = prod.OwnershipCensus(
        total_rows=10,
        rows_with_owner=8,
        null_user_id_rows=2,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=2,
        owner_disagreements=0,
    )
    failures = prod.check_postflight(before, after, updated=1)
    # Two independent alarms, which is the point of keeping the checks separate:
    # the rows that were missed, and the receipt that would misdescribe the run.
    assert any("still have a NULL user_id" in f for f in failures)
    assert any("were attributable" in f for f in failures)


def test_postflight_rejects_a_changed_row_count():
    census = prod.OwnershipCensus(
        total_rows=10,
        rows_with_owner=7,
        null_user_id_rows=3,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=3,
        owner_disagreements=0,
    )
    after = prod.OwnershipCensus(
        total_rows=11,
        rows_with_owner=10,
        null_user_id_rows=0,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=0,
        owner_disagreements=0,
    )
    failures = prod.check_postflight(census, after, updated=3)
    assert any("row count moved" in f for f in failures)


def test_postflight_rejects_a_moved_disagreement_count():
    before = prod.OwnershipCensus(
        total_rows=4,
        rows_with_owner=2,
        null_user_id_rows=2,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=2,
        owner_disagreements=1,
    )
    after = prod.OwnershipCensus(
        total_rows=4,
        rows_with_owner=4,
        null_user_id_rows=0,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=0,
        owner_disagreements=2,
    )
    failures = prod.check_postflight(before, after, updated=2)
    assert any("disagreements moved" in f for f in failures)


def test_postflight_accepts_the_expected_write():
    before = prod.OwnershipCensus(
        total_rows=5,
        rows_with_owner=2,
        null_user_id_rows=3,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=3,
        owner_disagreements=1,
    )
    after = prod.OwnershipCensus(
        total_rows=5,
        rows_with_owner=5,
        null_user_id_rows=0,
        also_null_character_id=0,
        missing_character=0,
        character_missing_owner=0,
        deterministically_backfillable=0,
        owner_disagreements=1,
    )
    assert prod.check_postflight(before, after, updated=3) == []


def test_a_failed_postflight_rolls_the_whole_update_back(engine, tmp_path, monkeypatch):
    """The write and its verification share one transaction, or neither holds.

    A partial UPDATE is simulated at the one seam where it could really happen —
    the statement itself — so the rollback under test is the production path's,
    not a contrived exception.
    """
    _seed(engine, [(0, None, ANCIENT), (1, None, ANCIENT), (0, None, ANCIENT)])

    def partial_update(conn):
        conn.execute(
            text(
                "UPDATE character_images SET user_id = ("
                "  SELECT c.owner_id FROM characters c WHERE c.id = character_id"
                ") WHERE user_id IS NULL AND id = ("
                "  SELECT min(id) FROM character_images WHERE user_id IS NULL)"
            )
        )
        return 1  # claims one row; three were eligible

    monkeypatch.setattr(prod, "apply_backfill", partial_update)

    with pytest.raises(dev_backfill.BackfillAborted):
        _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    # Rolled back: all three rows are ownerless again, including the one written.
    assert _null_count(engine) == 3


def test_an_aborted_run_leaves_a_failure_receipt(engine, tmp_path, monkeypatch):
    """The refusal is on disk even though the transaction is gone."""
    _seed(engine, [(0, None, ANCIENT), (1, None, ANCIENT)])
    monkeypatch.setattr(prod, "apply_backfill", lambda conn: 0)

    with pytest.raises(dev_backfill.BackfillAborted):
        _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    receipts = list(tmp_path.glob("production_backfill_*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt["state"] == "aborted"
    assert receipt["failure_reasons"]


# ── Receipt ──────────────────────────────────────────────────────────────────


def test_receipt_records_the_run_exactly(engine, tmp_path):
    users, chars, image_ids = _seed(
        engine, [(0, None, ANCIENT), (1, None, ANCIENT), (0, 1, ANCIENT)]
    )

    result = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())
    receipt = json.loads(result.receipt_path.read_text())

    assert receipt["schema"] == prod.RECEIPT_SCHEMA
    assert receipt["database"] == UNKNOWN_EXTERNAL
    assert receipt["mode"] == "apply"
    assert receipt["state"] == "pending"  # rewritten to applied by main(), post-commit
    assert receipt["generated_at"].startswith("2026-09-10T12:00:00")
    assert receipt["ids"] == sorted(image_ids[:2])
    assert receipt["row_count"] == 2
    assert receipt["preflight"]["null_user_id_rows"] == 2
    assert receipt["preflight_reconciles"] is True
    assert receipt["preflight_unattributable"] == 0
    assert "rollback_sql" in receipt


def test_receipt_names_a_classification_and_never_a_connection_string(engine, tmp_path):
    """Safe to paste into a ticket: labels and counts, no host, user or password."""
    _seed(engine, [(0, None, ANCIENT)])
    result = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())

    raw = result.receipt_path.read_text()
    lowered = raw.lower()
    for forbidden in ("postgres://", "postgresql://", "password", "@", "helium", "neon"):
        assert forbidden not in lowered

    # What it DOES carry is the classification label, and only that.
    assert json.loads(raw)["database"] == UNKNOWN_EXTERNAL


def test_a_rerun_in_the_same_second_does_not_overwrite_the_applied_receipt(
    engine, tmp_path
):
    """Confirming idempotence must not destroy the record of what was written.

    Re-running immediately after an apply is the normal way to check the WHERE
    clause held. At second precision the re-run's "noop" receipt landed on the
    applied receipt's path, and the list of written ids was gone.
    """
    _seed(engine, [(0, None, ANCIENT), (1, None, ANCIENT)])

    applied = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())
    assert applied.updated == 2

    # Same wall-clock second, distinguished only by microseconds.
    with engine.begin() as conn:
        rerun = prod.run(
            conn,
            mutate=True,
            classification=UNKNOWN_EXTERNAL,
            receipt_dir=tmp_path,
            now=NOW.replace(microsecond=NOW.microsecond + 1),
            environ=_ack(),
            emit=lambda _line: None,
        )

    assert rerun.receipt_path != applied.receipt_path
    assert len(list(tmp_path.glob("production_backfill_*.json"))) == 2
    # The first receipt still names the rows it wrote.
    assert json.loads(applied.receipt_path.read_text())["row_count"] == 2


def test_receipt_ids_are_exactly_the_rows_that_changed(engine, tmp_path):
    """The rollback instrument must not name a row the run did not write."""
    users, chars, image_ids = _seed(
        engine, [(0, 1, ANCIENT), (1, None, ANCIENT), (0, None, ANCIENT)]
    )

    result = _run(engine, mutate=True, receipt_dir=tmp_path, environ=_ack())
    receipt = json.loads(result.receipt_path.read_text())

    assert receipt["ids"] == sorted([image_ids[1], image_ids[2]])
    assert image_ids[0] not in receipt["ids"]

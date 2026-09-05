"""Tests for scripts/backfill_character_image_owners.py (Phase 4B1).

The script mutates a real database, so the parts worth testing are the ones
that decide WHETHER to mutate: the preconditions, the quota guard, the exact
row set, the manifest, and idempotence. Those are all pure functions of a
connection, which is why :func:`run` takes one instead of opening it — the DEV
guard lives in ``main()`` alone and is exercised separately here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import sessionmaker

# The tool lives in the repo-root scripts/ tree, beside the DEV guard it calls.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import backfill_character_image_owners as backfill
from scripts.assert_dev_db import DatabaseTargetError

from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User


NOW = datetime(2026, 9, 5, 12, 0, 0)


@pytest.fixture()
def engine(tmp_path):
    """A throwaway SQLite database carrying the real schema."""
    eng = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}", future=True)
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


def _seed(engine, rows):
    """Create two accounts, a character each, and *rows* images.

    ``rows`` is a list of ``(owner_index, user_id_or_None, age_days)``. Returns
    ``(user_ids, image_ids)`` with image ids in creation order.
    """
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    try:
        users = []
        chars = []
        for i in range(2):
            u = User(
                email=f"owner{i}@test.local",
                username=f"owner{i}",
                hashed_password="x",
            )
            db.add(u)
            db.flush()
            c = Character(owner_id=u.id, name=f"Char {i}")
            db.add(c)
            db.flush()
            users.append(u.id)
            chars.append(c.id)

        image_ids = []
        for owner_index, user_id, age_days in rows:
            img = CharacterImage(
                character_id=chars[owner_index],
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
        return conn.execute(
            text("SELECT count(*) FROM character_images WHERE user_id IS NULL")
        ).scalar_one()


def _run(engine, *, mutate, manifest_dir, now=NOW):
    with engine.begin() as conn:
        return backfill.run(
            conn,
            mutate=mutate,
            manifest_dir=manifest_dir,
            now=now,
            emit=lambda _line: None,
        )


# ── The duplicated constant ──────────────────────────────────────────────────


def test_quota_window_matches_the_service_it_mirrors():
    """The script's window constant is a copy; a drifted copy is a silent bug.

    If the service window changes and this does not, the guard measures the
    wrong period and reports a zero delta that is not zero.
    """
    from app.services import image_quota

    assert backfill.QUOTA_WINDOW_DAYS == image_quota._WINDOW_DAYS


# ── Dry run ──────────────────────────────────────────────────────────────────


def test_dry_run_makes_no_writes(engine, tmp_path):
    _seed(engine, [(0, None, 90), (0, None, 60), (1, None, 30)])

    result = _run(engine, mutate=False, manifest_dir=tmp_path / "manifests")

    assert result.eligible == 3
    assert result.updated == 0
    assert result.mutated is False
    assert _null_count(engine) == 3, "dry run must not write"
    assert result.manifest_path is None
    assert not (tmp_path / "manifests").exists(), "dry run must not write a manifest"


# ── Preconditions ────────────────────────────────────────────────────────────


def test_owner_disagreement_aborts_without_mutating(engine, tmp_path):
    users, _chars, _ids = _seed(engine, [(0, None, 90)])
    # Attribute one of owner 0's images to owner 1 — the "populated user_id
    # disagrees with characters.owner_id" case the rule cannot resolve.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO character_images "
                "(character_id, user_id, kind, status, visibility, file_path, "
                " created_at, public_gallery_enabled, safety_state, safety_policy_version) "
                "SELECT character_id, :other, kind, status, visibility, 'x.png', "
                "       created_at, 0, 'unreviewed', 0 "
                "FROM character_images LIMIT 1"
            ),
            {"other": users[1]},
        )

    with pytest.raises(backfill.BackfillAborted) as exc:
        _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")

    assert "disagrees with characters.owner_id" in exc.value.reasons[0]
    assert _null_count(engine) == 1, "abort must leave the data untouched"


def test_orphaned_character_reference_aborts(engine, tmp_path):
    _seed(engine, [(0, None, 90)])
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO character_images "
                "(character_id, user_id, kind, status, visibility, file_path, "
                " created_at, public_gallery_enabled, safety_state, safety_policy_version) "
                "VALUES (99999, NULL, 'generated', 'active', 'private', 'orphan.png', "
                "        :created, 0, 'unreviewed', 0)"
            ),
            {"created": NOW - timedelta(days=90)},
        )

    with pytest.raises(backfill.BackfillAborted) as exc:
        _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")

    assert "character that does not exist" in exc.value.reasons[0]
    assert _null_count(engine) == 2


def test_null_character_id_aborts():
    """The NOT NULL guard fires if the schema ever moves ahead of this script.

    ``character_id`` is NOT NULL today, so this state is unreachable through
    the real schema — it is checked against a bare table to prove the guard
    would actually catch a Phase 4C schema running a Phase 4B1 script.
    """
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE characters (id INTEGER PRIMARY KEY, owner_id INTEGER)"))
        conn.execute(
            text(
                "CREATE TABLE character_images "
                "(id INTEGER PRIMARY KEY, user_id INTEGER, character_id INTEGER, "
                " created_at TIMESTAMP)"
            )
        )
        conn.execute(text("INSERT INTO character_images VALUES (1, NULL, NULL, NULL)"))
        reasons = backfill.check_preconditions(conn)

    assert any("NULL character_id" in r for r in reasons)
    eng.dispose()


# ── Quota guard ──────────────────────────────────────────────────────────────


def test_quota_delta_guard_aborts_when_a_backfilled_row_is_in_window(engine, tmp_path):
    # One un-owned row two days old: inside the seven-day allowance window.
    _seed(engine, [(0, None, 2), (0, None, 90)])

    with pytest.raises(backfill.BackfillAborted) as exc:
        _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")

    assert "quota window" in exc.value.reasons[0]
    assert _null_count(engine) == 2, "the guard must abort before any write"


def test_quota_report_shows_per_owner_before_and_after(engine, tmp_path):
    users, _chars, ids = _seed(
        engine,
        [
            (0, None, 2),   # un-owned, in window — would be charged to owner 0
            (0, None, 2),   # given to owner 0 below: their existing usage
            (1, None, 90),  # outside the window — no allowance effect either way
        ],
    )
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE character_images SET user_id = :u WHERE id = :i"),
            {"u": users[0], "i": ids[1]},
        )
        impact = backfill.quota_impact(conn, now=NOW)

    assert impact.rows_in_window == 1
    assert impact.before[users[0]] == 1
    assert impact.after[users[0]] == 2
    assert impact.delta == 1


def test_rows_outside_the_window_have_no_quota_effect(engine, tmp_path):
    _seed(engine, [(0, None, 8), (1, None, 400)])
    with engine.begin() as conn:
        impact = backfill.quota_impact(conn, now=NOW)

    assert impact.rows_in_window == 0
    assert impact.delta == 0


# ── The write ────────────────────────────────────────────────────────────────


def test_confirmed_run_updates_exactly_the_eligible_rows(engine, tmp_path):
    users, _chars, ids = _seed(
        engine,
        [(0, None, 90), (0, None, 60), (1, None, 30)],
    )
    # A row that already has its owner must be left alone, not rewritten.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE character_images SET user_id = :u WHERE id = :i"),
            {"u": users[0], "i": ids[0]},
        )

    result = _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")

    assert result.eligible == 2
    assert result.updated == 2
    assert result.remaining_null == 0
    assert result.disagreements == 0

    with engine.connect() as conn:
        owners = dict(
            conn.execute(text("SELECT id, user_id FROM character_images")).all()
        )
    assert owners[ids[0]] == users[0]
    assert owners[ids[1]] == users[0]
    assert owners[ids[2]] == users[1]


def test_second_confirmed_run_is_idempotent(engine, tmp_path):
    _seed(engine, [(0, None, 90), (1, None, 60)])
    manifests = tmp_path / "manifests"

    first = _run(engine, mutate=True, manifest_dir=manifests)
    second = _run(engine, mutate=True, manifest_dir=manifests)

    assert first.updated == 2
    assert second.eligible == 0
    assert second.updated == 0
    assert second.mutated is False
    assert second.manifest_path is None, "a no-op run writes no manifest"
    assert len(list(manifests.glob("*.json"))) == 1


# ── Manifest ─────────────────────────────────────────────────────────────────


def test_manifest_contains_exactly_the_changed_ids(engine, tmp_path):
    users, _chars, ids = _seed(engine, [(0, None, 90), (0, None, 60), (1, None, 30)])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE character_images SET user_id = :u WHERE id = :i"),
            {"u": users[0], "i": ids[0]},
        )

    result = _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")
    manifest = json.loads(result.manifest_path.read_text())

    assert manifest["ids"] == [ids[1], ids[2]]
    assert manifest["row_count"] == 2
    assert ids[0] not in manifest["ids"], (
        "a row that already had an owner must never appear in the reversal set"
    )
    assert manifest["schema"] == backfill.MANIFEST_SCHEMA
    assert manifest["database"] == "DEV"


def test_manifest_carries_no_row_content_or_connection_details(engine, tmp_path):
    _seed(engine, [(0, None, 90)])
    result = _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")
    raw = result.manifest_path.read_text()

    for forbidden in ("owner0@test.local", "static/generated", "helium", "password"):
        assert forbidden not in raw, f"manifest leaked {forbidden!r}"
    assert set(json.loads(raw)) == {
        "schema",
        "generated_at",
        "database",
        "operation",
        "row_count",
        "ids",
        "rollback_sql",
        "rollback_note",
    }


def test_manifest_ids_are_a_precise_rollback_set(engine, tmp_path):
    """Applying the recorded reversal to exactly these ids restores the state."""
    users, _chars, ids = _seed(engine, [(0, None, 90), (0, None, 60)])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE character_images SET user_id = :u WHERE id = :i"),
            {"u": users[0], "i": ids[0]},
        )
    before = {ids[0]: users[0], ids[1]: None}

    result = _run(engine, mutate=True, manifest_dir=tmp_path / "manifests")
    manifest_ids = json.loads(result.manifest_path.read_text())["ids"]

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE character_images SET user_id = NULL WHERE id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
            {"ids": manifest_ids},
        )
    with engine.connect() as conn:
        after = dict(conn.execute(text("SELECT id, user_id FROM character_images")).all())

    assert after == before


# ── main() — flags and the DEV guard ─────────────────────────────────────────


def test_contradictory_flags_are_refused(capsys):
    assert backfill.main(["--dry-run", "--confirm"]) == 2
    assert "not both" in capsys.readouterr().err


def test_main_refuses_a_non_dev_target(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://u:p@some-host.neon.tech/db"
    )
    with pytest.raises(DatabaseTargetError) as exc:
        backfill.main(["--dry-run"])
    assert "NEON" in str(exc.value)
    assert "some-host" not in str(exc.value), "a refusal must not echo the target"


def test_main_refuses_when_no_target_is_configured(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseTargetError):
        backfill.main(["--dry-run"])

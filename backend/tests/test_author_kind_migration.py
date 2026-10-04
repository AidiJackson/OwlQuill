"""Migration ``ak01_author_kind`` — durable authorship provenance.

Runs the REAL ``upgrade()``/``downgrade()`` through Alembic's ``Operations``
against a throwaway SQLite file shaped like the pre-migration tables, so what is
pinned is the SQL the migration actually issues — not a re-statement of it.

The property under test is that the backfill is deterministic and nothing more:
``character_id IS NOT NULL`` becomes ``character``; every characterless row
stays NULL (unknown), whoever wrote it and whenever — no attribution is
inferred from account type, timestamps, usernames, ownership or content.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

_BACKEND = Path(__file__).resolve().parent.parent
_MIGRATION = _BACKEND / "alembic" / "versions" / "ak01_add_author_kind.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("ak01_under_test", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ak01 = _load_migration()


@pytest.fixture()
def pre_migration_engine(tmp_path):
    """posts/comments as they are BEFORE ak01: no author_kind column."""
    engine = create_engine(f"sqlite:///{tmp_path / 'ak01.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, is_seeder BOOLEAN)"))
        conn.execute(text(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, author_user_id INTEGER NOT NULL, "
            "character_id INTEGER, content TEXT NOT NULL, created_at TEXT)"))
        conn.execute(text(
            "CREATE TABLE comments (id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, "
            "author_user_id INTEGER NOT NULL, character_id INTEGER, content TEXT NOT NULL, "
            "created_at TEXT)"))
        # Rows chosen to TEMPT a heuristic: a seeder account, a very old row, a
        # row whose content says "legacy", a username that says "wanderer".
        conn.execute(text("INSERT INTO users VALUES (1, 'founder', 1), (2, 'wanderer_amy', 0)"))
        conn.execute(text(
            "INSERT INTO posts VALUES "
            "(1, 1, 59, 'character post', '2026-09-01'),"
            "(2, 1, NULL, 'legacy account post', '2025-01-01'),"
            "(3, 2, NULL, 'post orphaned by a deletion', '2026-09-30')"))
        conn.execute(text(
            "INSERT INTO comments VALUES "
            "(1, 1, 1, 59, 'character comment', '2026-09-01'),"
            "(2, 1, 2, NULL, 'wanderer-looking comment', '2026-09-02'),"
            "(3, 1, 1, NULL, 'comment orphaned by a deletion', '2026-09-03')"))
    yield engine
    engine.dispose()


def _run(engine, fn):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()


def _kinds(engine, table):
    with engine.connect() as conn:
        return dict(conn.execute(text(f"SELECT id, author_kind FROM {table} ORDER BY id")).all())


def test_backfill_is_deterministic_and_infers_nothing(pre_migration_engine):
    _run(pre_migration_engine, ak01.upgrade)
    assert _kinds(pre_migration_engine, "posts") == {1: "character", 2: None, 3: None}
    assert _kinds(pre_migration_engine, "comments") == {1: "character", 2: None, 3: None}


def test_the_column_is_nullable_text_with_no_default(pre_migration_engine):
    _run(pre_migration_engine, ak01.upgrade)
    for table in ("posts", "comments"):
        [col] = [c for c in inspect(pre_migration_engine).get_columns(table) if c["name"] == "author_kind"]
        assert col["nullable"] is True
        assert col["default"] is None
        assert getattr(col["type"], "length", None) == 16


def test_upgrade_touches_no_other_column(pre_migration_engine):
    with pre_migration_engine.connect() as conn:
        before = conn.execute(text("SELECT id, author_user_id, character_id, content FROM posts ORDER BY id")).all()
    _run(pre_migration_engine, ak01.upgrade)
    with pre_migration_engine.connect() as conn:
        after = conn.execute(text("SELECT id, author_user_id, character_id, content FROM posts ORDER BY id")).all()
    assert before == after


def test_downgrade_removes_the_column(pre_migration_engine):
    _run(pre_migration_engine, ak01.upgrade)
    _run(pre_migration_engine, ak01.downgrade)
    for table in ("posts", "comments"):
        assert "author_kind" not in {c["name"] for c in inspect(pre_migration_engine).get_columns(table)}


def test_ak01_is_the_single_head_on_top_of_the_previous_head():
    script = ScriptDirectory.from_config(Config(str(_BACKEND / "alembic.ini")))
    assert script.get_heads() == ["ak01_author_kind"]
    assert script.get_revision("ak01_author_kind").down_revision == "p4d3_02_v2_face_card_kinds"


def test_the_model_columns_match_the_migration():
    from app.models.comment import Comment
    from app.models.post import Post

    for model in (Post, Comment):
        col = model.__table__.columns["author_kind"]
        assert col.nullable is True
        assert col.type.length == 16
        assert col.default is None and col.server_default is None

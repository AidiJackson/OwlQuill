"""``scripts/character_inventory.py`` — the per-character dependency inventory.

Same posture as ``test_media_inventory.py``: nothing here reaches DEV or LIVE.
The guards it shares with the media inventory (statement screen, target
declaration, read-only handshake, privilege refusal) are already pinned there;
this file pins what is NEW:

  1. its fixed query set passes the shared statement screen, reads only tables
     and columns that exist in the models, and binds nothing but the id;
  2. its delete-consequence map matches every ForeignKey to ``characters.id``;
  3. it imports nothing from ``app.*`` and exposes no arbitrary-SQL entry point;
  4. END TO END on a throwaway SQLite file opened READ-ONLY (``mode=ro``) with
     the shared screen installed: the counts are right, and the printed and
     JSON reports carry no prose, message body, notification text, prompt,
     image path, email or username — seeded here as unmistakable markers.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
import app.models  # noqa: F401  (register every table on Base.metadata)
from app.models.adult_identity import (
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)
from app.models.character import Character, VisibilityEnum
from app.models.character_dna import CharacterDNA
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum
from app.models.comment import Comment
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.notification import Notification
from app.models.post import Post
from app.models.post_mention import PostMention
from app.models.reaction import Reaction
from app.models.realm import Realm
from app.models.story_space import (
    PublishedStory,
    PublishedStorySegment,
    StorySpace,
    StorySpaceChannel,
    StorySpacePost,
)
from app.models.user import User

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "character_inventory.py"


def _load():
    spec = importlib.util.spec_from_file_location("character_inventory_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: ``dataclasses`` resolves the module by name
    # while processing ``Check`` under ``from __future__ import annotations``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ci = _load()
from scripts import media_inventory as mi  # noqa: E402  (sys.path set by the script)


# ══════════════════════════════════════════════════════════════════════════════
# 1–3. Static contract
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("check", ci.CHECKS, ids=lambda c: f"{c.section}.{c.key}")
def test_every_query_passes_the_shared_read_only_screen(check):
    assert mi.statement_is_read_only(check.sql), check.sql


@pytest.mark.parametrize("check", ci.CHECKS, ids=lambda c: f"{c.section}.{c.key}")
def test_every_required_table_and_column_exists_in_the_models(check):
    for req in check.requires:
        table, _, column = req.partition(".")
        assert table in Base.metadata.tables, f"{check.key}: no table {table}"
        if column:
            assert column in Base.metadata.tables[table].columns, f"{check.key}: no {req}"


@pytest.mark.parametrize("check", ci.CHECKS, ids=lambda c: f"{c.section}.{c.key}")
def test_the_only_bound_values_are_the_id_and_patterns_built_from_it(check):
    bound = ci._params_for(check, 7)
    for name, value in bound.items():
        assert name == "cid" or name in check.params
        assert isinstance(value, int) or (isinstance(value, str) and "7" in value)


def test_the_delete_map_matches_every_foreign_key_to_characters():
    actual = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.column.table.name == "characters":
                    actual[(table.name, column.name)] = fk.ondelete
    assert actual == ci.ON_CHARACTER_DELETE


def test_every_table_with_a_character_fk_is_counted_somewhere():
    read = {req.split(".")[0] for c in ci.CHECKS for req in c.requires}
    for table, _ in ci.ON_CHARACTER_DELETE:
        assert table in read, f"{table} references characters but is never inventoried"


def test_privilege_refusal_covers_every_table_the_tool_reads():
    assert set(ci.PRIVILEGE_CHECK_TABLES) == {
        req.split(".")[0] for c in ci.CHECKS for req in c.requires
    }


def test_notification_patterns_do_not_match_a_longer_id():
    pats = ci._notification_patterns(7, "author_character_id")
    import fnmatch
    as_glob = [p.replace("%", "*") for p in pats.values()]
    assert any(fnmatch.fnmatchcase('{"author_character_id":7,"x":1}', g) for g in as_glob)
    assert any(fnmatch.fnmatchcase('{"a":1, "author_character_id": 7}', g) for g in as_glob)
    assert not any(fnmatch.fnmatchcase('{"author_character_id":70,"x":1}', g) for g in as_glob)


def test_the_script_imports_nothing_from_the_application():
    tree = ast.parse(_SCRIPT.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not [m for m in imported if m == "app" or m.startswith("app.")]
    for banned in ("boto3", "botocore", "requests", "httpx", "urllib.request",
                   "openai", "replicate", "sqlalchemy.orm"):
        assert banned not in imported, banned


def test_the_script_has_no_arbitrary_sql_entry_point():
    tree = ast.parse(_SCRIPT.read_text())
    declared: set[str] = set()
    bare_calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            bare_calls.add(node.func.id)
        if getattr(node.func, "attr", None) == "add_argument":
            declared |= {a.value for a in node.args if isinstance(a, ast.Constant)}
    assert declared == {"--url-env", "--expect", "--verify-only", "--character-id", "--json"}
    for banned in ("eval", "exec", "input", "__import__"):
        assert banned not in bare_calls


def test_main_refuses_a_mismatched_target_before_connecting(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CI_INV_URL", f"sqlite:///{tmp_path / 'x.db'}")
    rc = ci.main(["--url-env", "CI_INV_URL", "--expect", "DEV", "--character-id", "1"])
    assert rc == 3
    out = capsys.readouterr().out
    assert "x.db" not in out and "sqlite" not in out.lower()
    assert not (tmp_path / "x.db").exists()          # no connection was opened


def test_main_requires_a_character_id_unless_verifying(monkeypatch, capsys):
    monkeypatch.setenv("CI_INV_URL", "postgresql://u:p@h/db")
    assert ci.main(["--url-env", "CI_INV_URL", "--expect", "DEV"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 4. End to end, read-only, on a throwaway SQLite file
# ══════════════════════════════════════════════════════════════════════════════

SECRETS = (
    "SECRET-POST-PROSE", "SECRET-COMMENT-PROSE", "SECRET-MESSAGE-BODY",
    "SECRET-NOTIF-PREVIEW", "secret-image-path", "SECRET-PROMPT",
    "secret-owner@example.com", "secret_owner_username", "SECRET-SPACE-POST",
    "SECRET-SEGMENT", "secret-weights-uri",
)
CID = 7          # chosen so that 70 below proves the id boundary
OTHER_CID = 70


@pytest.fixture()
def seeded(tmp_path):
    path = tmp_path / "inv.db"
    writer = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=writer)
    db = sessionmaker(bind=writer)()

    owner = User(id=1, email="secret-owner@example.com", username="secret_owner_username",
                 hashed_password="x")
    other = User(id=2, email="o@example.com", username="other_acct", hashed_password="x")
    db.add_all([owner, other])
    db.flush()
    me = Character(id=CID, owner_id=1, name="Pan", visibility=VisibilityEnum.PUBLIC,
                   public_home_enabled=True,
                   avatar_url="https://cdn.example/static/secret-image-path/a.png")
    them = Character(id=OTHER_CID, owner_id=2, name="Bard")
    db.add_all([me, them])
    db.flush()

    realm = Realm(id=1, owner_id=1, name="R", slug="r", is_public=True)
    db.add(realm)
    db.flush()
    p1 = Post(id=1, realm_id=1, author_user_id=1, character_id=CID, content="SECRET-POST-PROSE",
              image_url="/static/secret-image-path/p.png")
    p2 = Post(id=2, realm_id=1, author_user_id=1, character_id=CID, content="SECRET-POST-PROSE")
    p3 = Post(id=3, realm_id=1, author_user_id=2, character_id=OTHER_CID, content="@Pan SECRET-POST-PROSE")
    db.add_all([p1, p2, p3])
    db.flush()
    db.add_all([
        Comment(post_id=1, author_user_id=2, character_id=OTHER_CID, content="SECRET-COMMENT-PROSE"),
        Comment(post_id=1, author_user_id=1, character_id=CID, content="SECRET-COMMENT-PROSE"),
        Reaction(post_id=1, user_id=2, type="heart"),
        PostMention(post_id=3, mention_text="@Pan", mentioned_character_id=CID),
    ])

    convo = Conversation(id=1, character_a_id=CID, character_b_id=OTHER_CID)
    db.add(convo)
    db.flush()
    db.add_all([
        Message(conversation_id=1, sender_character_id=CID, body="SECRET-MESSAGE-BODY"),
        Message(conversation_id=1, sender_character_id=OTHER_CID, body="SECRET-MESSAGE-BODY"),
        Message(conversation_id=1, sender_character_id=OTHER_CID, body="SECRET-MESSAGE-BODY"),
    ])

    db.add_all([
        Notification(user_id=2, type="mention", payload=json.dumps(
            {"author_character_id": CID, "mentioned_character_id": OTHER_CID,
             "post_preview": "SECRET-NOTIF-PREVIEW"}, separators=(",", ":"))),
        Notification(user_id=1, type="mention", payload=json.dumps(
            {"author_character_id": OTHER_CID, "mentioned_character_id": CID,
             "post_preview": "SECRET-NOTIF-PREVIEW"})),          # legacy ": " spelling
        Notification(user_id=1, type="mention", payload=json.dumps(
            {"author_character_id": 77, "mentioned_character_id": 700})),  # decoys
    ])

    db.add_all([
        CharacterImage(user_id=1, character_id=CID, kind=ImageKindEnum.GENERATED,
                       status=ImageStatusEnum.ACTIVE, file_path="static/secret-image-path/a.png",
                       prompt_summary="SECRET-PROMPT"),
        CharacterImage(user_id=1, character_id=CID, kind=ImageKindEnum.GENERATED,
                       status=ImageStatusEnum.ARCHIVED, file_path="static/secret-image-path/b.png",
                       prompt_summary="SECRET-PROMPT"),
    ])

    space = StorySpace(id=1, owner_id=1, name="S")
    db.add(space)
    db.flush()
    chan = StorySpaceChannel(id=1, space_id=1, channel_type="story", name="story")
    db.add(chan)
    db.flush()
    db.add(StorySpacePost(space_id=1, channel_id=1, author_user_id=1, character_id=CID,
                          content="SECRET-SPACE-POST"))
    story = PublishedStory(id=1, publisher_user_id=1, title="T")
    db.add(story)
    db.flush()
    db.add(PublishedStorySegment(published_story_id=1, position=1, content="SECRET-SEGMENT",
                                 character_id=CID, character_name_snap="Pan"))

    db.add_all([CharacterIdentityCanon(character_id=CID, status="locked", face_canon_json="{}"),
                CharacterDNA(character_id=CID)])
    model = AdultIdentityModel(id=1, character_id=CID)
    db.add(model)
    db.flush()
    db.add_all([
        AdultIdentityModelVersion(identity_id=1, version_index=1, lora_weights_uri="secret-weights-uri"),
        AdultIdentityTrainingJob(identity_id=1, provider="fake"),
    ])
    owner.active_character_id = CID
    db.commit()
    db.close()
    writer.dispose()

    # READ-ONLY: SQLite refuses every write on this connection, and the shared
    # screen refuses any statement that is not provably read-only.
    reader = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")

    @event.listens_for(reader, "before_cursor_execute")
    def _screen(conn, cursor, statement, parameters, context, executemany):
        if not mi.statement_is_read_only(statement):
            raise mi.ReadOnlyViolation(statement[:40])

    yield reader
    reader.dispose()


@pytest.fixture()
def sqlite_introspection(monkeypatch):
    """The production introspection reads information_schema (PostgreSQL); on
    SQLite answer the same two questions with the inspector."""
    # Plain SELECTs, so the introspection itself also passes the screen (the
    # inspector's PRAGMA statements are, correctly, refused by it).
    def table_exists(conn, table):
        return conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :t"), {"t": table}
        ).scalar() is not None

    def column_exists(conn, table, column):
        return conn.execute(text(
            "SELECT 1 FROM pragma_table_info(:t) WHERE name = :c"), {"t": table, "c": column}
        ).scalar() is not None

    monkeypatch.setattr(ci, "table_exists", table_exists)
    monkeypatch.setattr(ci, "column_exists", column_exists)


def _r(report, section, key):
    return report[section][key]["result"]


def test_end_to_end_counts(seeded, sqlite_introspection):
    with seeded.connect() as conn:
        report = ci.inventory(conn, CID)

    ident = _r(report, "identity", "character")
    assert ident["id"] == CID and ident["owner_id"] == 1 and ident["name"] == "Pan"
    assert ident["public_home_enabled"] in (True, 1)
    assert ident["avatar_set"] == 1 and ident["cover_set"] == 0
    assert _r(report, "identity", "selected_as_active_character_by_accounts") == 1
    [av] = _r(report, "identity", "avatar_pointer_rows")
    assert av["assoc"] == "this_character" and av["n"] == 1
    assert _r(report, "identity", "cover_pointer_rows") == []

    assert _r(report, "social", "posts") == {"total": 2, "with_image": 1, "without_realm": 0}
    assert _r(report, "social", "others_comments_on_its_posts") == {"comments": 1, "distinct_accounts": 1}
    assert _r(report, "social", "reactions_on_its_posts")["reactions"] == 1
    assert _r(report, "social", "comments") == 1
    assert _r(report, "social", "mentions_targeting") == {"mentions": 1, "posts": 1}
    assert _r(report, "social", "mentions_targeting_in_other_accounts_posts") == 1

    assert _r(report, "story_spaces", "story_space_posts") == {"posts": 1, "spaces": 1}
    assert _r(report, "story_spaces", "published_story_segments") == {"segments": 1, "stories": 1}

    assert _r(report, "messaging", "conversations") == 1
    assert _r(report, "messaging", "messages_in_its_conversations") == {"total": 3, "sent_by_it": 1}
    assert _r(report, "messaging", "conversation_counterparts") == {
        "conversations_with_other_accounts": 1, "distinct_other_accounts": 1}

    assert _r(report, "notifications", "as_actor") == [{"type": "mention", "n": 1}]
    assert _r(report, "notifications", "as_mentioned") == [{"type": "mention", "n": 1}]

    images = _r(report, "images", "character_images_by_status_kind")
    assert sum(r["n"] for r in images) == 2 and len(images) == 2

    assert _r(report, "canon", "dna") == 1
    assert len(_r(report, "canon", "identity_canon")) == 1
    assert _r(report, "adult_identity", "adult_model_versions") == {
        "versions": 1, "with_external_weights": 1}
    assert sum(r["n"] for r in _r(report, "adult_identity", "adult_training_jobs_by_state")) == 1
    assert _r(report, "soft_references", "rp_story_threads_selecting_it") == 0
    assert report["fk_on_character_delete"]["CASCADE"]


def test_the_report_carries_no_content_or_account_identity(seeded, sqlite_introspection, capsys):
    with seeded.connect() as conn:
        report = ci.inventory(conn, CID)
    ci.print_report(report)
    printed = capsys.readouterr().out
    as_json = json.dumps(report, default=str)
    for blob in (printed, as_json):
        for secret in SECRETS:
            assert secret not in blob, secret
        for marker in mi.FORBIDDEN_IN_JSON:
            assert marker not in blob.lower(), marker


def test_the_inventory_cannot_write(seeded, sqlite_introspection):
    """The connection itself refuses writes, and the screen refuses them first."""
    with seeded.connect() as conn:
        with pytest.raises(mi.ReadOnlyViolation):
            conn.execute(text("UPDATE characters SET name = 'x' WHERE id = 7"))
        with pytest.raises(mi.ReadOnlyViolation):
            conn.execute(text("WITH d AS (DELETE FROM posts RETURNING *) SELECT * FROM d"))


def test_an_unknown_character_reports_not_found(seeded, sqlite_introspection, capsys):
    with seeded.connect() as conn:
        report = ci.inventory(conn, 999)
    assert _r(report, "identity", "character") is None
    ci.print_report(report)
    assert "NOT FOUND" in capsys.readouterr().out

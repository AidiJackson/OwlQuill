"""Phase 4D3-3 — canon assets and the transactions that create them.

The invariant: **if a canon reference becomes durable, its image is already a
first-class owned asset; and if the surrounding transaction does not commit,
neither the row nor the object survives.**

Storage writes real files into a temp tree with object storage OFF, so
compensation runs for real rather than being mocked — a mocked ``delete_object``
would pass whether or not the bytes were actually removed.

Also pins the two things that are easy to get backwards:

* the canon-aware replacement MUST be able to archive a superseded asset, even
  though 4D3-2 made generic archiving refuse live canon assets;
* a losing generation candidate must leave nothing behind at all.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core import storage
from app.core.config import settings
from app.core.database import Base
from app.models.character import Character
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
)
from app.models.user import User
from app.services.asset_persistence import OwnedBy, persist_image_asset
from app.services.canon_references import (
    archive_superseded_canon_asset,
    is_canon_referenced,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"canon-txn-bytes" * 16
PNG2 = b"\x89PNG\r\n\x1a\n" + b"canon-txn-second" * 16


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_GENERATED_DIR", tmp_path / "static" / "generated")
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
    return tmp_path


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'canon_txn.db'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def cast(db):
    owner = User(email="owner@4d3t.test.com", username="owner4d3t", hashed_password="x")
    other = User(email="other@4d3t.test.com", username="other4d3t", hashed_password="x")
    db.add_all([owner, other])
    db.flush()
    character = Character(owner_id=owner.id, name="Txn Character")
    db.add(character)
    db.flush()
    canon = CharacterIdentityCanon(character_id=character.id)
    db.add(canon)
    db.commit()
    return {"owner": owner, "other": other, "character": character, "canon": canon}


def _objects(root: Path) -> list[Path]:
    return sorted(p for p in (root / "static").rglob("*") if p.is_file())


def _persist(db, character, kind=ImageKindEnum.IDENTITY_BODY_MAP, content=PNG):
    return persist_image_asset(
        db, content=content, owner=OwnedBy.character(character),
        kind=kind, provider="google",
    )


# ── storage succeeds, the rest fails ─────────────────────────────────────────


def test_a_transaction_that_never_commits_leaves_no_row_and_no_object(
    db, cast, local_storage
):
    """The canon write's failure mode: bytes stored, canon assignment raises."""
    image = _persist(db, cast["character"])
    assert len(_objects(local_storage)) == 1

    db.rollback()
    db.close()

    assert _objects(local_storage) == [], "object outlived a transaction that never committed"


def test_a_committed_canon_write_keeps_both_halves(db, cast, local_storage):
    image = _persist(db, cast["character"])
    cast["canon"].body_canon_json = json.dumps({"body_map_image_url": image.file_path})
    db.commit()

    assert len(_objects(local_storage)) == 1
    assert db.query(CharacterImage).filter(CharacterImage.id == image.id).one().storage_key


def test_a_failed_mark_lookup_leaves_no_orphan(client, db_session, local_storage):
    """The route persists, then discovers the mark does not exist and 404s.

    Before 4D3-3 the legacy write had already stored the bytes and nothing knew
    to clean up — this exact path is where part of the rowless bucket came from.
    """
    from tests.conftest import auth_headers, get_auth_token, make_admin

    email = "markfail@4d3t.test.com"
    get_auth_token(client, email=email, username="umarkfail")
    make_admin(email)
    hdrs = auth_headers(get_auth_token(client, email=email, username="umarkfail"))
    char_id = client.post("/characters/", json={"name": "MarkFail", "description": "d"},
                          headers=hdrs).json()["id"]

    before = len(_objects(local_storage))
    resp = client.post(
        f"/characters/{char_id}/identity-canon/upload/mark/pbm_missing",
        files={"file": ("m.png", PNG, "image/png")},
        data={"slot": "detail"},
        headers=hdrs,
    )
    assert resp.status_code == 404, resp.text

    rows = db_session.query(CharacterImage).filter(
        CharacterImage.character_id == char_id
    ).all()
    assert rows == [], "a row survived a request that 404'd"
    assert len(_objects(local_storage)) == before, "an object survived a request that 404'd"


# ── replacement ──────────────────────────────────────────────────────────────


def test_replacement_archives_the_uniquely_resolved_previous_row(db, cast, local_storage):
    old = _persist(db, cast["character"], content=PNG)
    cast["canon"].body_canon_json = json.dumps({"body_map_image_url": old.file_path})
    db.commit()

    new = _persist(db, cast["character"], content=PNG2)
    cast["canon"].body_canon_json = json.dumps({"body_map_image_url": new.file_path})
    archived = archive_superseded_canon_asset(
        db, previous_url=old.file_path, character=cast["character"], replacement=new
    )
    db.commit()

    assert archived is not None and archived.id == old.id
    assert db.query(CharacterImage).filter(CharacterImage.id == old.id).one().status \
        == ImageStatusEnum.ARCHIVED
    assert db.query(CharacterImage).filter(CharacterImage.id == new.id).one().status \
        == ImageStatusEnum.ACTIVE
    # The bytes of the superseded asset are RETAINED — archiving is a lifecycle
    # change, not a deletion.
    assert len(_objects(local_storage)) == 2


def test_a_rowless_previous_reference_is_left_untouched(db, cast, local_storage):
    """The 100 historical canon urls with no row. Nothing to archive, no
    backfill, and no error."""
    new = _persist(db, cast["character"])
    archived = archive_superseded_canon_asset(
        db,
        previous_url="https://r2.example/generated/never-had-a-row.png",
        character=cast["character"],
        replacement=new,
    )
    db.commit()
    assert archived is None
    assert db.query(CharacterImage).count() == 1


def test_a_row_owned_by_someone_else_is_not_archived(db, cast, local_storage):
    foreign = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["other"]),
        kind=ImageKindEnum.GENERATED, provider="google",
    )
    db.commit()

    new = _persist(db, cast["character"], content=PNG2)
    archived = archive_superseded_canon_asset(
        db, previous_url=foreign.file_path, character=cast["character"], replacement=new
    )
    db.commit()

    assert archived is None
    assert db.query(CharacterImage).filter(CharacterImage.id == foreign.id).one().status \
        == ImageStatusEnum.ACTIVE


def test_reassigning_the_same_asset_does_not_archive_it(db, cast, local_storage):
    image = _persist(db, cast["character"])
    db.commit()
    assert archive_superseded_canon_asset(
        db, previous_url=image.file_path, character=cast["character"], replacement=image
    ) is None
    assert image.status == ImageStatusEnum.ACTIVE


def test_canon_aware_replacement_works_despite_the_generic_archive_guard(
    db, cast, local_storage
):
    """4D3-2 made generic archiving refuse a live canon asset. The canon-aware
    path must still retire it — it updates BOTH halves, which is exactly what
    the generic routes cannot do and why they are refused."""
    old = _persist(db, cast["character"])
    cast["canon"].body_canon_json = json.dumps({"body_map_image_url": old.file_path})
    db.commit()

    # The generic guard says: hands off.
    assert is_canon_referenced(db, old) is True

    # The canon-aware replacement proceeds anyway, in one transaction.
    new = _persist(db, cast["character"], content=PNG2)
    cast["canon"].body_canon_json = json.dumps({"body_map_image_url": new.file_path})
    archived = archive_superseded_canon_asset(
        db, previous_url=old.file_path, character=cast["character"], replacement=new
    )
    db.commit()

    assert archived is not None
    assert old.status == ImageStatusEnum.ARCHIVED
    assert is_canon_referenced(db, old) is False   # canon has moved on
    assert is_canon_referenced(db, new) is True


def test_the_canon_writers_do_not_call_the_generic_protection(db):
    """Pinned by source: the replacement path must not ask permission of a rule
    written for other callers."""
    import ast
    import pathlib

    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    for rel in ("api/routes/canon_api.py", "api/routes/body_canon.py",
                "api/routes/character_accessory.py", "services/canon_pack_builder.py"):
        tree = ast.parse((app_root / rel).read_text())
        called = {
            (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        assert "is_canon_referenced" not in called, rel


# ── winner-only persistence ──────────────────────────────────────────────────


def test_generate_card_stores_nothing_and_returns_bytes(monkeypatch, local_storage):
    """Losing candidates never reach storage because ``generate_card`` no longer
    writes at all — it returns the selected bytes and the caller persists."""
    import app.services.canon_card_generator as gen

    src = Path(gen.__file__).read_text()
    assert "save_image(" not in src.replace("``save_image(png)``", "")
    assert _objects(local_storage) == []


def test_a_losing_candidate_leaves_no_row_and_no_object(db, cast, local_storage):
    """Two candidates generated, one selected. Only the winner is durable."""
    losing_bytes = PNG
    winning_bytes = PNG2

    # Only the winner is handed to the primitive — that IS the discipline.
    winner = _persist(db, cast["character"], content=winning_bytes)
    db.commit()

    assert db.query(CharacterImage).count() == 1
    objects = _objects(local_storage)
    assert len(objects) == 1
    assert objects[0].read_bytes() == winning_bytes
    assert all(p.read_bytes() != losing_bytes for p in objects)


def test_pack_helpers_return_results_not_urls():
    """Structural pin for winner-only selection: the helpers hand back the
    chosen ``CardResult`` so the caller persists exactly one candidate."""
    import inspect

    import app.services.canon_pack_builder as builder

    for fn in (builder._build_face_front, builder._build_dependent_card):
        source = inspect.getsource(fn)
        assert "return res.url" not in source
        assert "return oa.url" not in source


# ── per-slot durability ──────────────────────────────────────────────────────


def test_an_earlier_committed_slot_survives_a_later_failure(db, cast, local_storage):
    """The pack commits per slot, so a failure at slot N leaves slots 1..N-1
    durable and compensates only the in-flight object."""
    first = _persist(db, cast["character"], kind=ImageKindEnum.ANCHOR_FRONT)
    cast["canon"].face_canon_json = json.dumps({"face_front_image_url": first.file_path})
    db.commit()
    assert len(_objects(local_storage)) == 1

    # Second slot: object written, then the transaction is abandoned.
    _persist(db, cast["character"], kind=ImageKindEnum.IDENTITY_BODY_MAP, content=PNG2)
    assert len(_objects(local_storage)) == 2
    db.rollback()
    db.close()

    remaining = _objects(local_storage)
    assert len(remaining) == 1, "the in-flight object was not compensated"
    assert remaining[0].read_bytes() == PNG

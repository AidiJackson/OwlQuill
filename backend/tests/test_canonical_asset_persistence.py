"""The canonical durable-asset primitive (Phase 4D1).

``persist_image_asset`` is the one supported way to create a durable image
asset. These tests are about the guarantees it makes, and each of them is a
failure mode this codebase has actually produced:

* an asset with no owner — 4B1 found ``user_id`` meaning "whoever generated
  this"; 4B2 made the column NOT NULL;
* an asset owned by the requester rather than the owner — an admin editing
  somebody else's character used to file the image in the founder's library;
* bytes with no row — 98 identity-canon objects, every account avatar;
* a row with no bytes, or bytes with no row, when one half of the write fails;
* an object that survives a transaction its row never joined.

The storage layer is redirected to a temp directory with object storage OFF, so
every test writes and deletes real files and the compensation paths are exercised
rather than mocked.
"""
import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core import storage
from app.core.config import settings
from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.services.asset_persistence import (
    ORPHAN_OBJECT,
    OwnedBy,
    persist_image_asset,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"canonical-asset-bytes" * 8


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    """Real files on disk, in a temp tree, with R2 off."""
    generated = tmp_path / "static" / "generated"
    monkeypatch.setattr(storage, "_GENERATED_DIR", generated)
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
    return tmp_path


@pytest.fixture()
def fk_engine(tmp_path):
    """Foreign keys actually enforced — SQLite ignores them unless asked."""
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(fk_engine):
    return sessionmaker(bind=fk_engine)


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def cast(db):
    """An owner with a character, and an unrelated admin account."""
    owner = User(email="owner@4d1.test", username="owner4d1", hashed_password="x")
    admin = User(email="admin@4d1.test", username="admin4d1", hashed_password="x",
                 is_admin=True)
    db.add_all([owner, admin])
    db.flush()
    character = Character(owner_id=owner.id, name="Canonical Character")
    db.add(character)
    db.flush()
    db.commit()
    return {"owner": owner, "admin": admin, "character": character}


def _object_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "static").rglob("*") if p.is_file())


# ── ownership principal ──────────────────────────────────────────────────────


def test_account_principal_owns_with_no_character(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert image.user_id == cast["owner"].id
    assert image.character_id is None


def test_character_principal_derives_owner_and_association_together(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert image.user_id == cast["character"].owner_id
    assert image.character_id == cast["character"].id


def test_an_admin_acting_on_someone_elses_character_does_not_become_the_owner(
    db, cast, local_storage
):
    """The failure this principal exists to make impossible.

    ``OwnedBy.character`` reads both values off the Character, so there is no
    argument an admin's identity could be passed as. The admin is simply not
    part of the call.
    """
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="gpt-image",
    )
    db.commit()
    assert image.user_id == cast["owner"].id
    assert image.user_id != cast["admin"].id


def test_there_is_no_raw_owner_id_constructor():
    """A bare int cannot tell an owner from a requester; that is the point."""
    constructors = {n for n in dir(OwnedBy) if not n.startswith("_")}
    assert constructors == {"character", "account"}


def test_a_raw_id_is_rejected_as_the_owner(db, cast, local_storage):
    with pytest.raises(TypeError, match="OwnedBy"):
        persist_image_asset(
            db, content=PNG, owner=cast["owner"].id,  # type: ignore[arg-type]
            kind=ImageKindEnum.GENERATED, provider="stub",
        )
    assert _object_files(local_storage) == []


def test_a_character_without_an_owner_is_refused(db, local_storage):
    orphan = Character(owner_id=None, name="No Owner")
    with pytest.raises(ValueError, match="owner"):
        OwnedBy.character(orphan)


def test_ownership_is_not_optional(db, cast, local_storage):
    """There is no call shape that omits an owner."""
    with pytest.raises(TypeError):
        persist_image_asset(  # type: ignore[call-arg]
            db, content=PNG, kind=ImageKindEnum.GENERATED, provider="stub",
        )


# ── required provenance and kind ─────────────────────────────────────────────


def test_provider_must_be_stated_even_when_it_is_none(db, cast, local_storage):
    """Required, though nullable: 'a user supplied these bytes' is an answer."""
    with pytest.raises(TypeError):
        persist_image_asset(  # type: ignore[call-arg]
            db, content=PNG, owner=OwnedBy.account(cast["owner"]),
            kind=ImageKindEnum.GENERATED,
        )
    explicit = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.UPLOADED, provider=None,
    )
    db.commit()
    assert explicit.provider is None


def test_kind_must_be_an_enum_member(db, cast, local_storage):
    with pytest.raises(TypeError, match="ImageKindEnum"):
        persist_image_asset(
            db, content=PNG, owner=OwnedBy.account(cast["owner"]),
            kind="generated",  # type: ignore[arg-type]
            provider="stub",
        )


def test_empty_content_is_refused(db, cast, local_storage):
    with pytest.raises(ValueError, match="empty"):
        persist_image_asset(
            db, content=b"", owner=OwnedBy.account(cast["owner"]),
            kind=ImageKindEnum.GENERATED, provider="stub",
        )
    assert _object_files(local_storage) == []


# ── safety state ─────────────────────────────────────────────────────────────


def test_every_canonical_asset_starts_unreviewed(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="gpt-image",
    )
    db.commit()
    assert image.safety_state == SAFETY_STATE_UNREVIEWED
    assert image.safety_policy_version == SAFETY_POLICY_VERSION_NONE
    assert image.safety_decided_at is None
    assert image.safety_decided_by is None
    assert image.safety_decision_source is None


def test_no_caller_can_request_an_approved_asset(db, cast, local_storage):
    """Provenance is evidence; eligibility is a decision, and none has been made.

    There is no policy version 1, so nothing can honestly be approved. The
    absence of the parameter is the guarantee — a keyword that does not exist
    cannot be passed by a writer added next year.
    """
    import inspect as _inspect

    params = set(_inspect.signature(persist_image_asset).parameters)
    assert "safety_state" not in params
    assert "safety_policy_version" not in params

    for forbidden in ("safety_state", "safety_policy_version", "status"):
        with pytest.raises(TypeError):
            persist_image_asset(
                db, content=PNG, owner=OwnedBy.account(cast["owner"]),
                kind=ImageKindEnum.GENERATED, provider="stub",
                **{forbidden: "approved"},
            )


def test_a_provider_with_a_content_filter_is_still_unreviewed(db, cast, local_storage):
    """The one editor row that reached the public gallery came from gpt-image."""
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="gpt-image",
    )
    db.commit()
    assert image.safety_state == SAFETY_STATE_UNREVIEWED


# ── lifecycle and storage identity ───────────────────────────────────────────


def test_lifecycle_defaults_are_active_and_private(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert image.status == ImageStatusEnum.ACTIVE
    assert image.visibility == ImageVisibilityEnum.PRIVATE


def test_storage_key_is_always_recorded(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert image.storage_key
    assert image.storage_key.startswith("generated/")
    assert storage._MINTED_KEY_RE.match(image.storage_key)


def test_file_path_stays_legacy_compatible(db, cast, local_storage):
    """Every reader still resolves it; nothing downstream had to change."""
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert image.file_path == f"static/{image.storage_key}"
    assert storage.file_path_to_url(image.file_path) == f"/{image.file_path}"
    assert storage.load_image_bytes(image.file_path) == PNG


def test_storage_key_and_file_path_name_the_same_object(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    on_disk = local_storage / "static" / image.storage_key
    assert on_disk.is_file()
    assert on_disk.read_bytes() == PNG


# ── lineage ──────────────────────────────────────────────────────────────────


def test_single_source_lineage_is_recorded(db, cast, local_storage):
    source = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.flush()
    derived = persist_image_asset(
        db, content=PNG + b"crop", owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider=None, derived_from=source,
        metadata={"derived": "avatar_crop"},
    )
    db.commit()
    assert derived.derived_from_image_id == source.id
    assert derived.character_id is None


def test_lineage_refuses_a_non_character_image_source(db, cast, local_storage):
    """No polymorphic lineage: a UserImage source is metadata, not an FK."""
    from app.models.user_image import UserImage

    src = UserImage(user_id=cast["owner"].id, kind="profile_cover",
                    file_path="static/generated/x.png")
    db.add(src)
    db.flush()
    with pytest.raises(TypeError, match="CharacterImage"):
        persist_image_asset(
            db, content=PNG, owner=OwnedBy.account(cast["owner"]),
            kind=ImageKindEnum.GENERATED, provider=None, derived_from=src,  # type: ignore[arg-type]
        )


def test_lineage_is_absent_by_default(db, cast, local_storage):
    """Multi-source writers leave it unset rather than naming one of several."""
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
        metadata={"manual_refs": [{"image_id": 1}, {"image_id": 2}]},
    )
    db.commit()
    assert image.derived_from_image_id is None
    assert len(image.metadata_json["manual_refs"]) == 2


# ── transactions ─────────────────────────────────────────────────────────────


def test_persist_never_commits(db, cast, local_storage, session_factory):
    """The row joins the caller's transaction; the caller decides its fate."""
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    assert image.id is not None            # flushed, so the id exists
    other = session_factory()
    try:
        assert other.get(CharacterImage, image.id) is None  # but not committed
    finally:
        other.close()


def test_a_committed_transaction_keeps_the_row_and_the_object(
    db, cast, local_storage, session_factory
):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    key = image.storage_key
    db.commit()

    other = session_factory()
    try:
        assert other.get(CharacterImage, image.id) is not None
    finally:
        other.close()
    assert (local_storage / "static" / key).is_file()


def test_an_explicit_rollback_removes_the_row_and_the_object(
    db, cast, local_storage, session_factory
):
    """THE PROBLEM 4D1 EXISTS TO CLOSE.

    Compensating only when the INSERT fails is not enough: persist succeeds, the
    route then does something else that raises, the transaction rolls back — and
    the object survives forever with no row that ever existed.
    """
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    image_id, key = image.id, image.storage_key
    assert (local_storage / "static" / key).is_file()

    db.rollback()

    other = session_factory()
    try:
        assert other.get(CharacterImage, image_id) is None
    finally:
        other.close()
    assert not (local_storage / "static" / key).exists()


def test_closing_the_session_without_committing_removes_the_object(
    cast, local_storage, session_factory
):
    """The path that actually happens in production.

    FastAPI's ``get_db`` only calls ``Session.close()``. SQLAlchemy 2.0.25 emits
    neither ``after_rollback`` nor ``after_soft_rollback`` for that, which is
    why the hook is on ``after_transaction_end`` — verified, not assumed.
    """
    session = session_factory()
    image = persist_image_asset(
        session, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    key = image.storage_key
    assert (local_storage / "static" / key).is_file()

    session.close()          # no commit, no rollback — exactly get_db's finally

    assert not (local_storage / "static" / key).exists()


def test_a_route_raising_after_persist_leaves_nothing_behind(
    cast, local_storage, session_factory
):
    """The realistic shape: persist succeeds, later work fails, finally: close."""
    session = session_factory()
    key = None
    try:
        image = persist_image_asset(
            session, content=PNG, owner=OwnedBy.account(cast["owner"]),
            kind=ImageKindEnum.GENERATED, provider="stub",
        )
        key = image.storage_key
        raise RuntimeError("the rest of the route failed")
    except RuntimeError:
        pass
    finally:
        session.close()

    assert key is not None
    assert not (local_storage / "static" / key).exists()


def test_a_commit_then_a_later_rollback_keeps_the_committed_object(
    cast, local_storage, session_factory
):
    """Committed assets are forgotten; only the uncommitted one is compensated."""
    session = session_factory()
    kept = persist_image_asset(
        session, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    kept_key = kept.storage_key
    session.commit()

    doomed = persist_image_asset(
        session, content=PNG + b"2", owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    doomed_key = doomed.storage_key
    session.rollback()
    session.close()

    assert (local_storage / "static" / kept_key).is_file()
    assert not (local_storage / "static" / doomed_key).exists()


# ── failure compensation ─────────────────────────────────────────────────────


def test_a_storage_failure_leaves_no_row(db, cast, local_storage, monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("R2 unavailable")

    monkeypatch.setattr("app.services.asset_persistence.put_object", boom)
    before = db.query(CharacterImage).count()
    with pytest.raises(RuntimeError, match="R2 unavailable"):
        persist_image_asset(
            db, content=PNG, owner=OwnedBy.account(cast["owner"]),
            kind=ImageKindEnum.GENERATED, provider="stub",
        )
    assert db.query(CharacterImage).count() == before


def test_a_row_failure_deletes_the_object_it_just_wrote(db, cast, local_storage, monkeypatch):
    """The object must not outlive a row that was never inserted."""
    seen: dict = {}
    real_put = storage.put_object

    def spy(content, *, key):
        stored = real_put(content, key=key)
        seen["key"] = stored.storage_key
        return stored

    monkeypatch.setattr("app.services.asset_persistence.put_object", spy)
    # Built BEFORE flush is broken: reading owner.id can trigger autoflush, and
    # the failure under test is the INSERT, not the principal.
    owner = OwnedBy.account(cast["owner"])
    monkeypatch.setattr(
        db, "flush", lambda *a, **k: (_ for _ in ()).throw(IntegrityError("x", {}, Exception()))
    )

    with pytest.raises(IntegrityError):
        persist_image_asset(
            db, content=PNG, owner=owner,
            kind=ImageKindEnum.GENERATED, provider="stub",
        )
    assert seen["key"], "the object must have been written before the row failed"
    assert not (local_storage / "static" / seen["key"]).exists()


def test_a_failed_cleanup_logs_orphan_object_and_the_original_error_wins(
    db, cast, local_storage, monkeypatch, caplog
):
    """A diagnostic must never outrank the error it describes.

    This module has been bitten by that once already — see the comment in
    ``storage._load_from_r2`` about a defensive one-liner replacing a real
    ModuleNotFoundError with an AttributeError from the handler.
    """
    def cleanup_boom(_key):
        raise RuntimeError("bucket unreachable during cleanup")

    monkeypatch.setattr("app.services.asset_persistence.delete_object", cleanup_boom)
    owner = OwnedBy.account(cast["owner"])   # before flush is broken; see above
    monkeypatch.setattr(
        db, "flush",
        lambda *a, **k: (_ for _ in ()).throw(IntegrityError("original", {}, Exception())),
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(IntegrityError):      # the ORIGINAL error, not the cleanup's
            persist_image_asset(
                db, content=PNG, owner=owner,
                kind=ImageKindEnum.GENERATED, provider="stub",
            )

    orphan_lines = [r.message for r in caplog.records if ORPHAN_OBJECT in r.message]
    assert orphan_lines, "cleanup failure must be recorded for later reconciliation"
    assert "generated/" in orphan_lines[0]
    assert "cleanup_error=RuntimeError" in orphan_lines[0]


# ── the transient primitive is a different thing ─────────────────────────────


def test_the_transient_primitive_creates_no_row(db, cast, local_storage, caplog):
    before = db.query(CharacterImage).count()
    with caplog.at_level(logging.INFO):
        path = storage.put_transient_object(PNG, purpose="editor_job_source_snapshot")
    assert db.query(CharacterImage).count() == before
    assert storage.load_image_bytes(path) == PNG
    # The stated purpose is the observable: rowlessness is recorded as intent.
    stated = [r.message for r in caplog.records if "TRANSIENT_OBJECT" in r.message]
    assert stated and "purpose=editor_job_source_snapshot" in stated[0]
    assert f"key={storage.TRANSIENT_KEY_PREFIX}/" in stated[0]


def test_the_transient_primitive_demands_a_purpose():
    """Rowlessness has to be a stated intention, not an omission."""
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="purpose"):
            storage.put_transient_object(PNG, purpose=bad)
    with pytest.raises(TypeError):
        storage.put_transient_object(PNG)  # type: ignore[call-arg]


def test_durable_and_transient_objects_are_distinguishable_by_key(db, cast, local_storage):
    """In the object store the two carry different prefixes.

    Local mode keeps one flat directory — ``_GENERATED_DIR`` is what every
    reader resolves and what the test fixture redirects — so the distinction
    lives in the minted key, which is the production (R2) identity and the value
    ``storage_key`` records.
    """
    asset = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    assert asset.storage_key.startswith(f"{storage.DURABLE_KEY_PREFIX}/")
    assert storage.mint_object_key(
        PNG, prefix=storage.TRANSIENT_KEY_PREFIX
    ).startswith(f"{storage.TRANSIENT_KEY_PREFIX}/")


def test_delete_object_refuses_a_key_it_did_not_mint(local_storage):
    """Compensation, not a retention feature."""
    for bad in ("static/generated/a.png", "../etc/passwd", "generated/../x.png", ""):
        with pytest.raises(ValueError, match="Refusing to delete"):
            storage.delete_object(bad)


# ── the invariants earlier phases established still hold ─────────────────────


def test_an_ownerless_row_is_still_impossible(db, cast, local_storage):
    """4B2. The canonical writer cannot produce one, and nor can raw SQL."""
    db.add(CharacterImage(
        character_id=None, kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE, visibility=ImageVisibilityEnum.PRIVATE,
        file_path="static/generated/ownerless.png",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_character_deletion_still_sets_the_association_null(db, cast, local_storage):
    """4C, now for a row the canonical writer created."""
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()
    image_id, key = image.id, image.storage_key

    db.delete(db.get(Character, cast["character"].id))
    db.commit()

    db.expire_all()
    survivor = db.get(CharacterImage, image_id)
    assert survivor is not None
    assert survivor.character_id is None
    assert survivor.user_id == cast["owner"].id
    assert survivor.storage_key == key
    assert survivor.safety_state == SAFETY_STATE_UNREVIEWED
    # A committed object is never compensated by a later transaction.
    assert (local_storage / "static" / key).is_file()


def test_account_deletion_is_still_restricted(db, cast, local_storage):
    """4B2, still reached now that 4C removed the ORM cascade."""
    persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    db.commit()

    with pytest.raises(IntegrityError):
        db.delete(db.get(User, cast["owner"].id))
        db.commit()
    db.rollback()
    assert db.get(User, cast["owner"].id) is not None


def test_no_safety_state_publication_gate_was_activated(db, cast, local_storage):
    """4E is not this phase. An unreviewed asset is judged on provenance alone."""
    from app.schemas.character_image import is_public_post_image, is_public_surface_safe

    safe = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="gpt-image",
    )
    unsafe = persist_image_asset(
        db, content=PNG + b"x", owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider="replicate_nsfw",
    )
    db.commit()

    assert safe.safety_state == SAFETY_STATE_UNREVIEWED
    assert is_public_surface_safe(safe) is True      # unreviewed does NOT withhold
    assert is_public_post_image(safe) is True
    assert is_public_surface_safe(unsafe) is False   # provenance still does


def test_the_session_event_the_hook_relies_on_is_the_right_one(session_factory):
    """Pins the SQLAlchemy behaviour the compensation hook is built on.

    The hook is on ``after_transaction_end`` rather than ``after_rollback``
    because ``after_rollback`` does not fire for a ``close()`` without a commit
    — which is precisely what FastAPI's ``get_db`` does in its ``finally``. That
    was measured against SQLAlchemy 2.0.25, not assumed, and it is pinned here
    so an upgrade that changes it fails loudly instead of silently reintroducing
    orphan objects.
    """
    from sqlalchemy.orm import Session as _Session

    fired: list[str] = []

    def rec(name):
        def handler(session, *_a, **_kw):
            fired.append(name)
        return handler

    handlers = {
        name: rec(name)
        for name in ("after_rollback", "after_soft_rollback", "after_transaction_end")
    }
    for name, handler in handlers.items():
        event.listen(_Session, name, handler)
    try:
        session = session_factory()
        session.add(User(email="ev@4d1.test", username="ev4d1", hashed_password="x"))
        session.flush()
        session.close()          # no commit, no rollback
    finally:
        for name, handler in handlers.items():
            event.remove(_Session, name, handler)

    assert "after_transaction_end" in fired, "the hook's event must fire on close()"
    assert "after_rollback" not in fired, (
        "after_rollback now fires on close(); the compensation hook could be "
        "simplified — re-read app/services/asset_persistence.py before changing it."
    )
    assert "after_soft_rollback" not in fired

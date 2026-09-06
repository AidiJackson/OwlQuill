"""Phase 4D2 — the ordinary durable writers, and both avatar crops.

4D1 built ``persist_image_asset`` and migrated nothing. 4D2 moves the writers
that had no reason to be special: scene images, body-identity slots, the
character-visual routes, the candidate-slot face crop, the generation pipeline,
the editor, the library stub — and the two avatar crops that were the largest
source of rowless objects in the bucket.

What these tests are about is not "the call was changed". It is the set of
properties the change has to preserve or establish:

* every durable output is an owned row, with a storage key and no safety
  decision;
* the OWNER is the character's owner, never the admin or the requester who
  happened to make the call;
* lineage is recorded when a single source genuinely exists and NOT invented
  when several do;
* the avatar crops become resolvable — and cannot launder an unsafe source by
  becoming so;
* the editor's job snapshot stays deliberately rowless;
* a transaction that does not commit leaves neither the row nor the object.

The storage layer writes real files into a temp tree with object storage off, so
compensation runs for real rather than being mocked.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core import storage
from app.core.config import settings
from app.core.database import Base
from app.models.candidate_slot import CandidateSlot
from app.models.character import Character
from app.models.character_image import (
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_APPROVED,
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.models.user_image import UserImage
from app.schemas.character_image import (
    derived_provenance,
    is_public_surface_safe,
)
from app.services.asset_persistence import (
    OwnedBy,
    persist_derived_image_asset,
    persist_image_asset,
    source_image_for_url,
)
from app.services.character_home_media import resolve_public_media_url

PNG = b"\x89PNG\r\n\x1a\n" + b"phase-4d2-source-bytes" * 8
CROP = b"\x89PNG\r\n\x1a\n" + b"phase-4d2-crop-bytes" * 8


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    """Real files on disk, in a temp tree, with R2 off."""
    generated = tmp_path / "static" / "generated"
    monkeypatch.setattr(storage, "_GENERATED_DIR", generated)
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
    return tmp_path


@pytest.fixture()
def fk_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p4d2.db'}")

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
    owner = User(email="owner@4d2.test", username="owner4d2", hashed_password="x")
    admin = User(email="admin@4d2.test", username="admin4d2", hashed_password="x",
                 is_admin=True)
    db.add_all([owner, admin])
    db.flush()
    character = Character(owner_id=owner.id, name="Migrated Character")
    db.add(character)
    db.flush()
    db.commit()
    return {"owner": owner, "admin": admin, "character": character}


def _objects(root: Path) -> list[Path]:
    return sorted(p for p in (root / "static").rglob("*") if p.is_file())


def _source_asset(db, cast, *, provider="google", metadata=None):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.GENERATED, provider=provider, metadata=metadata,
    )
    db.commit()
    return image


# ── what every migrated writer must produce ──────────────────────────────────


def test_a_migrated_writer_produces_an_owned_row_with_a_storage_key(db, cast, local_storage):
    """The shape 4D2 is establishing, asserted once for the primitive itself.

    Per-writer coverage lives in each writer's own suite; what belongs here is
    the contract they all now share, because before 4D2 a durable write could
    satisfy none of it and still look successful.
    """
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.SCENE_ONLY, provider="google",
    )
    db.commit()

    assert image.id is not None
    assert image.user_id == cast["owner"].id
    assert image.character_id == cast["character"].id
    assert image.storage_key
    assert image.file_path
    assert image.status == ImageStatusEnum.ACTIVE
    assert image.visibility == ImageVisibilityEnum.PRIVATE
    assert image.safety_state == SAFETY_STATE_UNREVIEWED
    assert image.safety_policy_version == SAFETY_POLICY_VERSION_NONE


def test_the_requester_cannot_become_the_owner(db, cast, local_storage):
    """4B2's invariant, restated for the writers 4D2 moved.

    ``admin_canon_import`` and the editor route both admit an admin onto
    somebody else's character. The canonical writer has no parameter that could
    file the result in the admin's library, and this is the assertion that the
    migrated call sites did not reintroduce one.
    """
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.IDENTITY_BODY_FRONT, provider="admin_upload",
        metadata={"admin_email": cast["admin"].email},
    )
    db.commit()

    assert image.user_id == cast["owner"].id
    assert image.user_id != cast["admin"].id
    # The requester is still recorded — as evidence, in metadata, which is where
    # requester identity belongs.
    assert image.metadata_json["admin_email"] == cast["admin"].email


def test_an_account_asset_carries_no_character_association(db, cast, local_storage):
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.UPLOADED, provider=None,
    )
    db.commit()
    assert image.user_id == cast["owner"].id
    assert image.character_id is None


# ── lineage: honest, or absent ───────────────────────────────────────────────


def test_a_single_source_transformation_records_its_source(db, cast, local_storage):
    source = _source_asset(db, cast)
    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.IDENTITY_FACE_REF, source=source,
    )
    db.commit()
    assert crop.derived_from_image_id == source.id


def test_a_multi_source_generation_claims_no_lineage(db, cast, local_storage):
    """The rule that keeps the column meaning something.

    A scene image, an editor edit and a pipeline generation each draw on a
    prompt plus zero-to-three references. ``derived_from_image_id`` names ONE
    row; naming any of several would be a false record, so those writers leave
    it unset and describe their references in metadata.
    """
    ref_a = _source_asset(db, cast)
    ref_b = _source_asset(db, cast)
    generated = persist_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.SCENE_ONLY, provider="gpt-image",
        metadata={"source_image_ids": [ref_a.id, ref_b.id]},
    )
    db.commit()

    assert generated.derived_from_image_id is None
    assert generated.metadata_json["source_image_ids"] == [ref_a.id, ref_b.id]


def test_a_user_image_source_records_lineage_in_metadata_not_the_column(db, cast, local_storage):
    """The account-avatar case: a real source, and no column that can hold it.

    ``derived_from_image_id`` is a FK to ``character_images``. A crop of a
    ``UserImage`` has a source, and pointing that FK at a row in a different
    table is not available — so the record goes where the schema can carry it,
    and 4D2 does NOT add a second FK to make the two cases look alike.
    """
    user_image = UserImage(
        user_id=cast["owner"].id, kind="profile_cover", status="active",
        provider="stub", file_path="static/generated/legacy-cover.png",
    )
    db.add(user_image)
    db.commit()

    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.account(cast["owner"]),
        kind=ImageKindEnum.UPLOADED, source=user_image,
        metadata={"avatar_crop": True},
    )
    db.commit()

    assert crop.derived_from_image_id is None
    assert crop.metadata_json["derived_from"] == {
        "table": "user_images", "id": user_image.id,
    }
    assert crop.metadata_json["avatar_crop"] is True


def test_a_source_url_that_names_no_row_yields_no_lineage(db, cast, local_storage):
    """``source_image_for_url`` refuses to guess.

    The candidate-slot promoter is handed a client-supplied url. When it names a
    stored asset the crop gets real lineage; when it names none — or several —
    the honest answer is that the source is unknown, and a crop that claims a
    source it cannot identify is worse than one that claims nothing.
    """
    assert source_image_for_url(db, "static/generated/never-existed.png") is None
    assert source_image_for_url(db, None) is None

    stored = _source_asset(db, cast)
    assert source_image_for_url(db, stored.file_path).id == stored.id


def test_an_ambiguous_source_url_yields_no_lineage(db, cast, local_storage):
    """Two rows on one file is not a source, it is a question."""
    first = _source_asset(db, cast)
    twin = CharacterImage(
        user_id=cast["owner"].id, character_id=cast["character"].id,
        kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE, file_path=first.file_path,
    )
    db.add(twin)
    db.commit()

    assert source_image_for_url(db, first.file_path) is None


# ── provenance: a crop must not launder its source ───────────────────────────


@pytest.mark.parametrize(
    "provider, metadata",
    [
        ("replicate_nsfw", {"adult_studio": True, "provider": "replicate_nsfw"}),
        ("self_hosted", {"editor_generated": True}),
        ("gpt-image", {"editor_generated": True, "provider": "gpt-image"}),
    ],
)
def test_a_crop_of_an_unsafe_source_is_itself_unsafe(
    db, cast, local_storage, provider, metadata
):
    """THE regression 4D2 had to create and then close.

    While the avatar crops were rowless, a crop of studio output was suppressed
    on every shared surface because ``resolve_public_media_url`` could resolve
    nothing — an accident, not a decision. Giving the crop a row makes it
    resolvable, and a resolvable row written with ``provider=None`` and fresh
    metadata reads as SAFE. That crop is itself a ``CharacterImage`` its owner
    can select, so it would then pass the character-avatar route's
    ``is_public_surface_safe`` gate that the ORIGINAL had just failed.

    So the derived writer carries the source's provenance markers forward, and
    the crop answers exactly as its source does.
    """
    source = _source_asset(db, cast, provider=provider, metadata=metadata)
    assert not is_public_surface_safe(source)

    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.UPLOADED, source=source,
        metadata={"avatar_crop": True, "source": "character_avatar_crop"},
    )
    db.commit()

    assert not is_public_surface_safe(crop), (
        "a crop laundered its source's provenance — an unsafe image became "
        "publicly presentable by being cropped"
    )
    assert resolve_public_media_url(db, crop.file_path) is None


def test_a_caller_cannot_overwrite_inherited_provenance_with_its_own_metadata(
    db, cast, local_storage
):
    """Inheritance is applied LAST, on purpose.

    A writer that passed ``{"adult_studio": False}`` — or simply reused a
    metadata dict — must not be able to clear a marker it did not set.
    """
    source = _source_asset(
        db, cast, provider="replicate_nsfw",
        metadata={"adult_studio": True, "provider": "replicate_nsfw"},
    )
    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.UPLOADED, source=source,
        metadata={"adult_studio": False, "provider": "stub"},
    )
    db.commit()

    assert crop.metadata_json["adult_studio"] is True
    assert crop.metadata_json["provider"] == "replicate_nsfw"
    assert not is_public_surface_safe(crop)


def test_a_crop_of_a_safe_source_stays_safe_and_resolvable(db, cast, local_storage):
    """Inheritance is conservative in ONE direction only.

    It can make a derived asset ineligible; it can never make one eligible,
    because every marker it copies excludes. An ordinary crop is unaffected.
    """
    source = _source_asset(db, cast, provider="google", metadata={"library": True})
    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.UPLOADED, source=source, metadata={"avatar_crop": True},
    )
    db.commit()

    assert is_public_surface_safe(crop)
    assert resolve_public_media_url(db, crop.file_path) == crop.file_path
    assert crop.provider == "google"


def test_provenance_inheritance_never_copies_a_safety_decision(db, cast, local_storage):
    """Evidence is inheritable. A decision is not.

    ``safety_state`` records that a policy of a stated version judged specific
    bytes. Copying one onto different bytes would be a fabricated decision, and
    it is exactly what ``SAFETY_STATE_APPROVED`` documents must never happen by
    inference. The crop starts unreviewed however its source was decided.
    """
    source = _source_asset(db, cast)
    source.safety_state = SAFETY_STATE_APPROVED
    source.safety_policy_version = 1
    source.safety_decision_source = "human"
    from datetime import datetime, timezone
    source.safety_decided_at = datetime.now(timezone.utc)
    db.commit()

    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.UPLOADED, source=source,
    )
    db.commit()

    assert crop.safety_state == SAFETY_STATE_UNREVIEWED
    assert crop.safety_policy_version == SAFETY_POLICY_VERSION_NONE


def test_derived_provenance_reads_the_three_signals_and_no_others(db, cast, local_storage):
    """The helper, directly — it is the whole of the laundering defence."""
    source = _source_asset(
        db, cast, provider="self_hosted",
        metadata={"editor_generated": True, "provider": "self_hosted",
                  "prompt": "a private prompt", "strength": 0.4},
    )
    provider, fragment = derived_provenance(source)

    assert provider == "self_hosted"
    assert fragment == {"provider": "self_hosted", "editor_generated": True}
    # The source's prompt and parameters are NOT the derived asset's, and are
    # not copied: this carries exclusion markers, not a payload.
    assert "prompt" not in fragment
    assert "strength" not in fragment


def test_a_derived_asset_with_no_identifiable_source_inherits_nothing(db, cast, local_storage):
    crop = persist_derived_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.IDENTITY_FACE_REF, source=None,
        metadata={"source": "evolution_promote"},
    )
    db.commit()
    assert crop.provider is None
    assert crop.derived_from_image_id is None
    assert "derived_from" not in (crop.metadata_json or {})


# ── safety_state is still inert ──────────────────────────────────────────────


def test_safety_state_is_not_an_eligibility_gate(db, cast, local_storage):
    """Unchanged by 4D2, and asserted so it stays that way until 4E.

    Every row 4D2 creates is ``unreviewed``. If ``unreviewed`` were consulted by
    the public predicate, this migration would have silently hidden every newly
    written asset; if ``rejected`` were consulted, 4E would already be live.
    Neither is true — presentation is still decided by provenance alone.
    """
    image = _source_asset(db, cast, provider="google")
    assert image.safety_state == SAFETY_STATE_UNREVIEWED
    assert is_public_surface_safe(image)

    image.safety_state = "rejected"
    image.safety_policy_version = 1
    image.safety_decision_source = "human"
    from datetime import datetime, timezone
    image.safety_decided_at = datetime.now(timezone.utc)
    db.commit()

    assert is_public_surface_safe(image), (
        "safety_state became an eligibility gate — that is Phase 4E, and it "
        "must be a deliberate change with its own enforcement review"
    )


# ── transactions ─────────────────────────────────────────────────────────────


def test_a_rollback_after_the_writer_removes_both_the_row_and_the_object(
    db, cast, local_storage
):
    """The compensation 4D1 built, exercised through a 4D2 call shape.

    Every migrated writer now flushes its row inside the caller's transaction
    and commits later — sometimes several statements later, as in the
    body-slot routes that update ``identity_anchor_json`` after persisting.
    A failure in between must leave neither half.
    """
    image = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.SCENE_ONLY, provider="google",
    )
    image_id = image.id
    assert len(_objects(local_storage)) == 1

    db.rollback()

    assert db.query(CharacterImage).filter(CharacterImage.id == image_id).first() is None
    assert _objects(local_storage) == []


def test_closing_without_committing_removes_both_halves(db, cast, local_storage, session_factory):
    """The path FastAPI actually takes.

    ``get_db`` closes the session in its ``finally`` and never rolls back
    explicitly, so a route that raises after persisting resolves its
    transaction by CLOSING it. Both halves still have to go.
    """
    session = session_factory()
    character = session.get(Character, cast["character"].id)
    image = persist_image_asset(
        session, content=PNG, owner=OwnedBy.character(character),
        kind=ImageKindEnum.GENERATED, provider="stub",
    )
    image_id = image.id
    assert len(_objects(local_storage)) == 1

    session.close()

    assert db.query(CharacterImage).filter(CharacterImage.id == image_id).first() is None
    assert _objects(local_storage) == []


def test_the_archive_then_insert_order_leaves_the_new_row_active(db, cast, local_storage):
    """Why the migrated slot writers archive BEFORE they persist.

    The body-identity slot routes and the body_front autogen both run a bulk
    UPDATE matching ``(character_id, kind)``. The canonical writer flushes, so a
    row inserted first is matched by that UPDATE and archived on the spot — the
    old order was safe only because ``save_image`` left nothing to find.
    """
    old = persist_image_asset(
        db, content=PNG, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.IDENTITY_BODY_FRONT, provider="auto_generated",
    )
    db.commit()

    db.query(CharacterImage).filter(
        CharacterImage.character_id == cast["character"].id,
        CharacterImage.kind == ImageKindEnum.IDENTITY_BODY_FRONT,
    ).update({"status": ImageStatusEnum.ARCHIVED})
    new = persist_image_asset(
        db, content=CROP, owner=OwnedBy.character(cast["character"]),
        kind=ImageKindEnum.IDENTITY_BODY_FRONT, provider="auto_generated",
    )
    db.commit()

    db.refresh(old)
    assert old.status == ImageStatusEnum.ARCHIVED
    assert new.status == ImageStatusEnum.ACTIVE


# ── 4C: a character's deletion does not take its owner's assets ──────────────


def test_character_deletion_detaches_rather_than_deletes_the_asset(db, cast, local_storage):
    """4C's behaviour, re-asserted over rows 4D2 writes.

    Every migrated writer uses ``OwnedBy.character``, so every row it creates
    carries both an owner and an association. Deleting the character must clear
    the association and leave the asset with its owner — not remove it.
    """
    image = _source_asset(db, cast)
    image_id = image.id

    db.delete(db.get(Character, cast["character"].id))
    db.commit()

    survivor = db.query(CharacterImage).filter(CharacterImage.id == image_id).first()
    assert survivor is not None
    assert survivor.character_id is None
    assert survivor.user_id == cast["owner"].id


# ── the editor's job snapshot is deliberately NOT an asset ───────────────────


def test_the_editor_source_snapshot_creates_no_row(db, cast, local_storage):
    """Rowlessness as a STATED intention rather than an omission.

    ``POST /editor/jobs`` copies the source image so the detached driver reads a
    stable path even if the original is deleted. Those bytes are job scratch: a
    duplicate of something the owner already has, whose lifetime is one
    operation, which nobody browses and nobody publishes. Giving it a
    ``CharacterImage`` row would put a copy of every edited source into the
    owner's library.

    ``put_transient_object`` demands a ``purpose``, so the difference between
    this and a durable asset is a decision somebody made at the call site, not a
    function that happened to be shorter to call.
    """
    before = db.query(CharacterImage).count()
    file_path = storage.put_transient_object(
        PNG, purpose="editor_job_source_snapshot"
    )

    assert db.query(CharacterImage).count() == before
    assert file_path
    assert len(_objects(local_storage)) == 1
    # The stored path is still resolvable by the driver, exactly as before.
    assert storage.load_image_bytes(file_path) == PNG


def test_transient_bytes_cannot_be_written_without_saying_why(local_storage):
    with pytest.raises(ValueError, match="requires a purpose"):
        storage.put_transient_object(PNG, purpose="")


def test_the_editor_job_route_uses_the_transient_writer(local_storage):
    """Structural, because the property is about which function is called.

    A future edit that swapped this back to a durable write would satisfy every
    behavioural assertion above — the job would still run — while silently
    adding one library row per edit. What is being pinned is the CHOICE.
    """
    import ast
    from pathlib import Path as _Path

    module = _Path(__file__).resolve().parent.parent / "app" / "api" / "routes" / "editor_studio.py"
    tree = ast.parse(module.read_text())
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "put_transient_object" in called
    assert "save_image" not in called

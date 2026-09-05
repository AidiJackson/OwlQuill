"""Every CharacterImage must have an owning account (Phase 4B2).

``user_id`` is NOT NULL and its foreign key is ``ON DELETE RESTRICT``. Two
guarantees follow, and they are tested separately because they are enforced by
different things:

* **No ownerless row can be created.** NOT NULL, enforced by the column.
* **No account can be deleted out from under its assets.** RESTRICT, enforced
  by the foreign key — and only when the delete actually reaches the foreign
  key. Phase 4C removed the ORM cascade that used to walk around it, so
  ``test_orm_account_delete_is_now_refused`` proves the refusal is reached.

These tests use their own engine with ``PRAGMA foreign_keys=ON``. SQLite ignores
foreign keys unless asked, so the shared ``db_session`` fixture would report a
passing RESTRICT test that proves nothing at all.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User


@pytest.fixture()
def fk_engine(tmp_path):
    """A throwaway database that actually enforces foreign keys."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fk.db'}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(fk_engine):
    return sessionmaker(bind=fk_engine)


@pytest.fixture()
def owned_asset(session_factory):
    """One account, one character, one owned image with a full row of state."""
    db = session_factory()
    try:
        owner = User(email="owner@constraint.example.com", username="cowner",
                     hashed_password="x")
        bystander = User(email="other@constraint.example.com", username="cother",
                         hashed_password="x")
        db.add_all([owner, bystander])
        db.flush()

        character = Character(owner_id=owner.id, name="Constraint Character")
        db.add(character)
        db.flush()

        image = CharacterImage(
            character_id=character.id,
            user_id=owner.id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider="stub",
            prompt_summary="a summary",
            seed="seed-1",
            metadata_json={"library": True},
            file_path="static/generated/constraint.png",
            storage_key="generated/constraint.png",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        db.add(image)
        db.commit()
        return {
            "owner_id": owner.id,
            "bystander_id": bystander.id,
            "character_id": character.id,
            "image_id": image.id,
        }
    finally:
        db.close()


# ── the schema itself ────────────────────────────────────────────────────────


def test_user_id_is_not_null_with_on_delete_restrict(fk_engine):
    """The model agrees with what migration p4b02 puts on the database."""
    columns = {c["name"]: c for c in inspect(fk_engine).get_columns("character_images")}
    assert columns["user_id"]["nullable"] is False

    fk = next(
        fk for fk in inspect(fk_engine).get_foreign_keys("character_images")
        if fk["constrained_columns"] == ["user_id"]
    )
    assert fk["referred_table"] == "users"
    assert fk["options"].get("ondelete") == "RESTRICT"


def test_ownership_and_association_are_different_rules(fk_engine):
    """The two columns say different things and must not converge.

    This assertion used to read "4B2 changes ownership only; association stays
    exactly as it was" and pinned ``character_id`` as NOT NULL/CASCADE. That was
    true of 4B2 and is no longer true of the schema: Phase 4C made association
    optional. What survives from the original intent — and what is worth pinning
    permanently — is that the two columns are governed by DIFFERENT rules, so
    neither phase's change can quietly be applied to the other column::

        user_id      mandatory, RESTRICT   ownership
        character_id optional,  SET NULL   association

    The 4C half is proven in full in ``test_optional_character_association.py``;
    it is asserted here so that re-tightening ``character_id``, or loosening
    ``user_id``, fails in the ownership suite too.
    """
    columns = {c["name"]: c for c in inspect(fk_engine).get_columns("character_images")}
    assert columns["user_id"]["nullable"] is False
    assert columns["character_id"]["nullable"] is True

    fks = {
        tuple(fk["constrained_columns"]): fk
        for fk in inspect(fk_engine).get_foreign_keys("character_images")
    }
    assert fks[("user_id",)]["options"].get("ondelete") == "RESTRICT"
    assert fks[("character_id",)]["options"].get("ondelete") == "SET NULL"


def test_no_orm_relationship_navigates_from_user_to_character_images():
    """Choosing RESTRICT at the database means not undoing it in the ORM.

    A ``User.<x>`` relationship to CharacterImage with a delete cascade would
    make SQLAlchemy delete the rows itself, so the foreign key would never be
    asked and the refusal would never happen.
    """
    targets = {
        rel.mapper.class_ for rel in inspect(User).relationships
    }
    assert CharacterImage not in targets


# ── account deletion: the RESTRICT ───────────────────────────────────────────


def test_raw_delete_of_an_owner_is_refused_by_the_database(session_factory, owned_asset):
    """The database refuses, not the application.

    Deliberately raw SQL: this is the guarantee that holds for code nobody has
    written yet, including a psql session. It is a different and stronger claim
    than ``scripts/reset_account.py`` refusing, which is an application check
    that a future script could simply not perform.
    """
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": owned_asset["owner_id"]},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_the_asset_survives_a_refused_account_deletion(session_factory, owned_asset):
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": owned_asset["owner_id"]},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        image = db.get(CharacterImage, owned_asset["image_id"])
        assert image is not None
        # Ownership itself: not detached, not nulled.
        assert image.user_id == owned_asset["owner_id"]
        # Association, safety audit, storage identity and provenance columns.
        assert image.character_id == owned_asset["character_id"]
        assert image.safety_state == SAFETY_STATE_UNREVIEWED
        assert image.safety_policy_version == 0
        assert image.file_path == "static/generated/constraint.png"
        assert image.storage_key == "generated/constraint.png"
        assert image.provider == "stub"
        assert image.seed == "seed-1"
        assert image.metadata_json == {"library": True}
        assert image.created_at == datetime(2026, 1, 1, 12, 0, 0)
        # And the account is still there, so nothing half-happened.
        assert db.get(User, owned_asset["owner_id"]) is not None
    finally:
        db.close()


def test_a_refused_deletion_cannot_produce_a_null_owner(session_factory, owned_asset):
    """The failure mode the old ``SET NULL`` had: silently detached assets."""
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": owned_asset["owner_id"]},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        nulls = db.execute(
            text("SELECT count(*) FROM character_images WHERE user_id IS NULL")
        ).scalar_one()
        assert nulls == 0
    finally:
        db.close()


def test_deleting_an_account_that_owns_nothing_still_works(session_factory, owned_asset):
    """RESTRICT is about assets, not about accounts."""
    db = session_factory()
    try:
        db.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": owned_asset["bystander_id"]},
        )
        db.commit()
        assert db.get(User, owned_asset["bystander_id"]) is None
        # The owner and their asset are untouched by an unrelated deletion.
        assert db.get(CharacterImage, owned_asset["image_id"]) is not None
    finally:
        db.close()


def test_an_owner_becomes_deletable_once_the_assets_are_gone(session_factory, owned_asset):
    """The refusal is a gate, not a permanent lock on the account."""
    db = session_factory()
    try:
        db.execute(
            text("DELETE FROM character_images WHERE id = :iid"),
            {"iid": owned_asset["image_id"]},
        )
        db.execute(
            text("DELETE FROM characters WHERE id = :cid"),
            {"cid": owned_asset["character_id"]},
        )
        db.execute(
            text("DELETE FROM users WHERE id = :uid"), {"uid": owned_asset["owner_id"]}
        )
        db.commit()
        assert db.get(User, owned_asset["owner_id"]) is None
    finally:
        db.close()


def test_orm_account_delete_is_now_refused(session_factory, owned_asset):
    """Phase 4C closed the gap this test used to pin open.

    It previously asserted the OPPOSITE: that ``Session.delete(user)``
    succeeded, because ``User.characters`` and ``Character.images`` were both
    ``all, delete-orphan``, so SQLAlchemy deleted the image rows itself and
    ``DELETE FROM users`` found nothing referencing the account. The RESTRICT
    was real and unreachable. That test carried an instruction to invert the
    day the cascade changed; 4C is that day.

    ``Character.images`` no longer cascades deletes, so the image row survives
    the character, still referencing the account — and the foreign key is
    finally the thing that answers. ``User.characters`` was NOT changed and is
    still ``all, delete-orphan``: the bypass was always the second hop.
    """
    db = session_factory()
    try:
        user = db.get(User, owned_asset["owner_id"])
        with pytest.raises(IntegrityError):
            db.delete(user)
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        assert db.get(User, owned_asset["owner_id"]) is not None
        image = db.get(CharacterImage, owned_asset["image_id"])
        assert image is not None
        assert image.user_id == owned_asset["owner_id"]
        # The whole attempt rolled back together, so the character deletion
        # that the ORM had already emitted did not survive either.
        assert image.character_id == owned_asset["character_id"]
    finally:
        db.close()


# ── insert behaviour: the NOT NULL ───────────────────────────────────────────


def test_raw_insert_without_an_owner_is_rejected(session_factory, owned_asset):
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO character_images "
                    "(character_id, user_id, kind, status, visibility, file_path, "
                    " created_at, public_gallery_enabled, safety_state, "
                    " safety_policy_version) "
                    "VALUES (:cid, NULL, 'generated', 'active', 'private', "
                    "        'static/generated/ownerless.png', :now, 0, "
                    "        'unreviewed', 0)"
                ),
                {"cid": owned_asset["character_id"], "now": datetime.utcnow()},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_orm_insert_without_an_owner_is_rejected(session_factory, owned_asset):
    db = session_factory()
    try:
        db.add(
            CharacterImage(
                character_id=owned_asset["character_id"],
                kind=ImageKindEnum.GENERATED,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                file_path="static/generated/orm-ownerless.png",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_insert_naming_an_account_that_does_not_exist_is_rejected(
    session_factory, owned_asset
):
    """NOT NULL alone would accept a fabricated id; the FK is what refuses it."""
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO character_images "
                    "(character_id, user_id, kind, status, visibility, file_path, "
                    " created_at, public_gallery_enabled, safety_state, "
                    " safety_policy_version) "
                    "VALUES (:cid, 999999, 'generated', 'active', 'private', "
                    "        'static/generated/ghost.png', :now, 0, "
                    "        'unreviewed', 0)"
                ),
                {"cid": owned_asset["character_id"], "now": datetime.utcnow()},
            )
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_a_refused_insert_leaves_existing_rows_untouched(session_factory, owned_asset):
    """Rows that were backfilled earlier keep their owner through a failed write."""
    db = session_factory()
    try:
        db.add(
            CharacterImage(
                character_id=owned_asset["character_id"],
                kind=ImageKindEnum.GENERATED,
                status=ImageStatusEnum.ACTIVE,
                visibility=ImageVisibilityEnum.PRIVATE,
                file_path="static/generated/doomed.png",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        image = db.get(CharacterImage, owned_asset["image_id"])
        assert image.user_id == owned_asset["owner_id"]
        assert db.query(CharacterImage).count() == 1
    finally:
        db.close()


def test_an_owned_insert_succeeds(session_factory, owned_asset):
    db = session_factory()
    try:
        image = CharacterImage(
            character_id=owned_asset["character_id"],
            user_id=owned_asset["owner_id"],
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path="static/generated/owned.png",
        )
        db.add(image)
        db.commit()
        assert image.id is not None
        assert image.user_id == owned_asset["owner_id"]
    finally:
        db.close()

"""An asset may outlive its character (Phase 4C).

    user_id      = ownership   — mandatory, RESTRICT
    character_id = association — optional,  SET NULL

Deleting a character drops the association and keeps the asset: its owner, its
safety decision, its provenance, its lineage, its storage pointer and its
lifecycle all survive. Deleting an ACCOUNT is refused, because the images that
now survive still reference it — which is the refusal Phase 4B2 built and could
not reach while the ORM deleted those rows first.

Most of this cannot be proven on the shared ``db_session`` fixture: SQLite
ignores foreign keys unless asked, so a ``SET NULL`` test there would pass
without the database doing anything. The schema/deletion tests below use their
own engine with ``PRAGMA foreign_keys=ON``; the API tests use the shared client
because they are about routes, not about the database.
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
from app.models.editor_job import EditorJob
from app.models.image_generation_job import ImageGenerationJob
from app.models.user import User
from tests.conftest import auth_headers, character_owner_id, get_auth_token


# ── database-level fixtures (foreign keys actually enforced) ─────────────────


@pytest.fixture()
def fk_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'assoc.db'}")

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
def scene(session_factory):
    """One owner, one character, one fully-populated image, one job of each kind."""
    db = session_factory()
    try:
        owner = User(email="assoc-owner@test.local", username="assocowner",
                     hashed_password="x")
        bystander = User(email="assoc-other@test.local", username="assocother",
                         hashed_password="x")
        db.add_all([owner, bystander])
        db.flush()

        character = Character(owner_id=owner.id, name="Doomed Character")
        db.add(character)
        db.flush()

        parent = CharacterImage(
            character_id=character.id, user_id=owner.id,
            kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE, file_path="static/generated/parent.png",
            created_at=datetime(2026, 1, 1, 9, 0, 0),
        )
        db.add(parent)
        db.flush()

        image = CharacterImage(
            character_id=character.id,
            user_id=owner.id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            public_gallery_enabled=True,
            provider="stub",
            prompt_summary="a summary",
            seed="seed-4c",
            metadata_json={"library": True},
            file_path="static/generated/assoc.png",
            storage_key="generated/assoc.png",
            derived_from_image_id=parent.id,
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        db.add(image)
        db.flush()

        gen_job = ImageGenerationJob(
            public_id="pub4c", user_id=owner.id, character_id=character.id,
            status="completed", idempotency_key="idem-4c", image_id=image.id,
        )
        editor_job = EditorJob(
            character_id=character.id, user_id=bystander.id,
            prompt="p", provider="self_hosted", state="completed",
            run_id="run-4c", image_id=image.id,
        )
        db.add_all([gen_job, editor_job])
        db.commit()

        return {
            "owner_id": owner.id,
            "bystander_id": bystander.id,
            "character_id": character.id,
            "image_id": image.id,
            "parent_id": parent.id,
            "gen_job_id": gen_job.id,
            "editor_job_id": editor_job.id,
        }
    finally:
        db.close()


# ── the schema and the ORM ───────────────────────────────────────────────────


def test_character_id_is_optional_with_on_delete_set_null(fk_engine):
    columns = {c["name"]: c for c in inspect(fk_engine).get_columns("character_images")}
    assert columns["character_id"]["nullable"] is True

    fk = next(
        fk for fk in inspect(fk_engine).get_foreign_keys("character_images")
        if fk["constrained_columns"] == ["character_id"]
    )
    assert fk["referred_table"] == "characters"
    assert fk["options"].get("ondelete") == "SET NULL"


def test_user_id_is_untouched_by_this_phase(fk_engine):
    """4C changes association only. Ownership stays exactly as 4B2 left it."""
    columns = {c["name"]: c for c in inspect(fk_engine).get_columns("character_images")}
    assert columns["user_id"]["nullable"] is False

    fk = next(
        fk for fk in inspect(fk_engine).get_foreign_keys("character_images")
        if fk["constrained_columns"] == ["user_id"]
    )
    assert fk["options"].get("ondelete") == "RESTRICT"


@pytest.mark.parametrize("table", ["image_generation_jobs", "editor_jobs"])
def test_job_tables_keep_their_requester_when_the_character_goes(fk_engine, table):
    """The job row is the requester of record; it must outlive the association."""
    columns = {c["name"]: c for c in inspect(fk_engine).get_columns(table)}
    assert columns["character_id"]["nullable"] is True
    assert columns["user_id"]["nullable"] is False

    fk = next(
        fk for fk in inspect(fk_engine).get_foreign_keys(table)
        if fk["constrained_columns"] == ["character_id"]
    )
    assert fk["options"].get("ondelete") == "SET NULL"


def test_character_images_relationship_does_not_cascade_deletes():
    cascade = inspect(Character).relationships["images"].cascade
    assert "delete" not in cascade
    assert "delete-orphan" not in cascade
    assert "save-update" in cascade and "merge" in cascade


def test_passive_deletes_is_off_so_the_orm_does_the_nulling():
    """Deliberate: see the comment on ``Character.images``.

    With ``passive_deletes=True`` the nulling would be delegated to the database
    FK, which the shared SQLite fixture does not enforce — the suite would go
    green while proving nothing.
    """
    assert inspect(Character).relationships["images"].passive_deletes is False


def test_user_characters_relationship_is_deliberately_unchanged():
    """4C did not need to touch it, and pinning that says so."""
    cascade = inspect(User).relationships["characters"].cascade
    assert "delete" in cascade and "delete-orphan" in cascade


def test_index_on_character_id_survives(fk_engine):
    names = {ix["name"] for ix in inspect(fk_engine).get_indexes("character_images")}
    assert "ix_character_images_character_id" in names


# ── deleting a character preserves the asset ─────────────────────────────────


def _delete_character_via_orm(session_factory, character_id):
    db = session_factory()
    try:
        db.delete(db.get(Character, character_id))
        db.commit()
    finally:
        db.close()


def _delete_character_via_raw_sql(session_factory, character_id):
    db = session_factory()
    try:
        db.execute(text("DELETE FROM characters WHERE id = :cid"), {"cid": character_id})
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize(
    "delete", [_delete_character_via_orm, _delete_character_via_raw_sql],
    ids=["orm", "raw-sql"],
)
def test_deleting_a_character_preserves_the_asset_entirely(
    session_factory, scene, delete
):
    """Both routes must agree, and for different reasons.

    The ORM path proves the relationship no longer cascades. The raw-SQL path
    proves the DATABASE rule — the guarantee that holds for a psql session, a
    bulk delete, or any code nobody has written yet. If only the ORM were fixed,
    the second of these would still destroy the row.
    """
    delete(session_factory, scene["character_id"])

    db = session_factory()
    try:
        image = db.get(CharacterImage, scene["image_id"])
        assert image is not None

        # association gone, ownership intact
        assert image.character_id is None
        assert image.user_id == scene["owner_id"]

        # the full 4A safety audit
        assert image.safety_state == SAFETY_STATE_UNREVIEWED
        assert image.safety_policy_version == 0
        assert image.safety_decided_at is None
        assert image.safety_decided_by is None
        assert image.safety_decision_source is None
        assert image.safety_reason is None

        # provenance
        assert image.provider == "stub"
        assert image.seed == "seed-4c"
        assert image.prompt_summary == "a summary"
        assert image.metadata_json == {"library": True}

        # lineage — and the parent it points at survived too
        assert image.derived_from_image_id == scene["parent_id"]
        assert db.get(CharacterImage, scene["parent_id"]) is not None

        # storage
        assert image.file_path == "static/generated/assoc.png"
        assert image.storage_key == "generated/assoc.png"

        # lifecycle
        assert image.status == ImageStatusEnum.ACTIVE
        assert image.visibility == ImageVisibilityEnum.PRIVATE
        assert image.kind == ImageKindEnum.GENERATED
        assert image.created_at == datetime(2026, 1, 1, 12, 0, 0)

        # the character really is gone
        assert db.get(Character, scene["character_id"]) is None
    finally:
        db.close()


def test_creator_gallery_selection_is_not_cleared(session_factory, scene):
    """Deliberate: the flag is a creator's choice, not a derived value.

    It is unreachable anyway — the gallery route is character-scoped and the
    character is gone — so clearing it would destroy a decision to no effect.
    """
    _delete_character_via_orm(session_factory, scene["character_id"])
    db = session_factory()
    try:
        assert db.get(CharacterImage, scene["image_id"]).public_gallery_enabled is True
    finally:
        db.close()


def test_job_records_survive_the_character(session_factory, scene):
    """The requester of record outlives the association it was created under."""
    _delete_character_via_orm(session_factory, scene["character_id"])

    db = session_factory()
    try:
        gen = db.get(ImageGenerationJob, scene["gen_job_id"])
        assert gen is not None
        assert gen.character_id is None
        assert gen.user_id == scene["owner_id"]
        assert gen.image_id == scene["image_id"]

        editor = db.get(EditorJob, scene["editor_job_id"])
        assert editor is not None
        assert editor.character_id is None
        # The editor job's requester was NOT the owner — that distinction is
        # exactly what this row exists to preserve (see Phase 4B2).
        assert editor.user_id == scene["bystander_id"]
        assert editor.user_id != scene["owner_id"]
    finally:
        db.close()


# ── deleting the account is now genuinely refused ────────────────────────────


def test_account_deletion_is_refused_and_rolls_back_atomically(session_factory, scene):
    db = session_factory()
    try:
        with pytest.raises(IntegrityError):
            db.delete(db.get(User, scene["owner_id"]))
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        assert db.get(User, scene["owner_id"]) is not None
        # The character deletion the ORM had already emitted rolled back too.
        assert db.get(Character, scene["character_id"]) is not None
        image = db.get(CharacterImage, scene["image_id"])
        assert image is not None
        assert image.user_id == scene["owner_id"]
        assert image.character_id == scene["character_id"]
    finally:
        db.close()


def test_an_account_owning_only_characterless_assets_is_still_refused(
    session_factory, scene
):
    """The refusal is about ownership, not about characters."""
    _delete_character_via_orm(session_factory, scene["character_id"])

    db = session_factory()
    try:
        assert db.get(CharacterImage, scene["image_id"]).character_id is None
        with pytest.raises(IntegrityError):
            db.delete(db.get(User, scene["owner_id"]))
            db.commit()
        db.rollback()
    finally:
        db.close()

    db = session_factory()
    try:
        assert db.get(User, scene["owner_id"]) is not None
        assert db.get(CharacterImage, scene["image_id"]) is not None
    finally:
        db.close()


def test_no_ownerless_image_can_be_created(session_factory, scene):
    """4B2's guarantee must not regress under the new column shape."""
    db = session_factory()
    try:
        db.add(CharacterImage(
            character_id=None,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path="static/generated/ownerless-4c.png",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_a_characterless_owned_image_is_a_legal_row(session_factory, scene):
    """The shape Phase 4D's account avatar will need."""
    db = session_factory()
    try:
        image = CharacterImage(
            character_id=None,
            user_id=scene["owner_id"],
            derived_from_image_id=scene["image_id"],
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path="static/generated/account-level.png",
        )
        db.add(image)
        db.commit()
        assert image.id is not None
        assert image.character_id is None
        assert image.user_id == scene["owner_id"]
        assert image.derived_from_image_id == scene["image_id"]
        assert image.safety_state == SAFETY_STATE_UNREVIEWED
    finally:
        db.close()


# ── API behaviour: the library, the scoping, the archive ─────────────────────
#
# These run on the shared client/db_session fixtures because they are about
# routes. The characterless state is produced the way production produces it —
# by deleting the character — and that works here without SQLite foreign keys
# because ``passive_deletes`` is False, so the ORM issues the UPDATE itself.


def _orphan_one_image(client, db_session, email, username):
    """Owner with two characters; the first is deleted, orphaning its image.

    Both characters are inserted directly rather than through ``POST
    /characters/``: the route enforces a per-account creation cooldown
    (``next_character_allowed_at``), and this test needs two characters, not a
    test of that cooldown.
    """
    token = get_auth_token(client, email=email, username=username)
    owner_id = db_session.query(User).filter(User.email == email).one().id

    doomed_row = Character(owner_id=owner_id, name="Doomed")
    kept_row = Character(owner_id=owner_id, name="Kept")
    db_session.add_all([doomed_row, kept_row])
    db_session.commit()
    doomed, kept = doomed_row.id, kept_row.id

    image = CharacterImage(
        character_id=doomed,
        user_id=character_owner_id(db_session, doomed),
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        metadata_json={"library": True},
        file_path="static/generated/orphaned.png",
    )
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)
    image_id = image.id

    db_session.delete(db_session.get(Character, doomed))
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(CharacterImage, image_id).character_id is None

    return token, kept, image_id


def test_characterless_asset_stays_in_the_owners_library(client, db_session):
    token, _kept, image_id = _orphan_one_image(
        client, db_session, "lib4c@test.com", "lib4c"
    )
    resp = client.get("/users/me/character-images", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    rows = {r["id"]: r for r in resp.json()}
    assert image_id in rows
    assert rows[image_id]["character_id"] is None


def test_characterless_asset_stays_in_the_library_images_endpoint(client, db_session):
    token, _kept, image_id = _orphan_one_image(
        client, db_session, "lib4c2@test.com", "lib4c2"
    )
    resp = client.get("/images/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert image_id in {r["id"] for r in resp.json()}


def test_the_quota_still_counts_a_characterless_asset(client, db_session):
    """Quota is keyed on the owning account, so losing a character costs nothing
    and earns nothing."""
    from app.services.image_quota import get_quota_status

    token, _kept, image_id = _orphan_one_image(
        client, db_session, "quota4c@test.com", "quota4c"
    )
    user = db_session.get(User, db_session.get(CharacterImage, image_id).user_id)
    status_before = get_quota_status(user, db_session)
    if status_before.get("unlimited"):
        pytest.skip("account is quota-exempt; nothing to count")
    assert status_before["used"] >= 1


def test_another_character_cannot_see_the_characterless_asset(client, db_session):
    """Same owner, different character — association scoping still holds."""
    token, kept, image_id = _orphan_one_image(
        client, db_session, "scope4c@test.com", "scope4c"
    )
    resp = client.get(f"/characters/{kept}/images", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert image_id not in {r["id"] for r in resp.json()}

    filtered = client.get(
        f"/users/me/character-images?character_id={kept}", headers=auth_headers(token)
    )
    assert filtered.status_code == 200
    assert image_id not in {r["id"] for r in filtered.json()}


def test_the_deleted_characters_surfaces_are_gone(client, db_session):
    token = get_auth_token(client, email="gone4c@test.com", username="gone4c")
    cid = client.post(
        "/characters/", json={"name": "Vanishing", "species": "human"},
        headers=auth_headers(token),
    ).json()["id"]
    db_session.delete(db_session.get(Character, cid))
    db_session.commit()

    assert client.get(f"/characters/{cid}/public-home/images").status_code == 404
    assert client.get(f"/characters/{cid}/images",
                      headers=auth_headers(token)).status_code == 404


def test_no_route_can_reassociate_an_asset(client):
    """Deliberate absence. Re-association is a product decision nobody has made."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if "character-images" in path or "/images/" in path:
            assert "reassociate" not in path
            assert "associate" not in path


# ── the account-scoped archive ───────────────────────────────────────────────


def test_the_owner_can_archive_a_characterless_asset(client, db_session):
    """The gap this route exists to close: no character, no character URL."""
    token, _kept, image_id = _orphan_one_image(
        client, db_session, "arch4c@test.com", "arch4c"
    )
    resp = client.delete(
        f"/users/me/character-images/{image_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    row = db_session.get(CharacterImage, image_id)
    # Archived, not destroyed: every column that mattered is still here.
    assert row is not None
    assert row.status == ImageStatusEnum.ARCHIVED
    assert row.user_id is not None
    assert row.file_path == "static/generated/orphaned.png"

    listed = client.get("/users/me/character-images", headers=auth_headers(token))
    assert image_id not in {r["id"] for r in listed.json()}


def test_the_account_archive_also_works_for_an_associated_asset(client, db_session):
    token = get_auth_token(client, email="arch4c2@test.com", username="arch4c2")
    cid = client.post(
        "/characters/", json={"name": "Still Here", "species": "human"},
        headers=auth_headers(token),
    ).json()["id"]
    image = CharacterImage(
        character_id=cid, user_id=character_owner_id(db_session, cid),
        kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE, file_path="static/generated/assoc-arch.png",
    )
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)

    resp = client.delete(
        f"/users/me/character-images/{image.id}", headers=auth_headers(token)
    )
    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert db_session.get(CharacterImage, image.id).status == ImageStatusEnum.ARCHIVED


def test_the_account_archive_refuses_someone_elses_asset_as_404(client, db_session):
    """404, not 403: a 403 would confirm the row exists in another library."""
    _token, _kept, image_id = _orphan_one_image(
        client, db_session, "victim4c@test.com", "victim4c"
    )
    intruder = get_auth_token(client, email="intruder4c@test.com", username="intruder4c")

    resp = client.delete(
        f"/users/me/character-images/{image_id}", headers=auth_headers(intruder)
    )
    assert resp.status_code == 404
    db_session.expire_all()
    assert db_session.get(CharacterImage, image_id).status == ImageStatusEnum.ACTIVE


def test_the_account_archive_still_protects_the_identity_anchors(client, db_session):
    token = get_auth_token(client, email="anchor4c@test.com", username="anchor4c")
    cid = client.post(
        "/characters/", json={"name": "Anchored", "species": "human"},
        headers=auth_headers(token),
    ).json()["id"]
    anchor = CharacterImage(
        character_id=cid, user_id=character_owner_id(db_session, cid),
        kind=ImageKindEnum.ANCHOR_FRONT, status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE, file_path="static/generated/anchor4c.png",
    )
    db_session.add(anchor)
    db_session.commit()
    db_session.refresh(anchor)

    resp = client.delete(
        f"/users/me/character-images/{anchor.id}", headers=auth_headers(token)
    )
    assert resp.status_code == 422
    assert "anchor" in resp.json()["detail"].lower()
    db_session.expire_all()
    assert db_session.get(CharacterImage, anchor.id).status == ImageStatusEnum.ACTIVE


def test_the_character_scoped_archive_stays_association_scoped(client, db_session):
    """It must NOT gain the ability to reach a characterless asset."""
    token, kept, image_id = _orphan_one_image(
        client, db_session, "scoped4c@test.com", "scoped4c"
    )
    resp = client.delete(
        f"/characters/{kept}/images/{image_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 404
    db_session.expire_all()
    assert db_session.get(CharacterImage, image_id).status == ImageStatusEnum.ACTIVE


# ── public / shared surfaces ─────────────────────────────────────────────────


def test_a_surviving_asset_still_resolves_for_shared_surfaces(client, db_session):
    """The regression 4C repairs.

    Before 4C the row was destroyed with the character, so a post attachment or
    an ACCOUNT avatar pointing at that file resolved to no rows — and both
    resolvers withhold an unresolvable URL by design. The reference silently
    went blank. Now the row survives and the reference keeps working.
    """
    from app.services.character_home_media import (
        resolve_public_media_url,
        resolve_public_post_image_url,
    )

    _token, _kept, image_id = _orphan_one_image(
        client, db_session, "shared4c@test.com", "shared4c"
    )
    url = "/static/generated/orphaned.png"

    assert resolve_public_media_url(db_session, url) == url
    assert resolve_public_post_image_url(db_session, url) == url

    row = db_session.get(CharacterImage, image_id)
    assert row.character_id is None


def test_an_unsafe_characterless_asset_is_still_withheld(client, db_session):
    """Losing a character is not a way to launder provenance."""
    from app.services.character_home_media import resolve_public_media_url

    token = get_auth_token(client, email="unsafe4c@test.com", username="unsafe4c")
    cid = client.post(
        "/characters/", json={"name": "Unsafe Source", "species": "human"},
        headers=auth_headers(token),
    ).json()["id"]
    image = CharacterImage(
        character_id=cid, user_id=character_owner_id(db_session, cid),
        kind=ImageKindEnum.GENERATED, status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="replicate_nsfw",
        file_path="static/generated/unsafe4c.png",
    )
    db_session.add(image)
    db_session.commit()
    db_session.refresh(image)
    image_id = image.id

    db_session.delete(db_session.get(Character, cid))
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(CharacterImage, image_id).character_id is None

    assert resolve_public_media_url(
        db_session, "/static/generated/unsafe4c.png"
    ) is None


def test_an_archived_characterless_asset_is_withheld_from_posts(client, db_session):
    """Archiving is the owner's delete, and it still suppresses the attachment."""
    from app.services.character_home_media import resolve_public_post_image_url

    token, _kept, image_id = _orphan_one_image(
        client, db_session, "postarch4c@test.com", "postarch4c"
    )
    client.delete(
        f"/users/me/character-images/{image_id}", headers=auth_headers(token)
    )
    db_session.expire_all()
    assert resolve_public_post_image_url(
        db_session, "/static/generated/orphaned.png"
    ) is None

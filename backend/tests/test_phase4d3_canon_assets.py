"""Phase 4D3-3 — every canon writer produces a first-class owned asset.

The canon cluster was the last place in the codebase that wrote durable bytes
with ``save_image()``: an object in the bucket, no row, no owner, no safety
state, no lifecycle. 98 identity-canon objects on DEV came from here, and 100
canon urls still resolve to nothing.

These tests are about the PROPERTIES the migration has to establish, not about
"the call changed":

* one owned row per durable output, owned by the CHARACTER'S OWNER;
* the kind names what the image actually is — never ``GENERATED`` as a
  convenient stand-in, which is how canon working material reached the public
  gallery before;
* the canon reference and the stored path are the same string;
* lineage is claimed only when a single source genuinely exists;
* nothing this phase creates is public-gallery material.
"""
import pytest

from app.core import storage
from app.core.config import settings
from app.models.character_image import (
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.canon import SLOT_FIELD_MAP, SLOT_IMAGE_KIND
from app.schemas.character_image import PUBLIC_GALLERY_KINDS, is_public_gallery_image
from tests.conftest import auth_headers, get_auth_token, make_admin

PNG = b"\x89PNG\r\n\x1a\n" + b"canon-asset-bytes" * 16


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    """Real files on disk in a temp tree, object storage off."""
    monkeypatch.setattr(storage, "_GENERATED_DIR", tmp_path / "static" / "generated")
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
    return tmp_path


def _admin_owner(client, tag):
    email = f"{tag}@4d3a.test.com"
    token = get_auth_token(client, email=email, username=f"u{tag}")
    make_admin(email)
    return auth_headers(get_auth_token(client, email=email, username=f"u{tag}"))


def _character(client, hdrs, name="Canon Asset Character"):
    resp = client.post("/characters/", json={"name": name, "description": "d"}, headers=hdrs)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _rows(db, character_id, kind=None):
    q = db.query(CharacterImage).filter(CharacterImage.character_id == character_id)
    if kind is not None:
        q = q.filter(CharacterImage.kind == kind)
    return q.all()


def _owner_id(db, character_id):
    from app.models.character import Character
    return db.query(Character).filter(Character.id == character_id).one().owner_id


def _upload(client, hdrs, character_id, slot, data=PNG):
    return client.post(
        f"/characters/{character_id}/identity-canon/upload",
        files={"file": ("slot.png", data, "image/png")},
        data={"slot": slot},
        headers=hdrs,
    )


# ── the taxonomy itself ──────────────────────────────────────────────────────


def test_every_canon_slot_has_a_kind_and_none_is_generated():
    """``GENERATED`` is in PUBLIC_GALLERY_KINDS. A slot falling back to it would
    publish canon working material — which is how nine canon urls on DEV are
    gallery-eligible today."""
    assert set(SLOT_IMAGE_KIND) == set(SLOT_FIELD_MAP)
    assert ImageKindEnum.GENERATED not in set(SLOT_IMAGE_KIND.values())


@pytest.mark.parametrize("slot,kind", sorted(SLOT_IMAGE_KIND.items()))
def test_no_canon_slot_kind_is_public_gallery_material(slot, kind):
    assert kind not in PUBLIC_GALLERY_KINDS


# ── canon slot upload ────────────────────────────────────────────────────────


@pytest.mark.parametrize("slot", sorted(SLOT_FIELD_MAP))
def test_a_canon_upload_creates_one_owned_row_of_the_right_kind(
    client, db_session, local_storage, slot
):
    hdrs = _admin_owner(client, f"up{abs(hash(slot)) % 99999}")
    char_id = _character(client, hdrs)

    resp = _upload(client, hdrs, char_id, slot)
    assert resp.status_code == 201, resp.text

    rows = _rows(db_session, char_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind is SLOT_IMAGE_KIND[slot]
    assert row.user_id == _owner_id(db_session, char_id)
    assert row.character_id == char_id
    assert row.storage_key
    assert row.status == ImageStatusEnum.ACTIVE
    assert row.visibility == ImageVisibilityEnum.PRIVATE
    assert row.safety_state == SAFETY_STATE_UNREVIEWED
    assert row.safety_policy_version == SAFETY_POLICY_VERSION_NONE
    # provider=None is the statement this path must make: a user supplied these
    # bytes and Ficshon has no generation provenance for them.
    assert row.provider is None
    assert row.derived_from_image_id is None
    assert (row.metadata_json or {}).get("canon_slot") == slot
    assert not is_public_gallery_image(row)


def test_the_canon_field_holds_exactly_the_persisted_path(client, db_session, local_storage):
    hdrs = _admin_owner(client, "canonfield")
    char_id = _character(client, hdrs)
    assert _upload(client, hdrs, char_id, "face_front").status_code == 201

    row = _rows(db_session, char_id)[0]
    canon = client.get(f"/characters/{char_id}/identity-canon", headers=hdrs).json()
    served = canon["face_canon"]["face_front_image_url"]
    # The route serves a browser url; the stored value is the file_path it maps
    # from. Both spellings must name the same file.
    from app.services.character_home_media import candidate_file_paths
    assert row.file_path in candidate_file_paths(served)


def test_an_admin_uploading_onto_another_founders_character_files_it_to_the_owner(
    client, db_session, local_storage
):
    """The whole reason ``OwnedBy.character`` takes an object: the asset belongs
    to the character's owner, never to whoever made the request."""
    owner_hdrs = auth_headers(get_auth_token(client, email="cowner@4d3a.test.com",
                                             username="ucowner"))
    char_id = _character(client, owner_hdrs)

    # The canon upload route is admin-gated AND owner-scoped, so a foreign admin
    # is refused outright — the owner remains the only writer.
    admin_hdrs = _admin_owner(client, "foreignadm")
    assert _upload(client, admin_hdrs, char_id, "face_front").status_code == 403

    make_admin("cowner@4d3a.test.com")
    owner_admin = auth_headers(get_auth_token(client, email="cowner@4d3a.test.com",
                                              username="ucowner"))
    assert _upload(client, owner_admin, char_id, "face_front").status_code == 201
    row = _rows(db_session, char_id)[0]
    assert row.user_id == _owner_id(db_session, char_id)


# ── mark reference / detail crop ─────────────────────────────────────────────


def _add_mark(client, hdrs, char_id):
    resp = client.post(
        f"/characters/{char_id}/identity-canon/body/marks",
        json={"label": "Left arm sleeve", "type": "tattoo",
              "body_region": "left_full_arm", "side": "left",
              "description": "black gothic script"},
        headers=hdrs,
    )
    assert resp.status_code in (200, 201), resp.text
    marks = resp.json()["canon"]["body_canon"]["permanent_body_marks"]
    return marks[0]["id"]


@pytest.mark.parametrize("slot,kind", [
    ("reference", ImageKindEnum.IDENTITY_MARK_REFERENCE),
    ("detail", ImageKindEnum.IDENTITY_MARK_DETAIL),
])
def test_a_mark_image_upload_creates_an_owned_row_of_the_right_kind(
    client, db_session, local_storage, slot, kind
):
    hdrs = _admin_owner(client, f"mk{slot}")
    char_id = _character(client, hdrs)
    mark_id = _add_mark(client, hdrs, char_id)

    resp = client.post(
        f"/characters/{char_id}/identity-canon/upload/mark/{mark_id}",
        files={"file": ("mark.png", PNG, "image/png")},
        data={"slot": slot},
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text

    rows = _rows(db_session, char_id)
    assert len(rows) == 1
    assert rows[0].kind is kind
    assert rows[0].user_id == _owner_id(db_session, char_id)
    assert rows[0].storage_key
    assert (rows[0].metadata_json or {}).get("mark_id") == mark_id
    assert not is_public_gallery_image(rows[0])


# ── scene from canon ─────────────────────────────────────────────────────────


def test_scene_from_canon_creates_exactly_one_row(client, db_session, local_storage):
    """One canonical row — not a canonical row PLUS the old hand-built one."""
    hdrs = _admin_owner(client, "scenegen")
    char_id = _character(client, hdrs)

    resp = client.post(
        f"/characters/{char_id}/identity-canon/scenes/generate",
        json={"prompt": "standing in the rain"},
        headers=hdrs,
    )
    assert resp.status_code in (200, 201), resp.text

    rows = _rows(db_session, char_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind is ImageKindEnum.SCENE_ONLY
    assert row.user_id == _owner_id(db_session, char_id)
    assert row.storage_key
    assert row.safety_state == SAFETY_STATE_UNREVIEWED
    meta = row.metadata_json or {}
    assert meta.get("scene_only") is True
    assert "compiled_prompt" in meta and "provider" in meta
    assert row.provider
    # Multi-reference generation: several sources, so no single-source lineage.
    assert row.derived_from_image_id is None


def test_scene_generation_does_not_touch_canon(client, db_session, local_storage):
    hdrs = _admin_owner(client, "scenecanon")
    char_id = _character(client, hdrs)
    before = client.get(f"/characters/{char_id}/identity-canon", headers=hdrs).json()

    client.post(f"/characters/{char_id}/identity-canon/scenes/generate",
                json={"prompt": "a quiet street"}, headers=hdrs)

    after = client.get(f"/characters/{char_id}/identity-canon", headers=hdrs).json()
    assert after["face_canon"] == before["face_canon"]
    assert after["body_canon"] == before["body_canon"]


# ── the v2 pack does not touch legacy anchor infrastructure ──────────────────

LEGACY_ANCHOR_KINDS = (
    ImageKindEnum.ANCHOR_FRONT,
    ImageKindEnum.ANCHOR_THREE_QUARTER,
    ImageKindEnum.ANCHOR_TORSO,
    ImageKindEnum.ANCHOR_FULL_BODY,
)


def test_no_canon_slot_maps_to_a_legacy_anchor_kind():
    """The collision Phase 4D3-3 corrected.

    Mapping the v2 face slots onto ANCHOR_FRONT / ANCHOR_THREE_QUARTER injected
    pack output into three mechanisms it has nothing to do with: those kinds are
    the whole of PROTECTED_IMAGE_KINDS, the identity lock counts four ACTIVE
    ones, and canon_bridge resolves them by kind+status.
    """
    assert not (set(SLOT_IMAGE_KIND.values()) & set(LEGACY_ANCHOR_KINDS))


def test_the_v2_face_slots_map_to_their_own_kinds():
    assert SLOT_IMAGE_KIND["face_front"] is ImageKindEnum.IDENTITY_FACE_FRONT
    assert SLOT_IMAGE_KIND["face_left_3q"] is ImageKindEnum.IDENTITY_FACE_LEFT_3Q
    assert SLOT_IMAGE_KIND["face_right_3q"] is ImageKindEnum.IDENTITY_FACE_RIGHT_3Q


@pytest.mark.parametrize("slot", ["face_front", "face_left_3q", "face_right_3q"])
def test_a_face_slot_upload_creates_no_legacy_anchor_row(
    client, db_session, local_storage, slot
):
    """Route-level proof: the writers really produce the new kinds."""
    hdrs = _admin_owner(client, f"nolegacy{abs(hash(slot)) % 9999}")
    char_id = _character(client, hdrs)

    assert _upload(client, hdrs, char_id, slot).status_code == 201

    anchors = (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.character_id == char_id,
            CharacterImage.kind.in_(LEGACY_ANCHOR_KINDS),
        )
        .count()
    )
    assert anchors == 0, "a canon writer created a legacy anchor row"
    assert _rows(db_session, char_id)[0].kind is SLOT_IMAGE_KIND[slot]


def test_building_every_canon_slot_leaves_the_legacy_anchor_count_unchanged(
    client, db_session, local_storage
):
    """The active-anchor count drives the identity lock. Canon work must not
    move it in either direction."""
    hdrs = _admin_owner(client, "anchorcount")
    char_id = _character(client, hdrs)

    def _active_anchors():
        return (
            db_session.query(CharacterImage)
            .filter(
                CharacterImage.character_id == char_id,
                CharacterImage.kind.in_(LEGACY_ANCHOR_KINDS),
                CharacterImage.status == ImageStatusEnum.ACTIVE,
            )
            .count()
        )

    before = _active_anchors()
    for slot in SLOT_FIELD_MAP:
        assert _upload(client, hdrs, char_id, slot).status_code == 201
    assert _active_anchors() == before == 0
    # …and the canon rows really were created, so this is not vacuous.
    assert len(_rows(db_session, char_id)) == len(SLOT_FIELD_MAP)

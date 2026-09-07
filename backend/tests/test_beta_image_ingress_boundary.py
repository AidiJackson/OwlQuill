"""The closed-beta image-ingress boundary — Phase Beta Boundary 1.

THE PRODUCT RULE UNDER TEST: an ordinary user brings the CHARACTER as text and
Ficshon creates its visual identity. An ordinary user does not supply image
bytes, and does not supply image URLs that Ficshon did not itself produce.
Admin and Seeder are the deliberate internal exception and keep every
image-input capability they have.

WHY THIS FILE EXISTS SEPARATELY FROM THE ROUTE SUITES. The refusals live on
endpoints whose other behaviour is already covered — Editor Studio mechanics in
test_editor_studio.py, canon writes in test_canon_rebuild.py, the candidate-slot
lifecycle in test_candidate_slot.py, identity accessories in
test_identity_accessory.py. What is NOT covered anywhere else is the
boundary as a single rule: that the same four accounts get the same four answers
on every ingress, that the text half of each endpoint keeps working, and that
nothing reaches a provider on the way to a refusal. Splitting those assertions
across the route suites would make the rule invisible in exactly the way that
lets one endpoint quietly drift out of it.

NO PROVIDER IS EVER CALLED HERE. The refusal tests assert that positively
(``mock_get.assert_not_called()``), which is the property that actually matters:
"403" and "403 after the bytes were already on the wire" look identical in a
status code and are not the same guarantee.
"""
import io

import pytest
from fastapi.testclient import TestClient

from app.core.image_ingress import (
    guard_supplied_image_fields,
    may_supply_image_input,
    supplied_image_fields,
)
from tests.conftest import (
    TestingSessionLocal,
    auth_headers,
    character_owner_id,
    get_auth_token,
    make_admin,
    make_seeder,
)

EDITOR_ENDPOINT = "/editor/generate"
GET_EDITOR = "app.api.routes.editor_studio.get_editor"

#: Minimal valid 1x1 PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4e0000000049454e44ae426082"
)

_EXTERNAL_URL = "https://evil.example.com/a-real-persons-face.jpg"


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Deterministic local disk storage (env may default to R2)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Account helpers ───────────────────────────────────────────────────────────


def _creator(client: TestClient, email: str, username: str) -> tuple[str, int]:
    """An ORDINARY one-character Creator — the outsider beta persona.

    Deliberately built the way the boundary's premise says it is built: a plain
    registration plus one character, which is all it takes to pass
    ``require_creator``. If that ever stops being true this fixture is where it
    shows up.
    """
    token = get_auth_token(client, email=email, username=username)
    resp = client.post(
        "/characters/",
        json={"name": f"{username} Char", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()["id"]


def _seeder(client: TestClient, email: str, username: str) -> tuple[str, int]:
    token, cid = _creator(client, email, username)
    make_seeder(email)
    return token, cid


def _admin(client: TestClient, email: str, username: str) -> tuple[str, int]:
    token, cid = _creator(client, email, username)
    make_admin(email)
    return token, cid


def _wanderer(client: TestClient, email: str, username: str) -> str:
    """A registered account with no character and no unlock."""
    return get_auth_token(client, email=email, username=username)


def _user(email: str):
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        return db.query(User).filter(User.email == email).one()
    finally:
        db.close()


def _seed_image(cid: int, *, status=None, character_id: int | None = None):
    """One real ACTIVE ``CharacterImage`` for *cid*, owned by *cid*'s owner."""
    from app.core.storage import save_image
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    db = TestingSessionLocal()
    try:
        img = CharacterImage(
            character_id=character_id if character_id is not None else cid,
            user_id=character_owner_id(db, cid),
            kind=ImageKindEnum.SCENE_ONLY,
            status=status or ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path=save_image(_PNG_BYTES),
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return img.id, img.file_path
    finally:
        db.close()


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    """Take a character through the ordinary text-driven identity lock."""
    hdrs = auth_headers(token)
    resp = client.post(f"/characters/{cid}/identity-pack/generate", json={}, headers=hdrs)
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": resp.json()["pack_id"]},
        headers=hdrs,
    )
    assert resp.status_code == 200, resp.text


def _png_upload(name: str = "face-claim.png"):
    return ("images", (name, io.BytesIO(_PNG_BYTES), "image/png"))


def _editor_form(cid: int, **overrides) -> dict:
    data = {
        "character_id": str(cid),
        "prompt": "same character, different scene",
        "provider": "gpt-image",
        "strength": "0.25",
    }
    data.update({k: str(v) for k, v in overrides.items()})
    return data


def _assert_boundary_refusal(resp) -> None:
    """The uniform refusal shape, asserted once so all guarded routes must agree."""
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "user_supplied_image_input_closed", detail
    assert detail["fields"], "the refusal must name the offending field(s)"


# ── 1. The policy table ───────────────────────────────────────────────────────
#
# The whole beta rule in one place. When Seeder's status is decided, THIS is the
# test that changes — and a single-line change in image_ingress.py is what makes
# it pass, which is the point of routing every guard through one predicate.


def test_policy_table_admin_and_seeder_may_supply_image_input(client):
    _admin(client, "bib_admin@test.com", "bibadmin")
    _seeder(client, "bib_seeder@test.com", "bibseeder")

    assert may_supply_image_input(_user("bib_admin@test.com")) is True
    assert may_supply_image_input(_user("bib_seeder@test.com")) is True


def test_policy_table_ordinary_creator_and_wanderer_may_not(client):
    _creator(client, "bib_creator@test.com", "bibcreator")
    _wanderer(client, "bib_wanderer@test.com", "bibwanderer")

    creator = _user("bib_creator@test.com")
    wanderer = _user("bib_wanderer@test.com")

    assert may_supply_image_input(creator) is False
    assert may_supply_image_input(wanderer) is False

    # The premise the boundary rests on, asserted rather than assumed: the
    # ordinary creator IS a creator by the entitlement system's own reckoning.
    # If require_creator ever stopped admitting them, this boundary would be
    # closing a door nobody could reach and the failure should be loud.
    from app.core.entitlements import can_use_creator_tools

    db = TestingSessionLocal()
    try:
        assert can_use_creator_tools(db, db.merge(creator)) is True
        assert can_use_creator_tools(db, db.merge(wanderer)) is False
    finally:
        db.close()


def test_policy_table_unauthenticated_is_refused():
    """``None`` is not a founder. Guards against a truthiness slip in a
    predicate whose callers may hold an optional user."""
    assert may_supply_image_input(None) is False


# ── 2. The field detector ─────────────────────────────────────────────────────


def test_supplied_image_fields_reads_what_the_client_sent():
    """Explicit null is not a supplied image; empty string is.

    The writers dump with ``exclude_none=True``, so a null writes nothing and
    there is nothing to refuse. ``""`` IS written, so "supplied something falsy"
    must not be a way through.
    """
    from app.schemas.canon import FaceCanonUpdate

    fields = ("face_front_image_url", "face_left_3q_image_url")

    assert supplied_image_fields(FaceCanonUpdate(), fields) == []
    assert supplied_image_fields(FaceCanonUpdate(face_description="x"), fields) == []
    assert supplied_image_fields(
        FaceCanonUpdate.model_validate({"face_front_image_url": None}), fields
    ) == []
    assert supplied_image_fields(
        FaceCanonUpdate.model_validate({"face_front_image_url": ""}), fields
    ) == ["face_front_image_url"]
    assert supplied_image_fields(
        FaceCanonUpdate.model_validate({"face_front_image_url": _EXTERNAL_URL}), fields
    ) == ["face_front_image_url"]


def test_guard_admits_a_founder_and_refuses_everyone_else(client):
    """The guard composes the two questions in the right order.

    Written against the helper rather than a route so the composition is pinned
    independently of any endpoint's own validation.
    """
    from fastapi import HTTPException

    from app.schemas.canon import FaceCanonUpdate

    _seeder(client, "bib_guard_s@test.com", "bibguards")
    _creator(client, "bib_guard_c@test.com", "bibguardc")
    payload = FaceCanonUpdate.model_validate({"face_front_image_url": _EXTERNAL_URL})
    fields = ("face_front_image_url",)

    # Founder: passes.
    guard_supplied_image_fields(_user("bib_guard_s@test.com"), payload, fields)
    # Non-founder supplying nothing image-shaped: passes.
    guard_supplied_image_fields(
        _user("bib_guard_c@test.com"), FaceCanonUpdate(face_description="x"), fields
    )
    # Non-founder supplying an image URL: refused.
    with pytest.raises(HTTPException) as exc:
        guard_supplied_image_fields(_user("bib_guard_c@test.com"), payload, fields)
    assert exc.value.status_code == 403


# ── 3. The field lists cannot silently fall behind the schemas ────────────────


def test_canon_image_field_lists_cover_every_url_field_on_their_schemas():
    """A canon image field added to a schema must be added to the guard list.

    Derived from the schemas rather than hand-copied, so this fails the moment
    somebody introduces a new ``*_image_url`` / ``*_crop_url`` on one of the four
    guarded request bodies without deciding whether it is conditioning input.
    Deliberately a test and not the implementation: a suffix rule in production
    code would adopt future fields silently, which is how a boundary stops being
    a decision and becomes an accident.
    """
    from app.api.routes.canon_api import (
        ACCESSORY_IMAGE_FIELDS,
        BODY_CANON_IMAGE_FIELDS,
        FACE_CANON_IMAGE_FIELDS,
        MARK_IMAGE_FIELDS,
    )
    from app.schemas.canon import (
        AddAccessoryRequest,
        AddPermanentMarkRequest,
        BodyCanonUpdate,
        FaceCanonUpdate,
    )

    def url_fields(model) -> set[str]:
        return {
            name
            for name in model.model_fields
            if name.endswith("_url")
        }

    assert url_fields(FaceCanonUpdate) == set(FACE_CANON_IMAGE_FIELDS)
    assert url_fields(BodyCanonUpdate) == set(BODY_CANON_IMAGE_FIELDS)
    assert url_fields(AddPermanentMarkRequest) == set(MARK_IMAGE_FIELDS)
    assert url_fields(AddAccessoryRequest) == set(ACCESSORY_IMAGE_FIELDS)

    # The v1 identity-accessory route keeps its own list on its own module —
    # a different request body writing a different store, so a shared constant
    # would tie two independent decisions together.
    from app.api.routes.character_accessory import (
        ACCESSORY_IMAGE_FIELDS as V1_ACCESSORY_IMAGE_FIELDS,
        AccessoryCreateRequest,
    )

    assert url_fields(AccessoryCreateRequest) == set(V1_ACCESSORY_IMAGE_FIELDS)


def test_guarded_canon_schemas_declare_no_field_aliases():
    """``model_fields_set`` is alias-proof, but the guard lists are name-matched.

    Pinning "no aliases here" keeps the two facts from having to be reasoned
    about together: as long as it holds, a field's wire name and its guard-list
    name are the same string.
    """
    from app.schemas.canon import (
        AddAccessoryRequest,
        AddPermanentMarkRequest,
        BodyCanonUpdate,
        FaceCanonUpdate,
    )

    from app.api.routes.character_accessory import AccessoryCreateRequest

    for model in (
        FaceCanonUpdate,
        BodyCanonUpdate,
        AddPermanentMarkRequest,
        AddAccessoryRequest,
        AccessoryCreateRequest,
    ):
        for name, field in model.model_fields.items():
            assert field.alias is None, f"{model.__name__}.{name} declares an alias"
            assert field.validation_alias is None, f"{model.__name__}.{name}"


# ── 4. Ordinary Creator is refused on every canon ingress ─────────────────────


def test_creator_cannot_set_a_face_canon_image_url(client):
    token, cid = _creator(client, "bib_face@test.com", "bibface")
    resp = client.patch(
        f"/characters/{cid}/identity-canon/face",
        json={"face_front_image_url": _EXTERNAL_URL},
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp)
    assert resp.json()["detail"]["fields"] == ["face_front_image_url"]

    # And nothing was written: the canon must not carry a slot the caller was
    # refused. A 403 that still persisted the URL would be the worst outcome.
    got = client.get(
        f"/characters/{cid}/identity-canon", headers=auth_headers(token)
    ).json()
    assert not (got.get("face_canon") or {}).get("face_front_image_url")


def test_creator_cannot_set_a_body_canon_image_url(client):
    token, cid = _creator(client, "bib_body@test.com", "bibbody")
    resp = client.patch(
        f"/characters/{cid}/identity-canon/body",
        json={"body_front_image_url": _EXTERNAL_URL, "build": "lean"},
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp)
    # The legitimate text field travelling alongside does NOT get written either
    # — the whole request is refused, so a client cannot smuggle a URL through
    # by pairing it with an edit the caller is entitled to make.
    got = client.get(
        f"/characters/{cid}/identity-canon", headers=auth_headers(token)
    ).json()
    body_canon = got.get("body_canon") or {}
    assert not body_canon.get("body_front_image_url")
    assert body_canon.get("build") in (None, "")


def test_creator_cannot_set_a_mark_reference_image(client):
    token, cid = _creator(client, "bib_mark@test.com", "bibmark")
    for field in ("reference_image_url", "detail_crop_url"):
        resp = client.post(
            f"/characters/{cid}/identity-canon/body/marks",
            json={
                "label": "Left sleeve",
                "type": "tattoo",
                "body_region": "left_full_arm",
                "side": "left",
                "description": "black ink serpent from shoulder to wrist",
                field: _EXTERNAL_URL,
            },
            headers=auth_headers(token),
        )
        _assert_boundary_refusal(resp)
        assert resp.json()["detail"]["fields"] == [field]


def test_creator_cannot_set_an_accessory_anchor_image(client):
    token, cid = _creator(client, "bib_acc@test.com", "bibacc")
    for field in ("design_anchor_image_url", "fit_anchor_image_url"):
        resp = client.post(
            f"/characters/{cid}/identity-canon/accessories",
            json={
                "label": "Venetian mask",
                "type": "mask",
                "description": "ornate white and gold half-mask",
                field: _EXTERNAL_URL,
            },
            headers=auth_headers(token),
        )
        _assert_boundary_refusal(resp)
        assert resp.json()["detail"]["fields"] == [field]


# ── 4b. Identity accessories (v1) — the same rule on a sibling route ─────────
#
# ``POST /{id}/identity-accessory`` writes ``identity_anchor_json["accessories"]``
# rather than canon, and its ``anchor_image_url`` is NOT a
# ``load_image_bytes`` conditioning sink today. It is guarded anyway: it is the
# same product question, and "not a sink yet" is a fact about the current call
# graph rather than a boundary. The generate-anchor route writes the same field
# with a URL Ficshon produced and is deliberately untouched.


def _accessory_payload(**overrides) -> dict:
    payload = {
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask covering the lower face",
        "visual_rules": ["Matte black metal", "Riveted edges"],
    }
    payload.update(overrides)
    return payload


def test_creator_can_still_create_an_identity_accessory_from_text(client):
    """The legitimate half: everything except the supplied image."""
    token, cid = _creator(client, "bib_ia_ok@test.com", "bibiaok")
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json=_accessory_payload(),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    mask = next(a for a in resp.json()["accessories"] if a["type"] == "mask")
    assert mask["name"] == "Iron Mask"
    assert mask["description"] == "A heavy iron mask covering the lower face"
    assert mask["visual_rules"] == ["Matte black metal", "Riveted edges"]
    assert mask["locked"] is True
    assert mask["anchor_image_url"] is None


def test_creator_cannot_supply_an_identity_accessory_anchor_image(client):
    """Same refusal shape as every other ingress — one rule, not five."""
    token, cid = _creator(client, "bib_ia_no@test.com", "bibiano")
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json=_accessory_payload(anchor_image_url=_EXTERNAL_URL),
        headers=auth_headers(token),
    )
    _assert_boundary_refusal(resp)
    assert resp.json()["detail"]["fields"] == ["anchor_image_url"]

    # Nothing was written — not the URL, and not the accessory that carried it.
    listed = client.post(
        f"/characters/{cid}/identity-accessory",
        json=_accessory_payload(name="Clean Mask"),
        headers=auth_headers(token),
    ).json()["accessories"]
    assert all(a.get("anchor_image_url") is None for a in listed)


def test_creator_accessory_refusal_is_a_server_side_decision(client):
    """Direct API invocation, no client involved.

    The route still EXISTS for this account — it answers 200 for the same call
    without the image field — so the refusal is authorization, not the endpoint
    having been taken away. That distinction is what makes it a boundary rather
    than a removed feature.
    """
    token, cid = _creator(client, "bib_ia_api@test.com", "bibiaapi")
    hdrs = auth_headers(token)
    url = f"/characters/{cid}/identity-accessory"

    assert client.post(url, json=_accessory_payload(), headers=hdrs).status_code == 200
    refused = client.post(
        url, json=_accessory_payload(anchor_image_url=_EXTERNAL_URL), headers=hdrs
    )
    assert refused.status_code == 403, refused.text
    assert refused.status_code != 404


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_may_still_supply_an_accessory_anchor_image(client, role):
    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bib_ia_{role}@test.com", f"bibia{role}")

    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json=_accessory_payload(anchor_image_url="https://cdn.example.com/mask.png"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    mask = next(a for a in resp.json()["accessories"] if a["type"] == "mask")
    assert mask["anchor_image_url"] == "https://cdn.example.com/mask.png"


def test_accessory_anchor_generation_is_unaffected_for_an_ordinary_creator(client):
    """The GENERATED route to the same field is untouched.

    This is the half the boundary must not break: an ordinary creator describes
    the accessory and Ficshon produces its anchor. Only SUPPLYING one closed.
    """
    from unittest.mock import MagicMock, patch

    token, cid = _creator(client, "bib_ia_gen@test.com", "bibiagen")
    hdrs = auth_headers(token)

    created = client.post(
        f"/characters/{cid}/identity-accessory", json=_accessory_payload(), headers=hdrs
    )
    assert created.status_code == 200, created.text
    acc_id = next(a for a in created.json()["accessories"] if a["type"] == "mask")["id"]

    provider = MagicMock()
    provider.generate_image = MagicMock(return_value=_PNG_BYTES)
    with patch(
        "app.api.routes.character_accessory.get_provider_for_option",
        return_value=provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-accessory/generate-anchor",
            json={"accessory_id": acc_id},
            headers=hdrs,
        )
    assert resp.status_code == 200, resp.text
    accessory = resp.json()["accessory"]
    assert accessory["anchor_status"] == "generated"
    assert accessory["anchor_image_url"], "generation must still fill the anchor slot"
    provider.generate_image.assert_called_once()


# ── 5. The TEXT half of those same endpoints still works ─────────────────────
#
# The reason the boundary is per-field and not per-route. A creator's written
# canon is the beta's whole premise; closing it would be the opposite of the
# product rule.


def test_creator_can_still_write_text_canon_and_marks_and_accessories(client):
    token, cid = _creator(client, "bib_text@test.com", "bibtext")
    hdrs = auth_headers(token)

    resp = client.patch(
        f"/characters/{cid}/identity-canon/face",
        json={"face_description": "sharp jaw, grey eyes, a broken nose"},
        headers=hdrs,
    )
    assert resp.status_code == 200, resp.text

    resp = client.patch(
        f"/characters/{cid}/identity-canon/body",
        json={"build": "lean", "skin_tone": "olive", "body_description": "wiry"},
        headers=hdrs,
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"/characters/{cid}/identity-canon/body/marks",
        json={
            "label": "Left sleeve",
            "type": "tattoo",
            "body_region": "left_full_arm",
            "side": "left",
            "description": "black ink serpent from shoulder to wrist",
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f"/characters/{cid}/identity-canon/accessories",
        json={
            "label": "Venetian mask",
            "type": "mask",
            "description": "ornate white and gold half-mask",
            "trigger_keywords": ["mask", "masked"],
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text

    got = client.get(f"/characters/{cid}/identity-canon", headers=hdrs).json()
    assert got["face_canon"]["face_description"] == "sharp jaw, grey eyes, a broken nose"
    assert got["body_canon"]["build"] == "lean"
    assert len(got["body_canon"]["permanent_body_marks"]) == 1
    assert len(got["accessories"]) == 1


# ── 6. Founder/Seeder keep every canon image capability ──────────────────────


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_may_still_supply_canon_image_urls(client, role):
    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bib_f_{role}@test.com", f"bibf{role}")
    hdrs = auth_headers(token)

    assert client.patch(
        f"/characters/{cid}/identity-canon/face",
        json={"face_front_image_url": "https://cdn.example.com/face.png"},
        headers=hdrs,
    ).status_code == 200

    assert client.patch(
        f"/characters/{cid}/identity-canon/body",
        json={"body_front_image_url": "https://cdn.example.com/body.png"},
        headers=hdrs,
    ).status_code == 200

    assert client.post(
        f"/characters/{cid}/identity-canon/body/marks",
        json={
            "label": "Left sleeve",
            "type": "tattoo",
            "body_region": "left_full_arm",
            "side": "left",
            "description": "black ink serpent",
            "reference_image_url": "https://cdn.example.com/mark.png",
        },
        headers=hdrs,
    ).status_code == 201

    assert client.post(
        f"/characters/{cid}/identity-canon/accessories",
        json={
            "label": "Mask",
            "type": "mask",
            "description": "half-mask",
            "design_anchor_image_url": "https://cdn.example.com/acc.png",
        },
        headers=hdrs,
    ).status_code == 201

    got = client.get(f"/characters/{cid}/identity-canon", headers=hdrs).json()
    assert got["face_canon"]["face_front_image_url"]
    assert got["body_canon"]["body_front_image_url"]


# ── 7. Candidate slot: resolution, not trust ─────────────────────────────────


def test_candidate_slot_accepts_an_owned_active_asset(client):
    token, cid = _creator(client, "bib_cs_ok@test.com", "bibcsok")
    _lock_character(client, token, cid)
    _image_id, file_path = _seed_image(cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": file_path},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["image_url"] == file_path


def test_candidate_slot_accepts_the_servable_spelling_of_an_owned_asset(client):
    """``file_path_to_url`` is not injective, and the client renders the servable
    form. Both spellings must resolve to the same row — and what is STORED is the
    row's own canonical ``file_path``, never the spelling that arrived."""
    from app.core.storage import file_path_to_url

    token, cid = _creator(client, "bib_cs_url@test.com", "bibcsurl")
    _lock_character(client, token, cid)
    _image_id, file_path = _seed_image(cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": file_path_to_url(file_path)},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["image_url"] == file_path


def test_candidate_slot_refuses_an_arbitrary_external_url(client):
    """The SSRF / face-claim primitive. ``promote`` copies this string into
    ``identity_anchor_json``, which ``load_image_bytes`` later fetches and hands
    to an image provider."""
    token, cid = _creator(client, "bib_cs_ext@test.com", "bibcsext")
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": _EXTERNAL_URL},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "own active images" in resp.json()["detail"]


def test_candidate_slot_refuses_a_bare_storage_filename(client):
    """With object storage on, a bare filename is read as a BUCKET KEY. Refusing
    it here is what stops the endpoint being a cross-account object read."""
    token, cid = _creator(client, "bib_cs_key@test.com", "bibcskey")
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "somebody-elses-object.png"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


def test_candidate_slot_refuses_another_characters_asset(client):
    """Same ACCOUNT, different character. Owning the asset is not enough — the
    candidate replaces THIS character's identity anchor."""
    token, cid = _seeder(client, "bib_cs_other@test.com", "bibcsother")
    _lock_character(client, token, cid)
    resp = client.post(
        "/characters/",
        json={"name": "Second Char", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    other_cid = resp.json()["id"]
    _image_id, other_path = _seed_image(other_cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": other_path},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


def test_candidate_slot_refuses_another_accounts_asset(client):
    token_a, cid_a = _creator(client, "bib_cs_a@test.com", "bibcsa")
    _lock_character(client, token_a, cid_a)
    _token_b, cid_b = _creator(client, "bib_cs_b@test.com", "bibcsb")
    _image_id, b_path = _seed_image(cid_b)

    resp = client.post(
        f"/characters/{cid_a}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": b_path},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 422, resp.text


def test_candidate_slot_refuses_an_archived_asset(client):
    from app.models.character_image import ImageStatusEnum

    token, cid = _creator(client, "bib_cs_arch@test.com", "bibcsarch")
    _lock_character(client, token, cid)
    _image_id, path = _seed_image(cid, status=ImageStatusEnum.ARCHIVED)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": path},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


def test_candidate_slot_resolution_applies_to_founders_too(client):
    """Not a role check. A founder's own reference images ARE rows, so the
    invariant costs them nothing — and closing the URL primitive for everyone is
    what closes it for the operator account an attacker would most like to have.
    """
    token, cid = _seeder(client, "bib_cs_f@test.com", "bibcsf")
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": _EXTERNAL_URL},
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


# ── 8. Editor Studio: uploads closed, library ids open ───────────────────────


def test_creator_upload_is_refused_without_calling_the_provider(client):
    """THE assertion this file exists for. A 403 issued after the bytes reached
    the provider would look identical in a status code and be a different
    guarantee entirely."""
    from unittest.mock import patch

    token, cid = _creator(client, "bib_ed_c@test.com", "biedc")
    with patch(GET_EDITOR) as mock_get:
        resp = client.post(
            EDITOR_ENDPOINT,
            data=_editor_form(cid),
            files=[_png_upload()],
            headers=auth_headers(token),
        )
    _assert_boundary_refusal(resp)
    assert resp.json()["detail"]["fields"] == ["images"]
    mock_get.assert_not_called()


def test_creator_upload_refusal_does_not_depend_on_owning_the_character(client):
    """The refusal is about the ACCOUNT and the PAYLOAD, so it lands before the
    character is even looked up — which also means it cannot be used to probe
    which character ids exist."""
    from unittest.mock import patch

    token, _cid = _creator(client, "bib_ed_probe@test.com", "biedprobe")
    with patch(GET_EDITOR) as mock_get:
        resp = client.post(
            EDITOR_ENDPOINT,
            data=_editor_form(999999),
            files=[_png_upload()],
            headers=auth_headers(token),
        )
    _assert_boundary_refusal(resp)
    mock_get.assert_not_called()


def test_creator_can_still_edit_their_own_ficshon_generated_image(client):
    """``source_image_ids`` stays open: these are rows Ficshon produced, and
    editing them is what Editor Studio is FOR."""
    from unittest.mock import MagicMock, patch

    token, cid = _creator(client, "bib_ed_ids@test.com", "biedids")
    image_id, _path = _seed_image(cid)

    editor = MagicMock()
    editor.editor_version = "e1"
    editor.edit = MagicMock(return_value=_PNG_BYTES)
    with patch(GET_EDITOR, return_value=editor):
        resp = client.post(
            EDITOR_ENDPOINT,
            data=_editor_form(cid, source_image_ids=str(image_id)),
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image"]["metadata_json"]["source_image_ids"] == [image_id]
    # The existing non-public semantics are untouched by this increment.
    assert body["image"]["metadata_json"]["editor_generated"] is True


def test_creator_source_image_ids_are_still_scoped_to_the_character(client):
    """The pre-existing constraint must not have been weakened while the upload
    path was being closed."""
    token, cid = _seeder(client, "bib_ed_scope@test.com", "biedscope")
    resp = client.post(
        "/characters/",
        json={"name": "Other Char", "species": "human"},
        headers=auth_headers(token),
    )
    other_cid = resp.json()["id"]
    other_image_id, _path = _seed_image(other_cid)

    resp = client.post(
        EDITOR_ENDPOINT,
        data=_editor_form(cid, source_image_ids=str(other_image_id)),
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text
    assert "not found" in resp.json()["detail"].lower()


def test_creator_source_image_ids_are_still_scoped_to_active_status(client):
    from app.models.character_image import ImageStatusEnum

    token, cid = _creator(client, "bib_ed_arch@test.com", "biedarch")
    image_id, _path = _seed_image(cid, status=ImageStatusEnum.ARCHIVED)

    resp = client.post(
        EDITOR_ENDPOINT,
        data=_editor_form(cid, source_image_ids=str(image_id)),
        headers=auth_headers(token),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_accounts_keep_the_editor_upload_path(client, role):
    from unittest.mock import MagicMock, patch

    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bib_ed_{role}@test.com", f"bied{role}")

    editor = MagicMock()
    editor.editor_version = "e1"
    editor.edit = MagicMock(return_value=_PNG_BYTES)
    with patch(GET_EDITOR, return_value=editor):
        resp = client.post(
            EDITOR_ENDPOINT,
            data=_editor_form(cid),
            files=[_png_upload()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["image"]["metadata_json"]["uploaded_source_count"] == 1
    editor.edit.assert_called_once()


def test_wanderer_still_cannot_reach_editor_studio_at_all(client):
    """Unchanged and asserted, so the new guard is never mistaken for the thing
    keeping Wanderers out — ``require_creator`` does that, one layer earlier."""
    from unittest.mock import patch

    token = _wanderer(client, "bib_ed_w@test.com", "biedw")
    with patch(GET_EDITOR) as mock_get:
        resp = client.post(
            EDITOR_ENDPOINT,
            data=_editor_form(1),
            files=[_png_upload()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] != {}
    mock_get.assert_not_called()


# ── 9. Founder tooling regression pins (hard failure if these break) ─────────


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_device_upload_still_works(client, role):
    """``POST /characters/{id}/images/upload`` — the Admin Creator reference card
    and the Image Generator's founder upload. Untouched by this increment."""
    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bib_up_{role}@test.com", f"bibup{role}")

    resp = client.post(
        f"/characters/{cid}/images/upload",
        files={"file": ("ref.png", io.BytesIO(_PNG_BYTES), "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "uploaded"


def test_ordinary_creator_still_cannot_reach_the_founder_upload(client):
    token, cid = _creator(client, "bib_up_c@test.com", "bibupc")
    resp = client.post(
        f"/characters/{cid}/images/upload",
        files={"file": ("ref.png", io.BytesIO(_PNG_BYTES), "image/png")},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("role", ["seeder", "admin"])
def test_founder_manual_references_and_deliberate_mode_still_work(client, role):
    """Admin Creator's core: hand-picked reference cards under
    ``reference_mode=deliberate``, submitted as a founder job."""
    make = _seeder if role == "seeder" else _admin
    token, cid = make(client, f"bib_ref_{role}@test.com", f"bibref{role}")

    upload = client.post(
        f"/characters/{cid}/images/upload",
        files={"file": ("ref.png", io.BytesIO(_PNG_BYTES), "image/png")},
        headers=auth_headers(token),
    )
    assert upload.status_code == 201, upload.text
    ref_id = upload.json()["id"]

    from unittest.mock import patch

    with patch(
        "app.services.image_generation_job_service.start_image_generation_job",
        return_value=(_FakeJob(cid), False),
    ):
        resp = client.post(
            f"/characters/{cid}/image-generator/jobs",
            json={
                "prompt": "a portrait in the rain",
                "reference_image_ids": [ref_id],
                "reference_roles": ["unspecified"],
                "reference_mode": "deliberate",
                "idempotency_key": f"bib-{role}-key",
            },
            headers=auth_headers(token),
        )
    assert resp.status_code == 202, resp.text


def test_ordinary_creator_is_still_refused_manual_references(client):
    """Pre-existing founder gate, re-pinned here because this increment is the
    one that must not have widened it."""
    token, cid = _creator(client, "bib_ref_c@test.com", "bibrefc")
    image_id, _path = _seed_image(cid)

    resp = client.post(
        f"/characters/{cid}/image-generator/generate",
        json={"prompt": "a portrait", "reference_image_ids": [image_id]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 403, resp.text
    assert "founder tool" in str(resp.json()["detail"]).lower()


class _FakeJob:
    """Stand-in for an ImageGenerationJob row — the job runner is never started."""

    def __init__(self, character_id: int):
        self.public_id = "job-bib-1"
        self.character_id = character_id
        self.status = "queued"
        self.stage = None
        self.progress_message = None
        self.attempt_count = 0
        self.created_at = None
        self.started_at = None
        self.finished_at = None
        self.error_code = None
        self.error_message = None
        self.result_json = None
        self.image_id = None


# ── 10. Text-driven identity generation is untouched ─────────────────────────


def test_text_only_identity_generation_still_works_for_an_ordinary_creator(client):
    """The product rule's positive half. Uses the route's own ``dry_run`` seam —
    prompts are compiled and providers resolved, nothing is generated and no
    network is touched."""
    token, cid = _creator(client, "bib_gen@test.com", "bibgen")
    hdrs = auth_headers(token)

    assert client.post(
        f"/characters/{cid}/dna",
        json={"hair_color": "black", "eye_color": "grey"},
        headers=hdrs,
    ).status_code in (200, 201)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate?dry_run=true",
        json={"prompt_vibe": "rain-soaked alley, neon", "style": "realistic"},
        headers=hdrs,
    )
    assert resp.status_code == 200, resp.text

    # And the real (stub-provider) path still locks an identity end to end,
    # which is what "Ficshon creates the visual identity" has to mean.
    _lock_character(client, token, cid)
    char = client.get(f"/characters/{cid}", headers=hdrs).json()
    assert char["visual_locked"] is True

"""Tests for the image generator endpoint under the CharacterIdentityCanon contract.

Identity truth for /characters/{id}/image-generator/generate comes ONLY from
CharacterIdentityCanon, compiled by app.services.canon_compiler. There is no
legacy identity_anchor_json / body_identity_json / CharacterStyleElements path.

Contract:
  - include_character=False → plain scene from the user prompt (no identity).
  - include_character=True  → requires a populated CharacterIdentityCanon.
        Missing/incomplete canon → 409 "Character canon incomplete".
        Prompt is sourced from canon_compiler (face → body → permanent marks →
        requested accessories → scene → locked-canon clause). Removable
        accessories inject only on explicit trigger-keyword match.
  - Generated images save as SCENE_ONLY (COVER when is_cover); canon is never
    mutated by generation.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.conftest import character_owner_id


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Force local disk storage so save/load image bytes are deterministic
    (the test env may otherwise be configured for R2 object storage)."""
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Helpers ───────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str = "imggen@example.com") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Leonardo Baptiste", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


def _stub_png_bytes() -> bytes:
    """Return a valid stub PNG from the stub generator."""
    from app.services.stub_image_generator import generate_placeholder_png
    fp = generate_placeholder_png(label="test", sublabel="stub")
    from app.core.storage import load_image_bytes
    return load_image_bytes(fp)


def _stub_image_url(label: str = "ref") -> str:
    """Create a real stub PNG on disk and return a loadable /static URL for it."""
    from app.services.stub_image_generator import generate_placeholder_png
    fp = generate_placeholder_png(label=label, role="anchor_front")
    return f"/{fp}"


def _setup_canon(
    db_session,
    cid: int,
    *,
    marks: list[dict] | None = None,
    accessories: list[dict] | None = None,
    lock: bool = True,
    with_images: bool = True,
):
    """Build a populated CharacterIdentityCanon for a character via canon_service.

    Identity truth ONLY — no identity_anchor_json / body_identity_json / style
    elements. Commits so the generation route (separate session) sees it.
    """
    from app.services import canon_service as cs
    from app.schemas.canon import (
        FaceCanonData, BodyCanonData, AddPermanentMarkRequest, AddAccessoryRequest,
    )

    canon = cs.get_or_create_canon(cid, db_session)
    face = cs.load_face_canon(canon) or FaceCanonData()
    body = cs.load_body_canon(canon) or BodyCanonData()

    face.face_description = "sharp angular jaw, dark brown eyes, olive skin"
    body.body_description = "athletic build, medium height"
    body.build = "athletic"
    if with_images:
        face.face_front_image_url = _stub_image_url("face_front")
        body.body_front_image_url = _stub_image_url("body_front")
    if lock:
        face.locked = True
        body.locked = True

    cs._save_face(canon, face)
    cs._save_body(canon, body)

    for m in (marks or []):
        cs.add_permanent_mark(canon, AddPermanentMarkRequest(**m))
    for a in (accessories or []):
        cs.add_accessory(canon, AddAccessoryRequest(**a))

    if lock and with_images:
        canon.face_locked = True
        canon.body_locked = True

    db_session.commit()
    return canon


def _post(client, token, cid, body):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


def _mock_provider_succeeds() -> MagicMock:
    """A mock provider that succeeds on generate_with_anchors first (multi-image)."""
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(return_value=_stub_png_bytes())
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    return mock


def _mock_provider_single_image_only() -> MagicMock:
    """A mock provider that does NOT support multi-image input."""
    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    return mock


def _capture_prompt_provider(captured: dict) -> MagicMock:
    """Provider that records the compiled prompt on whichever path is used.

    Captures on all three provider methods so the prompt is recorded whether
    canon reference images load (multi-image / grounded) or not (text-only).
    """
    def _with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        captured["anchor_count"] = len(anchor_images)
        return _stub_png_bytes()

    def _grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured.setdefault("prompt", prompt)
        return _stub_png_bytes()

    def _text(*, prompt, size="1024x1024", reference_image_url=None):
        captured.setdefault("prompt", prompt)
        return _stub_png_bytes()

    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = _with_anchors
    mock.generate_grounded_image = _grounded
    mock.generate_image = _text
    return mock


# ── 1. Plain generation (include_character=False) ─────────────────────

def test_plain_generation_no_canon_required(client: TestClient):
    """include_character=False works without any canon."""
    token = _register_and_login(client, "imggen_plain@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "A peaceful mountain lake at dusk",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "scene_only"
    assert data["url"].startswith("/static/")
    meta = data["metadata_json"]
    assert meta["include_character"] is False
    assert meta["image_generator"] is True
    assert meta["character_id"] is None
    assert meta["canon_used"] is False
    assert meta["scene_only"] is True


def test_plain_generation_uses_clean_prompt(client: TestClient):
    """include_character=False sends only the user prompt — no identity injection."""
    token = _register_and_login(client, "imggen_clean@example.com")
    cid = _create_character(client, token)

    captured: dict = {}

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate
    mock_provider.generate_grounded_image = MagicMock(side_effect=NotImplementedError())

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock_provider):
        resp = _post(client, token, cid, {
            "prompt": "A simple landscape",
            "include_character": False,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("prompt") == "A simple landscape"


# ── 2. Provider option mapping (provider resolution, not identity) ────

def test_provider_option1_maps_to_openai(monkeypatch):
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option
    from app.services.image_provider import _OpenAIImageProvider  # type: ignore[attr-defined]

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option1")
    assert isinstance(provider, _OpenAIImageProvider)


def test_provider_option2_maps_to_google(client: TestClient, monkeypatch):
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option

    # Fake key: conftest strips the live GOOGLE_AI_API_KEY (Sprint 34) so the
    # provider constructor needs one injected, same as the option1 test above.
    monkeypatch.setattr(settings, "GOOGLE_AI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option2")
    assert "google" in type(provider).__name__.lower() or hasattr(provider, "_google")


def test_provider_toggle_disabled_forces_option1(monkeypatch):
    from app.core.config import settings
    from app.services.image_provider import get_provider_for_option, _OpenAIImageProvider  # type: ignore[attr-defined]

    monkeypatch.setattr(settings, "IMAGE_GENERATOR_PROVIDER_TOGGLE", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    provider = get_provider_for_option("option2")
    assert isinstance(provider, _OpenAIImageProvider)


# ── 3. include_character=True requires CharacterIdentityCanon ─────────

def test_include_character_without_canon_returns_409(client: TestClient):
    """include_character=True with no canon returns a graceful 409."""
    token = _register_and_login(client, "imggen_nocanon@example.com")
    cid = _create_character(client, token)

    resp = _post(client, token, cid, {
        "prompt": "Portrait in a dark forest",
        "include_character": True,
        "provider_option": "option1",
    })
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Character canon incomplete"


def test_include_character_empty_canon_returns_409(client: TestClient, db_session):
    """An empty (draft, no content) canon is still incomplete → 409."""
    token = _register_and_login(client, "imggen_emptycanon@example.com")
    cid = _create_character(client, token)
    # create the row but with no content
    from app.services import canon_service as cs
    cs.get_or_create_canon(cid, db_session)
    db_session.commit()

    resp = _post(client, token, cid, {
        "prompt": "Portrait in a dark forest",
        "include_character": True,
        "provider_option": "option1",
    })
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Character canon incomplete"


def test_include_character_with_canon_succeeds(client: TestClient, db_session):
    """include_character=True succeeds when canon is populated and provider works."""
    token = _register_and_login(client, "imggen_canon_ok@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_mock_provider_succeeds()):
        resp = _post(client, token, cid, {
            "prompt": "Standing in a library",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["include_character"] is True
    assert meta["character_id"] == cid
    assert meta["canon_used"] is True


# ── 4. Compiled prompt is sourced from canon_compiler ─────────────────

def test_compiled_prompt_minimal_and_card_driven(client: TestClient, db_session):
    """P12: the provider prompt is the user scene (essentially unchanged) plus a
    minimal safety directive — identity comes from the routed canon cards, so no
    canon prose / marking essays / relocation clauses appear in the prompt."""
    token = _register_and_login(client, "imggen_compiled@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Riding a horse at sunset",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "")
    assert "Riding a horse at sunset" in prompt
    for banned in ("FACE CANON", "BODY CANON", "PERMANENT BODY MARKS",
                   "relocate", "mirror", "locked face"):
        assert banned not in prompt, f"Removed prose leaked into prompt: {banned!r}"
    # canon_used is recorded and the prompt stays small.
    meta = resp.json()["metadata_json"]
    assert meta["compiled_prompt"]
    assert meta["canon_used"] is True


# ── 5. Removable accessories inject ONLY when requested ───────────────

_CHAIN_ACC = {
    "label": "Silver Chain",
    "type": "jewellery",
    "description": "silver chain necklace, medium-weight links resting on collarbone",
    "trigger_keywords": ["chain", "necklace", "silver chain"],
}
_MASK_ACC = {
    "label": "Urban Phantom Mask",
    "type": "mask",
    "description": "black lower-face mask, eyes visible",
    "trigger_keywords": ["mask", "masked"],
}


def test_chain_absent_when_not_requested(client: TestClient, db_session):
    """P3 #1: a plain beach prompt must NOT inject the chain accessory."""
    token = _register_and_login(client, "imggen_nochain@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, accessories=[_CHAIN_ACC])

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste standing on a beach in daylight",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "").lower()
    assert "chain" not in prompt
    assert "necklace" not in prompt


def test_chain_present_when_requested(client: TestClient, db_session):
    """P3 #2: an explicit chain request injects the chain accessory."""
    token = _register_and_login(client, "imggen_chain@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, accessories=[_CHAIN_ACC])

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste wearing a silver chain",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "").lower()
    assert "chain" in prompt


def test_mask_absent_when_not_requested(client: TestClient, db_session):
    """P3 #3: mask is omitted when not requested."""
    token = _register_and_login(client, "imggen_nomask@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, accessories=[_MASK_ACC])

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste standing on a beach in daylight",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "").lower()
    assert "mask" not in prompt


def test_mask_present_when_requested(client: TestClient, db_session):
    """P3 #4: mask appears when explicitly requested."""
    token = _register_and_login(client, "imggen_mask@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, accessories=[_MASK_ACC])

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste wearing his mask at night",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "").lower()
    assert "mask" in prompt


# ── 6. Permanent body marks (tattoos) are exact and not mirrored ──────

_TATTOO_MARKS = [
    {
        "label": "Right Arm Tribal Wolf Mark",
        "type": "tattoo",
        "body_region": "right_full_arm",
        "side": "right",
        "description": "tribal wolf tattoo sleeve",
    },
    {
        "label": "Left Arm Gothic Script Sleeve",
        "type": "tattoo",
        "body_region": "left_full_arm",
        "side": "left",
        "description": "gothic script tattoo sleeve",
    },
]


def test_permanent_marks_are_compact_clause(client: TestClient, db_session):
    """P13 (A+C): tattoo design surfaces as a compact immutable clause (so the
    provider has a semantic anchor), while geometry still comes from the cards.
    The bloated pre-P12 enumeration header stays gone."""
    token = _register_and_login(client, "imggen_marks@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, marks=_TATTOO_MARKS)

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste in a sleeveless shirt",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "")
    assert "Leonardo Baptiste in a sleeveless shirt" in prompt
    assert "PERMANENT BODY MARKS" not in prompt          # no bloated header
    assert "skin-bound anatomy" in prompt.lower()        # compact clause
    assert "tribal wolf" in prompt and "gothic script" in prompt


def test_marks_carry_compact_permanence_directive(client: TestClient, db_session):
    """P13 (C): the compact permanence directive is present; the pre-P12 verbose
    side-lock / relocation essays are NOT reintroduced."""
    token = _register_and_login(client, "imggen_nomirror@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, marks=_TATTOO_MARKS)

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste in a sleeveless shirt",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "").lower()
    assert "do not redesign, relocate, mirror" in prompt
    assert "for visual balance or composition" not in prompt


# ── 7. Reference images: multi-image vs grounded ──────────────────────

def test_multi_image_uses_canon_refs(client: TestClient, db_session):
    """When the provider supports multi-image, canon reference images are passed."""
    token = _register_and_login(client, "imggen_multi@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)  # with_images=True → face_front + body_front refs

    captured: dict = {}
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_capture_prompt_provider(captured)):
        resp = _post(client, token, cid, {
            "prompt": "In a cave",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("anchor_count", 0) >= 1
    meta = resp.json()["metadata_json"]
    assert meta["multi_image_used"] is True
    assert meta["refs_count"] >= 1


def test_grounded_fallback_when_multi_not_supported(client: TestClient, db_session):
    """When the provider lacks multi-image, falls back to grounded single-ref."""
    token = _register_and_login(client, "imggen_grounded@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    captured: dict = {}

    def _mock_grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured["called"] = True
        return _stub_png_bytes()

    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.generate_grounded_image = _mock_grounded
    mock.generate_image = MagicMock(
        side_effect=AssertionError("text should not be called when grounded succeeds")
    )

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "By a river",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    assert captured.get("called") is True
    meta = resp.json()["metadata_json"]
    assert meta["multi_image_used"] is False
    assert meta["used_ref"] is True


# ── 8. Scene generation is SCENE_ONLY and never mutates canon ─────────

def test_scene_saved_as_scene_only(client: TestClient, db_session):
    """Character generations save as SCENE_ONLY (not canon, not cover)."""
    token = _register_and_login(client, "imggen_sceneonly@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_mock_provider_succeeds()):
        resp = _post(client, token, cid, {
            "prompt": "Walking through rain",
            "include_character": True,
            "provider_option": "option1",
        })

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "scene_only"
    assert data["metadata_json"]["scene_only"] is True


def test_scene_generation_does_not_mutate_canon(client: TestClient, db_session):
    """Generating a scene must not change face/body canon JSON."""
    from app.models.character_identity_canon import CharacterIdentityCanon

    token = _register_and_login(client, "imggen_nomutate@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid, marks=_TATTOO_MARKS, accessories=[_CHAIN_ACC])

    before = db_session.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == cid
    ).first()
    face_before, body_before, acc_before = before.face_canon_json, before.body_canon_json, before.accessories_json

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_mock_provider_succeeds()):
        resp = _post(client, token, cid, {
            "prompt": "Leonardo Baptiste standing on a beach in daylight",
            "include_character": True,
            "provider_option": "option1",
        })
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    after = db_session.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == cid
    ).first()
    assert after.face_canon_json == face_before
    assert after.body_canon_json == body_before
    assert after.accessories_json == acc_before


# ── 9. Metadata contract (canon) ──────────────────────────────────────

def test_metadata_fields_plain(client: TestClient):
    token = _register_and_login(client, "imggen_meta_plain@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "A city at night",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]
    required = {"image_generator", "provider_option", "provider", "include_character",
                "prompt", "canon_used", "scene_only"}
    assert not (required - set(meta.keys()))


def test_metadata_fields_character(client: TestClient, db_session):
    token = _register_and_login(client, "imggen_meta_char@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=_mock_provider_succeeds()):
        resp = _post(client, token, cid, {
            "prompt": "Walking through rain",
            "include_character": True,
            "provider_option": "option1",
        })
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]
    required = {"image_generator", "provider_option", "provider", "include_character",
                "character_id", "prompt", "canon_used", "refs_count",
                "multi_image_used", "used_ref", "scene_only"}
    assert not (required - set(meta.keys()))
    assert meta["canon_used"] is True
    # No legacy strict-identity keys leak into the new contract.
    for legacy_key in ("strict_identity_mode", "anchor_types", "anchors_attached", "identity_hash"):
        assert legacy_key not in meta


def test_metadata_records_resolved_provider(client: TestClient):
    token = _register_and_login(client, "imggen_prov@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "A red balloon",
        "include_character": False,
        "provider_option": "option1",
    })
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]
    assert isinstance(meta.get("provider"), str) and meta["provider"]


# ── 10. Ownership / auth ──────────────────────────────────────────────

def test_other_user_cannot_generate(client: TestClient, db_session):
    owner = _register_and_login(client, "imggen_owner@example.com")
    cid = _create_character(client, owner)
    _setup_canon(db_session, cid)

    other = _register_and_login(client, "imggen_other@example.com")
    resp = _post(client, other, cid, {
        "prompt": "Trespassing",
        "include_character": True,
        "provider_option": "option1",
    })
    assert resp.status_code == 403


# ── S24AD: block ref-less fallback for canon generations ──────────────

def test_canon_provider_refusal_blocks_refless_fallback(client: TestClient, db_session):
    """Canon gen + provider REFUSES both ref-bearing calls → controlled 422,
    and the route NEVER degrades to the ref-less text-only path (the S24AC2
    Summer-bikini failure)."""
    token = _register_and_login(client, "imggen_refuse@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)  # with_images=True → refs load (ref_bytes non-empty)

    text_only = MagicMock(return_value=_stub_png_bytes())
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(
        side_effect=RuntimeError("google_refused_image: IMAGE_RECITATION"))
    mock.generate_grounded_image = MagicMock(
        side_effect=RuntimeError("google_refused_image: IMAGE_RECITATION"))
    mock.generate_image = text_only
    mock._model = "gemini-test"

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "Standing on a beach in a white bikini",
            "include_character": True,
            "provider_option": "option2",
        })

    assert resp.status_code == 422, resp.text
    # Wording is the recitation message, not the sexual-refusal one — this test
    # is about the fallback block, which is unchanged.
    assert "could not process this character reference combination" in (
        resp.json()["detail"].lower()
    )
    # The ref-less text-only fallback must NOT have run.
    text_only.assert_not_called()


def test_canon_transient_multi_failure_does_not_degrade_to_one_reference(
    client: TestClient, db_session
):
    """A transient multi-image failure must NOT fall back to one reference.

    This test previously asserted the opposite: that an exhausted multi-image
    call retried via generate_grounded_image(ref_bytes[0]). That bought
    availability by discarding five of the six references the router selected
    and saved the weaker result as if it were the real thing. Transient retries
    now live in the provider, where they re-send the COMPLETE reference set, so
    the route degrades to nothing — it either gets the real image or fails.
    """
    token = _register_and_login(client, "imggen_transient@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    text_only = MagicMock(return_value=_stub_png_bytes())
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(side_effect=RuntimeError("temporary upstream 503"))
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = text_only
    mock._model = "gemini-3.1-flash-image"

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "In a quiet library",
            "include_character": True,
            "provider_option": "option2",
        })

    assert resp.status_code == 422, resp.text
    mock.generate_grounded_image.assert_not_called()
    text_only.assert_not_called()
    # A transport failure is not a content problem and must not say it is.
    detail = resp.json()["detail"]
    assert detail == "Image generation failed for this character. Please try again."
    for word in ("adult", "explicit", "Adult Studio"):
        assert word.lower() not in detail.lower()


def test_noncanon_text_only_fallback_still_works(client: TestClient):
    """include_character=False (no refs) still uses the text-only path — the
    S24AD block only applies to canon generations with refs."""
    token = _register_and_login(client, "imggen_noncanon@example.com")
    cid = _create_character(client, token)

    text_only = MagicMock(return_value=_stub_png_bytes())
    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.generate_grounded_image = MagicMock(side_effect=NotImplementedError())
    mock.generate_image = text_only

    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "A neon city street in the rain",
            "include_character": False,
            "provider_option": "option2",
        })

    assert resp.status_code == 200, resp.text
    text_only.assert_called()
    assert resp.json()["metadata_json"]["canon_used"] is False


# ── Google block classification + reference-set diagnostics ───────────
#
# A canon generation whose ref-bearing calls all fail returns 422 either way;
# what changed is WHICH message, and what the operator can see in the log.


def _blocking_provider(reason: str) -> MagicMock:
    """Provider whose ref-bearing calls both fail with ``reason``."""
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(side_effect=RuntimeError(reason))
    mock.generate_grounded_image = MagicMock(side_effect=RuntimeError(reason))
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    mock._model = "gemini-3.1-flash-image"
    return mock


def _post_blocked(client, db_session, email, reason, prompt="Standing in his office"):
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)
    mock = _blocking_provider(reason)
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": prompt,
            "include_character": True,
            "provider_option": "option2",
        })
    return resp, mock, cid


def test_block_other_returns_neutral_message_not_adult_wording(client, db_session):
    """blockReason=OTHER on a benign prompt must NOT be reported as adult content."""
    resp, mock, _ = _post_blocked(
        client, db_session, "imggen_block_other@example.com",
        "google_prompt_blocked:OTHER:",
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail == (
        "Google could not process this character reference set. "
        "Try again or use another provider."
    )
    assert "adult" not in detail.lower()
    assert "explicit" not in detail.lower()
    # The ref-less fallback stays blocked exactly as before.
    mock.generate_image.assert_not_called()


def test_block_with_sexual_category_keeps_adult_guidance(client, db_session):
    """A genuine sexual safety category still routes the user to Adult Studio."""
    resp, _, _ = _post_blocked(
        client, db_session, "imggen_block_sexual@example.com",
        "google_prompt_blocked:SAFETY:HARM_CATEGORY_SEXUALLY_EXPLICIT=HIGH",
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "Adult Studio" in detail
    assert "adult/explicit wording" in detail


def test_image_recitation_is_not_a_sexual_refusal(client, db_session):
    """IMAGE_RECITATION is a recitation guard, not a safety verdict.

    Google attaches no harm category to it and it fires on entirely non-sexual
    reference sets, so it must never route the user to Adult Studio.
    """
    resp, _, _ = _post_blocked(
        client, db_session, "imggen_recitation@example.com",
        "google_refused_image: IMAGE_RECITATION",
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail == (
        "Google could not process this character reference combination. "
        "Try another provider or adjust the reference set."
    )
    for word in ("adult", "explicit", "sexual", "Adult Studio"):
        assert word.lower() not in detail.lower()


def test_image_recitation_classifies_as_image_recitation(client, db_session):
    """The classifier gives recitation its own neutral kind."""
    from app.services.image_generation_pipeline import _classify_ref_failure

    kind, block_reason, categories = _classify_ref_failure(
        "google_refused_image: IMAGE_RECITATION"
    )
    assert kind == "image_recitation"
    assert block_reason == "IMAGE_RECITATION"
    assert categories == []

    # And a genuine sexual category is still classified as such.
    kind, _, _ = _classify_ref_failure(
        "google_prompt_blocked:SAFETY:HARM_CATEGORY_SEXUALLY_EXPLICIT=HIGH"
    )
    assert kind == "sexual_refusal"


def test_unrelated_provider_failure_returns_generic_message(client, db_session):
    """A timeout is not a content problem and must not mention content at all."""
    resp, _, _ = _post_blocked(
        client, db_session, "imggen_timeout@example.com",
        "Google Gemini request failed: timed out",
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail == "Image generation failed for this character. Please try again."
    for word in ("adult", "explicit", "declined", "Adult Studio"):
        assert word.lower() not in detail.lower()


# ── Shared helpers for provider-interaction tests ──────────────────────

def _make_admin(db_session, email: str) -> None:
    from app.models.user import User as UserModel
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    assert user is not None, f"User {email!r} not found"
    user.is_admin = True
    db_session.commit()


def _generate_with(client, db_session, email, body_extra, *, admin: bool, provider=None):
    """Run one canon generation and return (response, provider mock)."""
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)
    if admin:
        _make_admin(db_session, email)

    mock = provider if provider is not None else _mock_provider_succeeds()
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "Standing in a library",
            "include_character": True,
            "provider_option": "option2",
            **body_extra,
        })
    return resp, mock


def test_block_diagnostic_carries_prod_vs_dev_comparison_fields(
    client, db_session, caplog, monkeypatch
):
    """The block line must be diffable against another runtime's block line.

    URL digests (h=) cannot settle a prod-vs-dev comparison: the two stores use
    different paths for the same card, so h= differs even when the bytes match.
    Only the content hash (b=), the credential fingerprint and the compiled-
    prompt hash identify what each runtime actually sent to Google.
    """
    import logging
    import hashlib

    secret = "AIza-diag-compare-key"
    monkeypatch.setenv("GOOGLE_AI_API_KEY", secret)
    expected_fp = hashlib.sha256(secret.encode()).hexdigest()[:12]

    with caplog.at_level(logging.WARNING, logger="app.services.image_generation_pipeline"):
        resp, _, cid = _post_blocked(
            client, db_session, "imggen_block_compare@example.com",
            "google_prompt_blocked:OTHER:",
        )
    assert resp.status_code == 422

    line = [
        r.getMessage() for r in caplog.records
        if "IMAGE_GEN_GOOGLE_BLOCKED " in r.getMessage()
    ][0]

    assert f"cred_fp={expected_fp}" in line
    assert "prompt_sha=" in line
    assert "prompt_len=" in line
    # Every loaded reference reports a content hash, byte count and mime type.
    assert line.count(":b=") == 2
    assert line.count(":mime=image/") == 2
    # And the key itself never reaches the log.
    assert secret not in line


def test_recitation_also_emits_the_reference_set_diagnostic(client, db_session, caplog):
    """IMAGE_RECITATION is the production Angelo failure — it must be diagnosed.

    Before recitation had its own kind it carried no block_reason, so the
    reference-set diagnostic never fired for exactly the failure that needed it.
    """
    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.image_generation_pipeline"):
        resp, _, cid = _post_blocked(
            client, db_session, "imggen_recit_diag@example.com",
            "google_refused_image: IMAGE_RECITATION",
        )
    assert resp.status_code == 422

    diag = [
        r.getMessage() for r in caplog.records
        if "IMAGE_GEN_GOOGLE_BLOCKED " in r.getMessage()
    ]
    assert len(diag) == 1, f"expected one diagnostic line, got {diag}"
    assert "block_reason=IMAGE_RECITATION" in diag[0]
    assert "failure_kind=image_recitation" not in diag[0]  # that lives on the other line

    kinds = [
        r.getMessage() for r in caplog.records
        if "IMAGE_GEN_CANON_REFUSED_BLOCKED" in r.getMessage()
    ]
    assert any("failure_kind=image_recitation" in k and "refused=False" in k for k in kinds)


def test_google_block_logs_reference_set_diagnostic(client, db_session, caplog):
    """The block diagnostic must identify the exact reference set involved."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.image_generation_pipeline"):
        resp, _, cid = _post_blocked(
            client, db_session, "imggen_block_diag@example.com",
            "google_prompt_blocked:OTHER:",
        )
    assert resp.status_code == 422

    diag = [r.getMessage() for r in caplog.records if "IMAGE_GEN_GOOGLE_BLOCKED " in r.getMessage()]
    assert len(diag) == 1, f"expected one diagnostic line, got {diag}"
    line = diag[0]

    for fragment in (
        f"character_id={cid}",
        "provider=google",
        "model=gemini-3.1-flash-image",
        "block_reason=OTHER",
        "safety_categories=[]",
        "refs_requested=2",
        "refs_loaded=2",
        "camera=unknown",
        "routed=False",
        "exposure=[]",
    ):
        assert fragment in line, f"missing {fragment!r} in: {line}"

    # Canon slot names, in routed order — available even on the fallback path
    # where SceneMeta.route_slots is empty.
    assert "slots=['face_front', 'body_front']" in line, line
    # Per-reference identity: position, slot, DB id (absent here), digest, load flag.
    assert "0:slot=face_front:id=-:h=" in line, line
    assert "1:slot=body_front:id=-:h=" in line, line
    assert "loaded=1" in line, line


def test_google_block_diagnostic_leaks_no_urls_or_bytes(client, db_session, caplog):
    """The diagnostic identifies references without exposing their locations."""
    import logging
    from app.services.canon_service import load_face_canon
    from app.models.character_identity_canon import CharacterIdentityCanon

    secret_prompt = "Zarnak quicksilver bellwether in his office"
    with caplog.at_level(logging.WARNING, logger="app.services.image_generation_pipeline"):
        resp, _, cid = _post_blocked(
            client, db_session, "imggen_block_noleak@example.com",
            "google_prompt_blocked:OTHER:", prompt=secret_prompt,
        )
    assert resp.status_code == 422

    canon = (
        db_session.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == cid)
        .first()
    )
    face_url = load_face_canon(canon).face_front_image_url

    line = next(
        r.getMessage() for r in caplog.records
        if "IMAGE_GEN_GOOGLE_BLOCKED " in r.getMessage()
    )
    assert face_url not in line
    assert "static/generated" not in line
    assert "http" not in line
    assert "?" not in line  # no query string, hence no signed-URL credential
    # No prompt text — neither the user's scene nor any compiled fragment.
    # Only the distinctive invented tokens are checked; short English words like
    # "in" appear legitimately inside field names ("image", "unknown").
    for token in ("Zarnak", "quicksilver", "bellwether", "office"):
        assert token not in line, f"prompt token {token!r} leaked into: {line}"
    assert "adult, fully clothed" not in line  # canon_compiler safety prefix


def test_google_block_diagnostic_reports_db_image_ids(client, db_session):
    """A reference backed by a CharacterImage row is named by its DB id."""
    import logging
    from app.models.character_image import (
        CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum,
    )
    from app.services.canon_service import load_face_canon
    from app.models.character_identity_canon import CharacterIdentityCanon

    token = _register_and_login(client, "imggen_block_dbid@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    canon = (
        db_session.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == cid)
        .first()
    )
    face_url = load_face_canon(canon).face_front_image_url
    row = CharacterImage(
        character_id=cid,
        user_id=character_owner_id(db_session, cid),
        kind=ImageKindEnum.ANCHOR_FRONT,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="openai",
        file_path=face_url,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    mock = _blocking_provider("google_prompt_blocked:OTHER:")
    import app.services.image_generation_pipeline as ig
    with patch.object(ig, "get_provider_for_option", return_value=mock), \
            patch.object(ig.logger, "warning") as warn:
        resp = _post(client, token, cid, {
            "prompt": "Standing in his office",
            "include_character": True,
            "provider_option": "option2",
        })

    assert resp.status_code == 422
    rendered = [call.args[0] % call.args[1:] for call in warn.call_args_list
                if "IMAGE_GEN_GOOGLE_BLOCKED " in call.args[0]]
    assert len(rendered) == 1, rendered
    assert f"0:slot=face_front:id={row.id}:" in rendered[0], rendered[0]


def test_non_block_failure_emits_no_reference_diagnostic(client, db_session, caplog):
    """The reference-set diagnostic is scoped to real provider blocks only."""
    import logging

    with caplog.at_level(logging.WARNING, logger="app.services.image_generation_pipeline"):
        resp, _, _ = _post_blocked(
            client, db_session, "imggen_nodiag@example.com",
            "temporary upstream 503",
        )
    assert resp.status_code == 422
    assert not [r for r in caplog.records if "IMAGE_GEN_GOOGLE_BLOCKED " in r.getMessage()]
    # The summary line still fires, and classifies the failure honestly.
    summary = next(
        r.getMessage() for r in caplog.records
        if "IMAGE_GEN_CANON_REFUSED_BLOCKED" in r.getMessage()
    )
    assert "failure_kind=unknown" in summary
    assert "refused=False" in summary


def test_canon_success_path_unaffected(client: TestClient, db_session):
    """Non-adult canon gen where the multi-image call succeeds is unaffected:
    200, refs used, text-only never touched (Pan normal-generation analogue)."""
    token = _register_and_login(client, "imggen_panok@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)

    mock = _mock_provider_succeeds()
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock):
        resp = _post(client, token, cid, {
            "prompt": "Pan in a black shirt with sleeves rolled to the elbows, in a forest",
            "include_character": True,
            "provider_option": "option2",
        })

    assert resp.status_code == 200, resp.text
    mock.generate_with_anchors.assert_called_once()
    mock.generate_image.assert_not_called()
    assert resp.json()["metadata_json"]["multi_image_used"] is True


# ── No silent identity degradation ────────────────────────────────────
#
# A canon request must succeed with the reference evidence the router selected,
# fail honestly, or retry inside the provider with that SAME evidence. It must
# never quietly regenerate from a weaker reference set and save the result as
# though it were the real thing.

def test_six_reference_failure_never_becomes_one_reference_generation(client, db_session):
    """A failed multi-reference canon call must NOT retry with ref_bytes[0]."""
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(
        side_effect=RuntimeError("google_prompt_blocked:OTHER:"))
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    mock._model = "gemini-3.1-flash-image"

    resp, _ = _generate_with(
        client, db_session, "imggen_nodegrade@example.com", {}, admin=False, provider=mock,
    )

    assert resp.status_code == 422, resp.text
    # The single-reference downgrade must never have been attempted...
    mock.generate_grounded_image.assert_not_called()
    # ...nor the reference-less text path.
    mock.generate_image.assert_not_called()


def test_single_reference_request_is_not_duplicated(client, db_session):
    """With one reference the grounded payload equals the multi payload.

    Retrying it could only repeat the first failure at full cost, so the route
    must not issue that second identical call.
    """
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(
        side_effect=RuntimeError("google_refused_image: IMAGE_RECITATION"))
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    mock._model = "gemini-3.1-flash-image"

    resp, _ = _generate_with(
        client, db_session, "imggen_nodupe@example.com", {}, admin=False, provider=mock,
    )

    assert resp.status_code == 422, resp.text
    assert mock.generate_with_anchors.call_count == 1
    mock.generate_grounded_image.assert_not_called()


def test_single_reference_provider_still_uses_grounded_path(client, db_session):
    """Removing the downgrade must not break genuinely single-reference providers.

    When a provider cannot consume multiple references, one reference is its
    real capability rather than a downgrade, so grounded remains its primary
    path — that behaviour is deliberately preserved.
    """
    mock = _mock_provider_single_image_only()
    resp, _ = _generate_with(
        client, db_session, "imggen_singleprov@example.com", {}, admin=False, provider=mock,
    )

    assert resp.status_code == 200, resp.text
    mock.generate_grounded_image.assert_called_once()


def test_successful_google_path_is_unchanged(client, db_session):
    """The happy path still sends every routed reference on the multi call."""
    captured: dict = {}
    resp, _ = _generate_with(
        client, db_session, "imggen_happy@example.com", {}, admin=False,
        provider=_capture_prompt_provider(captured),
    )

    assert resp.status_code == 200, resp.text
    assert captured["anchor_count"] == 2, "full reference set still sent"
    assert resp.json()["kind"] == "scene_only"


def test_no_automatic_provider_switch_on_google_block(client, db_session):
    """A Google block must not silently hand the request to another provider."""
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(
        side_effect=RuntimeError("google_prompt_blocked:OTHER:"))
    mock.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock.generate_image = MagicMock(return_value=_stub_png_bytes())
    mock._model = "gemini-3.1-flash-image"

    fallback = MagicMock()
    fallback.generate_image = MagicMock(return_value=_stub_png_bytes())

    token = _register_and_login(client, "imggen_noswitch@example.com")
    cid = _create_character(client, token)
    _setup_canon(db_session, cid)
    with patch("app.services.image_generation_pipeline.get_provider_for_option", return_value=mock), \
         patch("app.services.image_generation_pipeline.get_fallback_provider", return_value=fallback):
        resp = _post(client, token, cid, {
            "prompt": "Standing in a library",
            "include_character": True,
            "provider_option": "option2",
        })

    assert resp.status_code == 422, resp.text
    fallback.generate_image.assert_not_called()
    assert resp.json()["detail"] == (
        "Google could not process this character reference set. "
        "Try again or use another provider."
    )


def test_openai_remains_admin_only(client, db_session):
    """option1 (OpenAI) stays admin-gated — a Google block does not unlock it."""
    from app.services.image_provider import resolve_canon_provider_option

    effective, meta = resolve_canon_provider_option("option1", is_admin=False)
    assert effective != "option1", "non-admin must not reach OpenAI"

    effective_admin, _ = resolve_canon_provider_option("option1", is_admin=True)
    assert effective_admin == "option1", "admins keep explicit OpenAI exactly as before"


def test_max_ref_count_is_fully_removed(client, db_session):
    """The temporary payload probe must leave no runtime surface behind."""
    from app.api.routes.image_generator import ImageGenerateRequest

    assert "max_ref_count" not in ImageGenerateRequest.model_fields

    # An unknown field must not silently change the reference count either.
    captured: dict = {}
    resp, _ = _generate_with(
        client, db_session, "imggen_norefcap@example.com",
        {"max_ref_count": 1}, admin=True,
        provider=_capture_prompt_provider(captured),
    )
    assert resp.status_code == 200, resp.text
    assert captured["anchor_count"] == 2, "full reference set regardless of the old field"


def test_face_verify_regeneration_never_falls_back_to_refless(client, db_session):
    """A canon regeneration must not produce a reference-LESS candidate.

    _generate_scene_png used to end with a text-only tier. For a canon request
    that tier discards every reference, and a candidate that happened to score
    better on face verification would have been saved as the final image.
    """
    from app.services.image_generation_pipeline import _generate_scene_png

    provider = MagicMock()
    provider.generate_with_anchors = MagicMock(side_effect=RuntimeError("blocked"))
    provider.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    out = _generate_scene_png(
        provider, prompt="p",
        ref_bytes=[b"a", b"b"], provider_supports_multi=True,
    )

    assert out is None, "must give up rather than return weaker evidence"
    provider.generate_grounded_image.assert_not_called()
    provider.generate_image.assert_not_called()


def test_refless_generation_still_uses_text_path(client, db_session):
    """With no references selected there is nothing to weaken — text-only stands."""
    from app.services.image_generation_pipeline import _generate_scene_png

    provider = MagicMock()
    provider.generate_image = MagicMock(return_value=b"png")

    out = _generate_scene_png(
        provider, prompt="p", ref_bytes=[], provider_supports_multi=True,
    )

    assert out == b"png"
    provider.generate_image.assert_called_once()

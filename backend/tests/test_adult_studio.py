"""Adult Studio (18+ Studio) pipeline tests.

Covers prepare (manifest from locked canon), generate (multi-image, no silent
fallback, metadata), the safety gate, and the SDXL LoRA training-pack export.
Canon Studio is never touched here — these tests read canon as source truth via
the shared canon_test_utils helper.
"""
import io
import json
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from tests.conftest import auth_headers, get_auth_token
from tests.canon_test_utils import setup_canon


def _generation_enabled():
    """Context manager flipping the Phase 2 generation flag on for a test.

    Generation is disabled by default; these tests exercise the (later-enabled)
    provider path. No real provider is used — the provider is patched in-test.
    """
    return patch.object(settings, "ADULT_STUDIO_GENERATION_ENABLED", True)

# Self-contained PNG-ish bytes (>1000 bytes) — avoids depending on the storage
# backend (R2 vs local) for stub image generation in tests.
_DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2048


def _login(client: TestClient, email="adult@test.com", username="adultuser") -> str:
    return get_auth_token(client, email=email, username=username)


def _create_character(client: TestClient, token: str, name="Summer") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _summer_marks() -> list[dict]:
    return [
        {
            "label": "Butterfly floral sleeve",
            "type": "tattoo",
            "body_region": "right_upper_arm",
            "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
            "detail_crop_url": None,
        },
        {
            "label": "Black-and-white ballerina tattoo",
            "type": "tattoo",
            "body_region": "left_forearm",
            "side": "left",
            "description": "Left forearm black-and-white ballerina tattoo",
            "reference_image_url": "static/generated/mark_left.png",
        },
    ]


class _FakeProvider:
    supports_multi_image_input = True

    def __init__(self, fail=False, empty=False):
        self._fail = fail
        self._empty = empty
        self.calls = []

    def generate_with_anchors(self, *, prompt, anchor_images, size="1024x1024"):
        self.calls.append({"prompt": prompt, "n_refs": len(anchor_images)})
        if self._fail:
            raise RuntimeError("OpenAI refused: content policy")
        if self._empty:
            return b""
        return _DUMMY_PNG


# ── Prepare ────────────────────────────────────────────────────────────


def test_prepare_requires_locked_canon(client):
    token = _login(client)
    cid = _create_character(client, token)
    # No canon at all → 409
    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert resp.status_code == 409, resp.text


def test_prepare_builds_manifest_and_sets_prepared(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Phase 2: prepare lands on the new vocabulary 'prepared' (NOT 'ready' — the
    # identity is not trained). No provider is constructed during prepare.
    assert data["status"] == "prepared"
    assert data["provider"] is None
    assert data["refs_count"] >= 1
    assert data["marks_count"] == 2
    # New status fields come from AdultIdentityModel.
    assert data["canon_fingerprint"]
    assert data["stale"] is False
    assert data["training_enabled"] is False
    assert data["generation_enabled"] is False
    # Per-mark routes are surfaced from the render plan.
    assert len(data["marks"]) == 2
    routes = {m["route"] for m in data["marks"]}
    assert routes <= {"ip_adapter", "controlnet_canny", "inpaint_direct", "hybrid", "skip"}


def test_prepare_rejects_non_owner(client, db_session):
    owner_token = _login(client, email="owner@test.com", username="owner1")
    cid = _create_character(client, owner_token)
    setup_canon(db_session, cid, lock=True, with_images=True)

    other_token = _login(client, email="intruder@test.com", username="intruder1")
    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(other_token))
    assert resp.status_code == 403, resp.text


def test_status_reflects_prepared_after_prepare(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    resp = client.get(f"/adult-studio/characters/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Status is now served from AdultIdentityModel (prepared, not the legacy 'ready').
    assert data["status"] == "prepared"
    assert data["generation_enabled"] is False
    assert data["training_enabled"] is False


# ── Generate ───────────────────────────────────────────────────────────


def test_generate_disabled_returns_409_by_default(client, db_session):
    """Phase 2 default: generation is disabled → 409, with NO provider constructed."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    # Patch the provider factory to assert it is NEVER called while disabled.
    with patch("app.api.routes.adult_studio._get_adult_provider") as prov:
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach in a yellow bikini, adult woman"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 409, resp.text
    assert "disabled" in resp.json()["detail"].lower()
    prov.assert_not_called()


def test_generate_requires_prepare_first(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    with _generation_enabled():
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach in a yellow bikini, adult woman"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 409, resp.text


def test_generate_blocks_minor_terms(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    with _generation_enabled():
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "a teen schoolgirl on the beach in a bikini"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 400, resp.text
    assert "blocked" in resp.json()["detail"].lower()


def test_generate_succeeds_with_refs_and_metadata(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    fake = _FakeProvider()
    # Patch the ref loader so the test doesn't depend on the storage backend
    # (R2 vs local); production canon URLs load normally.
    with _generation_enabled(), \
         patch("app.api.routes.adult_studio._get_adult_provider", return_value=fake), \
         patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG), \
         patch("app.api.routes.adult_studio.save_image", return_value="static/generated/test_adult.png"):
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer standing on a beach at sunset wearing a yellow bikini, adult woman, both arms visible"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["multi_image_used"] is True
    assert data["refs_count"] >= 1
    assert data["used_refs"]
    assert data["provider"] == "openai"
    assert data["image_url"]
    assert data["failure_reason"] is None
    # The provider actually received the references (no text-only path).
    assert fake.calls and fake.calls[0]["n_refs"] >= 1


def test_generate_no_silent_text_fallback_on_provider_failure(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    fake = _FakeProvider(fail=True)
    with _generation_enabled(), \
         patch("app.api.routes.adult_studio._get_adult_provider", return_value=fake), \
         patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach in a yellow bikini, adult woman"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 502, resp.text
    detail = resp.json()["detail"]
    assert detail["multi_image_used"] is False
    assert "provider_error" in detail["failure_reason"]


# ── Training pack export ───────────────────────────────────────────────


def test_training_pack_requires_ready(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    # Not prepared yet → 409
    resp = client.get(f"/adult-studio/characters/{cid}/training-pack", headers=auth_headers(token))
    assert resp.status_code == 409, resp.text


def test_training_pack_rejects_non_owner(client, db_session):
    owner_token = _login(client, email="owner2@test.com", username="owner2")
    cid = _create_character(client, owner_token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(owner_token))

    other = _login(client, email="intruder2@test.com", username="intruder2")
    resp = client.get(f"/adult-studio/characters/{cid}/training-pack", headers=auth_headers(other))
    assert resp.status_code == 403, resp.text


def test_training_pack_exports_zip_with_captions_and_trigger(client, db_session):
    token = _login(client)
    cid = _create_character(client, token, name="Summer Fielding")
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    # Patch the ref loader so the export does not depend on the storage backend.
    with patch("app.services.adult_studio.load_image_bytes", return_value=_DUMMY_PNG):
        resp = client.get(
            f"/adult-studio/characters/{cid}/training-pack", headers=auth_headers(token)
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["x-training-pack-trigger"] == "ficsummerfielding"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    # Required top-level artifacts.
    for required in ("manifest.json", "captions.json", "training_notes.json", "README.txt"):
        assert required in names, f"missing {required}"
    # Fixed-slot face/body images present with stable names.
    assert "images/face_front.png" in names
    assert "images/body_front.png" in names
    # Mark images derived from canon marking regions.
    assert any(n.startswith("images/mark_right_upper_arm") for n in names)
    assert any(n.startswith("images/mark_left_forearm") for n in names)
    # Each image has a paired .txt caption.
    for n in names:
        if n.startswith("images/") and n.endswith(".png"):
            assert n[:-4] + ".txt" in names, f"missing caption for {n}"

    # Captions use the trigger token.
    captions = json.loads(zf.read("captions.json"))
    assert captions, "captions.json empty"
    assert all(c.startswith("ficsummerfielding") for c in captions.values())
    # Captions reflect canon permanent-mark truth (S24C factual style): the butterfly
    # sleeve is on the RIGHT upper arm and the ballerina is on the LEFT forearm.
    caption_blob = " ".join(captions.values()).lower()
    assert "butterfly floral sleeve tattoo on right upper arm" in caption_blob
    assert "black-and-white ballerina tattoo on left forearm" in caption_blob
    # Per-mark closeup captions exist with region + "closeup".
    assert "butterfly floral sleeve tattoo right upper arm closeup" in caption_blob
    assert "black-and-white ballerina tattoo left forearm closeup" in caption_blob

    notes = json.loads(zf.read("training_notes.json"))
    assert notes["character_id"] == cid
    assert notes["trigger_token"] == "ficsummerfielding"
    assert notes["source"] == "adult_studio_manifest"
    assert notes["recommended_model"] == "SDXL"
    assert notes["recommended_method"] == "character_lora"
    assert "identity truth" in notes["notes"].lower()

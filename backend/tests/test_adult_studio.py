"""Adult Studio (18+ Studio) pipeline tests.

Covers prepare (manifest from locked canon), generate (multi-image, no silent
fallback, metadata), and the safety gate. Canon Studio is never touched here —
these tests read canon as source truth via the shared canon_test_utils helper.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, get_auth_token
from tests.canon_test_utils import setup_canon

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
            "label": "Left upper arm butterfly floral tattoo",
            "type": "tattoo",
            "body_region": "left_upper_arm",
            "side": "left",
            "description": "colourful butterfly with floral detail on the left upper arm",
            "detail_crop_url": None,
        },
        {
            "label": "Right forearm ballet dancer tattoo",
            "type": "tattoo",
            "body_region": "right_forearm",
            "side": "right",
            "description": "black ink ballet dancer on the right forearm",
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


def test_prepare_builds_manifest_and_sets_ready(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ready"
    assert data["provider"] == "openai"
    assert data["refs_count"] >= 1
    assert data["marks_count"] == 2


def test_prepare_rejects_non_owner(client, db_session):
    owner_token = _login(client, email="owner@test.com", username="owner1")
    cid = _create_character(client, owner_token)
    setup_canon(db_session, cid, lock=True, with_images=True)

    other_token = _login(client, email="intruder@test.com", username="intruder1")
    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(other_token))
    assert resp.status_code == 403, resp.text


def test_status_reflects_ready_after_prepare(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    resp = client.get(f"/adult-studio/characters/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready"


# ── Generate ───────────────────────────────────────────────────────────


def test_generate_requires_prepare_first(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
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
    with patch("app.api.routes.adult_studio._get_adult_provider", return_value=fake), \
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
    with patch("app.api.routes.adult_studio._get_adult_provider", return_value=fake), \
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

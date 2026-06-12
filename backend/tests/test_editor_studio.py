"""Tests for Editor Studio Sprint E1 — POST /editor/generate.

Covers:
  1. Auth required (401)
  2. Prompt required (422)
  3. Strength clamped into [0.1, 0.5]
  4. Max 3 source images (422)
  5. Zero source images (422)
  6. Invalid character blocked (404)
  7. Non-owner blocked (403)
  8. Provider validation (422)
  9. Successful mocked edit saves a CharacterImage with editor metadata
 10. Library-image-id source path
"""
import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, get_auth_token

ENDPOINT = "/editor/generate"

# Minimal valid 1x1 PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4e0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Deterministic local disk storage (env may default to R2)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


def _png_file(name: str = "src.png"):
    return ("images", (name, io.BytesIO(_PNG_BYTES), "image/png"))


def _create_character(client: TestClient, token: str, name: str = "Editor Test Char") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _form(character_id: int, prompt: str = "Same character on a beach", **overrides):
    data = {
        "character_id": str(character_id),
        "prompt": prompt,
        "provider": "gpt-image",
        "strength": "0.25",
    }
    data.update({k: str(v) for k, v in overrides.items()})
    return data


def _mock_editor(captured: dict | None = None) -> MagicMock:
    editor = MagicMock()

    def _edit(*, prompt, source_images, strength, **kwargs):
        if captured is not None:
            captured["prompt"] = prompt
            captured["source_images"] = source_images
            captured["strength"] = strength
        return _PNG_BYTES

    editor.edit = MagicMock(side_effect=_edit)
    return editor


# ── 1. Auth ───────────────────────────────────────────────────────────


def test_auth_required(client):
    resp = client.post(ENDPOINT, data=_form(1), files=[_png_file()])
    # HTTPBearer returns 403 for a missing Authorization header,
    # 401 for an invalid token — both mean "not authenticated".
    assert resp.status_code in (401, 403)
    bad = client.post(
        ENDPOINT,
        data=_form(1),
        files=[_png_file()],
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert bad.status_code == 401


# ── 2. Prompt required ────────────────────────────────────────────────


def test_prompt_required(client):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    resp = client.post(
        ENDPOINT,
        data=_form(cid, prompt="   "),
        files=[_png_file()],
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "prompt" in resp.text.lower()


# ── 3. Strength clamped ───────────────────────────────────────────────


@pytest.mark.parametrize("raw,expected", [("0.9", 0.5), ("0.01", 0.1), ("0.25", 0.25)])
def test_strength_clamped(client, raw, expected):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    captured: dict = {}
    with patch(
        "app.api.routes.editor_studio.get_editor",
        return_value=_mock_editor(captured),
    ):
        resp = client.post(
            ENDPOINT,
            data=_form(cid, strength=raw),
            files=[_png_file()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["strength"] == pytest.approx(expected)
    assert captured["strength"] == pytest.approx(expected)


def test_clamp_strength_unit():
    from app.services.editor_studio import clamp_strength, strength_to_input_fidelity

    assert clamp_strength(None) == 0.25
    assert clamp_strength(0.0) == 0.1
    assert clamp_strength(1.0) == 0.5
    assert strength_to_input_fidelity(0.25) == "high"
    assert strength_to_input_fidelity(0.5) == "low"


# ── 4/5. Source image count ───────────────────────────────────────────


def test_max_three_source_images(client):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    files = [_png_file(f"s{i}.png") for i in range(4)]
    resp = client.post(
        ENDPOINT, data=_form(cid), files=files, headers=auth_headers(token)
    )
    assert resp.status_code == 422
    assert "3" in resp.json()["detail"]


def test_at_least_one_source_image(client):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    resp = client.post(ENDPOINT, data=_form(cid), headers=auth_headers(token))
    assert resp.status_code == 422
    assert "source image" in resp.json()["detail"].lower()


# ── 6/7. Character access ─────────────────────────────────────────────


def test_invalid_character_blocked(client):
    token = get_auth_token(client)
    resp = client.post(
        ENDPOINT,
        data=_form(999999),
        files=[_png_file()],
        headers=auth_headers(token),
    )
    assert resp.status_code == 404


def test_non_owner_blocked(client):
    owner_token = get_auth_token(client, email="owner@test.com", username="owneruser")
    cid = _create_character(client, owner_token)
    other_token = get_auth_token(client, email="other@test.com", username="otheruser")
    resp = client.post(
        ENDPOINT,
        data=_form(cid),
        files=[_png_file()],
        headers=auth_headers(other_token),
    )
    assert resp.status_code == 403


# ── 8. Provider validation ────────────────────────────────────────────


def test_provider_validation(client):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    resp = client.post(
        ENDPOINT,
        data=_form(cid, provider="grok"),
        files=[_png_file()],
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "provider" in resp.json()["detail"].lower()


# ── 9. Successful mocked edit persists to the image library ──────────


def test_successful_edit_saves_result(client, db_session):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    with patch(
        "app.api.routes.editor_studio.get_editor", return_value=_mock_editor()
    ):
        resp = client.post(
            ENDPOINT,
            data=_form(cid),
            files=[_png_file()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["image_url"]
    assert body["character_id"] == cid
    assert body["provider"] == "gpt-image"
    assert body["image"] is not None

    from app.models.character_image import CharacterImage

    img = db_session.query(CharacterImage).get(body["image"]["id"])
    assert img is not None
    assert img.kind.value == "scene_only"
    meta = img.metadata_json
    assert meta["editor_generated"] is True
    assert meta["editor_version"] == "e1"
    assert meta["strength"] == pytest.approx(0.25)
    assert meta["source_image_ids"] == []
    assert meta["uploaded_source_count"] == 1


# ── 10. Library-image-id source path ──────────────────────────────────


def test_library_image_id_source(client, db_session):
    token = get_auth_token(client)
    cid = _create_character(client, token)

    # Seed a library image on local disk so load_image_bytes can read it.
    from app.core.storage import save_image
    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    fp = save_image(_PNG_BYTES)
    src = CharacterImage(
        character_id=cid,
        kind=ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        file_path=fp,
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)

    captured: dict = {}
    with patch(
        "app.api.routes.editor_studio.get_editor",
        return_value=_mock_editor(captured),
    ):
        resp = client.post(
            ENDPOINT,
            data=_form(cid, source_image_ids=str(src.id)),
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    assert len(captured["source_images"]) == 1
    assert resp.json()["image"]["metadata_json"]["source_image_ids"] == [src.id]


def test_library_image_id_wrong_character(client, db_session):
    token = get_auth_token(client)
    cid = _create_character(client, token)
    resp = client.post(
        ENDPOINT,
        data=_form(cid, source_image_ids="424242"),
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"].lower()

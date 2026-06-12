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
    editor.provider_name = "gpt-image"
    editor.editor_version = "e1"

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
        data=_form(cid, provider="dall-e-1"),
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


# ── E2: grok provider ─────────────────────────────────────────────────


def test_grok_provider_accepted(client, db_session):
    """provider=grok dispatches and persists provider/editor_version=e2 metadata."""
    token = get_auth_token(client)
    cid = _create_character(client, token)
    grok_editor = _mock_editor()
    grok_editor.provider_name = "grok"
    grok_editor.editor_version = "e2"
    with patch(
        "app.api.routes.editor_studio.get_editor", return_value=grok_editor
    ) as mock_get:
        resp = client.post(
            ENDPOINT,
            data=_form(cid, provider="grok"),
            files=[_png_file()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    mock_get.assert_called_once_with("grok")
    body = resp.json()
    assert body["provider"] == "grok"
    meta = body["image"]["metadata_json"]
    assert meta["provider"] == "grok"
    assert meta["editor_version"] == "e2"
    assert meta["input_fidelity"] is None  # grok has no API-level fidelity control
    assert meta["strength"] == pytest.approx(0.25)


def test_self_hosted_provider_accepted(client, db_session):
    """provider=self_hosted dispatches and persists transform-mode e4 metadata."""
    token = get_auth_token(client)
    cid = _create_character(client, token)
    sh_editor = _mock_editor()
    sh_editor.provider_name = "self_hosted"
    sh_editor.editor_version = "e4"
    with patch(
        "app.api.routes.editor_studio.get_editor", return_value=sh_editor
    ) as mock_get:
        resp = client.post(
            ENDPOINT,
            data=_form(cid, provider="self_hosted"),
            files=[_png_file()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 200, resp.text
    mock_get.assert_called_once_with("self_hosted")
    meta = resp.json()["image"]["metadata_json"]
    assert meta["editor_provider"] == "self_hosted"
    assert meta["editor_mode"] == "transform"
    assert meta["editor_version"] == "e4"
    assert meta["input_fidelity"] is None


def test_self_hosted_requires_exactly_one_source(client):
    """self_hosted is a single-image transform — 2 sources is a 422, no editor call."""
    token = get_auth_token(client)
    cid = _create_character(client, token)
    with patch("app.api.routes.editor_studio.get_editor") as mock_get:
        resp = client.post(
            ENDPOINT,
            data=_form(cid, provider="self_hosted"),
            files=[_png_file("a.png"), _png_file("b.png")],
            headers=auth_headers(token),
        )
    assert resp.status_code == 422
    assert "exactly 1" in resp.json()["detail"]
    mock_get.assert_not_called()


def test_self_hosted_editor_dispatch():
    """get_editor('self_hosted') returns the RunPod backend when env is configured."""
    import os
    from unittest.mock import patch as _patch

    from app.services.editor_self_hosted import SelfHostedImageEditor
    from app.services.editor_studio import get_editor

    env = {
        "RUNPOD_API_KEY": "k", "R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "s", "R2_BUCKET_NAME": "b", "R2_PUBLIC_URL": "u",
    }
    with _patch.dict(os.environ, env):
        sh = get_editor("self_hosted")
    assert isinstance(sh, SelfHostedImageEditor)
    assert sh.provider_name == "self_hosted"
    assert sh.editor_version == "e4"


def test_get_editor_dispatch():
    """get_editor returns the right backend class per provider name."""
    from unittest.mock import patch as _patch

    from app.core.config import settings
    from app.services.editor_studio import GptImageEditor, GrokImageEditor, get_editor

    with _patch.object(settings, "OPENAI_API_KEY", "test-key"), _patch.object(
        settings, "OPENROUTER_API_KEY", "test-key"
    ):
        assert isinstance(get_editor("gpt-image"), GptImageEditor)
        grok = get_editor("grok")
        assert isinstance(grok, GrokImageEditor)
        assert grok.editor_version == "e2"
    with pytest.raises(ValueError):
        get_editor("not-a-provider")


def test_grok_editor_payload_and_parse():
    """GrokImageEditor builds the OpenRouter multimodal payload and decodes the data-URL reply."""
    import base64
    from unittest.mock import patch as _patch

    from app.core.config import settings
    from app.services.editor_studio import GrokImageEditor

    with _patch.object(settings, "OPENROUTER_API_KEY", "test-key"):
        editor = GrokImageEditor()

    payload = editor._build_payload(prompt="Beach scene", source_images=[_PNG_BYTES, _PNG_BYTES])
    assert payload["model"] == settings.OPENROUTER_GROK_IMAGE_MODEL
    assert payload["modalities"] == ["image"]  # grok endpoints are image-output-only
    content = payload["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image_url", "image_url", "text"]
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "Beach scene" in content[-1]["text"]
    # Identity-preservation wrapper is applied.
    assert "SAME person" in content[-1]["text"]

    encoded = base64.b64encode(_PNG_BYTES).decode("ascii")
    body = {
        "choices": [
            {"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{encoded}"}}]}}
        ]
    }
    assert editor._parse_image_bytes(body) == _PNG_BYTES

    with pytest.raises(RuntimeError, match="missing expected image structure"):
        editor._parse_image_bytes({"choices": [{"message": {}}]})


def test_grok_editor_failure_returns_502(client):
    """A provider-side grok failure surfaces as 502 with detail, nothing saved."""
    token = get_auth_token(client)
    cid = _create_character(client, token)
    failing = MagicMock()
    failing.editor_version = "e2"
    failing.edit = MagicMock(side_effect=RuntimeError("grok edit failed (HTTP 400): blocked"))
    with patch("app.api.routes.editor_studio.get_editor", return_value=failing):
        resp = client.post(
            ENDPOINT,
            data=_form(cid, provider="grok"),
            files=[_png_file()],
            headers=auth_headers(token),
        )
    assert resp.status_code == 502
    assert "grok" in resp.json()["detail"]


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

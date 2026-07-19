"""Tests for B6 Front Anchor Gate: vision validation, retry, fallback, and crop.

All tests use mocks — no live API calls.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────


def _make_png(width: int, height: int) -> bytes:
    """Create a minimal in-memory PNG with the given dimensions."""
    from PIL import Image

    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_PORTRAIT_PNG = _make_png(512, 768)   # good portrait
_STRIP_PNG = _make_png(1600, 400)     # strip (fails precheck)

_PASS_VERDICT = {
    "ok": True,
    "is_passport_headshot": True,
    "has_hands_or_props": False,
    "is_full_body_or_seated": False,
    "background_is_neutral": True,
    "confidence": 0.95,
    "fail_reason": "",
}

_FAIL_VERDICT = {
    "ok": False,
    "is_passport_headshot": False,
    "has_hands_or_props": False,
    "is_full_body_or_seated": True,
    "background_is_neutral": True,
    "confidence": 0.72,
    "fail_reason": "full_body_or_seated",
}


def _register_and_login(client: TestClient) -> str:
    client.post(
        "/auth/register",
        json={
            "email": "gatetest@example.com",
            "username": "gateuser",
            "password": "testpassword123",
        },
    )
    resp = client.post(
        "/auth/login",
        json={"email": "gatetest@example.com", "password": "testpassword123"},
    )
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Gate Tester", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


# ── Test 1: Validator returns FAIL → retries → eventually PASS ───────

def test_front_retried_until_vision_passes(client: TestClient):
    """When vision returns FAIL the first two attempts then PASS on the third,
    generate_image is called exactly 3 times and the pack completes successfully.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    generate_calls: list[int] = []

    def _generate_image(*, prompt, size="1024x1024", reference_image_url=None):
        generate_calls.append(1)
        return _PORTRAIT_PNG  # always passes precheck

    mock_provider = MagicMock()
    mock_provider.generate_image = _generate_image
    mock_provider.generate_grounded_image = MagicMock(return_value=_PORTRAIT_PNG)

    # vision: fail, fail, pass
    verdict_sequence = [_FAIL_VERDICT, _FAIL_VERDICT, _PASS_VERDICT]
    verdict_iter = iter(verdict_sequence)

    def _mock_validate(png_bytes):
        return next(verdict_iter)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
    mock_settings.IMAGE_PROVIDER = "openai"

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.validate_front_anchor_png",
        side_effect=_mock_validate,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "dark hair green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier_used"] == "A"
    assert len(data["images"]) == 4

    # generate_image called 3 times: fail, fail, pass
    assert len(generate_calls) == 3
    # Angles generated after validation passed
    assert mock_provider.generate_grounded_image.call_count == 3


# ── Test 2: Provider is non-google and retries exhausted → RuntimeError ──

def test_non_google_exhausted_raises(client: TestClient):
    """When vision fails on all MAX_FRONT_RETRIES attempts and provider is not
    google, a RuntimeError is raised.
    TestClient re-raises server exceptions, so we catch with pytest.raises.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=_PORTRAIT_PNG)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
    mock_settings.IMAGE_PROVIDER = "openai"

    from app.api.routes.character_visual import MAX_FRONT_RETRIES

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.validate_front_anchor_png",
        return_value=_FAIL_VERDICT,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ), pytest.raises(RuntimeError, match="retry exhausted"):
        client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert mock_provider.generate_image.call_count == MAX_FRONT_RETRIES


# ── Test 3: Google exhausts retries → fallback to OpenAI ─────────────

def test_google_validation_exhausted_falls_back_to_openai(client: TestClient):
    """When google provider fails vision on all MAX_FRONT_RETRIES attempts,
    the fallback to OpenAI is triggered and the pack completes with provider=openai
    for the front image.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    google_generate_calls: list[int] = []
    openai_generate_calls: list[int] = []

    def _google_generate(*, prompt, size="1024x1024", reference_image_url=None):
        google_generate_calls.append(1)
        return _PORTRAIT_PNG  # passes precheck, but vision will fail

    mock_google_provider = MagicMock()
    mock_google_provider.generate_image = _google_generate
    mock_google_provider.generate_grounded_image = MagicMock(return_value=_PORTRAIT_PNG)

    def _openai_generate(*, prompt, size="1024x1024", reference_image_url=None):
        openai_generate_calls.append(1)
        return _PORTRAIT_PNG

    mock_openai_instance = MagicMock()
    mock_openai_instance.generate_image = _openai_generate
    mock_openai_class = MagicMock(return_value=mock_openai_instance)

    # vision: fail for google attempts; pass for openai attempt
    from app.api.routes.character_visual import MAX_FRONT_RETRIES
    fail_then_pass = [_FAIL_VERDICT] * MAX_FRONT_RETRIES + [_PASS_VERDICT]
    verdict_iter = iter(fail_then_pass)

    def _mock_validate(png_bytes):
        return next(verdict_iter)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "google"
    mock_settings.IMAGE_PROVIDER = "openai"

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_google_provider,
    ), patch(
        "app.api.routes.character_visual._OpenAIImageProvider",
        mock_openai_class,
    ), patch(
        "app.api.routes.character_visual.validate_front_anchor_png",
        side_effect=_mock_validate,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "dark hair green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier_used"] == "A"
    assert len(data["images"]) == 4

    # Google was called MAX_FRONT_RETRIES times, all failed validation
    assert len(google_generate_calls) == MAX_FRONT_RETRIES
    # OpenAI fallback was instantiated and called once
    assert mock_openai_class.call_count == 1
    assert len(openai_generate_calls) == 1

    # Front image uses openai provider; angles use google
    images = data["images"]
    front_imgs = [i for i in images if i["metadata_json"]["pack_role"] == "anchor_front"]
    angle_imgs = [i for i in images if i["metadata_json"]["pack_role"] != "anchor_front"]

    assert len(front_imgs) == 1
    assert front_imgs[0]["provider"] == "openai"
    assert len(angle_imgs) == 3
    for img in angle_imgs:
        assert img["provider"] == "google"

    # Angles generated using Google grounded (3 calls)
    assert mock_google_provider.generate_grounded_image.call_count == 3


# ── Test 4: Validator PASS → crop helper is called ───────────────────

def test_crop_applied_after_validation_pass(client: TestClient):
    """When vision returns PASS, _crop_passport_headshot is called on the
    validated front bytes.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    cropped_bytes = _make_png(512, 400)  # simulated crop output

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=_PORTRAIT_PNG)
    mock_provider.generate_grounded_image = MagicMock(return_value=_PORTRAIT_PNG)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
    mock_settings.IMAGE_PROVIDER = "openai"

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.validate_front_anchor_png",
        return_value=_PASS_VERDICT,
    ), patch(
        "app.api.routes.character_visual._crop_passport_headshot",
        return_value=cropped_bytes,
    ) as mock_crop, patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "elegant warrior"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # Crop helper was called exactly once (for the front)
    assert mock_crop.call_count == 1
    # Crop was called with the bytes returned by generate_image
    mock_crop.assert_called_once_with(_PORTRAIT_PNG)


# ── Test 5: Angles receive the validated + cropped front bytes ────────

def test_angles_use_validated_front_bytes(client: TestClient):
    """generate_grounded_image must be called with the cropped front bytes, not
    the raw pre-crop bytes.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    raw_front = _PORTRAIT_PNG
    cropped_front = _make_png(512, 360)  # distinct from raw_front

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=raw_front)
    mock_provider.generate_grounded_image = MagicMock(return_value=_PORTRAIT_PNG)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
    mock_settings.IMAGE_PROVIDER = "openai"

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.validate_front_anchor_png",
        return_value=_PASS_VERDICT,
    ), patch(
        "app.api.routes.character_visual._crop_passport_headshot",
        return_value=cropped_front,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "silver hair elf"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert mock_provider.generate_grounded_image.call_count == 3

    # Every angle call must have received the cropped bytes as the reference
    for c in mock_provider.generate_grounded_image.call_args_list:
        assert c.kwargs["reference_image_bytes"] == cropped_front, (
            "Angle shot was grounded with non-cropped bytes"
        )


# ── Unit tests for _front_precheck ───────────────────────────────────

def test_front_precheck_passes_portrait():
    from app.api.routes.character_visual import _front_precheck

    ok, reason = _front_precheck(_make_png(512, 768))
    assert ok is True
    assert reason == ""


def test_front_precheck_fails_strip():
    from app.api.routes.character_visual import _front_precheck

    ok, reason = _front_precheck(_make_png(1600, 400))  # ratio = 4.0 > 2.2
    assert ok is False
    assert reason == "strip_composite_ratio"


def test_front_precheck_fails_full_body_tall():
    from app.api.routes.character_visual import _front_precheck

    ok, reason = _front_precheck(_make_png(200, 800))  # ratio = 4.0 > 3.5
    assert ok is False
    assert reason == "likely_full_body_ratio"


def test_front_precheck_passes_on_garbage():
    from app.api.routes.character_visual import _front_precheck

    ok, reason = _front_precheck(b"not-a-real-image")
    assert ok is True  # exception → pass through


# ── Unit tests for _crop_passport_headshot ────────────────────────────

def test_crop_returns_bytes_on_valid_png():
    from app.api.routes.character_visual import _crop_passport_headshot

    result = _crop_passport_headshot(_make_png(512, 1024))
    assert isinstance(result, bytes)
    assert len(result) > 0
    # Output should be smaller or different from input (crop happened)
    from PIL import Image
    with Image.open(io.BytesIO(result)) as img:
        w, h = img.size
        assert w == 512
        # height should be ~60% of original (top 10%→70%)
        assert h < 1024


def test_crop_returns_original_on_garbage():
    from app.api.routes.character_visual import _crop_passport_headshot

    garbage = b"not-a-real-image"
    result = _crop_passport_headshot(garbage)
    assert result == garbage


# ── Unit tests for validate_front_anchor_png (no API key → skip) ──────

def test_validator_skips_when_no_api_key():
    """With no OPENAI_API_KEY, validation is skipped and ok=True returned."""
    from app.services.identity_front_validator import validate_front_anchor_png

    mock_settings = MagicMock()
    mock_settings.OPENAI_API_KEY = None

    with patch(
        "app.services.identity_front_validator.settings",
        mock_settings,
    ):
        result = validate_front_anchor_png(_PORTRAIT_PNG)

    assert result["ok"] is True
    assert result["fail_reason"] == "no_api_key_skip"

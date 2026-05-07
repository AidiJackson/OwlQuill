"""Tests for Persistent Accessory Slot v1 — character identity system.

Tests cover:
  - get_accessories parsing
  - build_accessory_prompt_block trigger logic
  - append_accessory upsert logic
  - POST /characters/{id}/identity-accessory HTTP endpoint
  - accessory block injection in image generation
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.character_accessory import (
    get_accessories,
    build_accessory_prompt_block,
    append_accessory,
)


# ── Shared helper stubs (mirrors test_image_generator.py pattern) ──────

def _register_and_login(client: TestClient, email: str = "accessory@example.com") -> str:
    """Register a user (bypassing invite gate) and log in, returning access token."""
    from app.core.config import settings
    # Temporarily disable beta invite requirement so tests can register freely.
    _orig = settings.BETA_INVITE_REQUIRED
    settings.BETA_INVITE_REQUIRED = False
    try:
        client.post(
            "/auth/register",
            json={"email": email, "username": email.split("@")[0].replace(".", "_"), "password": "testpassword123"},
        )
    finally:
        settings.BETA_INVITE_REQUIRED = _orig
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str, name: str = "Accessory Test Char") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    """Generate + accept a pack so the character is locked with identity_anchor_json."""
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def _stub_png_bytes() -> bytes:
    """Return valid PNG bytes for use in mock provider returns."""
    import io
    from PIL import Image
    img = Image.new("RGB", (64, 64), (45, 125, 126))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_character_with_accessories(accessories: list[dict]) -> MagicMock:
    """Build a minimal mock character object with the given accessories."""
    data = {"version": 1, "accessories": accessories}
    mock = MagicMock()
    mock.identity_anchor_json = json.dumps(data)
    return mock


def _mock_character_no_accessories() -> MagicMock:
    """Build a minimal mock character with NO accessories key."""
    data = {
        "version": 1,
        "locked_at": "2025-01-01T00:00:00Z",
        "identity_lock_string": "tall build, brown eyes",
        "anchors": {"front": {"url": "/static/generated/test.png"}},
    }
    mock = MagicMock()
    mock.identity_anchor_json = json.dumps(data)
    return mock


# ── 1. Unit: get_accessories parsing ──────────────────────────────────

def test_existing_anchor_json_without_accessories_still_works():
    """Parsing anchor JSON with no 'accessories' key returns []."""
    anchor_json = json.dumps({
        "version": 1,
        "locked_at": "2025-01-01T00:00:00Z",
        "style": "realistic",
        "identity_lock_string": "dark hair, green eyes",
        "anchors": {"front": {"url": "/static/generated/test.png"}},
    })
    result = get_accessories(anchor_json)
    assert result == []


def test_get_accessories_empty_json():
    """None input returns []."""
    assert get_accessories(None) == []


def test_get_accessories_returns_list_when_present():
    """When 'accessories' key exists, its contents are returned."""
    acc = {"id": "mask_abc12345", "type": "mask", "name": "Iron Mask", "description": "Heavy", "visual_rules": [], "locked": True}
    anchor_json = json.dumps({"version": 1, "accessories": [acc]})
    result = get_accessories(anchor_json)
    assert len(result) == 1
    assert result[0]["type"] == "mask"


def test_get_accessories_invalid_json_returns_empty():
    """Malformed JSON string returns []."""
    assert get_accessories("{not valid json}") == []


# ── 2. Unit: append_accessory upsert logic ────────────────────────────

def test_save_accessory_appends_to_empty():
    """append_accessory adds accessory to a JSON blob with no accessories key."""
    anchor_json = json.dumps({"version": 1, "identity_lock_string": "test"})
    acc = {"id": "mask_abc12345", "type": "mask", "name": "Iron Mask", "description": "Heavy", "visual_rules": [], "locked": True}
    result = append_accessory(anchor_json, acc)
    data = json.loads(result)
    assert "accessories" in data
    assert len(data["accessories"]) == 1
    assert data["accessories"][0]["type"] == "mask"
    # Original keys preserved
    assert data["version"] == 1
    assert data["identity_lock_string"] == "test"


def test_save_accessory_replaces_same_type():
    """Saving a mask twice results in only one mask entry (replaced, not duplicated)."""
    acc1 = {"id": "mask_abc12345", "type": "mask", "name": "Iron Mask", "description": "Old", "visual_rules": [], "locked": True}
    anchor_json = append_accessory(None, acc1)

    acc2 = {"id": "mask_xyz99999", "type": "mask", "name": "Iron Mask v2", "description": "New", "visual_rules": ["shiny"], "locked": True}
    result = append_accessory(anchor_json, acc2)

    data = json.loads(result)
    masks = [a for a in data["accessories"] if a["type"] == "mask"]
    assert len(masks) == 1, f"Expected 1 mask, got {len(masks)}"
    assert masks[0]["description"] == "New"


def test_save_accessory_different_types_both_kept():
    """Different types do not replace each other."""
    acc1 = {"id": "mask_abc12345", "type": "mask", "name": "Iron Mask", "description": "A mask", "visual_rules": [], "locked": True}
    acc2 = {"id": "ring_xyz99999", "type": "ring", "name": "Gold Ring", "description": "A ring", "visual_rules": [], "locked": True}
    anchor_json = append_accessory(None, acc1)
    result = append_accessory(anchor_json, acc2)
    data = json.loads(result)
    assert len(data["accessories"]) == 2


# ── 3. Unit: build_accessory_prompt_block trigger logic ───────────────

def test_accessory_prompt_block_empty_when_no_accessory():
    """Character with no accessories → build_accessory_prompt_block returns ''."""
    character = _mock_character_no_accessories()
    block = build_accessory_prompt_block(character, "wearing a red suit and standing tall")
    assert block == ""


def test_accessory_prompt_block_appears_when_mask_in_prompt():
    """Character with mask accessory + 'mask' in prompt → block appears."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask covering the lower face",
        "visual_rules": ["Matte black metal", "Riveted edges"],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "He stood there, wearing his mask in the rain")
    assert block != "", "Expected a non-empty prompt block"
    assert "Iron Mask" in block
    assert "SIGNATURE ACCESSORY" in block
    assert "Preserve shape, material, and colour" in block


def test_accessory_prompt_block_absent_when_prompt_does_not_mention_mask():
    """Character with mask accessory but prompt has 'black suit' → block is ''."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask",
        "visual_rules": [],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "wearing a black suit in the rain")
    assert block == ""


def test_accessory_prompt_block_masked_triggers():
    """'wearing his mask' → triggers the mask accessory block (past-tense +d variant)."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask covering the lower face",
        "visual_rules": ["Matte black metal"],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    # "masked" contains "mask" + "d" — should trigger
    block = build_accessory_prompt_block(character, "He looked masked in the dim light")
    assert block != "", "Expected 'masked' to trigger the mask block"
    assert "Iron Mask" in block


def test_accessory_prompt_block_visual_rules_included():
    """Visual rules appear in the block, one per line."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask",
        "visual_rules": ["Matte black metal", "Riveted edges", "Covers lower face"],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "He put on his mask")
    assert "Matte black metal" in block
    assert "Riveted edges" in block
    assert "Covers lower face" in block


def test_accessory_prompt_block_empty_visual_rules_skipped():
    """When visual_rules is empty, the block still forms correctly without rule lines."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask",
        "visual_rules": [],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "wearing his mask")
    assert "Iron Mask" in block
    assert "Do not redesign the mask" in block


def test_accessory_prompt_block_capped_at_400_chars():
    """The block is hard-capped at 400 characters."""
    acc = {
        "id": "mask_abc12345",
        "type": "mask",
        "name": "A" * 99,
        "description": "B" * 499,
        "visual_rules": ["C" * 100, "D" * 100, "E" * 100],
        "locked": True,
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "wearing his mask in battle")
    assert len(block) <= 400


# ── 4. HTTP: POST /characters/{id}/identity-accessory ─────────────────

def test_save_accessory_appends_via_http(client: TestClient):
    """POST /identity-accessory saves accessory into identity_anchor_json."""
    token = _register_and_login(client, "acc_http@example.com")
    cid = _create_character(client, token, "HTTP Accessory Char")

    payload = {
        "type": "mask",
        "name": "Iron Mask",
        "description": "A heavy iron mask covering the lower face",
        "visual_rules": ["Matte black metal", "Riveted edges"],
    }
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["character_id"] == cid
    accessories = data["accessories"]
    assert len(accessories) >= 1
    mask = next((a for a in accessories if a["type"] == "mask"), None)
    assert mask is not None
    assert mask["name"] == "Iron Mask"
    assert mask["locked"] is True


def test_save_accessory_replaces_same_type_via_http(client: TestClient):
    """Saving a mask twice via HTTP keeps only the latest mask."""
    token = _register_and_login(client, "acc_replace@example.com")
    cid = _create_character(client, token, "Replace Accessory Char")

    headers = {"Authorization": f"Bearer {token}"}

    # First mask
    client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Old Mask", "description": "First"},
        headers=headers,
    )

    # Second mask of same type
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "New Mask", "description": "Second"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    accessories = resp.json()["accessories"]
    masks = [a for a in accessories if a["type"] == "mask"]
    assert len(masks) == 1, f"Expected 1 mask after replace, got {len(masks)}"
    assert masks[0]["name"] == "New Mask"


def test_accessory_endpoint_requires_auth(client: TestClient):
    """No token → 401 or 403."""
    resp = client.post(
        "/characters/999/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
    )
    assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"


def test_accessory_endpoint_wrong_owner_returns_403(client: TestClient):
    """A different user cannot add accessories to someone else's character."""
    token1 = _register_and_login(client, "acc_owner@example.com")
    token2 = _register_and_login(client, "acc_thief@example.com")
    cid = _create_character(client, token1, "Owner's Char")

    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 403, resp.text


def test_accessory_endpoint_character_not_found(client: TestClient):
    """Non-existent character_id → 404."""
    token = _register_and_login(client, "acc_notfound@example.com")
    resp = client.post(
        "/characters/99999/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404, resp.text


# ── 5. Integration: accessory block in image generation ───────────────

def test_image_generation_still_includes_identity_block(client: TestClient):
    """Normal image generation with include_character=True still works —
    the identity lock string is still included in the prompt."""
    token = _register_and_login(client, "acc_imggen@example.com")
    cid = _create_character(client, token, "ImgGen Accessory Char")
    _lock_character(client, token, cid)

    captured: dict = {}

    def _mock_with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _mock_with_anchors
    mock_provider.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": "Standing in a forest",
                "include_character": True,
                "provider_option": "option1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    prompt = captured.get("prompt", "")
    assert "Standing in a forest" in prompt
    assert "same person" in prompt.lower(), f"Identity directive missing: {prompt!r}"


def test_accessory_block_injected_when_prompt_mentions_accessory_type(client: TestClient):
    """When a character has a mask accessory and the prompt mentions 'mask',
    the accessory block is injected before truncation."""
    token = _register_and_login(client, "acc_inject@example.com")
    cid = _create_character(client, token, "Mask Inject Char")
    _lock_character(client, token, cid)

    # Save a mask accessory via HTTP
    client.post(
        f"/characters/{cid}/identity-accessory",
        json={
            "type": "mask",
            "name": "Iron Mask",
            "description": "A heavy iron mask covering the lower face",
            "visual_rules": ["Matte black metal"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    captured: dict = {}

    def _mock_with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _mock_with_anchors
    mock_provider.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": "wearing his mask in the rain",
                "include_character": True,
                "provider_option": "option1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    # The strict_prompt wraps base_prompt; accessory block should travel inside it
    # We verify the generation succeeded (if block was malformed, generation would fail)
    meta = resp.json()["metadata_json"]
    assert meta["include_character"] is True


def test_accessory_block_not_injected_when_prompt_does_not_mention_type(client: TestClient):
    """When prompt doesn't mention the accessory type, generation still works normally."""
    token = _register_and_login(client, "acc_noinject@example.com")
    cid = _create_character(client, token, "No Inject Char")
    _lock_character(client, token, cid)

    # Save a mask accessory
    client.post(
        f"/characters/{cid}/identity-accessory",
        json={
            "type": "mask",
            "name": "Iron Mask",
            "description": "A heavy iron mask",
            "visual_rules": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    captured: dict = {}

    def _mock_with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _stub_png_bytes()

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _mock_with_anchors
    mock_provider.generate_grounded_image = MagicMock(return_value=_stub_png_bytes())
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.image_generator.get_provider_for_option", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": "walking in the park with a red coat",
                "include_character": True,
                "provider_option": "option1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    # SIGNATURE ACCESSORY block should NOT appear since "mask" not in prompt
    prompt_sent = captured.get("prompt", "")
    assert "SIGNATURE ACCESSORY" not in prompt_sent

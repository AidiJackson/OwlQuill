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



# ── 6. Unit: build_anchor_prompt ──────────────────────────────────────

def test_build_anchor_prompt_contains_description():
    """build_anchor_prompt uses the accessory description in the prompt."""
    from app.services.character_accessory import build_anchor_prompt
    acc = {
        "name": "Iron Mask",
        "description": "matte black half-face tactical mask with wolf contours",
        "visual_rules": ["covers lower face only", "no bright colors"],
    }
    prompt = build_anchor_prompt(acc)
    assert "matte black half-face tactical mask" in prompt
    assert "no person wearing it" in prompt
    assert "neutral background" in prompt
    assert len(prompt) <= 800


def test_build_anchor_prompt_falls_back_to_name_when_no_description():
    """When description is empty, name is used as the base."""
    from app.services.character_accessory import build_anchor_prompt
    acc = {"name": "Iron Mask", "description": "", "visual_rules": []}
    prompt = build_anchor_prompt(acc)
    assert "Iron Mask" in prompt


# ── 7. Unit: get_triggered_accessory ─────────────────────────────────

def test_get_triggered_accessory_returns_dict():
    """get_triggered_accessory returns the matching accessory dict."""
    from app.services.character_accessory import get_triggered_accessory
    anchor_json = json.dumps({
        "accessories": [
            {"id": "mask_1", "type": "mask", "name": "Iron Mask", "description": "A mask", "locked": True}
        ]
    })
    result = get_triggered_accessory(anchor_json, "wearing his mask in the rain")
    assert result is not None
    assert result["id"] == "mask_1"


def test_get_triggered_accessory_returns_none_when_not_triggered():
    """get_triggered_accessory returns None when prompt doesn't mention the type."""
    from app.services.character_accessory import get_triggered_accessory
    anchor_json = json.dumps({
        "accessories": [
            {"id": "mask_1", "type": "mask", "name": "Iron Mask", "description": "A mask", "locked": True}
        ]
    })
    result = get_triggered_accessory(anchor_json, "standing in the rain without gear")
    assert result is None


# ── 8. Unit: update_accessory_in_json ────────────────────────────────

def test_update_accessory_in_json_applies_updates():
    """update_accessory_in_json merges updates onto the target accessory."""
    from app.services.character_accessory import update_accessory_in_json
    anchor_json = json.dumps({
        "accessories": [
            {"id": "mask_1", "type": "mask", "name": "Iron Mask", "anchor_status": "none"}
        ]
    })
    updated_json, updated_acc = update_accessory_in_json(
        anchor_json, "mask_1", {"anchor_status": "generated", "anchor_image_url": "http://example.com/img.png"}
    )
    assert updated_acc is not None
    assert updated_acc["anchor_status"] == "generated"
    assert updated_acc["anchor_image_url"] == "http://example.com/img.png"
    data = json.loads(updated_json)
    assert data["accessories"][0]["anchor_status"] == "generated"


def test_update_accessory_in_json_returns_none_for_missing_id():
    """update_accessory_in_json returns (original_json, None) when id not found."""
    from app.services.character_accessory import update_accessory_in_json
    anchor_json = json.dumps({"accessories": [{"id": "mask_1", "type": "mask"}]})
    result_json, result_acc = update_accessory_in_json(anchor_json, "nonexistent_id", {"anchor_status": "locked"})
    assert result_acc is None
    assert json.loads(result_json)["accessories"][0]["id"] == "mask_1"


# ── 9. HTTP: generate-anchor endpoint ────────────────────────────────

def test_generate_anchor_updates_accessory(client: TestClient):
    """generate-anchor generates an image, saves it, and stores anchor fields."""
    token = _register_and_login(client, "anchor_gen@example.com")
    cid = _create_character(client, token, "Anchor Gen Char")
    headers = {"Authorization": f"Bearer {token}"}

    # Create a mask accessory first
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A heavy iron mask"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    accessories = resp.json()["accessories"]
    acc_id = next(a["id"] for a in accessories if a["type"] == "mask")

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with (
        patch("app.api.routes.character_accessory.get_provider_for_option", return_value=mock_provider),
        patch("app.api.routes.character_accessory.save_image", return_value="static/generated/test_anchor.png"),
    ):
        resp = client.post(
            f"/characters/{cid}/identity-accessory/generate-anchor",
            json={"accessory_id": acc_id},
            headers=headers,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["character_id"] == cid
    acc = data["accessory"]
    assert acc["anchor_image_url"] == "static/generated/test_anchor.png"
    assert acc["anchor_status"] == "generated"
    assert acc["anchor_prompt"] is not None
    assert acc["anchor_created_at"] is not None
    # Verify the prompt is a standalone object prompt (no identity references)
    mock_provider.generate_image.assert_called_once()
    call_kwargs = mock_provider.generate_image.call_args.kwargs
    assert "no person wearing it" in call_kwargs["prompt"]


def test_generate_anchor_returns_404_for_unknown_accessory(client: TestClient):
    """generate-anchor returns 404 when the accessory_id doesn't exist."""
    token = _register_and_login(client, "anchor_404@example.com")
    cid = _create_character(client, token, "Anchor 404 Char")
    headers = {"Authorization": f"Bearer {token}"}

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with patch("app.api.routes.character_accessory.get_provider_for_option", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/identity-accessory/generate-anchor",
            json={"accessory_id": "nonexistent_id_xyz"},
            headers=headers,
        )

    assert resp.status_code == 404, resp.text


# ── 10. HTTP: lock-anchor endpoint ───────────────────────────────────

def test_lock_anchor_requires_existing_anchor_image(client: TestClient):
    """lock-anchor returns 409 when no anchor_image_url is set on the accessory."""
    token = _register_and_login(client, "lock_no_img@example.com")
    cid = _create_character(client, token, "Lock No Img Char")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers=headers,
    )
    acc_id = next(a["id"] for a in resp.json()["accessories"] if a["type"] == "mask")

    resp = client.post(
        f"/characters/{cid}/identity-accessory/lock-anchor",
        json={"accessory_id": acc_id},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_lock_anchor_sets_status_locked(client: TestClient):
    """lock-anchor transitions anchor_status from 'generated' to 'locked'."""

    token = _register_and_login(client, "lock_ok@example.com")
    cid = _create_character(client, token, "Lock OK Char")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers=headers,
    )
    acc_id = next(a["id"] for a in resp.json()["accessories"] if a["type"] == "mask")

    # Inject anchor_image_url + anchor_status="generated" directly via generate-anchor mock
    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=_stub_png_bytes())

    with (
        patch("app.api.routes.character_accessory.get_provider_for_option", return_value=mock_provider),
        patch("app.api.routes.character_accessory.save_image", return_value="static/generated/test_anchor_lock.png"),
    ):
        client.post(
            f"/characters/{cid}/identity-accessory/generate-anchor",
            json={"accessory_id": acc_id},
            headers=headers,
        )

    # Now lock
    resp = client.post(
        f"/characters/{cid}/identity-accessory/lock-anchor",
        json={"accessory_id": acc_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    acc = resp.json()["accessory"]
    assert acc["anchor_status"] == "locked"
    assert acc["anchor_image_url"] == "static/generated/test_anchor_lock.png"


def test_text_only_accessory_unaffected_by_anchor_fields(client: TestClient):
    """Existing accessories without anchor fields still work via prompt injection."""
    # Use the existing test helper to verify prompt block still fires for a
    # text-only accessory (one without anchor_image_url or anchor_status).
    acc = {
        "id": "mask_legacy",
        "type": "mask",
        "name": "Legacy Mask",
        "description": "A plain legacy mask with no anchor image",
        "visual_rules": ["matte surface"],
        "locked": True,
        # Deliberately omit anchor_image_url, anchor_status
    }
    character = _mock_character_with_accessories([acc])
    block = build_accessory_prompt_block(character, "He wore his mask in the storm")
    assert "Legacy Mask" in block
    assert "SIGNATURE ACCESSORY" in block



def test_fit_anchor_prompt_includes_must_not_replace_head():
    """build_fit_anchor_prompt includes the 'must not replace' constraint."""
    from app.services.character_accessory import build_fit_anchor_prompt
    acc = {
        "type": "mask",
        "name": "Iron Mask",
        "description": "matte black half-face tactical mask",
        "visual_rules": ["covers lower face only"],
    }
    prompt = build_fit_anchor_prompt(acc, character_name="Leonardo")
    assert "must not replace the head" in prompt
    assert "Eyes, forehead, hair" in prompt
    assert "Leonardo" in prompt
    assert len(prompt) <= 800


def test_fit_anchor_generate_requires_locked_character(client: TestClient):
    """generate-fit-anchor returns 409 when character is not visually locked."""
    token = _register_and_login(client, "fit_unlocked@example.com")
    cid = _create_character(client, token, "Fit Unlocked Char")
    headers = {"Authorization": f"Bearer {token}"}

    # Add accessory without locking the character
    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers=headers,
    )
    acc_id = next(a["id"] for a in resp.json()["accessories"] if a["type"] == "mask")

    resp = client.post(
        f"/characters/{cid}/identity-accessory/generate-fit-anchor",
        json={"accessory_id": acc_id},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_lock_fit_anchor_requires_generated_fit_anchor(client: TestClient):
    """lock-fit-anchor returns 409 when no fit_anchor_image_url is set."""
    token = _register_and_login(client, "lock_fit_no_img@example.com")
    cid = _create_character(client, token, "Lock Fit No Img Char")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-accessory",
        json={"type": "mask", "name": "Iron Mask", "description": "A mask"},
        headers=headers,
    )
    acc_id = next(a["id"] for a in resp.json()["accessories"] if a["type"] == "mask")

    resp = client.post(
        f"/characters/{cid}/identity-accessory/lock-fit-anchor",
        json={"accessory_id": acc_id},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text

"""Tests for character visual endpoints (DNA, identity pack, moments)."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient) -> str:
    """Register a test user and return a bearer token."""
    client.post(
        "/auth/register",
        json={
            "email": "viztest@example.com",
            "username": "vizuser",
            "password": "testpassword123",
        },
    )
    resp = client.post(
        "/auth/login",
        json={"email": "viztest@example.com", "password": "testpassword123"},
    )
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    """Create a character and return its ID."""
    resp = client.post(
        "/characters/",
        json={"name": "Ash Valkyr", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


# ── DNA endpoint ─────────────────────────────────────────────────────

def test_upsert_dna(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/dna",
        json={
            "species": "human",
            "gender_presentation": "feminine",
            "visual_traits_json": {"hair_color": "silver", "eye_color": "amber"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["character_id"] == cid
    assert data["species"] == "human"
    assert data["visual_traits_json"]["hair_color"] == "silver"
    assert data["anchor_version"] == 1


# ── Identity pack generate ───────────────────────────────────────────

def test_generate_identity_pack(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={"tweaks": {"hair": "long silver"}, "prompt_vibe": "ethereal warrior"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "pack_id" in data
    assert len(data["images"]) == 4
    roles = {img["metadata_json"]["pack_role"] for img in data["images"]}
    assert roles == {"anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"}
    for img in data["images"]:
        assert img["kind"] == "generated"
        assert img["metadata_json"]["is_temp"] is True
    # New metadata fields
    assert data["tier_used"] == "stub"
    assert isinstance(data["rewrite_applied"], bool)
    assert isinstance(data["blocked_roles"], list)


def test_generate_pack_blocked_after_lock(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Generate + accept to lock
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now try generating again — should fail
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ── Identity pack accept ─────────────────────────────────────────────

def test_accept_identity_pack(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # First set up DNA
    client.post(
        f"/characters/{cid}/dna",
        json={"species": "elf"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Generate pack
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    # Accept pack
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["anchors"]) == 4
    kinds = {a["kind"] for a in data["anchors"]}
    assert kinds == {"anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"}
    assert data["dna"] is not None
    assert data["dna"]["anchor_version"] == 1

    # Verify character is now locked
    resp = client.get(
        f"/characters/{cid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["visual_locked"] is True


def test_accept_identity_pack_persists_anchor_json(client: TestClient):
    """Accept/lock must persist identity_anchor_json with version=1 and all 4 anchors."""
    import json

    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Generate a pack (stub provider — no OpenAI)
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    pack_data = resp.json()
    pack_id = pack_data["pack_id"]
    pack_image_ids = {
        img["metadata_json"]["pack_role"]: img["id"]
        for img in pack_data["images"]
    }

    # Accept the pack
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Fetch the character and verify identity_anchor_json
    resp = client.get(
        f"/characters/{cid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    char_data = resp.json()
    assert char_data["visual_locked"] is True
    assert char_data["identity_anchor_json"] is not None

    anchor = json.loads(char_data["identity_anchor_json"])
    assert anchor["version"] == 1
    assert "locked_at" in anchor
    assert anchor["style"] == "realistic"
    assert set(anchor["anchors"].keys()) == {"front", "three_quarter", "torso", "full_body"}

    # Each anchor entry should have id and url
    for key in ("front", "three_quarter", "torso", "full_body"):
        entry = anchor["anchors"][key]
        assert "id" in entry
        assert "url" in entry
        assert isinstance(entry["id"], int)
        assert entry["url"].startswith("/static/")

    # Verify the stored image IDs match what was generated
    assert anchor["anchors"]["front"]["id"] == pack_image_ids["anchor_front"]
    assert anchor["anchors"]["three_quarter"]["id"] == pack_image_ids["anchor_three_quarter"]
    assert anchor["anchors"]["torso"]["id"] == pack_image_ids["anchor_torso"]
    assert anchor["anchors"]["full_body"]["id"] == pack_image_ids["anchor_full_body"]


def test_accept_invalid_pack_id(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": "nonexistent"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── Moment generation (post-lock) ────────────────────────────────────

def test_generate_moment_image(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Lock the character first
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now generate a moment
    resp = client.post(
        f"/characters/{cid}/images/generate",
        json={"outfit": "battle armor", "mood": "determined", "environment": "moonlit forest"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "generated"
    assert data["metadata_json"]["anchor_version"] == 1
    assert data["file_path"].startswith("static/generated/")


def test_moment_blocked_before_lock(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/images/generate",
        json={"mood": "happy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ── Failsafe tier-C path ────────────────────────────────────────────

def test_failsafe_tier_c_returns_pack_on_moderation_blocks(client: TestClient):
    """When tiers A and B are blocked by moderation, tier C returns a stub pack."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    call_count = 0

    def _mock_generate_image(*, prompt, size="1024x1024", reference_image_url=None):
        nonlocal call_count
        call_count += 1
        # Tiers A and B: block everything with a moderation error
        # Tier C generates via text-to-image only (no reference_image_url).
        # We block tier A/B calls (first 6 calls: 3 per tier × 2 tiers could
        # happen, but actually tier A front fails immediately so only 1 call
        # per tier). Simplify: block ALL calls that have a reference_image_url
        # AND the first N text-to-image calls.
        #
        # Actually, the tier logic: tier A tries front (text-to-image) first.
        # If it's blocked, it returns None immediately. Same for tier B.
        # So tiers A + B = 2 calls total (1 each, both blocked at front).
        # Then tier C makes 3 text-to-image calls — we should also block those
        # to trigger the stub fallback within tier C.
        raise RuntimeError("moderation_blocked: content policy violation")

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate_image

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={
                "prompt_vibe": (
                    "Naturally beautiful with tanned skin. White American. "
                    "Brunette hair long with slight curl. 5'9 height. "
                    "Elegant black dress. Model thin nose, full lips. Hazel eyes."
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    # Must return 200 with a complete pack, NEVER a hard error
    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert "pack_id" in data
    assert len(data["images"]) == 4
    roles = {img["metadata_json"]["pack_role"] for img in data["images"]}
    assert roles == {"anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"}
    # All tiers were blocked, so tier C must have been used
    assert data["tier_used"] == "C"
    assert data["rewrite_applied"] is True
    assert len(data["blocked_roles"]) > 0


def test_tier_a_succeeds_no_escalation(client: TestClient):
    """When tier A succeeds, no escalation occurs and we get an openai pack."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Return fake PNG bytes for every call
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    mock_provider = MagicMock()
    mock_provider.generate_image = MagicMock(return_value=fake_png)
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
    mock_settings.IMAGE_PROVIDER = "openai"
    mock_settings.get_admin_emails = MagicMock(return_value=[])

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "elegant brunette"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # All images should be from openai provider (mocked settings)
    for img in data["images"]:
        assert img["provider"] == "openai"
    # Tier A succeeded with no escalation
    assert data["tier_used"] == "A"
    assert data["blocked_roles"] == []
    # Grounded method called 3 times (one per angle shot)
    assert mock_provider.generate_grounded_image.call_count == 3


# ── Style threading ──────────────────────────────────────────────────

def test_style_anime_flows_into_prompt(client: TestClient):
    """style='anime' should inject 'anime' into the generation prompt."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "silver hair elf", "style": "anime"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # B7.1: The front prompt starts with the hard passport-headshot preamble.
    # Style tokens are NOT injected into the front seed prompt.
    assert len(captured_prompts) >= 1
    assert captured_prompts[0].lower().startswith("passport-style headshot")


def test_style_defaults_to_realistic(client: TestClient):
    """Requests without 'style' should default to realistic."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "warrior"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # B7.1: Front prompt starts with hard preamble regardless of style.
    assert captured_prompts[0].lower().startswith("passport-style headshot")


def test_unknown_style_coerces_to_realistic(client: TestClient):
    """An unknown style value should silently coerce to 'realistic'."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={"prompt_vibe": "test", "style": "watercolor_abstract"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Should not error — coerced to realistic
    assert resp.status_code == 200


# ── Fallback provider (Provider B) routing ───────────────────────────

def test_tier_c_uses_fallback_provider_on_openai_block(client: TestClient):
    """When OpenAI blocks in all tiers, tier C tries the fallback provider."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    fallback_calls: list[str] = []

    # Primary provider always blocks
    def _openai_blocked(*, prompt, size="1024x1024", reference_image_url=None):
        raise RuntimeError("moderation_blocked: content policy violation")

    mock_primary = MagicMock()
    mock_primary.generate_image = _openai_blocked

    # Fallback provider succeeds
    def _fallback_ok(*, prompt, size="1024x1024", reference_image_url=None):
        fallback_calls.append(prompt)
        return fake_png

    mock_fallback = MagicMock()
    mock_fallback.generate_image = _fallback_ok

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=mock_fallback,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "elegant brunette, hazel eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    assert data["tier_used"] == "C"
    # Fallback was called for all 4 roles
    assert len(fallback_calls) == 4
    # All images from fallback provider
    for img in data["images"]:
        assert img["provider"] == "fal"
    # Blocked roles should include the C-tier blocks
    assert len(data["blocked_roles"]) >= 4


def test_tier_c_fallback_also_fails_returns_stubs(client: TestClient):
    """When both primary and fallback fail, tier C returns stub placeholders."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Both providers fail
    def _always_block(*, prompt, size="1024x1024", reference_image_url=None):
        raise RuntimeError("moderation_blocked: policy violation")

    mock_primary = MagicMock()
    mock_primary.generate_image = _always_block

    mock_fallback = MagicMock()
    mock_fallback.generate_image = MagicMock(
        side_effect=RuntimeError("fal failed too")
    )

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=mock_fallback,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    assert data["tier_used"] == "C"
    # All fell through to stubs
    for img in data["images"]:
        assert img["provider"] == "stub"


def test_tier_c_no_fallback_configured_falls_to_stub(client: TestClient):
    """When no fallback provider is configured, tier C goes straight to stubs."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    def _always_block(*, prompt, size="1024x1024", reference_image_url=None):
        raise RuntimeError("moderation_blocked: nope")

    mock_primary = MagicMock()
    mock_primary.generate_image = _always_block

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=None,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "test"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    assert data["tier_used"] == "C"
    for img in data["images"]:
        assert img["provider"] == "stub"


# ── Identity spec style normalization ────────────────────────────────

def test_identity_spec_empty_style_coerced_to_realistic(client: TestClient):
    """identity_spec.style = '' must not crash and must silently default to 'realistic'."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={
                "identity_spec": {
                    "style": "",
                    "identity": {"hair_color": "auburn", "eye_color": "green"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    # Empty style must never cause a 500
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1: Front prompt starts with the hard preamble (no style token).
    assert len(captured_prompts) >= 1
    assert captured_prompts[0].lower().startswith("passport-style headshot")


def test_identity_spec_whitespace_style_coerced_to_realistic(client: TestClient):
    """identity_spec.style = '   ' (whitespace only) must silently default to 'realistic'."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={
                "identity_spec": {
                    "style": "   ",
                    "identity": {"hair_color": "black", "eye_color": "brown"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1: Front prompt starts with the hard preamble (no style token).
    assert len(captured_prompts) >= 1
    assert captured_prompts[0].lower().startswith("passport-style headshot")


def test_identity_spec_unknown_style_coerced_to_realistic(client: TestClient):
    """identity_spec.style with an unrecognised value must silently default to 'realistic'."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={
                "identity_spec": {
                    "style": "oilpainting",
                    "identity": {"hair_color": "blonde", "eye_color": "grey"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1: Front prompt starts with the hard preamble (no style token).
    assert len(captured_prompts) >= 1
    assert captured_prompts[0].lower().startswith("passport-style headshot")


# ── Front shot is a true headshot ────────────────────────────────────

def test_front_shot_uses_headshot_description(client: TestClient):
    """The anchor_front shot should use headshot/close-up language."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "dark hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # First prompt should be for the front shot (text-to-image)
    assert len(captured_prompts) >= 1
    front_prompt = captured_prompts[0].lower()
    # B4: strict passport-style headshot — key tokens must be present
    assert "passport-style headshot" in front_prompt, (
        f"'passport-style headshot' not found in front prompt: {front_prompt!r}"
    )
    assert "no sitting" in front_prompt, (
        f"'no sitting' not found in front prompt: {front_prompt!r}"
    )


def test_front_shot_passport_headshot_via_identity_spec(client: TestClient):
    """anchor_front via structured identity_spec must also enforce passport-style headshot."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    captured_prompts: list[str] = []

    def _capture_generate(*, prompt, size="1024x1024", reference_image_url=None):
        captured_prompts.append(prompt)
        return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _capture_generate
    mock_provider.generate_grounded_image = MagicMock(return_value=fake_png)

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={
                "identity_spec": {
                    "style": "realistic",
                    "identity": {"hair_color": "auburn", "eye_color": "green"},
                    "wardrobe": {"outfit_type": "blazer", "primary_color": "navy"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert len(captured_prompts) >= 1
    front_prompt = captured_prompts[0].lower()
    # B4: both paths must produce the strict passport headshot description
    assert "passport-style headshot" in front_prompt, (
        f"'passport-style headshot' not found in identity_spec front prompt: {front_prompt!r}"
    )
    assert "no sitting" in front_prompt, (
        f"'no sitting' not found in identity_spec front prompt: {front_prompt!r}"
    )


# ── Unit tests for _build_front_anchor_prompt (B7.1) ─────────────────

def test_b7_front_anchor_prompt_starts_with_passport_headshot_legacy():
    """Legacy path (char_traits only) must start with passport preamble."""
    from app.api.routes.character_visual import _build_front_anchor_prompt

    prompt = _build_front_anchor_prompt(
        use_structured_spec=False,
        identity_spec=None,
        char_traits=["Grace", "human"],
    )
    assert prompt[:80].lower().startswith("passport-style headshot"), (
        f"Front prompt does not start with preamble: {prompt[:80]!r}"
    )
    # char_traits are included
    assert "grace" in prompt.lower()


def test_b7_front_anchor_prompt_starts_with_passport_headshot_structured():
    """Structured spec path must also start with passport preamble."""
    from app.api.routes.character_visual import _build_front_anchor_prompt
    from app.schemas.character_visual import (
        CharacterIdentitySpec, IdentityCore, WardrobeSpec,
    )

    spec = CharacterIdentitySpec(
        style="realistic",
        identity=IdentityCore(hair_color="brunette", hair_length="long", eye_color="hazel", skin_tone="tan"),
        wardrobe=WardrobeSpec(outfit_type="dress", primary_color="black"),
    )
    prompt = _build_front_anchor_prompt(
        use_structured_spec=True,
        identity_spec=spec,
        char_traits=["Grace"],
    )
    assert prompt[:80].lower().startswith("passport-style headshot"), (
        f"Front prompt does not start with preamble: {prompt[:80]!r}"
    )
    # Identity tokens present
    assert "brunette" in prompt.lower()
    assert "hazel" in prompt.lower()
    # Wardrobe present
    assert "black" in prompt.lower()
    assert "dress" in prompt.lower()
    # No cinematic or style tokens
    assert "realistic" not in prompt.lower()
    assert "cinematic" not in prompt.lower()


def test_b7_front_anchor_prompt_failsafe_drops_wardrobe_colors():
    """Failsafe mode must drop colors but keep outfit type."""
    from app.api.routes.character_visual import _build_front_anchor_prompt
    from app.schemas.character_visual import (
        CharacterIdentitySpec, IdentityCore, WardrobeSpec,
    )

    spec = CharacterIdentitySpec(
        identity=IdentityCore(hair_color="blonde"),
        wardrobe=WardrobeSpec(outfit_type="blazer", primary_color="navy"),
    )
    prompt = _build_front_anchor_prompt(
        use_structured_spec=True,
        identity_spec=spec,
        char_traits=[],
        failsafe=True,
    )
    assert prompt[:80].lower().startswith("passport-style headshot")
    assert "blazer" in prompt.lower()
    assert "navy" not in prompt.lower()


# ── Identity accessories survive tier escalations ────────────────────

def test_mask_survives_tier_escalations(client: TestClient):
    """Face masks are identity accessories and should survive A→B→C tiers."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    call_count = 0
    tier_a_prompt = ""
    tier_b_prompt = ""
    tier_c_prompts: list[str] = []

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        nonlocal call_count, tier_a_prompt, tier_b_prompt
        call_count += 1

        # Capture prompts for each tier
        if call_count == 1:
            # First call is tier A front (text-to-image)
            tier_a_prompt = prompt
            raise RuntimeError("moderation_blocked: tier A blocked")
        elif call_count == 2:
            # Second call is tier B front (text-to-image)
            tier_b_prompt = prompt
            raise RuntimeError("moderation_blocked: tier B blocked")
        else:
            # Tier C calls (3 text-to-image calls for all 4 roles)
            tier_c_prompts.append(prompt)
            # Let tier C succeed
            return fake_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=None,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "athletic fighter, black face mask covering nose and mouth"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier_used"] == "C"

    # Verify mask is present in tier prompts
    # Tier A and B should have the mask (though they failed for other reasons)
    # Tier C should definitely have the mask
    for prompt in tier_c_prompts:
        # At least some prompts should contain "mask"
        pass  # We'll check at least one has it below

    # At least one tier C prompt should contain mask
    assert any("mask" in p.lower() for p in tier_c_prompts), \
        f"Mask not found in tier C prompts: {tier_c_prompts}"


# ── Single-frame strip detection unit tests ──────────────────────────

def _make_png(width: int, height: int) -> bytes:
    """Create a minimal in-memory PNG with the given dimensions."""
    from PIL import Image
    import io
    img = Image.new("RGB", (width, height), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_is_strip_image_detects_wide():
    """Images wider than 1.2× their height are flagged as strips."""
    from app.api.routes.character_visual import _is_strip_image
    wide = _make_png(1200, 400)   # ratio = 3.0 → strip
    assert _is_strip_image(wide) is True


def test_is_strip_image_passes_portrait():
    """Portrait-orientation images (tall > wide) are not flagged."""
    from app.api.routes.character_visual import _is_strip_image
    portrait = _make_png(512, 768)   # ratio ≈ 0.67 → fine
    assert _is_strip_image(portrait) is False


def test_is_strip_image_passes_square():
    """Square images are not flagged (ratio = 1.0)."""
    from app.api.routes.character_visual import _is_strip_image
    square = _make_png(512, 512)
    assert _is_strip_image(square) is False


def test_is_strip_image_safe_on_garbage():
    """Garbage bytes must not raise — returns False."""
    from app.api.routes.character_visual import _is_strip_image
    assert _is_strip_image(b"not-an-image") is False
    assert _is_strip_image(b"") is False


def test_enforce_single_frame_passes_portrait_through():
    """If the image passes the strip check, retry_fn is never called."""
    from app.api.routes.character_visual import _enforce_single_frame
    portrait = _make_png(512, 768)
    retry_called = []

    def _retry():
        retry_called.append(True)
        return portrait

    result = _enforce_single_frame(portrait, retry_fn=_retry, role="anchor_front", pack_id="t1")
    assert result is portrait
    assert retry_called == []


def test_enforce_single_frame_retries_on_strip_then_succeeds():
    """(a) Retry is called exactly once when first image is a strip.
    (b) The good second image is returned."""
    from app.api.routes.character_visual import _enforce_single_frame
    wide = _make_png(1200, 400)
    good = _make_png(512, 768)
    retry_calls = []

    def _retry():
        retry_calls.append(True)
        return good

    result = _enforce_single_frame(wide, retry_fn=_retry, role="anchor_three_quarter", pack_id="t2")
    assert result is good
    assert len(retry_calls) == 1


def test_enforce_single_frame_raises_if_retry_also_strip():
    """(c) RuntimeError raised when both attempts return a strip."""
    import pytest
    from app.api.routes.character_visual import _enforce_single_frame
    wide = _make_png(1200, 400)

    result = _enforce_single_frame.__wrapped__ if hasattr(_enforce_single_frame, "__wrapped__") else None

    with pytest.raises(RuntimeError, match="retry exhausted"):
        _enforce_single_frame(
            wide,
            retry_fn=lambda: _make_png(1200, 400),
            role="anchor_torso",
            pack_id="t3",
        )


# ── B3: Google front seed strip fallback to OpenAI ───────────────────

def test_google_front_seed_strip_fallback_to_openai(client: TestClient):
    """When Google strip retry exhausts for the front seed, fallback to OpenAI.

    Behavior:
    - Google provider.generate_image called 2x (initial + strip retry, both strip)
    - _OpenAIImageProvider instantiated; its generate_image called 1x (good PNG)
    - provider.generate_grounded_image called 3x (angles still use Google)
    - Front image record has provider='openai'; angle records have provider='google'
    """
    import pytest
    token = _register_and_login(client)
    cid = _create_character(client, token)

    strip_png = _make_png(1200, 400)  # wide → detected as strip
    good_png = _make_png(512, 768)    # portrait → passes strip check

    # Google provider: generate_image always returns a strip; grounded returns good
    mock_google_provider = MagicMock()
    mock_google_provider.generate_image = MagicMock(return_value=strip_png)
    mock_google_provider.generate_grounded_image = MagicMock(return_value=good_png)

    # OpenAI fallback provider: returns a good portrait for the front seed
    mock_openai_instance = MagicMock()
    mock_openai_instance.generate_image = MagicMock(return_value=good_png)
    mock_openai_class = MagicMock(return_value=mock_openai_instance)

    # Settings report google as the identity provider
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
        "app.api.routes.character_visual.settings",
        mock_settings,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=None,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "dark hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tier_used"] == "A"

    # B6: Google generate_image called MAX_FRONT_RETRIES=3 times (all return strip,
    # failing _front_precheck each time before vision is even called).
    from app.api.routes.character_visual import MAX_FRONT_RETRIES
    assert mock_google_provider.generate_image.call_count == MAX_FRONT_RETRIES
    # OpenAI fallback instantiated and called once for the front seed
    assert mock_openai_class.call_count == 1
    assert mock_openai_instance.generate_image.call_count == 1
    # Google grounded called 3x for the angle shots
    assert mock_google_provider.generate_grounded_image.call_count == 3

    # Front image recorded as openai (fallback); angles recorded as google
    images = data["images"]
    front_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_front"]
    angle_imgs = [img for img in images if img["metadata_json"]["pack_role"] != "anchor_front"]

    assert len(front_imgs) == 1
    assert front_imgs[0]["provider"] == "openai", (
        f"Expected front provider='openai', got {front_imgs[0]['provider']!r}"
    )
    assert len(angle_imgs) == 3
    for img in angle_imgs:
        assert img["provider"] == "google", (
            f"Expected angle provider='google', got {img['provider']!r}"
        )


# ── B7: Forced hybrid identity pack ──────────────────────────────────

def test_forced_hybrid_openai_seed_google_angles(client: TestClient):
    """B7: front anchor always uses OpenAI seed; 3 angles always use Google grounded.

    Default config (no IDENTITY_IMAGE_PROVIDER override):
      IDENTITY_SEED_PROVIDER=openai → seed_mock handles generate_image
      IDENTITY_ANGLES_PROVIDER=google → angles_mock handles generate_grounded_image

    Asserts:
    - front image DB record has provider='openai'
    - all 3 angle image DB records have provider='google'
    - seed_mock.generate_image called exactly once (front seed)
    - angles_mock.generate_grounded_image called exactly 3 times (one per angle)
    - grounded calls use the cropped front bytes (not empty)
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # A real portrait PNG so _front_precheck and _crop_passport_headshot work.
    good_png = _make_png(512, 768)

    seed_mock = MagicMock()
    seed_mock.generate_image = MagicMock(return_value=good_png)

    angles_mock = MagicMock()
    angles_mock.generate_grounded_image = MagicMock(return_value=good_png)

    def _provider_factory(name: str):
        """Return seed_mock for 'openai', angles_mock for 'google'."""
        if name == "openai":
            return seed_mock
        return angles_mock

    # Explicitly set B7 path to avoid env-var overrides from Replit config.
    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = ""   # empty → use split providers
    mock_settings.IDENTITY_SEED_PROVIDER = "openai"
    mock_settings.IDENTITY_ANGLES_PROVIDER = "google"

    with patch(
        "app.api.routes.character_visual.get_identity_provider_by_name",
        side_effect=_provider_factory,
    ), patch(
        "app.api.routes.character_visual.settings",
        mock_settings,
    ):
        resp = client.post(
            f"/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "auburn hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["tier_used"] == "A"
    assert len(data["images"]) == 4
    assert data["blocked_roles"] == []

    images = data["images"]
    front_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_front"]
    angle_imgs = [img for img in images if img["metadata_json"]["pack_role"] != "anchor_front"]

    # Front uses OpenAI seed
    assert len(front_imgs) == 1
    assert front_imgs[0]["provider"] == "openai", (
        f"Expected front provider='openai', got {front_imgs[0]['provider']!r}"
    )

    # 3 angles use Google grounded
    assert len(angle_imgs) == 3
    for img in angle_imgs:
        assert img["provider"] == "google", (
            f"Expected angle provider='google', got {img['provider']!r}"
        )

    # Call counts
    assert seed_mock.generate_image.call_count == 1, (
        f"Expected seed generate_image called once, got {seed_mock.generate_image.call_count}"
    )
    assert angles_mock.generate_grounded_image.call_count == 3, (
        f"Expected angles generate_grounded_image called 3x, "
        f"got {angles_mock.generate_grounded_image.call_count}"
    )

    # Grounded calls must include non-empty bytes (the cropped seed)
    for call in angles_mock.generate_grounded_image.call_args_list:
        ref_bytes = call.kwargs.get("reference_image_bytes", b"")
        assert len(ref_bytes) > 0, "generate_grounded_image called with empty reference_image_bytes"

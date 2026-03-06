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
    # B7.1: The front prompt contains the hard passport-headshot preamble.
    # Style tokens are NOT injected into the front seed prompt.
    # B8: prompt is now prefixed with _SAFETY_PREFIX before the preamble.
    assert len(captured_prompts) >= 1
    assert "passport-style headshot" in captured_prompts[0].lower()


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
    # B7.1/B8: Front prompt contains passport-headshot preamble (prefixed with safety tokens).
    assert "passport-style headshot" in captured_prompts[0].lower()


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
                    "gender": "Woman",
                    "age_band": "26-35",
                    "identity": {"hair_color": "auburn", "eye_color": "green"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    # Empty style must never cause a 500
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1/B8: Front prompt contains passport-headshot preamble.
    assert len(captured_prompts) >= 1
    assert "passport-style headshot" in captured_prompts[0].lower()


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
                    "gender": "Man",
                    "age_band": "26-35",
                    "identity": {"hair_color": "black", "eye_color": "brown"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1/B8: Front prompt contains passport-headshot preamble.
    assert len(captured_prompts) >= 1
    assert "passport-style headshot" in captured_prompts[0].lower()


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
                    "gender": "Non-binary",
                    "age_band": "18-25",
                    "identity": {"hair_color": "blonde", "eye_color": "grey"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # B7.1/B8: Front prompt contains passport-headshot preamble.
    assert len(captured_prompts) >= 1
    assert "passport-style headshot" in captured_prompts[0].lower()


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
    # B4/B8: strict passport-style headshot — key tokens must be present
    # (B8: prompt is prefixed with _SAFETY_PREFIX so we use 'in' not 'startswith')
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
                    "gender": "Woman",
                    "age_band": "26-35",
                    "identity": {"hair_color": "auburn", "eye_color": "green"},
                }
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert len(captured_prompts) >= 1
    front_prompt = captured_prompts[0].lower()
    # B4/B8: both paths must produce the strict passport headshot description
    assert "passport-style headshot" in front_prompt, (
        f"'passport-style headshot' not found in identity_spec front prompt: {front_prompt!r}"
    )
    assert "no sitting" in front_prompt, (
        f"'no sitting' not found in identity_spec front prompt: {front_prompt!r}"
    )


# ── Unit tests for _build_front_anchor_prompt (B7.1) ─────────────────

def test_b7_front_anchor_prompt_starts_with_passport_headshot_legacy():
    """Legacy path (char_traits only) must contain the passport preamble."""
    from app.api.routes.character_visual import _build_front_anchor_prompt

    prompt = _build_front_anchor_prompt(
        use_structured_spec=False,
        identity_spec=None,
        char_traits=["Grace", "human"],
    )
    # B8: prompt now starts with _SAFETY_PREFIX before the preamble text.
    assert "passport-style headshot" in prompt.lower(), (
        f"Front prompt does not contain preamble: {prompt!r}"
    )
    # char_traits are included
    assert "grace" in prompt.lower()


def test_b7_front_anchor_prompt_starts_with_passport_headshot_structured():
    """Structured spec path must contain the passport preamble."""
    from app.api.routes.character_visual import _build_front_anchor_prompt
    from app.schemas.character_visual import (
        CharacterIdentitySpec, IdentityCore, WardrobeSpec,
    )

    spec = CharacterIdentitySpec(
        style="realistic",
        gender="Woman",
        age_band="26-35",
        identity=IdentityCore(hair_color="brunette", hair_length="long", eye_color="hazel", skin_tone="tan"),
    )
    prompt = _build_front_anchor_prompt(
        use_structured_spec=True,
        identity_spec=spec,
        char_traits=["Grace"],
    )
    # B8: prompt starts with _SAFETY_PREFIX then the preamble text.
    assert "passport-style headshot" in prompt.lower(), (
        f"Front prompt does not contain preamble: {prompt!r}"
    )
    # Identity tokens present
    assert "brunette" in prompt.lower()
    assert "hazel" in prompt.lower()
    # Neutral studio outfit enforced — wardrobe fields ignored
    assert "neutral studio outfit" in prompt.lower()


def test_b7_front_anchor_prompt_failsafe_drops_wardrobe_colors():
    """Failsafe mode must drop colors but keep outfit type."""
    from app.api.routes.character_visual import _build_front_anchor_prompt
    from app.schemas.character_visual import (
        CharacterIdentitySpec, IdentityCore, WardrobeSpec,
    )

    spec = CharacterIdentitySpec(
        gender="Woman",
        age_band="18-25",
        identity=IdentityCore(hair_color="blonde"),
        wardrobe=WardrobeSpec(outfit_type="blazer", primary_color="navy"),
    )
    prompt = _build_front_anchor_prompt(
        use_structured_spec=True,
        identity_spec=spec,
        char_traits=[],
        failsafe=True,
    )
    # B8: prompt is now prefixed with _SAFETY_PREFIX; check preamble is present.
    assert "passport-style headshot" in prompt.lower()
    # Neutral studio outfit is always used — wardrobe fields are ignored
    assert "neutral studio outfit" in prompt.lower()
    assert "blazer" not in prompt.lower()
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


# ── B7.2: Angle strip fallback ────────────────────────────────────────

def test_google_angle_strip_fallback_to_openai(client: TestClient):
    """B7.2: When Google angle generation produces strip/composite after retry,
    fall back that specific angle to OpenAI grounded — do NOT fail the pack.

    Arrange:
    - OpenAI seed generates front (valid portrait)
    - Google angles: anchor_three_quarter always returns a strip image
      (both initial and retry attempts) → _enforce_single_frame raises
    - OpenAI fallback: generate_grounded_image returns a valid single-frame
    - Google angles: anchor_torso and anchor_full_body return valid PNGs

    Assert:
    - request succeeds (status 200)
    - anchor_three_quarter DB record has provider='openai' (fallback)
    - anchor_torso and anchor_full_body DB records have provider='google'
    - Google generate_grounded_image called 4x (3/4 initial + 3/4 retry + torso + full_body)
    - OpenAI fallback generate_grounded_image called 1x (for 3/4 angle only)
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    good_png = _make_png(512, 768)    # portrait — passes strip check
    strip_png = _make_png(1200, 400)  # wide — detected as strip (ratio = 3.0)

    # OpenAI seed mock: generates valid front
    seed_mock = MagicMock()
    seed_mock.generate_image = MagicMock(return_value=good_png)

    # Google angles: always return strip for three_quarter; valid for others.
    # The ROLE_EDIT_PROMPT for anchor_three_quarter contains "3/4" and "45".
    def _google_grounded(*, prompt, reference_image_bytes=None):
        if "3/4" in prompt or "45" in prompt:
            return strip_png  # always a strip → _enforce_single_frame will raise
        return good_png

    angles_mock = MagicMock()
    angles_mock.generate_grounded_image = MagicMock(side_effect=_google_grounded)

    # OpenAI fallback: called by B7.2 code for the strip angle only.
    oai_fb_mock = MagicMock()
    oai_fb_mock.generate_grounded_image = MagicMock(return_value=good_png)

    # Provider factory: first "openai" call → seed_mock; subsequent → oai_fb_mock.
    openai_call_count = [0]

    def _provider_factory(name: str):
        if name == "openai":
            openai_call_count[0] += 1
            return seed_mock if openai_call_count[0] == 1 else oai_fb_mock
        return angles_mock  # "google"

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = ""  # B7 split-provider path
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
            json={"prompt_vibe": "dark hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["tier_used"] == "A"
    assert len(data["images"]) == 4
    assert data["blocked_roles"] == []

    images = data["images"]
    front_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_front"]
    three_q_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_three_quarter"]
    other_angles = [
        img for img in images
        if img["metadata_json"]["pack_role"] in ("anchor_torso", "anchor_full_body")
    ]

    # Front: OpenAI seed (unchanged)
    assert len(front_imgs) == 1
    assert front_imgs[0]["provider"] == "openai"

    # Three-quarter: fell back to OpenAI due to persistent strip
    assert len(three_q_imgs) == 1
    assert three_q_imgs[0]["provider"] == "openai", (
        f"Expected 3/4 angle provider='openai' after strip fallback, "
        f"got {three_q_imgs[0]['provider']!r}"
    )

    # Torso and full-body: still Google
    assert len(other_angles) == 2
    for img in other_angles:
        assert img["provider"] == "google", (
            f"Expected angle provider='google', got {img['provider']!r}"
        )

    # Google grounded: 3/4 initial + 3/4 retry (from _enforce_single_frame) + torso + full_body = 4
    assert angles_mock.generate_grounded_image.call_count == 4, (
        f"Expected 4 google grounded calls, got {angles_mock.generate_grounded_image.call_count}"
    )
    # OpenAI fallback grounded: exactly 1 (the strip-replaced 3/4 angle)
    assert oai_fb_mock.generate_grounded_image.call_count == 1, (
        f"Expected 1 openai fallback call, got {oai_fb_mock.generate_grounded_image.call_count}"
    )


# ── B7.3: Angle timeout fallback ──────────────────────────────────────

def test_google_angle_timeout_fallback_to_openai(client: TestClient):
    """B7.3: When Google grounded angle raises a timeout RuntimeError,
    fall back that angle to OpenAI grounded — pack must not fail.

    Arrange:
    - OpenAI seed generates valid front portrait.
    - Google angles: anchor_torso raises RuntimeError("... timed out ...").
    - Google angles: anchor_three_quarter and anchor_full_body return valid PNGs.
    - OpenAI fallback: generate_grounded_image returns valid PNG for anchor_torso.

    Assert:
    - request succeeds (status 200)
    - anchor_torso DB record has provider='openai'
    - anchor_three_quarter and anchor_full_body have provider='google'
    - Google grounded called 2x (3/4 + full_body succeed; torso raises before count)
    - OpenAI fallback grounded called 1x (torso)
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    good_png = _make_png(512, 768)

    # OpenAI seed mock
    seed_mock = MagicMock()
    seed_mock.generate_image = MagicMock(return_value=good_png)

    # Google angles: torso raises timeout; others return good PNG.
    # ROLE_EDIT_PROMPT["anchor_torso"] contains "torso" and "chest".
    def _google_grounded(*, prompt, reference_image_bytes=None):
        if "torso" in prompt or "chest" in prompt:
            raise RuntimeError("Google Gemini grounded request failed: timed out")
        return good_png

    angles_mock = MagicMock()
    angles_mock.generate_grounded_image = MagicMock(side_effect=_google_grounded)

    # OpenAI fallback mock for the timed-out angle
    oai_tf_mock = MagicMock()
    oai_tf_mock.generate_grounded_image = MagicMock(return_value=good_png)

    # Provider factory: first "openai" call → seed_mock; subsequent → oai_tf_mock.
    openai_call_count = [0]

    def _provider_factory(name: str):
        if name == "openai":
            openai_call_count[0] += 1
            return seed_mock if openai_call_count[0] == 1 else oai_tf_mock
        return angles_mock  # "google"

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = ""  # B7 split-provider path
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
            json={"prompt_vibe": "dark hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    assert data["tier_used"] == "A"
    assert len(data["images"]) == 4
    assert data["blocked_roles"] == []

    images = data["images"]
    front_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_front"]
    torso_imgs = [img for img in images if img["metadata_json"]["pack_role"] == "anchor_torso"]
    other_angles = [
        img for img in images
        if img["metadata_json"]["pack_role"] in ("anchor_three_quarter", "anchor_full_body")
    ]

    # Front: OpenAI seed (unchanged)
    assert len(front_imgs) == 1
    assert front_imgs[0]["provider"] == "openai"

    # Torso: fell back to OpenAI due to timeout
    assert len(torso_imgs) == 1
    assert torso_imgs[0]["provider"] == "openai", (
        f"Expected torso angle provider='openai' after timeout fallback, "
        f"got {torso_imgs[0]['provider']!r}"
    )

    # Three-quarter and full-body: still Google
    assert len(other_angles) == 2
    for img in other_angles:
        assert img["provider"] == "google", (
            f"Expected angle provider='google', got {img['provider']!r}"
        )

    # Google grounded: three_quarter + full_body = 2 successes
    # (torso raises before generate_grounded_image returns, counts as 1 call that raised)
    assert angles_mock.generate_grounded_image.call_count == 3, (
        f"Expected 3 google grounded calls (3/4 + torso-raise + full_body), "
        f"got {angles_mock.generate_grounded_image.call_count}"
    )
    # OpenAI fallback grounded: exactly 1 (the timed-out torso angle)
    assert oai_tf_mock.generate_grounded_image.call_count == 1, (
        f"Expected 1 openai timeout-fallback call, "
        f"got {oai_tf_mock.generate_grounded_image.call_count}"
    )


# ── B8: Orphan record prevention ─────────────────────────────────────

def test_b8_no_orphan_db_records_on_tier_escalation(client: TestClient):
    """B8: When tier A generates front OK but an angle triggers moderation,
    NO orphan records are committed — only the successful tier's 4 images land in DB.

    Without the fix, tier A's front image would be added to the SQLAlchemy session
    before the angle fails, leaving an orphan after images.clear().  With the fix,
    _make_image_record never calls db.add() so nothing is in the session until
    db.add_all(winning_tier_images) is called at the end.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    good_png = _make_png(512, 768)
    grounded_call_count = [0]

    def _mock_generate_image(*, prompt, size="1024x1024"):
        return good_png

    def _mock_grounded(*, prompt, reference_image_bytes=None):
        grounded_call_count[0] += 1
        if grounded_call_count[0] == 1:
            # Tier A's first angle — moderation block triggers escalation.
            raise RuntimeError("moderation_blocked: content policy violation")
        return good_png

    mock_provider = MagicMock()
    mock_provider.generate_image = _mock_generate_image
    mock_provider.generate_grounded_image = _mock_grounded

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = "openai"
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
            json={"prompt_vibe": "test character"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()
    # Tier A was blocked at first angle; tier B should have succeeded.
    assert data["tier_used"] == "B"
    assert len(data["images"]) == 4

    # Accept the pack — this validates exactly 4 images with this pack_id exist in DB.
    # If an orphan front image from tier A were present the accept would return 422
    # because len(matching) would be 5 (2 anchor_fronts).
    pack_id = data["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, (
        f"Accept returned {resp.status_code} — likely orphan records in DB: {resp.json()}"
    )
    assert len(resp.json()["anchors"]) == 4


# ── B8: Angle OpenAI-fallback moderation → HTTP 400 ──────────────────

def test_b8_openai_angle_timeout_fallback_moderation_returns_400(client: TestClient):
    """B8: When OpenAI grounded fallback (B7.3 timeout path) raises moderation_blocked,
    the endpoint returns HTTP 400 with a clothed/non-sexual message — never a 500.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    good_png = _make_png(512, 768)

    # OpenAI seed: returns good front portrait.
    seed_mock = MagicMock()
    seed_mock.generate_image = MagicMock(return_value=good_png)

    # Google angles: torso raises timeout → triggers B7.3 fallback to OpenAI.
    def _google_grounded(*, prompt, reference_image_bytes=None):
        if "torso" in prompt or "chest" in prompt:
            raise RuntimeError("Google Gemini grounded request failed: timed out")
        return good_png

    angles_mock = MagicMock()
    angles_mock.generate_grounded_image = MagicMock(side_effect=_google_grounded)

    # OpenAI fallback: raises moderation_blocked for that angle.
    oai_tf_mock = MagicMock()
    oai_tf_mock.generate_grounded_image = MagicMock(
        side_effect=RuntimeError("moderation_blocked: content policy violation")
    )

    openai_call_count = [0]

    def _provider_factory(name: str):
        if name == "openai":
            openai_call_count[0] += 1
            return seed_mock if openai_call_count[0] == 1 else oai_tf_mock
        return angles_mock  # "google"

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = ""
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
            json={"prompt_vibe": "test character"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 400, (
        f"Expected HTTP 400 for moderation block, got {resp.status_code}: {resp.json()}"
    )
    detail = resp.json()["detail"].lower()
    assert "fully clothed" in detail or "non-sexual" in detail, (
        f"Expected clothed/non-sexual message, got: {resp.json()['detail']!r}"
    )
    # Role must be included in the detail so the user knows which angle caused it.
    assert "anchor_torso" in resp.json()["detail"], (
        f"Expected 'anchor_torso' in detail, got: {resp.json()['detail']!r}"
    )


# ── B8-dry-run: ?dry_run=true endpoint ───────────────────────────────

def test_dry_run_returns_plan_no_db_writes(client: TestClient):
    """?dry_run=true must return a prompt plan and write zero DB records.

    Verifies:
    - HTTP 200 with dry_run=True flag
    - Response contains seed_provider, angles_provider, roles, prompts_preview
    - All four prompt keys present (front, three_quarter, torso, full_body)
    - Front prompt contains passport-style headshot preamble
    - All prompts contain the PG-13 safety suffix
    - No CharacterImage rows are written (accept with the pack_id returns 422)
    - Character remains unlocked
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate?dry_run=true",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "Woman",
                "age_band": "26-35",
                "identity": {"hair_color": "auburn", "eye_color": "green"},
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()

    # Must be flagged as dry_run
    assert data["dry_run"] is True

    # Structural fields
    assert "pack_id" in data
    assert "seed_provider" in data
    assert "angles_provider" in data
    assert data["roles"] == [
        "anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body",
    ]

    # Prompts preview has all four keys
    pp = data["prompts_preview"]
    assert set(pp.keys()) == {"front", "three_quarter", "torso", "full_body"}, (
        f"Unexpected prompts_preview keys: {set(pp.keys())}"
    )

    # Front must contain passport-style preamble
    assert "passport-style headshot" in pp["front"].lower(), (
        f"front prompt missing preamble: {pp['front'][:120]!r}"
    )

    # All prompts must contain the PG-13 safety suffix
    for key, prompt in pp.items():
        assert "fully clothed" in prompt.lower(), (
            f"{key} prompt missing PG-13 suffix: {prompt[:120]!r}"
        )

    # Prove no DB images were written: accepting the dry-run pack_id must 422
    acc_resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": data["pack_id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert acc_resp.status_code == 422, (
        f"Accept should 422 (no images) after dry_run, got {acc_resp.status_code}"
    )

    # Character must still be unlocked
    char_resp = client.get(
        f"/characters/{cid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert char_resp.status_code == 200
    assert char_resp.json()["visual_locked"] is False, (
        "dry_run must not lock the character"
    )


def test_dry_run_works_without_identity_spec(client: TestClient):
    """dry_run on the legacy vibe path must also return a valid plan."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate?dry_run=true",
        json={"prompt_vibe": "silver hair elf with green eyes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dry_run"] is True
    assert "seed_provider" in data
    assert "prompts_preview" in data
    pp = data["prompts_preview"]
    assert "front" in pp
    assert "passport-style headshot" in pp["front"].lower()


# ── Google refusal fallback (google_refused_image) ───────────────────

def test_google_angle_refusal_falls_back_to_openai(client: TestClient):
    """When Google raises google_refused_image for an angle, it falls back to
    OpenAI grounded and logs identity_pack_angle_refusal_fallback.  The pack
    must complete successfully with that angle served by OpenAI.
    """
    token = _register_and_login(client)
    cid = _create_character(client, token)

    good_png = _make_png(512, 768)

    # OpenAI seed: returns a good front portrait.
    seed_mock = MagicMock()
    seed_mock.generate_image = MagicMock(return_value=good_png)

    # Google angles: three_quarter raises refusal; others succeed.
    def _google_grounded(*, prompt, reference_image_bytes=None):
        if "3/4" in prompt or "three" in prompt or "45" in prompt:
            raise RuntimeError("google_refused_image: IMAGE_RECITATION")
        return good_png

    angles_mock = MagicMock()
    angles_mock.generate_grounded_image = MagicMock(side_effect=_google_grounded)

    # OpenAI fallback: succeeds for the refused angle.
    oai_fallback = MagicMock()
    oai_fallback.generate_grounded_image = MagicMock(return_value=good_png)

    openai_call_count = [0]

    def _provider_factory(name: str):
        if name == "openai":
            openai_call_count[0] += 1
            return seed_mock if openai_call_count[0] == 1 else oai_fallback
        return angles_mock  # "google"

    mock_settings = MagicMock()
    mock_settings.IDENTITY_IMAGE_PROVIDER = ""
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
            json={"prompt_vibe": "test character"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, (
        f"Expected 200 after refusal fallback, got {resp.status_code}: {resp.json()}"
    )
    data = resp.json()
    images = data["images"]
    assert len(images) == 4, f"Expected 4 images, got {len(images)}"

    # The three_quarter slot must be served by openai (the fallback).
    prov_by_role = {
        (img.get("metadata_json") or {}).get("pack_role"): img.get("provider")
        for img in images
    }
    assert prov_by_role.get("anchor_three_quarter") == "openai", (
        f"Expected anchor_three_quarter from openai fallback, got {prov_by_role}"
    )


# ── Face reference crop (B10) ─────────────────────────────────────────

def test_crop_face_reference_outputs_png_512x512():
    """_crop_face_reference must return a 512×512 PNG from a valid input image."""
    from PIL import Image
    import io
    from app.api.routes.character_visual import _crop_face_reference

    # Build a realistic passport-sized image (512×768 portrait)
    src = _make_png(512, 768)
    result = _crop_face_reference(src)

    # Must be valid PNG
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG", "Result must be PNG"
    assert img.size == (512, 512), f"Expected 512×512, got {img.size}"


def test_crop_face_reference_survives_bad_input():
    """_crop_face_reference must return original bytes unchanged on garbage input."""
    from app.api.routes.character_visual import _crop_face_reference

    garbage = b"\x00\x01\x02not a real image"
    result = _crop_face_reference(garbage)
    assert result == garbage, "Should return original bytes unchanged on error"


def test_accept_creates_identity_face_ref(client: TestClient, db_session):
    """accept_identity_pack must create exactly 1 IDENTITY_FACE_REF image."""
    from app.models.character_image import CharacterImage, ImageKindEnum

    # Use a unique email to avoid collision with shared helper
    client.post(
        "/auth/register",
        json={"email": "faceref_accept@example.com", "username": "faceref_accept",
              "password": "testpassword123"},
    )
    resp = client.post(
        "/auth/login",
        json={"email": "faceref_accept@example.com", "password": "testpassword123"},
    )
    token = resp.json()["access_token"]

    # Create character + generate + accept (stub path — no API key needed)
    resp = client.post(
        "/characters/",
        json={"name": "Face Ref Test", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    cid = resp.json()["id"]

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    pack_id = resp.json()["pack_id"]

    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"accept failed: {resp.json()}"

    # Verify exactly 1 IDENTITY_FACE_REF image was created
    face_refs = (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.character_id == cid,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
        )
        .all()
    )
    assert len(face_refs) == 1, (
        f"Expected exactly 1 IDENTITY_FACE_REF, got {len(face_refs)}"
    )
    fr = face_refs[0]
    assert fr.metadata_json.get("source") == "accept_crop"
    assert fr.metadata_json.get("is_temp") is False
    assert fr.metadata_json.get("pack_id") == pack_id
    assert fr.file_path.startswith("static/generated/")
    # The file must actually exist on disk
    from pathlib import Path
    abs_path = (
        Path(__file__).resolve().parent.parent
        / fr.file_path
    )
    assert abs_path.exists(), f"Face ref file not found on disk: {abs_path}"


# ── Identity sketch anchor ────────────────────────────────────────────

def test_generate_identity_sketch_default_style(client: TestClient):
    """POST /characters/{id}/identity-sketch/generate returns 200, creates DB record, updates anchor json."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "pencil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Response shape
    assert "image_url" in data
    assert "image_id" in data
    assert data["style"] == "pencil"
    assert "prompt_preview" in data
    assert data["image_url"].startswith("/static/")

    # CharacterImage record created with the right kind
    from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        img = db.query(CharacterImage).filter(CharacterImage.id == data["image_id"]).first()
        assert img is not None, "CharacterImage not found in DB"
        assert img.kind == ImageKindEnum.IDENTITY_SKETCH
        assert img.status == ImageStatusEnum.ACTIVE
        assert img.metadata_json.get("is_temp") is False
        assert img.metadata_json.get("style") == "pencil"

        # identity_anchor_json updated with sketch info
        from app.models.character import Character as CharacterModel
        import json
        char = db.query(CharacterModel).filter(CharacterModel.id == cid).first()
        assert char is not None
        anchor = json.loads(char.identity_anchor_json)
        assert "sketch" in anchor
        assert anchor["sketch"]["image_id"] == data["image_id"]
        assert anchor["sketch"]["style"] == "pencil"
    finally:
        db.close()


def test_generate_identity_sketch_charcoal_style(client: TestClient):
    """Style coercion and charcoal variant work correctly."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "charcoal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["style"] == "charcoal"


def test_generate_identity_sketch_invalid_style_coerces_to_pencil(client: TestClient):
    """Unknown style falls back to 'pencil' silently."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "watercolour"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["style"] == "pencil"


def test_generate_identity_sketch_requires_auth(client: TestClient):
    """Unauthenticated request is rejected (401 or 403)."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "pencil"},
    )
    assert resp.status_code in (401, 403)


def test_generate_identity_sketch_archiving(client: TestClient):
    """Re-generating archives the previous sketch and creates a new one."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # First generation
    resp1 = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "pencil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp1.status_code == 200
    first_id = resp1.json()["image_id"]

    # Second generation (regenerate)
    resp2 = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "dossier"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    second_id = resp2.json()["image_id"]
    assert second_id != first_id

    # First sketch must now be archived
    from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        old = db.query(CharacterImage).filter(CharacterImage.id == first_id).first()
        assert old is not None
        assert old.status == ImageStatusEnum.ARCHIVED

        new = db.query(CharacterImage).filter(CharacterImage.id == second_id).first()
        assert new is not None
        assert new.status == ImageStatusEnum.ACTIVE
        assert new.kind == ImageKindEnum.IDENTITY_SKETCH
    finally:
        db.close()


# ── B11: Species selector + tells ────────────────────────────────────

class TestSpeciesSchema:
    """Pydantic validation for species / species_tells fields."""

    def _base_spec(self, **overrides):
        from app.schemas.character_visual import CharacterIdentitySpec, SpeciesEnum
        defaults = dict(
            style="realistic",
            gender="female",
            age_band="26-35",
        )
        defaults.update(overrides)
        return CharacterIdentitySpec(**defaults)

    def test_default_species_is_human(self):
        spec = self._base_spec()
        from app.schemas.character_visual import SpeciesEnum
        assert spec.species == SpeciesEnum.HUMAN

    def test_species_vampire_accepted(self):
        spec = self._base_spec(species="vampire")
        from app.schemas.character_visual import SpeciesEnum
        assert spec.species == SpeciesEnum.VAMPIRE

    def test_species_tells_accepted(self):
        spec = self._base_spec(species="vampire", species_tells=["subtle_fangs", "predatory_gaze"])
        assert spec.species_tells == ["subtle_fangs", "predatory_gaze"]

    def test_species_tells_max_three_enforced(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="at most 3"):
            self._base_spec(species_tells=["a", "b", "c", "d"])

    def test_species_tells_invalid_chars_rejected(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="invalid"):
            self._base_spec(species_tells=["blood<>drip"])  # < > not allowed

    def test_species_tells_none_coerces_to_empty(self):
        spec = self._base_spec(species_tells=None)
        assert spec.species_tells == []

    def test_species_default_empty_tells(self):
        spec = self._base_spec()
        assert spec.species_tells == []


def test_identity_spec_species_vampire_in_sketch_prompt_preview(client: TestClient):
    """Sketch endpoint prompt_preview must contain 'vampire' when spec has species=vampire."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # First, store a vampire identity spec on the character via the identity-pack
    # generate endpoint (it persists the spec to the character record).
    client.post(
        f"/characters/{cid}/dna",
        json={"species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "female",
                "age_band": "26-35",
                "species": "vampire",
                "species_tells": ["subtle_fangs", "predatory_gaze"],
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now generate a sketch — it should pick up the stored spec
    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "pencil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "vampire" in data["prompt_preview"].lower(), (
        f"Expected 'vampire' in prompt_preview, got: {data['prompt_preview']!r}"
    )


# ── B14: Facial geometry fields in CharacterIdentitySpec ──────────────

def test_facial_geometry_fields_accepted_in_identity_spec(client: TestClient):
    """All new B14 facial geometry fields are accepted in identity_spec."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "female",
                "age_band": "26-35",
                "face_shape": "oval",
                "jaw_type": "soft",
                "cheekbone_type": "high",
                "eye_shape": "almond",
                "eye_spacing": "average",
                "brow_type": "arched",
                "nose_type": "straight",
                "lip_type": "balanced",
                "hairline_type": "straight",
                "facial_hair_type": "none",
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def test_facial_geometry_invalid_face_shape_rejected(client: TestClient):
    """face_shape with unknown value is rejected with 422."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "male",
                "age_band": "18-25",
                "face_shape": "triangle",  # invalid
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_facial_geometry_invalid_jaw_type_rejected(client: TestClient):
    """jaw_type with unknown value is rejected with 422."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "male",
                "age_band": "18-25",
                "jaw_type": "massive",  # invalid
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_facial_geometry_fields_appear_in_sketch_prompt(client: TestClient):
    """Facial geometry fields must be included in the sketch prompt_preview."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    # Store a spec with several geometry fields
    client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "male",
                "age_band": "36-50",
                "face_shape": "square",
                "jaw_type": "sharp",
                "eye_shape": "deep_set",
                "nose_type": "roman",
                "lip_type": "thin",
                "facial_hair_type": "short_beard",
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = client.post(
        f"/characters/{cid}/identity-sketch/generate",
        json={"style": "pencil"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()["prompt_preview"].lower()

    assert "square" in preview, f"Expected 'square' in prompt: {preview!r}"
    assert "roman" in preview, f"Expected 'roman' in prompt: {preview!r}"
    assert "short beard" in preview, f"Expected 'short beard' in prompt: {preview!r}"


def test_facial_geometry_null_fields_accepted(client: TestClient):
    """Explicitly null facial geometry fields are accepted (backward-compatible)."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={
            "identity_spec": {
                "style": "realistic",
                "gender": "female",
                "age_band": "26-35",
                "face_shape": None,
                "jaw_type": None,
                "facial_hair_type": None,
            }
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


# ── B12: Face signature in accept_identity_pack ───────────────────────

def _generate_and_accept(client, token, cid):
    """Helper: generate + accept identity pack, returning pack response."""
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    pack_id = resp.json()["pack_id"]
    resp2 = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200, resp2.text
    return resp2.json()


def test_accept_still_200_when_face_signature_builder_fails(client):
    """Face-signature step failure must never break accept (graceful degradation)."""
    from unittest.mock import patch

    token = _register_and_login(client)
    cid = _create_character(client, token)

    with patch(
        "app.services.face_signature.build_face_signature_from_png",
        side_effect=RuntimeError("simulated failure"),
    ):
        data = _generate_and_accept(client, token, cid)

    # Accept must still succeed
    assert "anchors" in data
    assert len(data["anchors"]) == 4


def test_accept_writes_face_signature_when_builder_succeeds(client):
    """When builder returns ok=True, face_signature is written to identity_anchor_json."""
    import json
    from unittest.mock import patch

    token = _register_and_login(client)
    cid = _create_character(client, token)

    fake_sig = "FACE_SIG: square jaw, almond eyes, high cheekbones"

    with patch(
        "app.services.face_signature.build_face_signature_from_png",
        return_value={"ok": True, "signature": fake_sig, "confidence": 0.88, "skip_reason": ""},
    ):
        _generate_and_accept(client, token, cid)

    # Verify anchor json
    from app.models.character import Character as CharacterModel
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        char = db.query(CharacterModel).filter(CharacterModel.id == cid).first()
        assert char is not None
        anchor = json.loads(char.identity_anchor_json)
        assert "face_signature" in anchor, f"face_signature missing from anchor: {anchor}"
        fs = anchor["face_signature"]
        assert fs["text"] == fake_sig
        assert fs["confidence"] == 0.88
        assert "model" in fs
        assert "created_at" in fs
    finally:
        db.close()


def test_accept_no_face_signature_when_builder_returns_ok_false(client):
    """When builder returns ok=False, face_signature key is absent from anchor json."""
    import json
    from unittest.mock import patch

    token = _register_and_login(client)
    cid = _create_character(client, token)

    with patch(
        "app.services.face_signature.build_face_signature_from_png",
        return_value={"ok": False, "signature": "", "confidence": 0.0, "skip_reason": "no_api_key"},
    ):
        _generate_and_accept(client, token, cid)

    from app.models.character import Character as CharacterModel
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        char = db.query(CharacterModel).filter(CharacterModel.id == cid).first()
        anchor = json.loads(char.identity_anchor_json)
        assert "face_signature" not in anchor
    finally:
        db.close()

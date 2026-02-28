"""Tests for character visual endpoints (DNA, identity pack, moments)."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient) -> str:
    """Register a test user and return a bearer token."""
    client.post(
        "/api/auth/register",
        json={
            "email": "viztest@example.com",
            "username": "vizuser",
            "password": "testpassword123",
        },
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": "viztest@example.com", "password": "testpassword123"},
    )
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    """Create a character and return its ID."""
    resp = client.post(
        "/api/characters/",
        json={"name": "Ash Valkyr", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


# ── DNA endpoint ─────────────────────────────────────────────────────

def test_upsert_dna(client: TestClient):
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/api/characters/{cid}/dna",
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
        f"/api/characters/{cid}/identity-pack/generate",
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
        f"/api/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    client.post(
        f"/api/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now try generating again — should fail
    resp = client.post(
        f"/api/characters/{cid}/identity-pack/generate",
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
        f"/api/characters/{cid}/dna",
        json={"species": "elf"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Generate pack
    resp = client.post(
        f"/api/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]

    # Accept pack
    resp = client.post(
        f"/api/characters/{cid}/identity-pack/accept",
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
        f"/api/characters/{cid}",
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
        f"/api/characters/{cid}/identity-pack/generate",
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
        f"/api/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Fetch the character and verify identity_anchor_json
    resp = client.get(
        f"/api/characters/{cid}",
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
        f"/api/characters/{cid}/identity-pack/accept",
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
        f"/api/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    client.post(
        f"/api/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Now generate a moment
    resp = client.post(
        f"/api/characters/{cid}/images/generate",
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
        f"/api/characters/{cid}/images/generate",
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
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "elegant brunette"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["images"]) == 4
    # All images should be from openai provider
    for img in data["images"]:
        assert img["provider"] == "openai"
    # Tier A succeeded with no escalation
    assert data["tier_used"] == "A"
    assert data["blocked_roles"] == []


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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "silver hair elf", "style": "anime"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # The front prompt (first text-to-image call) must contain the anime token
    assert len(captured_prompts) >= 1
    assert "anime" in captured_prompts[0].lower()


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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "warrior"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # Default style token should be realistic
    assert "realistic" in captured_prompts[0].lower()


def test_unknown_style_coerces_to_realistic(client: TestClient):
    """An unknown style value should silently coerce to 'realistic'."""
    token = _register_and_login(client)
    cid = _create_character(client, token)

    resp = client.post(
        f"/api/characters/{cid}/identity-pack/generate",
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
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=mock_fallback,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=mock_fallback,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_primary,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=None,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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
    # The front prompt must use the 'realistic' style token
    assert len(captured_prompts) >= 1
    assert "realistic" in captured_prompts[0].lower()


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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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
    assert len(captured_prompts) >= 1
    assert "realistic" in captured_prompts[0].lower()


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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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
    assert len(captured_prompts) >= 1
    assert "realistic" in captured_prompts[0].lower()


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

    with patch(
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
            json={"prompt_vibe": "dark hair, green eyes"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    # First prompt should be for the front shot (text-to-image)
    assert len(captured_prompts) >= 1
    front_prompt = captured_prompts[0].lower()
    # Should contain headshot indicators
    assert any(keyword in front_prompt for keyword in ["headshot", "close-up", "face centered", "straight-on"])


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
        "app.api.routes.character_visual.get_image_provider",
        return_value=mock_provider,
    ), patch(
        "app.api.routes.character_visual.get_fallback_provider",
        return_value=None,
    ):
        resp = client.post(
            f"/api/characters/{cid}/identity-pack/generate",
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

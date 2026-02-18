"""Tests for scene image generation endpoint."""
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, email: str = "scenetest@example.com") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Scene Test Char", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
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
    assert resp.status_code == 200


# ── A) Locked character with anchor → 200 + correct metadata ────────

def test_scene_image_success_stub(client: TestClient):
    """Locked character with identity_anchor_json produces a scene image."""
    token = _register_and_login(client)
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/scene-images/generate",
        json={"prompt": "Standing in a moonlit forest clearing"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Image record created
    assert data["character_id"] == cid
    assert data["kind"] == "generated"
    assert data["url"].startswith("/static/")
    assert data["file_path"].startswith("static/generated/")

    # Metadata
    meta = data["metadata_json"]
    assert meta["library"] is True
    assert meta["scene"] is True
    assert meta["prompt"] == "Standing in a moonlit forest clearing"
    assert meta["style"] == "realistic"
    assert isinstance(meta["used_anchor"], bool)
    assert "identity_hash" in meta


# ── B) Not locked → 409 ─────────────────────────────────────────────

def test_scene_image_not_locked(client: TestClient):
    token = _register_and_login(client, email="scene_notlocked@example.com")
    cid = _create_character(client, token)

    resp = client.post(
        f"/characters/{cid}/scene-images/generate",
        json={"prompt": "A rainy street corner"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "Lock your character" in resp.json()["detail"]


# ── C) Missing anchor JSON → 409 ────────────────────────────────────

def test_scene_image_missing_anchor(client: TestClient, db_session):
    """Character is locked but identity_anchor_json is null → 409."""
    token = _register_and_login(client, email="scene_noanchor@example.com")
    cid = _create_character(client, token)

    # Manually lock without setting anchor JSON
    from app.models.character import Character as CharacterModel
    char = db_session.query(CharacterModel).filter(CharacterModel.id == cid).first()
    char.visual_locked = True
    char.identity_anchor_json = None
    db_session.commit()

    resp = client.post(
        f"/characters/{cid}/scene-images/generate",
        json={"prompt": "Walking through a garden"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "identity anchor" in resp.json()["detail"].lower()


# ── D) Edit unsupported → falls back to text-to-image ───────────────

def test_scene_image_edit_unsupported_falls_back(client: TestClient):
    """When provider edit raises NotImplementedError, falls back to text-to-image."""
    token = _register_and_login(client, email="scene_editfail@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    call_count = {"n": 0}

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        call_count["n"] += 1
        if reference_image_url is not None:
            # First call: edit attempt → fail
            raise NotImplementedError("edits not supported")
        # Second call: text-to-image → succeed
        # Return minimal valid PNG bytes
        import struct, zlib
        # 1x1 red PNG
        raw = b'\x00\xff\x00\x00'
        def _png():
            def chunk(ctype, data):
                c = ctype + data
                return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
            return (b'\x89PNG\r\n\x1a\n'
                    + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(raw))
                    + chunk(b'IEND', b''))
        return _png()

    mock_provider.generate_image = _mock_generate

    with patch("app.api.routes.scene_images.get_image_provider", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/scene-images/generate",
            json={"prompt": "Dramatic confrontation scene"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    # Should have called generate_image twice: once with ref (failed), once without
    assert call_count["n"] == 2
    # used_anchor should be false since edit failed
    assert data["metadata_json"]["used_anchor"] is False


# ── E) Style coercion ────────────────────────────────────────────────

def test_scene_image_style_coercion(client: TestClient):
    """Unknown style coerces to realistic."""
    token = _register_and_login(client, email="scene_style@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/scene-images/generate",
        json={"prompt": "A battle scene", "style": "UNKNOWN_STYLE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["metadata_json"]["style"] == "realistic"

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
    """When all reference-based generation raises NotImplementedError, falls back to text-to-image."""
    token = _register_and_login(client, email="scene_editfail@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    mock_provider = MagicMock()
    call_count = {"n": 0}

    # Face-ref grounded path also unsupported
    mock_provider.generate_grounded_image = MagicMock(
        side_effect=NotImplementedError("grounded not supported")
    )

    def _mock_generate(*, prompt, size="1024x1024", reference_image_url=None):
        call_count["n"] += 1
        if reference_image_url is not None:
            raise NotImplementedError("edits not supported")
        # Text-to-image → succeed
        import struct, zlib
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
    # generate_image called twice: once with ref_url (failed), once without
    assert call_count["n"] == 2
    # used_anchor should be false since all reference paths failed
    assert data["metadata_json"]["used_anchor"] is False
    assert data["metadata_json"]["used_face_ref"] is False


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


# ── F) Face reference grounded generation (B10) ──────────────────────

def _make_png_bytes(width: int = 512, height: int = 768) -> bytes:
    """Create a minimal valid PNG of the given size."""
    from PIL import Image
    import io
    img = Image.new("RGB", (width, height), color=(120, 80, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_scene_image_uses_face_ref_grounded(client: TestClient):
    """When IDENTITY_FACE_REF exists, scene generation uses generate_grounded_image
    with the face-ref bytes as the primary reference tier.
    """
    token = _register_and_login(client, email="scene_faceref@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)  # creates face_ref via accept

    good_png = _make_png_bytes()

    captured = {"prompt": None, "ref_bytes": None}

    def _mock_grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured["prompt"] = prompt
        captured["ref_bytes"] = reference_image_bytes
        return good_png

    mock_provider = MagicMock()
    mock_provider.generate_grounded_image = MagicMock(side_effect=_mock_grounded)

    with patch("app.api.routes.scene_images.get_image_provider", return_value=mock_provider):
        resp = client.post(
            f"/characters/{cid}/scene-images/generate",
            json={"prompt": "Standing in a burning library"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
    data = resp.json()

    assert data["metadata_json"]["used_anchor"] is True, "used_anchor should be True"
    assert data["metadata_json"]["used_face_ref"] is True, "used_face_ref should be True"

    # The grounded call must have been made with face-ref bytes (non-empty)
    assert captured["ref_bytes"] is not None, "generate_grounded_image was not called"
    assert len(captured["ref_bytes"]) > 0, "Reference bytes should not be empty"

    # Prompt must contain the face-ref instruction
    assert captured["prompt"] is not None
    assert "facial identity" in captured["prompt"].lower(), (
        f"Expected face-ref instruction in prompt, got: {captured['prompt']!r}"
    )
    assert "do not copy clothing" in captured["prompt"].lower(), (
        f"Expected clothing instruction in prompt, got: {captured['prompt']!r}"
    )


def test_scene_image_face_ref_metadata(client: TestClient):
    """Scene image metadata must always include used_face_ref key."""
    token = _register_and_login(client, email="scene_faceref_meta@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    # Stub mode — no real provider, face_ref bytes exist but grounded call isn't mocked.
    # The stub path sets used_face_ref=False (no provider), metadata key must still exist.
    resp = client.post(
        f"/characters/{cid}/scene-images/generate",
        json={"prompt": "Simple scene"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    meta = resp.json()["metadata_json"]
    assert "used_face_ref" in meta, "used_face_ref key must always be in metadata"


# ── B12: Face signature injected into Tier A prompt ──────────────────

def test_scene_prompt_includes_face_signature_when_present(client: TestClient):
    """Tier A grounded generation prompt must include face_signature text when stored."""
    import json
    from unittest.mock import patch, MagicMock

    token = _register_and_login(client, email="facesg@example.com")
    cid = _create_character(client, token)
    _lock_character(client, token, cid)

    # Manually inject a face_signature into the character's anchor json
    from app.models.character import Character as CharacterModel
    from tests.conftest import TestingSessionLocal
    db = TestingSessionLocal()
    try:
        char = db.query(CharacterModel).filter(CharacterModel.id == cid).first()
        anchor = json.loads(char.identity_anchor_json)
        anchor["face_signature"] = {
            "text": "FACE_SIG: square jaw, almond eyes",
            "confidence": 0.9,
            "model": "gpt-4o-mini",
            "created_at": "2026-03-05T00:00:00Z",
        }
        char.identity_anchor_json = json.dumps(anchor)
        db.commit()
    finally:
        db.close()

    # Capture the prompt passed to the grounded image provider
    captured_prompts: list[str] = []

    class _CapturingProvider:
        def generate_grounded_image(self, *, prompt, reference_image_bytes):
            captured_prompts.append(prompt)
            # Return a minimal valid PNG placeholder
            from app.services.stub_image_generator import generate_placeholder_png
            from pathlib import Path
            fp = generate_placeholder_png(label="scene", sublabel="test")
            abs_path = Path(__file__).resolve().parent.parent / fp
            return abs_path.read_bytes()

        def generate_image(self, *, prompt, **kwargs):
            raise NotImplementedError("force Tier A")

    with patch("app.api.routes.scene_images.get_image_provider", return_value=_CapturingProvider()):
        resp = client.post(
            f"/characters/{cid}/scene-images/generate",
            json={"prompt": "Standing in a moonlit clearing"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text

    # Face signature must appear at the start of the Tier A prompt
    assert len(captured_prompts) > 0, "No grounded generation call was made"
    tier_a_prompt = captured_prompts[0]
    assert "FACE_SIG" in tier_a_prompt, (
        f"Face signature not found in Tier A prompt: {tier_a_prompt!r}"
    )
    assert "square jaw" in tier_a_prompt

"""Regression tests for two tattoo-visibility bugs.

Bug 1: generate_image called load_markings without first syncing body_canon_json
       from active tattoo style elements, so stale/null body_canon_json produced
       zero tattoo text in the prompt.

Bug 2: accept_identity_pack overwrote identity_anchor_json without preserving
       existing body_slots, wiping locked tattoo_layout / body_front refs.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers


# ── Shared helpers ────────────────────────────────────────────────────

def _register_and_login(client: TestClient, email: str) -> str:
    username = email.split("@")[0].replace(".", "_").replace("+", "_")
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str, name: str = "TRChar") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _generate_pack(client: TestClient, token: str, cid: int) -> str:
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["pack_id"]


def _accept_pack(client: TestClient, token: str, cid: int, pack_id: str) -> None:
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    pack_id = _generate_pack(client, token, cid)
    _accept_pack(client, token, cid, pack_id)


# Minimal valid 1×1 PNG — used instead of calling the stub generator so tests
# don't depend on local file I/O when R2 object storage is active.
_STUB_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _mock_provider() -> MagicMock:
    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = MagicMock(return_value=_STUB_PNG)
    mock.generate_image = MagicMock(return_value=_STUB_PNG)
    return mock


@pytest.fixture(autouse=False)
def seeded_presets(db_session):
    """Seed style shop presets for this test."""
    from app.core.style_shop_seed import seed_style_presets
    seed_style_presets(db_session)


# ══════════════════════════════════════════════════════════════════════════════
# Canon contract — tattoos are CharacterIdentityCanon permanent marks, and
# CharacterStyleElements are shop data only (never identity truth in generation).
# ══════════════════════════════════════════════════════════════════════════════

from tests.canon_test_utils import setup_canon  # noqa: E402


def _capture_provider(captured: dict) -> MagicMock:
    def _with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _STUB_PNG

    def _grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured.setdefault("prompt", prompt)
        return _STUB_PNG

    def _text(*, prompt, size="1024x1024", reference_image_url=None):
        captured.setdefault("prompt", prompt)
        return _STUB_PNG

    mock = MagicMock()
    mock.supports_multi_image_input = True
    mock.generate_with_anchors = _with_anchors
    mock.generate_grounded_image = _grounded
    mock.generate_image = _text
    return mock


class TestCanonDrivesMarkings:
    """Generation reads permanent marks from CharacterIdentityCanon only."""

    _WOLF = {
        "label": "Right Arm Tribal Wolf Mark",
        "type": "tattoo",
        "body_region": "right_full_arm",
        "side": "right",
        "description": "tribal wolf tattoo sleeve",
    }

    def test_canon_marks_drive_prompt(self, client: TestClient, db_session):
        """A canon permanent mark appears in the compiled prompt."""
        token = _register_and_login(client, "tr_canon1@test.com")
        cid = _create_character(client, token, "CanonMarkChar")
        setup_canon(db_session, cid, marks=[self._WOLF], with_images=False)

        captured: dict = {}
        with patch(
            "app.services.image_generation_pipeline.get_provider_for_option",
            return_value=_capture_provider(captured),
        ):
            resp = client.post(
                f"/characters/{cid}/image-generator/generate",
                json={
                    "prompt": "standing in a sleeveless shirt",
                    "include_character": True,
                    "provider_option": "option1",
                },
                headers=auth_headers(token),
            )
        assert resp.status_code == 200, resp.text
        prompt = captured.get("prompt", "")
        # P13/P13b (A+C): mark surfaces via the compact skin-bound clause (region +
        # design), not the legacy "PERMANENT BODY MARKS" header.
        assert "PERMANENT BODY MARKS" not in prompt
        assert "skin-bound anatomy" in prompt.lower()
        assert "right arm" in prompt.lower()
        assert "tribal wolf tattoo sleeve" in prompt

    def test_style_element_is_not_identity_truth(
        self, client: TestClient, db_session, seeded_presets
    ):
        """An active tattoo style element (shop data) must NOT leak into the
        compiled prompt — identity truth comes only from canon marks."""
        token = _register_and_login(client, "tr_canon2@test.com")
        cid = _create_character(client, token, "StyleNotTruth")

        presets = client.get("/style-shops/presets?shop_type=tattoo").json()
        assert presets, "Need at least one tattoo preset"
        client.post(
            f"/characters/{cid}/style-elements",
            json={"preset_id": presets[0]["id"]},
            headers=auth_headers(token),
        )
        token_text = presets[0]["prompt_token"].split(",")[0].strip().lower()

        # Canon has NO permanent marks — the style element must not appear.
        setup_canon(db_session, cid, with_images=False)

        captured: dict = {}
        with patch(
            "app.services.image_generation_pipeline.get_provider_for_option",
            return_value=_capture_provider(captured),
        ):
            resp = client.post(
                f"/characters/{cid}/image-generator/generate",
                json={
                    "prompt": "sleeveless shirt arms visible",
                    "include_character": True,
                    "provider_option": "option1",
                },
                headers=auth_headers(token),
            )
        assert resp.status_code == 200, resp.text
        prompt = captured.get("prompt", "").lower()
        assert token_text not in prompt
        assert "PERMANENT BODY MARKS" not in captured.get("prompt", "")

    def test_generation_requires_canon(self, client: TestClient):
        """include_character=True without canon returns a graceful 409."""
        token = _register_and_login(client, "tr_canon3@test.com")
        cid = _create_character(client, token, "NoCanonChar")

        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": "sleeveless shirt",
                "include_character": True,
                "provider_option": "option1",
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Character canon incomplete"


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2 — accept preserves body_slots
# ══════════════════════════════════════════════════════════════════════════════

class TestAcceptPreservesBodySlots:
    """accept_identity_pack must not wipe existing body_slots from identity_anchor_json."""

    def _inject_body_slots(self, db_session, cid: int, slots: dict) -> None:
        from app.models.character import Character
        char = db_session.query(Character).filter(Character.id == cid).first()
        data: dict = {}
        if char.identity_anchor_json:
            try:
                data = json.loads(char.identity_anchor_json)
            except (ValueError, TypeError):
                pass
        data["body_slots"] = slots
        char.identity_anchor_json = json.dumps(data)
        db_session.commit()

    def test_tattoo_layout_preserved_after_accept(self, client: TestClient, db_session):
        """A locked tattoo_layout slot must survive pack acceptance."""
        from app.models.character import Character

        token = _register_and_login(client, "tr_accept_tl@test.com")
        cid = _create_character(client, token, "AcceptTLChar")

        # Generate a pack — character not yet locked
        pack_id = _generate_pack(client, token, cid)

        # Inject locked tattoo_layout BEFORE accepting
        self._inject_body_slots(db_session, cid, {
            "tattoo_layout": {"url": "http://cdn.test/tl.png", "status": "locked"},
        })

        # Accept the pack
        _accept_pack(client, token, cid, pack_id)

        # tattoo_layout must still be present
        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        anchor = json.loads(char.identity_anchor_json or "{}")
        tl = anchor.get("body_slots", {}).get("tattoo_layout", {})
        assert tl.get("status") == "locked", (
            f"tattoo_layout must remain locked after accept; got body_slots={anchor.get('body_slots')!r}"
        )
        assert tl.get("url") == "http://cdn.test/tl.png"

    def test_body_front_preserved_after_accept(self, client: TestClient, db_session):
        """A locked body_front slot must survive pack acceptance."""
        from app.models.character import Character

        token = _register_and_login(client, "tr_accept_bf@test.com")
        cid = _create_character(client, token, "AcceptBFChar")

        pack_id = _generate_pack(client, token, cid)

        self._inject_body_slots(db_session, cid, {
            "body_front": {"url": "http://cdn.test/bf.png", "status": "locked"},
        })

        _accept_pack(client, token, cid, pack_id)

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        anchor = json.loads(char.identity_anchor_json or "{}")
        bf = anchor.get("body_slots", {}).get("body_front", {})
        assert bf.get("status") == "locked", (
            f"body_front must remain locked after accept; got body_slots={anchor.get('body_slots')!r}"
        )
        assert bf.get("url") == "http://cdn.test/bf.png"

    def test_both_slots_preserved_after_accept(self, client: TestClient, db_session):
        """Both tattoo_layout and body_front survive a single accept call."""
        from app.models.character import Character

        token = _register_and_login(client, "tr_accept_both@test.com")
        cid = _create_character(client, token, "AcceptBothChar")

        pack_id = _generate_pack(client, token, cid)

        self._inject_body_slots(db_session, cid, {
            "tattoo_layout": {"url": "http://cdn.test/tl2.png", "status": "locked"},
            "body_front":    {"url": "http://cdn.test/bf2.png", "status": "locked"},
        })

        _accept_pack(client, token, cid, pack_id)

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        anchor = json.loads(char.identity_anchor_json or "{}")
        slots = anchor.get("body_slots", {})
        assert slots.get("tattoo_layout", {}).get("status") == "locked"
        assert slots.get("body_front", {}).get("status") == "locked"

    def test_pack_stages_marks_locked_when_tattoo_layout_preserved(
        self, client: TestClient, db_session
    ):
        """After accept, pack_stages.marks must be 'locked' when tattoo_layout slot
        is preserved AND body_canon_json has markings."""
        from app.models.character import Character
        from app.services.identity_evolution import compute_pack_stages

        token = _register_and_login(client, "tr_stages_marks@test.com")
        cid = _create_character(client, token, "StagesMarksChar")

        pack_id = _generate_pack(client, token, cid)

        # Set body marking + locked tattoo_layout
        char = db_session.query(Character).filter(Character.id == cid).first()
        char.body_canon_json = json.dumps({"markings": [
            {
                "id": "bm_test1", "type": "tattoo",
                "placement": "left_full_arm", "style": "serpent sleeve",
                "size": "full_sleeve", "description": "desc",
                "coverage": "sleeve", "anchor_image_url": None,
                "anchor_status": "missing", "anchor_prompt": None,
            }
        ]})
        db_session.commit()

        self._inject_body_slots(db_session, cid, {
            "tattoo_layout": {"url": "http://cdn.test/tl3.png", "status": "locked"},
        })

        _accept_pack(client, token, cid, pack_id)

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        stages = compute_pack_stages(char)
        assert stages["marks"] == "locked", (
            f"pack_stages.marks must be 'locked' when tattoo_layout preserved; got {stages!r}"
        )

    def test_pack_stages_body_locked_when_body_front_preserved(
        self, client: TestClient, db_session
    ):
        """After accept, pack_stages.body must be 'locked' when body_front is preserved."""
        from app.models.character import Character
        from app.services.identity_evolution import compute_pack_stages

        token = _register_and_login(client, "tr_stages_body@test.com")
        cid = _create_character(client, token, "StagesBodyChar")

        pack_id = _generate_pack(client, token, cid)

        self._inject_body_slots(db_session, cid, {
            "body_front": {"url": "http://cdn.test/bf3.png", "status": "locked"},
        })

        _accept_pack(client, token, cid, pack_id)

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        stages = compute_pack_stages(char)
        assert stages["body"] == "locked", (
            f"pack_stages.body must be 'locked' when body_front preserved; got {stages!r}"
        )

    def test_accept_does_not_affect_body_canon_json(self, client: TestClient, db_session):
        """accept_identity_pack must never touch body_canon_json."""
        from app.models.character import Character

        token = _register_and_login(client, "tr_accept_bc@test.com")
        cid = _create_character(client, token, "AcceptBCChar")

        # Put a known marking in body_canon_json
        char = db_session.query(Character).filter(Character.id == cid).first()
        char.body_canon_json = json.dumps({"markings": [
            {
                "id": "bm_sentinel", "type": "tattoo",
                "placement": "neck", "style": "vine",
                "size": "medium", "description": "sentinel",
                "coverage": None, "anchor_image_url": None,
                "anchor_status": "missing", "anchor_prompt": None,
            }
        ]})
        db_session.commit()

        pack_id = _generate_pack(client, token, cid)
        _accept_pack(client, token, cid, pack_id)

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == cid).first()
        bc = json.loads(char.body_canon_json or "{}")
        markings = bc.get("markings", [])
        assert len(markings) == 1
        assert markings[0]["id"] == "bm_sentinel", (
            "accept must not modify body_canon_json"
        )

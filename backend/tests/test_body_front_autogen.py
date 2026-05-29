"""Tests for Task #17 — auto-generate body_front when the identity pack is locked.

When a user accepts their identity pack, a body_front reference image is generated
automatically (for characters with body markings) so that canonical scene-generation
mode can enforce tattoo/anatomy placement from a real visual reference.

These tests cover the generate_body_front helper (prompt construction + provider
dispatch) and the accept-endpoint gating condition, without touching the database.
"""
import json
from types import SimpleNamespace

import app.api.routes.character_visual as cv


# ── Fakes ────────────────────────────────────────────────────────────────────


class _MultiImageProvider:
    """Provider that supports anchor grounding."""

    provider_name = "fake_multi"
    supports_multi_image_input = True

    def __init__(self):
        self.with_anchors_calls = []
        self.plain_calls = []

    def generate_with_anchors(self, prompt, anchor_images):
        self.with_anchors_calls.append((prompt, anchor_images))
        return b"ANCHORED_PNG_BYTES"

    def generate_image(self, prompt):
        self.plain_calls.append(prompt)
        return b"PLAIN_PNG_BYTES"


class _PlainProvider:
    """Provider with no multi-image support."""

    provider_name = "fake_plain"
    supports_multi_image_input = False

    def __init__(self):
        self.plain_calls = []

    def generate_image(self, prompt):
        self.plain_calls.append(prompt)
        return b"PLAIN_PNG_BYTES"


def _character(*, with_markings=True, with_anchors=True):
    markings = []
    if with_markings:
        markings = [{
            "type": "tattoo",
            "placement": "right_full_arm",
            "style": "tribal wolf",
            "size": "large",
            "description": "large tribal wolf tattoo on the right arm",
        }]
    anchors = {}
    if with_anchors:
        anchors = {
            "front": {"id": 1, "url": "/media/front.png"},
            "three_quarter": {"id": 2, "url": "/media/tq.png"},
        }
    anchor_json = {
        "identity_lock_string": "IDENTITY: tall lean human male",
        "anchors": anchors,
    }
    return SimpleNamespace(
        id=42,
        name="Leonardo",
        identity_anchor_json=json.dumps(anchor_json),
        body_canon_json=json.dumps({"markings": markings}),
    )


# ── generate_body_front: prompt + provider dispatch ──────────────────────────


class TestGenerateBodyFront:
    def test_uses_anchors_when_provider_supports_multi_image(self, monkeypatch):
        provider = _MultiImageProvider()
        monkeypatch.setattr(cv, "get_provider_for_option", lambda opt: provider)
        monkeypatch.setattr(cv, "load_image_bytes", lambda url: b"REF_" + url.encode())

        out = cv.generate_body_front(_character())

        assert out == b"ANCHORED_PNG_BYTES"
        assert len(provider.with_anchors_calls) == 1
        prompt, anchor_images = provider.with_anchors_calls[0]
        # Both locked anchors are passed as grounding references.
        assert len(anchor_images) == 2

    def test_prompt_is_sleeveless_front_with_markings(self, monkeypatch):
        provider = _MultiImageProvider()
        monkeypatch.setattr(cv, "get_provider_for_option", lambda opt: provider)
        monkeypatch.setattr(cv, "load_image_bytes", lambda url: b"REF")

        cv.generate_body_front(_character())

        prompt = provider.with_anchors_calls[0][0].lower()
        assert "front" in prompt
        assert "sleeveless" in prompt
        # Body markings flow into the prompt so the reference shows the tattoo.
        assert "tribal wolf" in prompt
        # Character name and identity lock string are present.
        assert "leonardo" in prompt

    def test_falls_back_to_generate_image_without_multi_support(self, monkeypatch):
        provider = _PlainProvider()
        monkeypatch.setattr(cv, "get_provider_for_option", lambda opt: provider)
        monkeypatch.setattr(cv, "load_image_bytes", lambda url: b"REF")

        out = cv.generate_body_front(_character())

        assert out == b"PLAIN_PNG_BYTES"
        assert len(provider.plain_calls) == 1

    def test_no_anchors_uses_plain_generation(self, monkeypatch):
        provider = _MultiImageProvider()
        monkeypatch.setattr(cv, "get_provider_for_option", lambda opt: provider)
        monkeypatch.setattr(cv, "load_image_bytes", lambda url: b"REF")

        out = cv.generate_body_front(_character(with_anchors=False))

        # No anchor refs → no grounding call, plain generation used instead.
        assert out == b"PLAIN_PNG_BYTES"
        assert provider.with_anchors_calls == []
        assert len(provider.plain_calls) == 1

    def test_works_without_markings(self, monkeypatch):
        # The helper itself is marking-agnostic; gating happens at the call site.
        provider = _MultiImageProvider()
        monkeypatch.setattr(cv, "get_provider_for_option", lambda opt: provider)
        monkeypatch.setattr(cv, "load_image_bytes", lambda url: b"REF")

        out = cv.generate_body_front(_character(with_markings=False))
        assert out == b"ANCHORED_PNG_BYTES"


# ── Accept-endpoint gating mirror ────────────────────────────────────────────


def _should_autogen(*, has_markings: bool, existing_body_front_url: str | None) -> bool:
    """Mirror of character_visual.py accept_identity_pack gating:

        _autogen_markings and not _existing_bf.get("url")
    """
    existing_bf = {"url": existing_body_front_url} if existing_body_front_url else {}
    return bool(has_markings) and not existing_bf.get("url")


class TestAutogenGating:
    def test_autogen_when_markings_and_no_existing_body_front(self):
        assert _should_autogen(has_markings=True, existing_body_front_url=None)

    def test_skip_when_no_markings(self):
        assert not _should_autogen(has_markings=False, existing_body_front_url=None)

    def test_skip_when_body_front_already_exists(self):
        # Manually uploaded / pre-existing body_front must never be regenerated.
        assert not _should_autogen(
            has_markings=True, existing_body_front_url="/media/manual_bf.png"
        )


# ── Endpoint integration: accept_identity_pack auto-generation ────────────────

import logging  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

from tests.conftest import auth_headers  # noqa: E402

_INT_SPEC = {
    "gender": "male",
    "age_band": "26-35",
    "style": "realistic",
    "identity": {
        "hair_color": "black",
        "hair_length": "short",
        "eye_color": "brown",
        "skin_tone": "tan",
    },
}

_MARKINGS_JSON = json.dumps({
    "markings": [{
        "type": "tattoo",
        "placement": "right_full_arm",
        "style": "tribal wolf",
        "size": "large",
        "description": "large tribal wolf tattoo on the right arm",
    }]
})


def _int_user(client, email, username):
    client.post("/auth/register",
                json={"email": email, "username": username, "password": "testpass!123"})
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return auth_headers(resp.json()["access_token"])


def _int_character(client, headers, name="AutogenChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"},
                       headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _int_generate(client, headers, char_id, spec=_INT_SPEC):
    with patch("app.api.routes.character_visual.generate_placeholder_png",
               return_value="static/generated/stub_test.png"):
        resp = client.post(f"/characters/{char_id}/identity-pack/generate",
                           json={"identity_spec": spec}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["pack_id"]


def _set_char_field(db_session, char_id, **fields):
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    for k, v in fields.items():
        setattr(char, k, v)
    db_session.commit()


def _reload_char(db_session, char_id):
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)
    return char


def test_accept_autogenerates_locked_body_front_when_markings(client, db_session):
    headers = _int_user(client, "autogen_ok@test.com", "autogenok")
    char_id = _int_character(client, headers)
    _set_char_field(db_session, char_id, body_canon_json=_MARKINGS_JSON)
    pack_id = _int_generate(client, headers, char_id)

    with patch("app.api.routes.character_visual.generate_body_front",
               return_value=b"BODY_FRONT_PNG_BYTES") as gen_mock, \
         patch("app.api.routes.character_visual.save_image",
               return_value="static/generated/auto_bf.png"):
        resp = client.post(f"/characters/{char_id}/identity-pack/accept",
                           json={"pack_id": pack_id}, headers=headers)

    assert resp.status_code == 200, resp.text
    gen_mock.assert_called_once()

    char = _reload_char(db_session, char_id)
    assert char.visual_locked is True
    anchor = json.loads(char.identity_anchor_json or "{}")
    bf = (anchor.get("body_slots") or {}).get("body_front") or {}
    assert bf.get("status") == "locked"
    assert bf.get("source") == "auto_generated"
    assert bf.get("url") == "static/generated/auto_bf.png"

    from app.models.character_image import (
        CharacterImage, ImageKindEnum, ImageStatusEnum,
    )
    ci = (db_session.query(CharacterImage)
          .filter(CharacterImage.character_id == char_id,
                  CharacterImage.kind == ImageKindEnum.IDENTITY_BODY_FRONT,
                  CharacterImage.status == ImageStatusEnum.ACTIVE)
          .first())
    assert ci is not None
    assert ci.file_path == "static/generated/auto_bf.png"


def test_accept_failure_does_not_block_lock(client, db_session, caplog):
    headers = _int_user(client, "autogen_fail@test.com", "autogenfail")
    char_id = _int_character(client, headers)
    _set_char_field(db_session, char_id, body_canon_json=_MARKINGS_JSON)
    pack_id = _int_generate(client, headers, char_id)

    with caplog.at_level(logging.WARNING, logger="app.api.routes.character_visual"), \
         patch("app.api.routes.character_visual.generate_body_front",
               side_effect=RuntimeError("provider down")):
        resp = client.post(f"/characters/{char_id}/identity-pack/accept",
                           json={"pack_id": pack_id}, headers=headers)

    # Lock still completes despite the autogen failure.
    assert resp.status_code == 200, resp.text
    char = _reload_char(db_session, char_id)
    assert char.visual_locked is True
    anchor = json.loads(char.identity_anchor_json or "{}")
    bf = (anchor.get("body_slots") or {}).get("body_front") or {}
    assert bf.get("status") != "locked"  # no body_front was stored
    assert any("BODY_FRONT_AUTOGEN_FAILED" in r.message for r in caplog.records)


def test_accept_skips_autogen_when_no_markings(client, db_session):
    headers = _int_user(client, "autogen_nomark@test.com", "autogennomark")
    char_id = _int_character(client, headers)  # no body_canon_json
    pack_id = _int_generate(client, headers, char_id)

    gen_mock = MagicMock(return_value=b"SHOULD_NOT_BE_CALLED")
    with patch("app.api.routes.character_visual.generate_body_front", gen_mock):
        resp = client.post(f"/characters/{char_id}/identity-pack/accept",
                           json={"pack_id": pack_id}, headers=headers)

    assert resp.status_code == 200, resp.text
    gen_mock.assert_not_called()
    char = _reload_char(db_session, char_id)
    anchor = json.loads(char.identity_anchor_json or "{}")
    assert "body_front" not in (anchor.get("body_slots") or {})


def test_accept_skips_autogen_when_body_front_exists(client, db_session):
    headers = _int_user(client, "autogen_exists@test.com", "autogenexists")
    char_id = _int_character(client, headers)
    _set_char_field(
        db_session, char_id,
        body_canon_json=_MARKINGS_JSON,
        identity_anchor_json=json.dumps({
            "body_slots": {
                "body_front": {"url": "/media/manual_bf.png", "status": "locked"}
            }
        }),
    )
    pack_id = _int_generate(client, headers, char_id)

    gen_mock = MagicMock(return_value=b"SHOULD_NOT_BE_CALLED")
    with patch("app.api.routes.character_visual.generate_body_front", gen_mock):
        resp = client.post(f"/characters/{char_id}/identity-pack/accept",
                           json={"pack_id": pack_id}, headers=headers)

    assert resp.status_code == 200, resp.text
    gen_mock.assert_not_called()
    char = _reload_char(db_session, char_id)
    anchor = json.loads(char.identity_anchor_json or "{}")
    bf = (anchor.get("body_slots") or {}).get("body_front") or {}
    # Pre-existing manual body_front is preserved untouched.
    assert bf.get("url") == "/media/manual_bf.png"

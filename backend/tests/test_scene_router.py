"""P10 — Scene-Aware Reference Router: deterministic routing tests.

Verifies that route_canon_refs() maps scene prompts to the correct canon
reference slots using rule-based keyword matching only (no LLM parsing).

Slot URL legend (full canon fixture):
  face_front  face_left_3q  face_right_3q  face_expression
  body_front  body_left     body_right     body_back
  body_map    final_card
"""
import json

import pytest
from unittest.mock import MagicMock

from app.services.scene_router import route_canon_refs, SceneMeta


# ── URLs by slot (must match _make_full_canon below) ──────────────────
FACE_FRONT = "https://cdn.test/face_front.png"
FACE_LEFT_3Q = "https://cdn.test/face_left_3q.png"
FACE_RIGHT_3Q = "https://cdn.test/face_right_3q.png"
FACE_EXPRESSION = "https://cdn.test/face_expression.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_LEFT = "https://cdn.test/body_left.png"
BODY_RIGHT = "https://cdn.test/body_right.png"
BODY_BACK = "https://cdn.test/body_back.png"
BODY_MAP = "https://cdn.test/body_map.png"
FINAL_CARD = "https://cdn.test/final_card.png"


def _make_full_canon():
    """Return a mock canon with all 10 image slots populated."""
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import FaceCanonData, BodyCanonData

    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 99

    face = FaceCanonData(
        face_front_image_url=FACE_FRONT,
        face_left_3q_image_url=FACE_LEFT_3Q,
        face_right_3q_image_url=FACE_RIGHT_3Q,
        face_expression_image_url=FACE_EXPRESSION,
    )
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_left_image_url=BODY_LEFT,
        body_right_image_url=BODY_RIGHT,
        body_back_image_url=BODY_BACK,
        body_map_image_url=BODY_MAP,
        final_character_card_image_url=FINAL_CARD,
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


# ── Spec acceptance cases ─────────────────────────────────────────────

class TestSpecRouting:
    """The five canonical routing examples from the P10 spec."""

    def test_face_on_sleeveless_routes_front_only(self):
        """'face on sleeveless shirt' → front refs only, sleeveless exposure."""
        urls, meta = route_canon_refs("face on sleeveless shirt", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "front"
        assert urls == [
            FACE_FRONT, FACE_LEFT_3Q, FACE_RIGHT_3Q,
            BODY_FRONT, BODY_MAP, FINAL_CARD,
        ]
        # No back/side/expression refs leak into a front scene.
        assert BODY_BACK not in urls
        assert BODY_LEFT not in urls
        assert BODY_RIGHT not in urls
        assert FACE_EXPRESSION not in urls
        assert "sleeveless" in meta.exposure

    def test_back_to_camera_shirtless_routes_back_only(self):
        """'back to camera shirtless' → back refs only, shirtless exposure."""
        urls, meta = route_canon_refs("back to camera shirtless", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "back"
        assert urls == [BODY_BACK, BODY_MAP, FINAL_CARD]
        # Front face refs must not appear in a back scene.
        assert FACE_FRONT not in urls
        assert BODY_FRONT not in urls
        assert "shirtless" in meta.exposure

    def test_side_profile_left_routes_left(self):
        """'side profile left' → left refs."""
        urls, meta = route_canon_refs("side profile left", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "left_profile"
        assert urls == [FACE_LEFT_3Q, BODY_LEFT, BODY_MAP, FINAL_CARD]
        assert BODY_RIGHT not in urls
        assert FACE_RIGHT_3Q not in urls

    def test_closeup_portrait_routes_portrait(self):
        """'close-up portrait smiling' → portrait refs (face_front, expression, card)."""
        urls, meta = route_canon_refs("close-up portrait smiling", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "portrait_closeup"
        assert urls == [FACE_FRONT, FACE_EXPRESSION, FINAL_CARD]
        # Portrait closeup intentionally drops body refs.
        assert BODY_FRONT not in urls
        assert BODY_MAP not in urls

    def test_ambiguous_prompt_falls_back_to_static_ordering(self):
        """Ambiguous prompt → fallback to collect_canon_reference_urls ordering."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = _make_full_canon()
        urls, meta = route_canon_refs("standing in a sunny field", canon)

        assert meta.routed is False
        assert meta.camera == "unknown"
        assert urls == collect_canon_reference_urls(canon)


# ── Orientation coverage ──────────────────────────────────────────────

class TestOrientationDetection:

    def test_right_profile_routes_right(self):
        urls, meta = route_canon_refs("right profile shot", _make_full_canon())
        assert meta.camera == "right_profile"
        assert urls == [FACE_RIGHT_3Q, BODY_RIGHT, BODY_MAP, FINAL_CARD]

    def test_left_3q_routes_left(self):
        urls, meta = route_canon_refs("three-quarter left view", _make_full_canon())
        assert meta.camera == "left_3q"
        assert urls == [FACE_LEFT_3Q, BODY_LEFT, BODY_MAP, FINAL_CARD]

    def test_right_3q_routes_right(self):
        urls, meta = route_canon_refs("3/4 right angle", _make_full_canon())
        assert meta.camera == "right_3q"
        assert urls == [FACE_RIGHT_3Q, BODY_RIGHT, BODY_MAP, FINAL_CARD]

    def test_full_body_routes_front_set(self):
        urls, meta = route_canon_refs("full body shot in the rain", _make_full_canon())
        assert meta.camera == "full_body"
        assert urls == [
            FACE_FRONT, FACE_LEFT_3Q, FACE_RIGHT_3Q,
            BODY_FRONT, BODY_MAP, FINAL_CARD,
        ]

    def test_priority_closeup_beats_front(self):
        """Portrait closeup outranks a co-occurring front signal."""
        _, meta = route_canon_refs("headshot facing camera", _make_full_canon())
        assert meta.camera == "portrait_closeup"

    def test_priority_back_beats_front(self):
        """Back signal outranks a co-occurring front signal."""
        _, meta = route_canon_refs("front-facing pose but back to camera", _make_full_canon())
        assert meta.camera == "back"


# ── Exposure detection ────────────────────────────────────────────────

class TestExposureDetection:

    def test_rolled_sleeves_detected(self):
        _, meta = route_canon_refs("front view with sleeves rolled up", _make_full_canon())
        assert "rolled_sleeves" in meta.exposure

    def test_multiple_exposure_signals(self):
        _, meta = route_canon_refs("facing camera in a leather jacket, long sleeves", _make_full_canon())
        assert "jacket" in meta.exposure
        assert "long_sleeves" in meta.exposure

    def test_no_exposure_signal_empty(self):
        _, meta = route_canon_refs("facing camera in the dark", _make_full_canon())
        assert meta.exposure == []


# ── Invariants ────────────────────────────────────────────────────────

class TestInvariants:

    @pytest.mark.parametrize("prompt,expected_camera", [
        ("front view", "front"),
        ("full body", "full_body"),
        ("back to camera", "back"),
        ("left profile", "left_profile"),
        ("right profile", "right_profile"),
        ("three quarter left", "left_3q"),
        ("three quarter right", "right_3q"),
    ])
    def test_body_map_and_final_card_preserved_in_non_portrait_scenes(self, prompt, expected_camera):
        """body_map + final_character_card reach every non-portrait body scene."""
        urls, meta = route_canon_refs(prompt, _make_full_canon())
        assert meta.camera == expected_camera
        assert BODY_MAP in urls, f"body_map missing for camera={expected_camera}"
        assert FINAL_CARD in urls, f"final_card missing for camera={expected_camera}"

    def test_routed_payload_no_larger_than_static(self):
        """Routed payloads are scene-scoped: never larger than the full static list."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = _make_full_canon()
        static_len = len(collect_canon_reference_urls(canon))
        for prompt in ("front view", "back to camera", "left profile", "close-up portrait"):
            urls, _ = route_canon_refs(prompt, canon)
            assert len(urls) <= static_len

    def test_missing_slots_skipped_silently(self):
        """A sparse canon yields only the route slots that have URLs set."""
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 7
        # Front route wants face_front, face_left_3q, face_right_3q, body_front,
        # body_map, final_card — but only face_front + final_card exist here.
        face = FaceCanonData(face_front_image_url=FACE_FRONT)
        body = BodyCanonData(final_character_card_image_url=FINAL_CARD)
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None

        urls, meta = route_canon_refs("front view", canon)
        assert urls == [FACE_FRONT, FINAL_CARD]
        assert meta.route_slots == ["face_front", "final_character_card"]

    def test_returns_scene_meta_type(self):
        _, meta = route_canon_refs("front view", _make_full_canon())
        assert isinstance(meta, SceneMeta)

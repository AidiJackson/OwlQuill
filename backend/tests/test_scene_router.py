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

    def test_face_on_sleeveless_routes_front_weighted(self):
        """'face on sleeveless shirt' → front weighting (body truth first)."""
        urls, meta = route_canon_refs("face on sleeveless shirt", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "front"
        # S24I: face identity leads; body truth (body_front, body_map) follows.
        assert urls == [
            FACE_FRONT, BODY_FRONT, FINAL_CARD,
            BODY_MAP, FACE_LEFT_3Q, FACE_RIGHT_3Q,
        ]
        # No back/side refs leak into a front scene; face_expression capped out.
        assert BODY_BACK not in urls
        assert BODY_LEFT not in urls
        assert BODY_RIGHT not in urls
        assert FACE_EXPRESSION not in urls
        assert "sleeveless" in meta.exposure

    def test_back_to_camera_shirtless_routes_back_weighted(self):
        """'back to camera shirtless' → back anatomy first, face as anchor."""
        urls, meta = route_canon_refs("back to camera shirtless", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "back"
        # P11: back anatomy dominates; tattoo/body truth preserved; face anchor.
        assert urls == [
            BODY_BACK, FINAL_CARD, BODY_MAP,
            FACE_FRONT, FACE_LEFT_3Q, FACE_RIGHT_3Q,
        ]
        assert urls[0] == BODY_BACK
        # Front body morphology is not a back-scene reference.
        assert BODY_FRONT not in urls
        assert BODY_LEFT not in urls
        assert "shirtless" in meta.exposure

    def test_side_profile_left_routes_left_weighted(self):
        """'side profile left' → left anatomy + matching 3q face dominate."""
        urls, meta = route_canon_refs("side profile left", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "left_profile"
        assert urls == [
            BODY_LEFT, FACE_LEFT_3Q, FINAL_CARD,
            BODY_MAP, FACE_FRONT, FACE_RIGHT_3Q,
        ]
        assert urls[:2] == [BODY_LEFT, FACE_LEFT_3Q]
        assert BODY_RIGHT not in urls

    def test_closeup_portrait_routes_portrait(self):
        """'close-up portrait smiling' → P14 hardened face stack: face_front,
        both 3/4 geometry refs, expression, then holistic card."""
        urls, meta = route_canon_refs("close-up portrait smiling", _make_full_canon())

        assert meta.routed is True
        assert meta.camera == "portrait_closeup"
        assert urls == [
            FACE_FRONT, FACE_LEFT_3Q, FACE_RIGHT_3Q, FACE_EXPRESSION, FINAL_CARD,
        ]
        assert urls[0] == FACE_FRONT  # face identity leads
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
        assert urls == [
            BODY_RIGHT, FACE_RIGHT_3Q, FINAL_CARD,
            BODY_MAP, FACE_FRONT, FACE_LEFT_3Q,
        ]
        assert urls[:2] == [BODY_RIGHT, FACE_RIGHT_3Q]

    def test_left_3q_routes_left(self):
        urls, meta = route_canon_refs("three-quarter left view", _make_full_canon())
        assert meta.camera == "left_3q"
        assert urls == [
            BODY_LEFT, FACE_LEFT_3Q, FINAL_CARD,
            BODY_MAP, FACE_FRONT, FACE_RIGHT_3Q,
        ]

    def test_right_3q_routes_right(self):
        urls, meta = route_canon_refs("3/4 right angle", _make_full_canon())
        assert meta.camera == "right_3q"
        assert urls == [
            BODY_RIGHT, FACE_RIGHT_3Q, FINAL_CARD,
            BODY_MAP, FACE_FRONT, FACE_LEFT_3Q,
        ]

    def test_full_body_routes_front_weighted(self):
        urls, meta = route_canon_refs("full body shot in the rain", _make_full_canon())
        assert meta.camera == "full_body"
        # full_body shares the front weighting profile (S24I: face leads).
        assert urls == [
            FACE_FRONT, BODY_FRONT, FINAL_CARD,
            BODY_MAP, FACE_LEFT_3Q, FACE_RIGHT_3Q,
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


# ── P11 orientation-aware weighting acceptance ────────────────────────

class TestP11WeightingAcceptance:
    """Exact slot ordering required by the P11 spec (A–F)."""

    def test_A_front_sleeveless_exact_order(self):
        """A. front sleeveless → body truth first, face reinforced, card early."""
        urls, meta = route_canon_refs(
            "Leonardo standing face on wearing a fitted sleeveless shirt, "
            "serious expression.",
            _make_full_canon(),
        )
        assert meta.camera == "front"
        # S24I: face identity leads; body truth follows.
        assert urls == [
            FACE_FRONT, BODY_FRONT, FINAL_CARD,
            BODY_MAP, FACE_LEFT_3Q, FACE_RIGHT_3Q,
        ]

    def test_B_back_first_slot_is_body_back(self):
        """B. back to camera shirtless → first slot body_back."""
        urls, meta = route_canon_refs("back to camera shirtless", _make_full_canon())
        assert meta.camera == "back"
        assert urls[0] == BODY_BACK

    def test_C_left_profile_first_slots(self):
        """C. left profile → first slots body_left, face_left_3q."""
        urls, meta = route_canon_refs("left profile", _make_full_canon())
        assert meta.camera == "left_profile"
        assert urls[:2] == [BODY_LEFT, FACE_LEFT_3Q]

    def test_D_right_profile_first_slots(self):
        """D. right profile → first slots body_right, face_right_3q."""
        urls, meta = route_canon_refs("right profile", _make_full_canon())
        assert meta.camera == "right_profile"
        assert urls[:2] == [BODY_RIGHT, FACE_RIGHT_3Q]

    def test_E_portrait_closeup_exact_order(self):
        """E. portrait smiling close-up → P14 hardened facial identity stack."""
        urls, meta = route_canon_refs("portrait smiling close-up", _make_full_canon())
        assert meta.camera == "portrait_closeup"
        assert urls == [
            FACE_FRONT, FACE_LEFT_3Q, FACE_RIGHT_3Q, FACE_EXPRESSION, FINAL_CARD,
        ]

    def test_F_ambiguous_fallback_unchanged(self):
        """F. ambiguous prompt → existing static fallback ordering, untouched."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = _make_full_canon()
        urls, meta = route_canon_refs("standing in a sunny field", canon)
        assert meta.routed is False
        assert meta.camera == "unknown"
        assert urls == collect_canon_reference_urls(canon)

    def test_front_face_expression_capped_out_of_full_canon(self):
        """face_expression is the 'if room' slot — dropped under the 6-cap."""
        urls, _ = route_canon_refs("front view", _make_full_canon())
        assert len(urls) == 6
        assert FACE_EXPRESSION not in urls

    def test_front_face_expression_fills_when_room(self):
        """Sparse front canon (body_map absent) → face_expression fills the slot."""
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 5
        # Front profile: body_front, face_front, final_card, [body_map missing],
        # face_left_3q, face_right_3q, face_expression → expression now has room.
        face = FaceCanonData(
            face_front_image_url=FACE_FRONT,
            face_left_3q_image_url=FACE_LEFT_3Q,
            face_right_3q_image_url=FACE_RIGHT_3Q,
            face_expression_image_url=FACE_EXPRESSION,
        )
        body = BodyCanonData(
            body_front_image_url=BODY_FRONT,
            final_character_card_image_url=FINAL_CARD,
        )
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None

        urls, _ = route_canon_refs("front view", canon)
        # S24I: face identity leads; body truth follows.
        assert urls == [
            FACE_FRONT, BODY_FRONT, FINAL_CARD,
            FACE_LEFT_3Q, FACE_RIGHT_3Q, FACE_EXPRESSION,
        ]
        assert len(urls) == 6


# ── P13 exposure-gated cropped-mark routing ───────────────────────────

LEFT_SLEEVE_CROP = "https://cdn.test/crop_left_sleeve.png"
RIGHT_WOLF_CROP = "https://cdn.test/crop_right_wolf.png"
NECK_CROP = "https://cdn.test/crop_neck.png"


def _make_canon_with_marks(marks):
    """Full-slot canon plus the supplied permanent_body_marks."""
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import FaceCanonData, BodyCanonData

    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 42
    face = FaceCanonData(
        face_front_image_url=FACE_FRONT,
        face_left_3q_image_url=FACE_LEFT_3Q,
        face_right_3q_image_url=FACE_RIGHT_3Q,
    )
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_left_image_url=BODY_LEFT,
        body_right_image_url=BODY_RIGHT,
        body_back_image_url=BODY_BACK,
        body_map_image_url=BODY_MAP,
        final_character_card_image_url=FINAL_CARD,
        permanent_body_marks=marks,
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


def _arm_marks():
    from app.schemas.canon import PermanentBodyMark
    return [
        PermanentBodyMark(
            label="Left sleeve", type="tattoo", body_region="left_full_arm",
            side="left", description="gothic script sleeve",
            reference_image_url=LEFT_SLEEVE_CROP,
        ),
        PermanentBodyMark(
            label="Wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf howling",
            reference_image_url=RIGHT_WOLF_CROP,
        ),
    ]


class TestExposureGatedCropRouting:
    """Acceptance: exposed-region marks route their crops; covered marks do not."""

    def test_sleeveless_front_routes_arm_crops(self):
        """1. Sleeveless/front routes body_front, body_map, and both arm crops."""
        urls, meta = route_canon_refs(
            "facing camera, sleeveless shirt, arms visible", _make_canon_with_marks(_arm_marks())
        )
        assert meta.camera == "front"
        assert LEFT_SLEEVE_CROP in urls
        assert RIGHT_WOLF_CROP in urls
        assert BODY_FRONT in urls
        assert BODY_MAP in urls
        assert len(urls) <= 6
        assert meta.mark_crops == 2

    def test_rolled_sleeves_routes_forearm_sleeve_not_upper_arm(self):
        """2. Rolled sleeves routes the visible sleeve crop, not the covered upper-arm wolf."""
        urls, meta = route_canon_refs(
            "facing camera, sleeves rolled up", _make_canon_with_marks(_arm_marks())
        )
        assert LEFT_SLEEVE_CROP in urls           # sleeve forearm portion visible
        assert RIGHT_WOLF_CROP not in urls         # upper arm stays covered
        assert BODY_FRONT in urls and BODY_MAP in urls
        assert meta.mark_crops == 1

    def test_pool_scene_routes_exposed_arm_crops(self):
        """3. Pool / open-arm scene routes exposed arm crops."""
        urls, meta = route_canon_refs(
            "facing camera at a swimming pool, arms out", _make_canon_with_marks(_arm_marks())
        )
        assert LEFT_SLEEVE_CROP in urls
        assert RIGHT_WOLF_CROP in urls

    def test_closeup_portrait_routes_no_crops(self):
        """4. Close portrait still prioritises face refs and routes no body crops."""
        urls, meta = route_canon_refs(
            "close-up portrait smiling", _make_canon_with_marks(_arm_marks())
        )
        assert meta.camera == "portrait_closeup"
        assert LEFT_SLEEVE_CROP not in urls
        assert RIGHT_WOLF_CROP not in urls
        assert meta.mark_crops == 0
        assert urls[0] == FACE_FRONT

    def test_open_collar_routes_neck_crop(self):
        from app.schemas.canon import PermanentBodyMark
        marks = [PermanentBodyMark(
            label="Neck ink", type="tattoo", body_region="neck", side="centre",
            description="blackwork", reference_image_url=NECK_CROP,
        )]
        urls, meta = route_canon_refs(
            "facing camera, open collar shirt", _make_canon_with_marks(marks)
        )
        assert NECK_CROP in urls
        assert meta.mark_crops == 1

    def test_long_sleeves_routes_no_arm_crops(self):
        """Covered arms route no crops and preserve body truth."""
        urls, meta = route_canon_refs(
            "facing camera, long-sleeve sweater", _make_canon_with_marks(_arm_marks())
        )
        assert LEFT_SLEEVE_CROP not in urls
        assert RIGHT_WOLF_CROP not in urls
        assert meta.mark_crops == 0
        # S24I: marks all covered → clothed body_front stays as covered body
        # truth; the bare-skin body_map placement sheet is suppressed.
        assert BODY_FRONT in urls
        assert BODY_MAP not in urls
        assert meta.body_map_suppressed is True

    def test_marks_without_crop_url_degrade_gracefully(self):
        """No reference_image_url → no crop routed; base routing intact."""
        from app.schemas.canon import PermanentBodyMark
        marks = [PermanentBodyMark(
            label="Left sleeve", type="tattoo", body_region="left_full_arm",
            side="left", description="gothic script sleeve",
        )]
        urls, meta = route_canon_refs(
            "facing camera, sleeveless shirt", _make_canon_with_marks(marks)
        )
        assert meta.mark_crops == 0
        assert BODY_FRONT in urls
        assert len(urls) <= 6

    def test_no_marks_routing_unchanged(self):
        """Canon with zero marks routes identically to the no-crop baseline."""
        urls, meta = route_canon_refs("facing camera, sleeveless shirt", _make_canon_with_marks([]))
        assert meta.mark_crops == 0
        # S24I: face leads; no marks → no coverage suppression, body_map stays.
        assert meta.body_map_suppressed is False
        assert urls == [
            FACE_FRONT, BODY_FRONT, FINAL_CARD,
            BODY_MAP, FACE_LEFT_3Q, FACE_RIGHT_3Q,
        ]


# ── P13b tattoo-binding regression: skin-bound crops, never floating symbols ──

class TestTattooBindingRegression:
    """Pool / open-arm scene: the wolf tattoo must bind to right-upper-arm
    anatomy, never render as a free-floating symbol beside the body.

    Covers the P13b fix end to end:
      #1 SceneMeta carries body-binding metadata for each routed crop
      #2 the compiled marking clause frames marks as skin-bound anatomy
      #3 routed refs pair the crop with a body anchor — never routed alone
    """

    _POOL_PROMPT = "facing camera at a swimming pool, arms out"

    def test_wolf_crop_paired_with_body_anchor(self):
        """#3: the wolf crop is routed, and a body anchor is always alongside it,
        so the provider grounds it on anatomy instead of floating it."""
        urls, meta = route_canon_refs(self._POOL_PROMPT, _make_canon_with_marks(_arm_marks()))
        assert RIGHT_WOLF_CROP in urls
        assert any(u in urls for u in (BODY_FRONT, BODY_MAP)), (
            f"crop routed without a body anchor — detached-symbol risk: {urls!r}"
        )
        assert meta.mark_crops >= 1

    def test_wolf_binding_metadata_is_right_upper_arm_anatomy(self):
        """#1: the routed crop preserves body_region/side/label/visibility so the
        wolf is interpreted as right upper-arm anatomy, not a loose graphic."""
        _, meta = route_canon_refs(self._POOL_PROMPT, _make_canon_with_marks(_arm_marks()))
        wolf = next((b for b in meta.mark_crop_bindings if b.url == RIGHT_WOLF_CROP), None)
        assert wolf is not None, f"wolf binding missing from {meta.mark_crop_bindings!r}"
        assert wolf.body_region == "right_upper_arm"
        assert wolf.side == "right"
        assert "wolf" in wolf.label.lower()
        assert wolf.visibility == "exposed"

    def test_crop_never_routed_alone_without_body_anchor(self):
        """#3 negative path: with no body anchor available, crops are dropped
        rather than routed alone — there is no detached-symbol path."""
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 7
        face = FaceCanonData(face_front_image_url=FACE_FRONT)
        # Marks + crops present, but the body carries NO image slots (no anchor).
        body = BodyCanonData(permanent_body_marks=_arm_marks())
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None

        urls, meta = route_canon_refs(self._POOL_PROMPT, canon)
        assert RIGHT_WOLF_CROP not in urls
        assert LEFT_SLEEVE_CROP not in urls
        assert meta.mark_crops == 0
        assert meta.mark_crop_bindings == []

    def test_pool_clause_frames_wolf_as_skin_bound(self):
        """#2: in an exposed (pool) scene the marking clause frames the wolf as
        skin-bound anatomy and forbids detaching/floating/reinterpreting it."""
        from app.services.canon_compiler import _permanent_marks_clause

        clause = _permanent_marks_clause(
            _make_canon_with_marks(_arm_marks()), self._POOL_PROMPT
        ).lower()
        assert "skin-bound anatomy" in clause
        assert "right upper arm: wolf howling permanently inked into skin" in clause
        assert "detach, float" in clause
        assert "reinterpret markings as symbols" in clause
        assert "remain attached to the correct body region and side" in clause


# ── Clothing truth > tattoo visibility (2026-05-31) ───────────────────

class TestClothingTruthOverTattooVisibility:
    """Clothing truth outranks tattoo visibility.

    Hierarchy: identity > anatomical binding > clothing truth >
    tattoo visibility > scene aesthetics.

    A covered tattoo must stay hidden — the model must never restyle a garment
    (cut/roll/tear/remove) to expose it. Only a region the requested clothing
    naturally leaves uncovered routes its high-fidelity crop. These regressions
    pin the Leo/Pan kitchen failure where a button-up shirt was turned into a
    cutout to reveal the right upper-arm wolf.
    """

    _KITCHEN = (
        "Leonardo standing in a beautiful modern kitchen, wearing a fitted "
        "black button-up shirt with sleeves rolled to the forearms, "
        "cinematic realism."
    )

    def test_1_kitchen_rolled_sleeve_forearm_routes_upper_arm_does_not(self):
        """1. Kitchen rolled-sleeve: forearm sleeve crop routes, the covered
        right upper-arm wolf does NOT, a body anchor still routes, no bloat."""
        canon = _make_canon_with_marks(_arm_marks())
        urls, meta = route_canon_refs(self._KITCHEN, canon)

        # Clothing-described scene with no orientation keyword still routes
        # (treated as a front body shot so exposure gating can run).
        assert meta.routed is True
        assert meta.camera == "front"
        assert "rolled_sleeves" in meta.exposure
        # Forearm portion of the left sleeve is exposed by rolled sleeves.
        assert LEFT_SLEEVE_CROP in urls
        # Right upper arm stays under the still-present sleeve → wolf NOT routed.
        assert RIGHT_WOLF_CROP not in urls
        assert meta.mark_crops == 1
        # Body anchor still routes so the marking binds to anatomy.
        assert any(u in urls for u in (BODY_FRONT, BODY_MAP))
        # No prompt bloat — routed payload never exceeds the provider cap.
        assert len(urls) <= 6

    def test_1_kitchen_prompt_carries_clothing_truth_directive(self):
        """1 (cont.): the compiled prompt asserts clothing truth over visibility."""
        from app.services.canon_compiler import compile_canon_prompt

        prompt = compile_canon_prompt(_make_canon_with_marks(_arm_marks()), self._KITCHEN).lower()
        assert "permanent markings obey scene clothing" in prompt
        assert "hidden markings remain hidden" in prompt
        # S24AH.1: the S24AB mandatory-exposed directive is reverted. Naturally
        # visible marks are preserved (not force-exposed); the directive that made
        # exposed tattoos "mandatory identity features" must be gone.
        assert "mandatory identity features" not in prompt
        # Compact, not a return to pre-P12 multi-paragraph prose bloat.
        assert "for visual balance or composition" not in prompt
        assert len(prompt) < 1200

    def test_2_sleeveless_routes_both_arm_crops(self):
        """2. Sleeveless: full arms exposed → both arm crops route."""
        urls, meta = route_canon_refs(
            "Leonardo wearing a sleeveless shirt, full arms visible",
            _make_canon_with_marks(_arm_marks()),
        )
        assert RIGHT_WOLF_CROP in urls
        assert LEFT_SLEEVE_CROP in urls
        assert meta.mark_crops == 2

    def test_3_short_sleeve_exposes_forearm_covers_upper_arm(self):
        """3. Short-sleeve: forearm crop routes (visible region); the upper-arm
        wolf stays covered by the short sleeve."""
        urls, meta = route_canon_refs(
            "Leonardo wearing a short-sleeve shirt",
            _make_canon_with_marks(_arm_marks()),
        )
        assert meta.routed is True
        assert "short_sleeves" in meta.exposure
        # Forearm sleeve crop depends on visible-region logic → exposed here.
        assert LEFT_SLEEVE_CROP in urls
        # Upper-arm wolf is covered by a short sleeve → stays hidden.
        assert RIGHT_WOLF_CROP not in urls

    def test_4_long_sleeve_routes_no_arm_crops(self):
        """4. Long-sleeve: arms covered → no arm tattoo crops route."""
        urls, meta = route_canon_refs(
            "Leonardo wearing a long-sleeve shirt",
            _make_canon_with_marks(_arm_marks()),
        )
        assert LEFT_SLEEVE_CROP not in urls
        assert RIGHT_WOLF_CROP not in urls
        assert meta.mark_crops == 0
        # S24I: covered marks ride the clothed body_front; the bare body_map
        # placement sheet is suppressed so marks are not pushed onto covered skin.
        assert BODY_FRONT in urls
        assert BODY_MAP not in urls
        assert meta.body_map_suppressed is True

    def test_5_portrait_closeup_routes_no_arm_crops(self):
        """5. Portrait close-up: facial identity only → no arm tattoo crops."""
        urls, meta = route_canon_refs(
            "close-up portrait of Leonardo smiling",
            _make_canon_with_marks(_arm_marks()),
        )
        assert meta.camera == "portrait_closeup"
        assert LEFT_SLEEVE_CROP not in urls
        assert RIGHT_WOLF_CROP not in urls
        assert meta.mark_crops == 0


# ── P14 body-truth dominance: crops are supporting evidence, never primary ──

class TestBodyTruthDominance:
    """P14 Phase 1/2 — body truth dominates the routed list; mark crops follow.

    Pins the Leo failure: a wolf crop must never act as primary truth. Body
    truth (body_front + body_map) and the face anchor must precede every crop so
    the provider reads "this person with these tattoos", not "a tattoo concept".
    """

    def test_face_leads_then_body_truth_then_crops(self):
        """Sleeveless front: face anchor leads, body truth precedes both crops,
        crops come last as supporting evidence."""
        urls, meta = route_canon_refs(
            "facing camera, sleeveless shirt, arms visible",
            _make_canon_with_marks(_arm_marks()),
        )
        slots = meta.route_slots
        # 1. Face identity leads (Phase 3) — never buried behind body/crops.
        assert slots[0] == "face_front"
        assert urls[0] == FACE_FRONT
        # 2. body_front + body_map both present and AHEAD of any crop (Phase 1/2).
        assert "body_front" in slots and "body_map" in slots
        first_crop = slots.index("mark_crop")
        assert slots.index("body_front") < first_crop
        assert slots.index("body_map") < first_crop
        # 3. Crops are supporting — strictly after body truth, never position 0/1.
        assert first_crop >= 2
        assert LEFT_SLEEVE_CROP in urls and RIGHT_WOLF_CROP in urls
        assert len(urls) <= 6

    def test_exposed_crop_precedes_holistic_card_p15b(self):
        """P15b: exposed mark crops route AHEAD of final_character_card (but still
        behind body_front/body_map) so OpenAI's position-weighted images.edit
        renders the forearm tattoo. body anchors stay dominant; no float."""
        urls, meta = route_canon_refs(
            "modern kitchen, button-up shirt with sleeves rolled to the forearms",
            _make_canon_with_marks(_arm_marks()),
        )
        slots = meta.route_slots
        assert "mark_crop" in slots and "final_character_card" in slots
        crop_i = slots.index("mark_crop")
        card_i = slots.index("final_character_card")
        # Crop now ahead of the holistic card (the P15b fix)...
        assert crop_i < card_i, f"crop must precede holistic card: {slots}"
        # ...but the two grounding anchors still lead it (anti-float preserved).
        assert slots.index("body_front") < crop_i
        assert slots.index("body_map") < crop_i
        # Rolled sleeve: forearm sleeve routed, upper-arm wolf still hidden.
        assert LEFT_SLEEVE_CROP in urls
        assert RIGHT_WOLF_CROP not in urls

    def test_crop_never_precedes_body_truth_profile(self):
        """Profile crop scene: body_front + body_map are pulled from the full
        canon (not just the camera route) and still precede the crop."""
        urls, meta = route_canon_refs(
            "left profile, sleeveless, arms visible",
            _make_canon_with_marks(_arm_marks()),
        )
        assert meta.camera == "left_profile"
        slots = meta.route_slots
        if "mark_crop" in slots:
            first_crop = slots.index("mark_crop")
            assert "body_front" in slots and slots.index("body_front") < first_crop
            assert "body_map" in slots and slots.index("body_map") < first_crop
            # Orientation-matched side also precedes the crop.
            assert "body_left" in slots and slots.index("body_left") < first_crop

    def test_skin_exposure_promotes_ambiguous_scene_to_front(self):
        """P14: a pool / open-shirt scene with NO camera keyword still engages
        body + crop routing (previously fell back to ambiguous, routing 0 crops).
        Named acceptance scenario: 'Pool/open shirt: tattoos match geometry'."""
        urls, meta = route_canon_refs(
            "at the swimming pool, open shirt, arms out, relaxed",
            _make_canon_with_marks(_arm_marks()),
        )
        assert meta.routed is True
        assert meta.camera == "front"
        # Exposed arm crops now route, grounded on body truth.
        assert RIGHT_WOLF_CROP in urls
        assert LEFT_SLEEVE_CROP in urls
        assert BODY_FRONT in urls and BODY_MAP in urls
        assert meta.mark_crops >= 1

    def test_truly_ambiguous_scene_still_falls_back(self):
        """No camera, garment, or skin cue → still the static fallback (unchanged)."""
        urls, meta = route_canon_refs(
            "standing in a sunny field", _make_canon_with_marks(_arm_marks())
        )
        assert meta.routed is False
        assert meta.camera == "unknown"
        assert meta.mark_crops == 0

    def test_crops_remain_contiguous_for_binding_slice(self):
        """Crops stay contiguous and in input order so crops[:crop_count]
        binding metadata stays aligned after the provider cap."""
        _, meta = route_canon_refs(
            "facing camera, sleeveless shirt, arms visible",
            _make_canon_with_marks(_arm_marks()),
        )
        slots = meta.route_slots
        crop_positions = [i for i, s in enumerate(slots) if s == "mark_crop"]
        # Contiguous block.
        assert crop_positions == list(
            range(crop_positions[0], crop_positions[0] + len(crop_positions))
        )
        # Bindings align to the routed crops in order.
        assert len(meta.mark_crop_bindings) == meta.mark_crops
        assert meta.mark_crop_bindings[0].url == LEFT_SLEEVE_CROP

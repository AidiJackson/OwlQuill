"""CANON SKIN/CLOTHING sprint — card-coverage separation tests.

The production Davies failure: chest tattoos rendered on/through an opaque
white shirt / three-piece suit. His body canon cards are shirtless and
tattoo-heavy while ``permanent_body_marks`` is EMPTY, so every mark-driven
occlusion mechanism was inert. These tests pin the mark-INDEPENDENT coverage
system that fixes it, and pin that legacy canons keep their existing routing.
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import (
    BodyCanonData,
    CardCoverage,
    COVERAGE_PRESETS,
    FaceCanonData,
    PermanentBodyMark,
)
from app.services.canon_compiler import compile_canon_prompt
from app.services.scene_router import route_canon_refs

FACE_FRONT = "https://cdn.test/face_front.png"
FACE_LEFT_3Q = "https://cdn.test/face_left_3q.png"
FACE_RIGHT_3Q = "https://cdn.test/face_right_3q.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"
STANDING = "https://cdn.test/standing_relaxed.png"
FINAL_CARD = "https://cdn.test/final_card.png"

SUIT_SCENE = "wearing an opaque white shirt and three-piece suit at a gala"


def _canon(
    *,
    coverage: dict | None = None,
    marks: list | None = None,
    with_body_map: bool = True,
    with_standing: bool = True,
    with_final: bool = False,
):
    """Davies-shaped mock canon: face refs + shirtless-style body refs."""
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 38
    face = FaceCanonData(
        face_front_image_url=FACE_FRONT,
        face_left_3q_image_url=FACE_LEFT_3Q,
        face_right_3q_image_url=FACE_RIGHT_3Q,
    )
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP if with_body_map else None,
        standing_relaxed_image_url=STANDING if with_standing else None,
        final_character_card_image_url=FINAL_CARD if with_final else None,
        permanent_body_marks=marks or [],
        card_coverage=coverage or {},
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


def _bare(slot_dict=None):
    return {"coverage_type": "bare_torso", **(slot_dict or {})}


# ── 1/16. Davies core: marks empty, bare card, fully clothed scene ────

class TestDaviesMarklessCoverage:
    def test_bare_declared_card_conflicts_in_clothed_scene(self):
        """(1) permanent_body_marks=[] + declared-bare body_front + suit scene
        → the bare card is treated as coverage-conflicting and suppressed."""
        urls, meta = route_canon_refs(
            SUIT_SCENE, _canon(coverage={"body_front": _bare()})
        )
        assert BODY_FRONT not in urls
        assert "body_front" in meta.coverage_suppressed
        # Coverage routing ran with zero marks (16).
        assert meta.coverage_suppressed  # non-empty despite marks==[]

    def test_body_map_suppressed_without_marks(self):
        """(13/16) The slot-default-bare body_map is suppressed for an
        explicitly clothed scene even with permanent_body_marks=[] — the exact
        production Davies case S24I could not handle."""
        urls, meta = route_canon_refs(SUIT_SCENE, _canon())
        assert BODY_MAP not in urls
        assert meta.body_map_suppressed is True
        assert "body_map" in meta.coverage_suppressed

    def test_clothed_alternative_preferred(self):
        """(2) With a declared fully-clothed card available, it is routed and
        the declared-bare card is suppressed."""
        urls, meta = route_canon_refs(
            "front view, " + SUIT_SCENE,
            _canon(coverage={
                "body_front": _bare(),
                "standing_relaxed": {"coverage_type": "fully_clothed"},
            }),
        )
        assert STANDING in urls
        assert BODY_FRONT not in urls
        assert meta.coverage_compatible == ["standing_relaxed"]

    def test_face_grounding_retained(self):
        """(17) Face references stay present and leading in covered scenes."""
        urls, meta = route_canon_refs(
            "front view, " + SUIT_SCENE, _canon(coverage={"body_front": _bare()})
        )
        assert urls[0] == FACE_FRONT
        assert FACE_LEFT_3Q in urls and FACE_RIGHT_3Q in urls


# ── 3–5. Mark-refined scenes ──────────────────────────────────────────

def _chest_mark(crop_url="https://cdn.test/chest_crop.png"):
    return PermanentBodyMark(
        label="Chest script", type="tattoo", body_region="chest", side="centre",
        description="gothic lettering across the chest",
        reference_image_url=crop_url,
    )


class TestMarkRefinement:
    def test_chest_tattoo_opaque_shirt_no_crop(self):
        """(3) Chest mark + opaque shirt → the chest crop is not routed."""
        urls, meta = route_canon_refs(
            "front view, " + SUIT_SCENE,
            _canon(marks=[_chest_mark().model_dump()]),
        )
        assert "https://cdn.test/chest_crop.png" not in urls
        assert meta.mark_crops == 0

    def test_shirtless_routes_body_map_and_crop(self):
        """(4/12) Shirtless scene → body_map authoritative, chest crop routed."""
        urls, meta = route_canon_refs(
            "shirtless at the gym",
            _canon(marks=[_chest_mark().model_dump()]),
        )
        assert BODY_MAP in urls
        assert meta.mark_crops == 1
        assert meta.body_map_suppressed is False

    def test_open_shirt_exposes_chest(self):
        """(5) Open shirt → chest recognised as exposed; body_map permitted."""
        urls, meta = route_canon_refs(
            "front view, open shirt", _canon(marks=[_chest_mark().model_dump()])
        )
        assert meta.scene_coverage["torso"] == "exposed"
        assert BODY_MAP in urls
        assert meta.mark_crops == 1

    def test_upper_arm_mark_long_sleeves_suppressed(self):
        """(6) Upper-arm tattoo + long sleeves → no arm crop, body_map dropped."""
        mark = PermanentBodyMark(
            label="Wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf head",
            reference_image_url="https://cdn.test/wolf.png",
        )
        urls, meta = route_canon_refs(
            "front view, long-sleeved dress shirt", _canon(marks=[mark.model_dump()])
        )
        assert "https://cdn.test/wolf.png" not in urls
        assert meta.mark_crops == 0
        assert BODY_MAP not in urls

    def test_upper_arm_mark_sleeveless_included(self):
        """(7) Upper-arm tattoo + sleeveless → crop routed."""
        mark = PermanentBodyMark(
            label="Wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf head",
            reference_image_url="https://cdn.test/wolf.png",
        )
        urls, meta = route_canon_refs(
            "front view, sleeveless top", _canon(marks=[mark.model_dump()])
        )
        assert "https://cdn.test/wolf.png" in urls
        assert meta.mark_crops == 1

    def test_rolled_sleeves_partial_exposure(self):
        """(8) Rolled sleeves → forearms exposed, upper arms covered; a
        declared bare-torso card counts as scene-useful (partial), not
        conflicting, so it stays routed."""
        urls, meta = route_canon_refs(
            "front view, dress shirt with rolled sleeves",
            _canon(coverage={"body_front": _bare()}),
        )
        assert meta.scene_coverage["forearms"] == "exposed"
        assert meta.scene_coverage["upper_arms"] == "covered_explicit"
        assert "body_front" in meta.coverage_partial
        assert BODY_FRONT in urls

    def test_shorts_expose_legs(self):
        """(9) Shorts → legs exposed; a declared shorts card is compatible."""
        urls, meta = route_canon_refs(
            "front view, t-shirt and shorts",
            _canon(coverage={"standing_relaxed": {"coverage_type": "shorts"}}),
        )
        assert meta.scene_coverage["legs"] == "exposed"
        assert "standing_relaxed" in meta.coverage_compatible
        assert STANDING in urls


# ── 10/11. Legacy behaviour ───────────────────────────────────────────

class TestLegacyCompatibility:
    def test_unknown_card_not_treated_as_clothed(self):
        """(10) A card with no metadata is unknown — recorded as such, never
        suppressed, never certified compatible."""
        urls, meta = route_canon_refs(SUIT_SCENE, _canon())
        assert "body_front" in meta.coverage_unknown
        assert "body_front" not in meta.coverage_compatible
        assert BODY_FRONT in urls  # legacy card keeps routing

    def test_all_bare_cards_keeps_one_anchor(self):
        """(11) Every body card declared bare + covered scene → the strongest
        body anchor is retained, conflict recorded, no total grounding loss."""
        urls, meta = route_canon_refs(
            "front view, " + SUIT_SCENE,
            _canon(coverage={
                "body_front": _bare(),
                "body_map": _bare(),
                "standing_relaxed": _bare(),
            }),
        )
        assert meta.coverage_conflict_anchor == "body_front"
        assert BODY_FRONT in urls          # anchor retained
        assert BODY_MAP not in urls        # the rest suppressed
        assert STANDING not in urls
        assert urls[0] == FACE_FRONT       # face still leads

    def test_markless_plain_character_unaffected(self):
        """(14/23) Ordinary markless character, camera-only prompt (no
        clothing vocabulary) → routing and prompt byte-identical to before."""
        urls, meta = route_canon_refs("front view", _canon())
        assert BODY_MAP in urls and BODY_FRONT in urls
        assert meta.coverage_suppressed == []
        prompt = compile_canon_prompt(_canon(), "standing in a sunny field")
        assert "fabric" not in prompt and "covered" not in prompt

    def test_marks_still_refine_when_available(self):
        """(15) Structured marks continue to drive crop routing on top of
        coverage routing — refinement, not gating."""
        urls, meta = route_canon_refs(
            "front view, open shirt", _canon(marks=[_chest_mark().model_dump()])
        )
        assert meta.mark_crops == 1  # mark data refined the route


# ── Compiler occlusion invariant ──────────────────────────────────────

class TestOcclusionClause:
    def test_fires_for_markless_bare_canon_in_explicit_scene(self):
        prompt = compile_canon_prompt(_canon(), SUIT_SCENE)
        assert "not visible on or through the fabric" in prompt
        assert "chest and torso" in prompt

    def test_never_names_a_design(self):
        """Region-level only — no tattoo description leaks into the prompt."""
        prompt = compile_canon_prompt(_canon(), SUIT_SCENE)
        for word in ("tattoo design", "lettering", "phoenix", "script"):
            assert word not in prompt.lower()

    def test_silent_without_explicit_cover_vocabulary(self):
        """covered_default scenes stay byte-stable (no prompt bloat)."""
        prompt = compile_canon_prompt(_canon(), "Angelo in his office")
        assert "fabric" not in prompt

    def test_silent_when_marks_exist(self):
        """Mark-driven clause owns occlusion wording when marks are present."""
        prompt = compile_canon_prompt(
            _canon(marks=[_chest_mark().model_dump()]), SUIT_SCENE
        )
        assert "Hidden markings remain hidden" in prompt
        assert "not visible on or through the fabric" not in prompt

    def test_silent_without_bare_evidence(self):
        """No body_map, no declared-bare card → nothing to occlude."""
        prompt = compile_canon_prompt(
            _canon(with_body_map=False), SUIT_SCENE
        )
        assert "fabric" not in prompt

    def test_silent_for_portraits(self):
        prompt = compile_canon_prompt(_canon(), "close-up portrait, suit and tie")
        assert "fabric" not in prompt


# ── 18–21. Vest / waistcoat / three-piece vocabulary ─────────────────

class TestVestDisambiguation:
    @pytest.mark.parametrize("phrase", [
        "wearing a vest",
        "waistcoat and pocket watch",
        "three-piece suit",
        "suit vest and tie",
    ])
    def test_formal_vest_terms_do_not_expose_arms(self, phrase):
        """(18–21) Tailoring vocabulary must not read as bare arms."""
        _, meta = route_canon_refs(f"front view, {phrase}", _canon())
        assert meta.scene_coverage["upper_arms"] != "exposed"
        assert meta.mark_crops == 0

    @pytest.mark.parametrize("phrase,expected", [
        ("waistcoat", "covered_explicit"),
        ("three-piece suit", "covered_explicit"),
        ("suit vest", "covered_explicit"),
    ])
    def test_formal_terms_read_as_explicit_torso_cover(self, phrase, expected):
        _, meta = route_canon_refs(f"front view, wearing a {phrase}", _canon())
        assert meta.scene_coverage["torso"] == expected

    def test_sleeveless_terms_still_expose_arms(self):
        """The unambiguous exposure vocabulary is unchanged."""
        _, meta = route_canon_refs("front view, tank top", _canon())
        assert meta.scene_coverage["upper_arms"] == "exposed"

    def test_swimsuit_is_exposure_not_suit(self):
        """'swimsuit' contains 'suit' — exposure-first precedence resolves it."""
        _, meta = route_canon_refs("at the beach in a swimsuit", _canon())
        assert meta.scene_coverage["torso"] == "exposed"


# ── 22. Explicit vs unknown scene coverage ────────────────────────────

class TestExplicitVsUnknown:
    def test_explicit_cover_recorded(self):
        _, meta = route_canon_refs("front view, dress shirt", _canon())
        assert meta.scene_coverage["torso"] == "covered_explicit"

    def test_unspecified_scene_is_covered_default(self):
        _, meta = route_canon_refs("front view", _canon())
        assert meta.scene_coverage["torso"] == "covered_default"

    def test_covered_default_never_suppresses(self):
        """The conservative default gates marks/crops but not card routing."""
        urls, meta = route_canon_refs("front view", _canon())
        assert meta.coverage_suppressed == []
        assert BODY_MAP in urls


# ── 27/28. Serialization compatibility ────────────────────────────────

class TestSchemaCompatibility:
    def test_old_json_without_coverage_parses(self):
        """(27/29) Pre-sprint canon JSON deserializes; no migration needed."""
        old = {
            "body_front_image_url": BODY_FRONT,
            "permanent_body_marks": [],
            "locked": True,
        }
        body = BodyCanonData(**old)
        assert body.card_coverage == {}
        assert body.locked is True

    def test_coverage_round_trips(self):
        """(28) New metadata survives model_dump → json → reload."""
        body = BodyCanonData(
            body_front_image_url=BODY_FRONT,
            card_coverage={"body_front": CardCoverage(coverage_type="bare_torso")},
        )
        reloaded = BodyCanonData(**json.loads(json.dumps(body.model_dump())))
        cov = reloaded.card_coverage["body_front"]
        assert cov.coverage_type == "bare_torso"
        assert set(cov.visible_skin_regions) == set(COVERAGE_PRESETS["bare_torso"])

    def test_presets_expand_and_custom_requires_regions(self):
        assert CardCoverage(coverage_type="fully_clothed").visible_skin_regions == []
        assert "forearms" in CardCoverage(coverage_type="short_sleeves").visible_skin_regions
        custom = CardCoverage(coverage_type="custom", visible_skin_regions=["legs"])
        assert custom.visible_skin_regions == ["legs"]
        with pytest.raises(ValueError):
            CardCoverage(coverage_type="custom")
        with pytest.raises(ValueError):
            CardCoverage(coverage_type="nonsense")
        with pytest.raises(ValueError):
            CardCoverage(coverage_type="custom", visible_skin_regions=["wings"])

    def test_unknown_slot_rejected(self):
        with pytest.raises(ValueError):
            BodyCanonData(card_coverage={"face_front": {"coverage_type": "bare_torso"}})


# ── 30. Diagnostics hygiene ───────────────────────────────────────────

class TestDiagnostics:
    def test_router_log_contains_no_urls_or_prompt(self, caplog):
        """(30) Coverage diagnostics carry slots and states only."""
        import logging
        secret_scene = SUIT_SCENE + " SECRETPHRASE"
        with caplog.at_level(logging.INFO, logger="app.services.scene_router"):
            route_canon_refs(secret_scene, _canon())
        lines = [r.getMessage() for r in caplog.records if "SCENE_ROUTER" in r.getMessage()]
        assert lines, "router must log its coverage decision"
        for line in lines:
            assert "SECRETPHRASE" not in line
            assert "https://" not in line
            assert "coverage_suppressed=" in line

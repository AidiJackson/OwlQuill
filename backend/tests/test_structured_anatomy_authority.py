"""Structured anatomy is the only authority — free text never widens it.

Proven defect this pins closed: Summer's butterfly piece is registered as
``left_upper_arm`` (shoulder to elbow, per her own body-map legend) but is
LABELLED "Butterfly floral sleeve". A substring search for "sleeve" over the
label and description widened its anatomy to include the forearm, so a
rolled-sleeve scene judged it exposed, described it as visible, routed its
crop — and the model rendered it on the only bare arm skin in frame.

The rule these tests enforce:

    STRUCTURED ANATOMY (body_region, side) = authority
    FREE TEXT (label, description)          = visual/design description only

Never the reverse. Free text still reaches the prompt as the DESIGN of a mark;
it must never change region, side, exposure, crop routing or occlusion.
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt
from app.services.scene_router import _mark_region_exposed, route_canon_refs

FACE_FRONT = "https://cdn.test/face_front.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"
CROP = "https://cdn.test/crop.png"

ROLLED = "Summer at her desk with shirt sleeves rolled up"
SHORT_SLEEVE = "Summer in a bar wearing a t-shirt"
SLEEVELESS = "Summer in a sleeveless top at the gym"
LONG_SLEEVE = "Summer at a formal dinner in a long-sleeved suit"


def _mark(region, side="centre", label="mark", description=None, crop=CROP):
    return PermanentBodyMark(
        label=label, type="tattoo", body_region=region, side=side,
        description=description or f"{label} design", detail_crop_url=crop,
    )


def _canon(marks):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 60
    canon.face_canon_json = json.dumps(
        FaceCanonData(face_front_image_url=FACE_FRONT).model_dump())
    canon.body_canon_json = json.dumps(BodyCanonData(
        body_front_image_url=BODY_FRONT, body_map_image_url=BODY_MAP,
        permanent_body_marks=marks,
    ).model_dump())
    canon.accessories_json = None
    return canon


# ── A. "sleeve" in a label grants no forearm authority ────────────────

class TestLabelDoesNotWidenAnatomy:
    SLEEVE_LABEL = "Butterfly floral sleeve"

    def test_upper_arm_stays_upper_arm_despite_sleeve_label(self):
        # Region decides. The label is irrelevant to exposure.
        assert _mark_region_exposed("left_upper_arm", ROLLED.lower()) is False

    def test_identical_region_behaves_identically_whatever_the_label(self):
        plain = _canon([_mark("left_upper_arm", "left", "Butterfly floral")])
        sleeve = _canon([_mark("left_upper_arm", "left", self.SLEEVE_LABEL)])
        _u1, m1 = route_canon_refs(ROLLED, plain)
        _u2, m2 = route_canon_refs(ROLLED, sleeve)
        assert m1.mark_crops == m2.mark_crops == 0

    def test_sleeve_labelled_upper_arm_crop_not_routed_when_rolled(self):
        _urls, meta = route_canon_refs(
            ROLLED, _canon([_mark("left_upper_arm", "left", self.SLEEVE_LABEL)]))
        assert meta.mark_crops == 0

    def test_sleeve_word_in_description_does_not_widen_either(self):
        mark = _mark("left_upper_arm", "left", "Butterfly floral",
                     description="a full sleeve of butterflies and wildflowers")
        assert _mark_region_exposed(mark.body_region, ROLLED.lower()) is False
        _urls, meta = route_canon_refs(ROLLED, _canon([mark]))
        assert meta.mark_crops == 0


# ── B. rolled sleeves + upper-arm-only mark → covered ─────────────────

class TestRolledSleevesCoverUpperArm:
    def test_crop_does_not_route(self):
        _urls, meta = route_canon_refs(
            ROLLED, _canon([_mark("left_upper_arm", "left", "Butterfly floral sleeve")]))
        assert meta.mark_crops == 0

    def test_compiler_does_not_describe_the_covered_mark(self):
        prompt = compile_canon_prompt(
            _canon([_mark("left_upper_arm", "left", "Butterfly floral sleeve")]), ROLLED)
        # No per-mark geometry line naming it as visible anatomy...
        assert "left upper arm:" not in prompt
        # ...and clothing truth is still asserted.
        assert "Permanent markings obey scene clothing" in prompt

    def test_short_sleeves_also_cover_the_upper_arm(self):
        _urls, meta = route_canon_refs(
            SHORT_SLEEVE, _canon([_mark("left_upper_arm", "left", "Butterfly floral sleeve")]))
        assert meta.mark_crops == 0


# ── C. sleeveless + upper-arm mark → visible ──────────────────────────

class TestSleevelessExposesUpperArm:
    def test_crop_routes(self):
        _urls, meta = route_canon_refs(
            SLEEVELESS, _canon([_mark("left_upper_arm", "left", "Butterfly floral")]))
        assert meta.mark_crops == 1
        assert meta.mark_crop_bindings[0].body_region == "left_upper_arm"

    def test_compiler_describes_it(self):
        prompt = compile_canon_prompt(
            _canon([_mark("left_upper_arm", "left", "Butterfly floral")]), SLEEVELESS)
        assert "left upper arm:" in prompt


# ── D. genuine structured full arm still spans both segments ──────────

class TestStructuredFullArm:
    def test_full_arm_exposed_by_rolled_sleeves(self):
        assert _mark_region_exposed("right_full_arm", ROLLED.lower()) is True

    def test_full_arm_exposed_when_bare(self):
        assert _mark_region_exposed("right_full_arm", SLEEVELESS.lower()) is True

    def test_full_arm_covered_by_long_sleeves(self):
        assert _mark_region_exposed("right_full_arm", LONG_SLEEVE.lower()) is False

    def test_full_arm_crop_routes_under_rolled_sleeves(self):
        _urls, meta = route_canon_refs(
            ROLLED, _canon([_mark("right_full_arm", "right", "Wolf sleeve")]))
        assert meta.mark_crops == 1

    def test_full_arm_spans_both_region_groups(self):
        from app.services.card_coverage import mark_region_groups
        assert mark_region_groups("right_full_arm") == frozenset({"upper_arms", "forearms"})
        assert mark_region_groups("right_upper_arm") == frozenset({"upper_arms"})


# ── E. no free-text word widens structured authority ──────────────────

class TestNoTextWidensAuthority:
    @pytest.mark.parametrize("word", ["sleeve", "hand", "chest", "back", "neck",
                                      "face", "knuckles", "full arm", "forearm"])
    def test_region_word_in_label_does_not_grant_that_region(self, word):
        from app.services.card_coverage import mark_location_authority
        body = BodyCanonData(permanent_body_marks=[
            PermanentBodyMark(label=f"design with {word} in the name", type="tattoo",
                              body_region="left_upper_arm", side="left",
                              description=f"a {word} motif"),
        ])
        # Authority comes from body_region alone.
        assert mark_location_authority(body) == frozenset({"upper_arms"})

    @pytest.mark.parametrize("word", ["sleeve", "hand", "chest", "neck"])
    def test_region_word_does_not_change_exposure(self, word):
        mark = _mark("left_upper_arm", "left", f"{word} piece",
                     description=f"{word} styled artwork")
        assert _mark_region_exposed(mark.body_region, ROLLED.lower()) is False


# ── F. side words in free text never override structured side ─────────

class TestTextNeverOverridesSide:
    def test_authority_ignores_side_words_in_text(self):
        from app.services.card_coverage import mark_location_authority
        body = BodyCanonData(permanent_body_marks=[
            PermanentBodyMark(label="Right arm piece", type="tattoo",
                              body_region="left_forearm", side="left",
                              description="right forearm artwork"),
        ])
        assert mark_location_authority(body) == frozenset({"forearms"})

    def test_binding_carries_structured_side_not_text_side(self):
        mark = PermanentBodyMark(
            label="Right arm ballerina", type="tattoo",
            body_region="right_forearm", side="right",
            description="left forearm ballerina", detail_crop_url=CROP)
        _urls, meta = route_canon_refs(ROLLED, _canon([mark]))
        assert meta.mark_crops == 1
        binding = meta.mark_crop_bindings[0]
        assert binding.side == "right"
        assert binding.body_region == "right_forearm"

    def test_compiler_region_phrase_comes_from_structured_region(self):
        mark = PermanentBodyMark(
            label="Left arm ballerina", type="tattoo",
            body_region="right_forearm", side="right",
            description="ballerina figure", detail_crop_url=CROP)
        prompt = compile_canon_prompt(_canon([mark]), ROLLED)
        assert "right forearm:" in prompt
        assert "left forearm:" not in prompt


# ── G. free text still reaches the prompt as DESIGN ───────────────────

class TestFreeTextRemainsTheDesign:
    def test_description_is_injected_as_design(self):
        mark = _mark("right_forearm", "right", "Ballerina",
                     description="black-and-white ballerina with ink splatter")
        prompt = compile_canon_prompt(_canon([mark]), ROLLED)
        assert "black-and-white ballerina with ink splatter" in prompt

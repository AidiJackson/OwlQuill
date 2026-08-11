"""The mark architecture must work for characters the code has never seen.

Every character in this file is INVENTED. Davies, Pan and Summer are regression
fixtures and live in their own suites; nothing here may depend on them, because
the product requirement is not "Summer works" — it is:

    a completely unseen character declares permanent markings through
    structured canon and gets correct image behaviour, with no production
    code knowing who that character is.

Each case therefore states canon + scene and asserts the user-visible outcome.
Where two characters have mirrored anatomy, the assertions are mirrored too: any
rule that passes for one and fails for the other is character-specific.

Case index (the brief's minimum set):
  A  left forearm only + rolled sleeves      H  contradictory layered clothing
  B  right full arm + short sleeves          I  contradictory free-text label
  C  upper arm only + long sleeves           J  oversized user scene
  D  hand tattoo + gloves                    K  unmappable mark region
  E  chest tattoo + shirt                    L  vague prompt
  F  markless character                      M  tattoo-emphasis prompt
  G  different marks on opposite arms        N  unrelated ink/marking language
  plus a many-mark character for the reference cap.
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import (
    _IDENTITY_PRIORITY,
    _PROMPT_CAP,
    _SAFETY_PREFIX,
    compile_canon_prompt,
)
from app.services.scene_router import MAX_PROVIDER_REFS, route_canon_refs

FACE = "https://cdn.test/face.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"


def _mark(region, side, label, description, crop=None, mtype="tattoo"):
    return PermanentBodyMark(
        label=label, type=mtype, body_region=region, side=side,
        description=description,
        detail_crop_url=crop or f"https://cdn.test/crop_{region}_{side}.png",
    )


def _canon(marks, *, character_id=900, marked_regions=None, body_map=True):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = character_id
    canon.face_canon_json = json.dumps(
        FaceCanonData(face_front_image_url=FACE).model_dump())
    canon.body_canon_json = json.dumps(BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP if body_map else None,
        permanent_body_marks=marks, marked_regions=marked_regions,
    ).model_dump())
    canon.accessories_json = None
    return canon


def _routed(scene, canon):
    urls, meta = route_canon_refs(scene, canon)
    return urls, meta


def _regions_routed(meta):
    return {(b.body_region, b.side) for b in meta.mark_crop_bindings}


# ── A. Forearm-only mark, clean upper arm, rolled sleeves ─────────────

class TestForearmOnlyMark:
    """Rowan: one left-forearm piece. His upper arm is clean skin."""

    def canon(self):
        return _canon([_mark("left_forearm", "left", "Lighthouse",
                             "a stone lighthouse in fine linework")])

    SCENE = "Rowan at his desk with shirt sleeves rolled up"

    def test_the_forearm_mark_is_visible_and_routed(self):
        _urls, meta = _routed(self.SCENE, self.canon())
        assert _regions_routed(meta) == {("left_forearm", "left")}

    def test_the_clean_upper_arm_is_never_claimed_as_marked(self):
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "upper arm" not in out
        assert "left forearm" in out

    def test_nothing_is_printed_on_the_covered_torso(self):
        out = compile_canon_prompt(self.canon(), self.SCENE)
        assert "never on it" in out or "not visible on or through" in out

    def test_no_opposite_side_migration(self):
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "right forearm" not in out


# ── B. True full-arm mark, short sleeves ──────────────────────────────

class TestFullArmMarkUnderShortSleeves:
    """Nadia: a genuine right full-arm sleeve. A t-shirt bares her forearms."""

    def canon(self):
        return _canon([_mark("right_full_arm", "right", "Koi sleeve",
                             "koi and waves in full colour")])

    SCENE = "Nadia in a t-shirt at the market"

    def test_the_exposed_portion_routes_with_the_correct_side(self):
        _urls, meta = _routed(self.SCENE, self.canon())
        assert _regions_routed(meta) == {("right_full_arm", "right")}

    def test_the_covered_portion_stays_under_the_garment(self):
        out = compile_canon_prompt(self.canon(), self.SCENE)
        assert "Hidden markings remain hidden" in out or "under the fabric" in out

    def test_no_left_arm_migration(self):
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "left arm" not in out
        assert "right arm" in out

    def test_long_sleeves_hide_it_entirely(self):
        scene = "Nadia in a long-sleeved sweater at the market"
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene).lower()
        assert "koi and waves" not in out


# ── C. Upper-arm-only mark, long sleeves ──────────────────────────────

class TestUpperArmMarkUnderLongSleeves:
    """Idris: a small left upper-arm anchor, fully covered here."""

    def canon(self):
        return _canon([_mark("left_upper_arm", "left", "Anchor",
                             "a small black anchor")])

    SCENE = "Idris in a long-sleeved shirt at the office"

    def test_nothing_is_visible_and_nothing_routes(self):
        _urls, meta = _routed(self.SCENE, self.canon())
        assert meta.mark_crops == 0

    def test_the_design_is_never_named(self):
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "anchor" not in out

    def test_asking_for_tattoos_does_not_uncover_it(self):
        scene = "Idris in a long-sleeved shirt at the office, show his tattoos"
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene).lower()
        assert "anchor" not in out
        assert "under the fabric" in out or "not visible on or through" in out

    def test_no_migration_to_the_forearm_or_hand(self):
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "forearm" not in out
        # The hand is clean skin for this character and must be asserted so.
        assert "hands" in out


# ── D. Hand mark + gloves ─────────────────────────────────────────────

class TestHandMarkAndGloves:
    """Vesna: knuckle script. Hands are visible unless something covers them."""

    def canon(self):
        return _canon([_mark("right_hand", "right", "Knuckle script",
                             "letters across the knuckles")])

    def test_bare_hands_route_the_mark(self):
        _urls, meta = _routed("Vesna at a cafe", self.canon())
        assert _regions_routed(meta) == {("right_hand", "right")}

    def test_gloves_suppress_it_completely(self):
        _urls, meta = _routed("Vesna in leather gloves on a motorcycle",
                              self.canon())
        assert meta.mark_crops == 0

    def test_gloves_do_not_print_the_mark_on_the_glove(self):
        out = compile_canon_prompt(
            self.canon(), "Vesna in leather gloves on a motorcycle").lower()
        assert "letters across the knuckles" not in out


# ── E. Chest mark + shirt ─────────────────────────────────────────────

class TestChestMarkUnderAShirt:
    """Tomas: a sternum compass. The Davies print-through case, generically."""

    def canon(self):
        return _canon([_mark("chest", "centre", "Compass rose",
                             "a large compass across the sternum")])

    SCENE = "Tomas in a buttoned dress shirt at dinner"

    def test_nothing_routes_and_the_design_is_never_named(self):
        _urls, meta = _routed(self.SCENE, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), self.SCENE).lower()
        assert "compass" not in out

    def test_the_occlusion_invariant_is_stated(self):
        out = compile_canon_prompt(self.canon(), self.SCENE)
        assert "under the fabric" in out or "not visible on or through" in out

    @pytest.mark.parametrize("emphasis", [
        "tattoos visible", "any tattoos that should be visible are visible",
        "show his tattoos", "his ink on display",
    ])
    def test_emphasis_cannot_open_the_shirt(self, emphasis):
        """The prompt-attack case: asking for visible tattoos must not reveal,
        name or print a mark the scene covers."""
        scene = f"{self.SCENE}, {emphasis}"
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene).lower()
        assert "compass" not in out
        assert "never printed" in out or "never on it" in out or "not visible on" in out


# ── F. Markless character ─────────────────────────────────────────────

class TestMarklessCharacter:
    """Elin declares no markings at all. Nothing may invent any."""

    def canon(self):
        return _canon([], marked_regions=[])

    @pytest.mark.parametrize("scene", [
        "Elin in her office",
        "Elin in her office - any tattoos that should be visible are visible",
        "Elin in a sleeveless top at the beach",
        "Elin in a sports bra under a heavy winter parka",
    ])
    def test_no_marks_are_ever_asserted(self, scene):
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene).lower()
        assert "canonical anatomy is fixed" not in out
        assert "belongs on the" not in out

    def test_clean_skin_truth_is_still_asserted(self):
        out = compile_canon_prompt(self.canon(), "Elin in a sleeveless top")
        assert "Clean-skin truth" in out

    def test_a_long_scene_keeps_safety_and_identity(self):
        """This was a general image-system regression, not a tattoo one: the
        old fitting policy could emit the scene alone for ANY character."""
        scene = "Elin in a vast rain-lit atrium " + "with brass filigree " * 140
        out = compile_canon_prompt(self.canon(), scene)
        assert out.startswith(_SAFETY_PREFIX)
        assert _IDENTITY_PRIORITY in out
        assert len(out) <= _PROMPT_CAP


# ── G. Different marks on opposite arms ───────────────────────────────

MIRROR_A = [("left_full_arm", "left", "Ivy piece", "ivy vines and moths"),
            ("right_forearm", "right", "Sparrow", "a sparrow mid-flight")]
MIRROR_B = [("right_full_arm", "right", "Ivy piece", "ivy vines and moths"),
            ("left_forearm", "left", "Sparrow", "a sparrow mid-flight")]


class TestOppositeLimbMarks:
    """Kofi and his mirror image. Anything true of one must be true of the other
    with the sides swapped — otherwise the rule knows a character, not anatomy.
    """

    @pytest.mark.parametrize("spec,full,fore", [
        (MIRROR_A, "left", "right"),
        (MIRROR_B, "right", "left"),
    ])
    def test_each_design_is_bound_to_its_own_side(self, spec, full, fore):
        canon = _canon([_mark(*m) for m in spec])
        out = compile_canon_prompt(
            canon, "Kofi in his office, show his tattoos")
        ivy = out.index("Ivy piece")
        sparrow = out.index("Sparrow")
        assert f"{full} arm" in out[ivy:sparrow]
        assert f"{fore} forearm" in out[sparrow:]
        assert f"never the {fore} arm" in out[ivy:sparrow]
        assert f"never the {full} arm" in out[sparrow:]

    @pytest.mark.parametrize("spec,full,fore", [
        (MIRROR_A, "left", "right"),
        (MIRROR_B, "right", "left"),
    ])
    def test_both_crops_route_with_correct_sides(self, spec, full, fore):
        canon = _canon([_mark(*m) for m in spec])
        _urls, meta = _routed("Kofi in his office, show his tattoos", canon)
        assert meta.mark_crops == 2
        assert _regions_routed(meta) == {
            (f"{full}_full_arm", full), (f"{fore}_forearm", fore)}

    def test_rolled_sleeves_expose_both_and_still_keep_sides_apart(self):
        canon = _canon([_mark(*m) for m in MIRROR_A])
        _urls, meta = _routed("Kofi at his desk with sleeves rolled up", canon)
        assert _regions_routed(meta) == {
            ("left_full_arm", "left"), ("right_forearm", "right")}


# ── H. Contradictory layered clothing ─────────────────────────────────

class TestContradictoryLayers:
    """The blocker this phase closed: credible evidence both ways.

    A definitionally sleeveless garment used to beat any cover word, so "a
    sports bra under a heavy winter parka" asserted bare arms, routed a crop and
    invited ink onto a coat sleeve. Neither reading may win now.
    """

    def canon(self):
        return _canon([_mark(*m) for m in MIRROR_A])

    @pytest.mark.parametrize("scene", [
        "Kofi in a sports bra under a heavy winter parka",
        "Kofi in a bralette under a long-sleeved cardigan",
        "Kofi in a singlet vest under a hoodie",
        "Kofi in a long-sleeved vest top",
        "Kofi in a tank top under a wool overcoat",
        "Kofi in a jacket over a tank top",
        # Found by adversarial probing after the fix: three layers, and a
        # wrapped garment whose sleeves the cover vocabulary had not learned.
        "Kofi in a tank top, a cardigan and a parka",
        "Kofi in a bikini top and a kimono",
        "Kofi in a swimsuit under a long coat",
        "Kofi shirtless under an open long-sleeved shirt",
    ])
    def test_no_crop_routes_and_no_skin_is_claimed_bare(self, scene):
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene).lower()
        assert "ivy vines" not in out
        assert "a sparrow mid-flight" not in out
        assert "permanently inked into skin" not in out

    @pytest.mark.parametrize("scene", [
        "Kofi in a sports bra under a heavy winter parka, show his tattoos",
        "Kofi in a jacket over a tank top, any tattoos that should be visible are visible",
    ])
    def test_emphasis_cannot_resolve_the_contradiction_either(self, scene):
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0

    def test_the_conditional_occlusion_invariant_still_protects_the_arms(self):
        """Unresolved is not unprotected: the ink-on-fabric rule must still be
        stated, because the scene may well render the arms covered."""
        out = compile_canon_prompt(
            self.canon(), "Kofi in a sports bra under a heavy winter parka")
        assert ("Wherever clothing covers" in out) or ("Opaque clothing covers" in out)

    def test_an_unambiguous_sleeveless_scene_is_unaffected(self):
        _urls, meta = _routed("Kofi in a sports bra at the gym", self.canon())
        assert meta.mark_crops == 2


# ── I. Contradictory free-text label / description ────────────────────

class TestFreeTextNeverBecomesAnatomy:
    """Labels and descriptions are free text. The schema's own example label is
    'Left arm gothic script sleeve', so creators DO put anatomy in them.

    body_region is the only anatomy the provider may read. A contradictory label
    must not reach the prompt beside it.
    """

    HOSTILE = [
        ("left_forearm", "left", "Right shoulder eagle",
         "an eagle across the right shoulder blade"),
        ("right_forearm", "right", "Left hand roses", "roses over the left hand"),
        ("left_upper_arm", "left", "Full sleeve dragon",
         "a dragon running the whole arm from shoulder to wrist"),
        ("chest", "centre", "Back piece phoenix", "a phoenix across the back"),
    ]

    @pytest.mark.parametrize("region,side,label,description", HOSTILE)
    def test_the_prompt_carries_one_anatomy_only(self, region, side, label,
                                                 description):
        canon = _canon([_mark(region, side, label, description)])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        # The structured region is stated...
        from app.services.canon_compiler import _region_phrase
        assert _region_phrase(region) in out
        # ...and the contradictory free text is not.
        assert label not in out
        assert description not in out

    @pytest.mark.parametrize("region,label,description", [
        ("left_forearm", "Right arm rose", "a rose in black linework"),
        ("right_forearm", "Left arm rose", "a rose in black linework"),
        ("right_upper_arm", "left side crest", "a family crest"),
    ])
    def test_a_side_qualified_limb_word_is_caught_too(self, region, label,
                                                      description):
        """"Right arm rose" on a left_forearm mark contradicts the region even
        though "arm" alone claims no specific segment."""
        canon = _canon([_mark(region, region.split("_")[0], label, description)])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert label not in out

    @pytest.mark.parametrize("label,description", [
        # Words that merely CONTAIN an anatomy term must not trip the check —
        # "leg" in "elegant", "back" in "backlit", "arms" in a pose.
        ("Elegant rose", "elegant fine linework in black"),
        ("Backlit phoenix", "a phoenix in backlit gold tones"),
        ("Legacy anchor", "a legacy anchor design in faded ink"),
        ("Neckerchief knot", "a knotted cord motif"),
    ])
    def test_words_merely_containing_anatomy_terms_are_not_contradictions(
            self, label, description):
        canon = _canon([_mark("left_forearm", "left", label, description)])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert label in out, "consistent design text was thrown away"

    def test_a_consistent_label_is_still_used(self):
        """The rule is 'no contradiction', not 'never use the label' — two
        designs must stay distinguishable."""
        canon = _canon([_mark("left_full_arm", "left", "Butterfly floral sleeve",
                              "butterflies and wildflowers in fine line work")])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert "Butterfly floral sleeve" in out

    def test_a_sideless_region_rejects_a_label_that_asserts_a_side(self):
        canon = _canon([_mark("chest", "centre", "Left chest swallow",
                              "a swallow on the chest")])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert "Left chest swallow" not in out
        assert "chest" in out

    def test_routing_was_never_affected_by_the_label(self):
        """Routing already derived from structured fields; prove it stayed that
        way while the prose was being fixed."""
        canon = _canon([_mark("left_forearm", "left", "Right shoulder eagle",
                              "an eagle across the right shoulder blade")])
        _urls, meta = _routed("Mira at her desk with sleeves rolled up", canon)
        assert _regions_routed(meta) == {("left_forearm", "left")}


# ── side field vs region ──────────────────────────────────────────────

class TestStructuredRegionOutranksTheSideField:
    """``side`` is stored independently of ``body_region`` and nothing validates
    them against each other. The region is authoritative."""

    def test_a_contradicting_side_field_never_produces_contradictory_prose(self):
        canon = _canon([_mark("right_forearm", "left", "Ballerina",
                              "a ballerina in ink-splatter shading")])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert "right forearm" in out
        assert "never the right arm" not in out
        assert "never the left arm" in out

    def test_a_sideless_side_field_does_not_lose_side_protection(self):
        """``side="centre"`` on a side-named region used to erase the exclusion
        entirely — the protection the clause exists for."""
        canon = _canon([_mark("left_forearm", "centre", "Anchor", "a small anchor")])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert "never the right arm" in out

    def test_a_genuinely_sideless_region_claims_no_mirror(self):
        canon = _canon([_mark("chest", "centre", "Compass", "a compass rose")])
        out = compile_canon_prompt(canon, "Mira in her office, show her tattoos")
        assert "never mirrored or moved across the body" in out


# ── J. Oversized user scene ───────────────────────────────────────────

class TestOversizedScene:
    """Priority fitting. The scene is trimmed; grounding is not evicted."""

    def canon(self):
        return _canon([_mark(*m) for m in MIRROR_A])

    def many_marks(self, n=14):
        regions = ["chest", "back", "neck", "left_upper_arm", "right_upper_arm",
                   "left_forearm", "right_forearm", "abdomen", "ribs",
                   "left_thigh", "right_thigh", "left_calf", "right_calf",
                   "upper_back"]
        return _canon([
            _mark(regions[i % len(regions)], "centre", f"Mark {i}", "y" * 400)
            for i in range(n)
        ])

    HUGE = ("Kofi stands in a vast rain-lit atrium, "
            + "with intricate brass filigree overhead " * 90
            + "any tattoos that should be visible are visible")

    @pytest.mark.parametrize("canon_name", ["canon", "many_marks"])
    def test_safety_and_identity_always_survive(self, canon_name):
        canon = getattr(self, canon_name)()
        out = compile_canon_prompt(canon, self.HUGE)
        assert out.startswith(_SAFETY_PREFIX)
        assert _IDENTITY_PRIORITY in out

    @pytest.mark.parametrize("canon_name", ["canon", "many_marks"])
    def test_the_cap_is_respected(self, canon_name):
        canon = getattr(self, canon_name)()
        assert len(compile_canon_prompt(canon, self.HUGE)) <= _PROMPT_CAP

    @pytest.mark.parametrize("canon_name", ["canon", "many_marks"])
    def test_the_scene_is_still_represented(self, canon_name):
        canon = getattr(self, canon_name)()
        out = compile_canon_prompt(canon, self.HUGE)
        assert "vast rain-lit atrium" in out

    def test_structural_invariants_survive_a_huge_scene(self):
        out = compile_canon_prompt(self.canon(), self.HUGE)
        assert "Clean-skin truth" in out
        assert ("Wherever clothing covers" in out) or ("Opaque clothing covers" in out)

    def test_design_detail_is_what_gets_sacrificed_first(self):
        """A 14-mark character overflows on descriptions alone. The descriptions
        are the expendable content — not the invariants, not the scene."""
        out = compile_canon_prompt(self.many_marks(), self.HUGE)
        assert "y" * 400 not in out
        assert "Clean-skin truth" in out
        assert "vast rain-lit atrium" in out

    def test_a_scene_longer_than_the_whole_cap_still_keeps_grounding(self):
        scene = "Kofi " + "in an endless marble corridor " * 200
        assert len(scene) > _PROMPT_CAP
        out = compile_canon_prompt(self.canon(), scene)
        assert out.startswith(_SAFETY_PREFIX)
        assert _IDENTITY_PRIORITY in out
        assert "marble corridor" in out
        assert len(out) <= _PROMPT_CAP


# ── K. Unmappable mark region ─────────────────────────────────────────

class TestUnmappableRegion:
    """A creator may type a region the coverage vocabulary cannot map. Unknown
    anatomy must fail conservatively, never confidently."""

    def canon(self):
        return _canon([_mark("tailbone", "centre", "Serpent",
                             "a long serpent along the tailbone")])

    def test_no_crop_routes_for_an_unmappable_region(self):
        _urls, meta = _routed("Kofi in his office, show his tattoos", self.canon())
        assert meta.mark_crops == 0

    def test_the_design_is_not_named_in_a_dressed_scene(self):
        """The 'never name a hidden design' rule protected mappable regions
        only; an unmappable one was named in a fully covered scene."""
        out = compile_canon_prompt(
            self.canon(),
            "Kofi at a formal dinner in a three-piece suit and trousers, "
            "show his tattoos").lower()
        assert "serpent" not in out

    def test_it_is_still_named_when_nothing_is_covered(self):
        out = compile_canon_prompt(
            self.canon(), "Kofi in his office, show his tattoos")
        assert "tailbone" in out

    def test_no_clean_skin_claims_are_made_around_it(self):
        """mark_location_authority vetoes on unmappable regions, so no region
        may be asserted clean — a clean-skin claim could contradict the mark."""
        out = compile_canon_prompt(self.canon(), "Kofi in his office")
        assert "Clean-skin truth" not in out


# ── L / M / N. Vague, emphasis, and unrelated language ────────────────

class TestScenePhrasing:
    def canon(self):
        return _canon([_mark(*m) for m in MIRROR_A])

    def test_L_a_vague_prompt_routes_nothing_and_stays_quiet(self):
        _urls, meta = _routed("Kofi in his office", self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), "Kofi in his office")
        assert "belongs on the" not in out
        assert out.rstrip().endswith("Kofi in his office")

    def test_M_an_emphasis_prompt_binds_anatomy_without_claiming_bare_skin(self):
        scene = "Kofi in his office, any tattoos that should be visible are visible"
        out = compile_canon_prompt(self.canon(), scene)
        assert "belongs on the left arm" in out
        assert "only where this scene's own clothing leaves that skin bare" in out
        for overclaim in ("arms are bare", "skin is bare", "shirtless"):
            assert overclaim not in out.lower()

    @pytest.mark.parametrize("scene", [
        "Kofi writing with an ink pen at his desk",
        "Kofi marking papers in his study",
        "an ink drawing on the wall behind Kofi",
        "Kofi walking past the scars of the old city wall",
        "Kofi in his office, no tattoos visible",
        "Kofi visiting a tattoo parlour with a friend",
    ])
    def test_N_unrelated_or_negated_language_is_not_a_request(self, scene):
        _urls, meta = _routed(scene, self.canon())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(self.canon(), scene)
        assert "belongs on the" not in out

    @pytest.mark.parametrize("scene", [
        "Kofi, no jacket, show his tattoos",
        "Kofi with no hat, his tattoos on display",
        "Kofi in his office with no coat, any tattoos that should be visible are visible",
    ])
    def test_an_unrelated_negation_elsewhere_does_not_cancel_the_request(self, scene):
        """Found by adversarial probing: the negation guard's window ran across
        clause boundaries, so the "no" in "no jacket" cancelled a real request.

        Asserted on the trigger itself. Whether anatomy is then NAMED depends on
        the garment reading, and "no jacket" / "no coat" still read as covering
        garments — a separate, conservative limitation (it hides marks, never
        prints them) recorded in the changelog.
        """
        from app.services.canon_compiler import scene_requests_marks
        assert scene_requests_marks(scene) is True

    def test_a_request_beside_an_unrelated_negation_still_binds_anatomy(self):
        out = compile_canon_prompt(
            self.canon(), "Kofi with no hat, his tattoos on display")
        assert "belongs on the" in out

    def test_a_markless_character_ignores_mark_language_entirely(self):
        canon = _canon([], marked_regions=[])
        for scene in ("Kofi writing with an ink pen",
                      "Kofi in a tattoo parlour, show his tattoos"):
            _urls, meta = _routed(scene, canon)
            assert meta.mark_crops == 0


# ── Reference cap with many marks ─────────────────────────────────────

class TestReferenceCapWithManyMarks:
    """A heavily marked character must not starve the face or body anchors."""

    def canon(self):
        return _canon([
            _mark("left_full_arm", "left", "Ivy", "ivy vines"),
            _mark("right_forearm", "right", "Sparrow", "a sparrow"),
            _mark("left_hand", "left", "Ring band", "a band around one finger"),
            _mark("chest", "centre", "Compass", "a compass rose"),
            _mark("neck", "centre", "Star", "a small star"),
            _mark("right_upper_arm", "right", "Moth", "a moth"),
        ])

    @pytest.mark.parametrize("scene", [
        "Kofi in a sleeveless top at the beach",
        "Kofi shirtless by the pool, tattoos visible",
        "Kofi at his desk with sleeves rolled up",
        "Kofi in his office, show his tattoos",
    ])
    def test_the_cap_holds_and_the_face_still_leads(self, scene):
        urls, meta = _routed(scene, self.canon())
        assert len(urls) <= MAX_PROVIDER_REFS
        assert len(urls) == len(set(urls)), "a reference was routed twice"
        if meta.route_slots:
            assert meta.route_slots[0].startswith("face")

    @pytest.mark.parametrize("scene", [
        "Kofi in a sleeveless top at the beach",
        "Kofi in his office, show his tattoos",
    ])
    def test_crops_never_lead_and_always_have_a_body_anchor(self, scene):
        _urls, meta = _routed(scene, self.canon())
        if meta.mark_crops:
            assert meta.route_slots[0] != "mark_crop"
            assert any(s.startswith("body") for s in meta.route_slots)

    def test_crops_are_capped_so_body_truth_survives(self):
        _urls, meta = _routed("Kofi shirtless by the pool", self.canon())
        assert meta.mark_crops <= 2
        assert len(meta.mark_crop_bindings) == meta.mark_crops

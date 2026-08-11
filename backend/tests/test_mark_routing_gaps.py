"""The three mark-routing gaps closed after the Summer canon correction.

Each class states a PRODUCT invariant and the observed failure that motivated
it. None of them assert "the code currently does X" — where an assertion would
only restate today's implementation it is written as the user-visible rule
instead (e.g. "a sports bra bares the arms", not "sports bra is in set S").

  A  Sleeveless garment vocabulary
     A sports-bra gym scene produced Summer with a bare right forearm: the
     phrase carried no exposure signal, so no mark was judged visible, no crop
     routed and no mark named. The rule: ordinary words for garments that
     genuinely bare the arms must bare the arms — and only the arms.

  B  Explicit mark request under unspecified clothing
     "Summer in her office - any tattoos that should be visible are visible"
     resolved every region to covered_default, emitted no per-mark anatomy at
     all, and the provider swapped both designs across arms. The rule: an
     explicit request for markings must never cost the compiler its knowledge
     of WHERE each marking belongs — while never asserting that covered skin
     is visible.

  C  Segment-blind crops (documented, not fixed — see the class docstring)
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt, scene_requests_marks
from app.services.card_coverage import scene_region_states
from app.services.scene_router import arm_exposure_states, route_canon_refs

FACE_FRONT = "https://cdn.test/face_front.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"
CROP = "https://cdn.test/crop.png"

# Summer's real anatomy, used because these defects were found on it.
BUTTERFLY = dict(region="left_full_arm", side="left", label="Butterfly floral sleeve",
                 description="butterflies and wildflowers in fine black line work")
BALLERINA = dict(region="right_forearm", side="right", label="Ballerina tattoo",
                 description="black-and-white ballerina with ink-splatter shading")

EMPHASIS = "Summer in her office - any tattoos that should be visible are visible"
PLAIN_OFFICE = "Summer in her office"


def _mark(region, side="centre", label="mark", description=None, crop=CROP):
    return PermanentBodyMark(
        label=label, type="tattoo", body_region=region, side=side,
        description=description or f"{label} design", detail_crop_url=crop,
    )


def _canon(marks, *, marked_regions=None):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 60
    canon.face_canon_json = json.dumps(
        FaceCanonData(face_front_image_url=FACE_FRONT).model_dump())
    canon.body_canon_json = json.dumps(BodyCanonData(
        body_front_image_url=BODY_FRONT, body_map_image_url=BODY_MAP,
        permanent_body_marks=marks, marked_regions=marked_regions,
    ).model_dump())
    canon.accessories_json = None
    return canon


def _summer():
    return _canon([_mark(**{**BUTTERFLY, "region": BUTTERFLY["region"]}),
                   _mark(**BALLERINA)])


def _mark_kwargs(spec):
    return dict(region=spec["region"], side=spec["side"], label=spec["label"],
                description=spec["description"])


# ── A. Garments that bare the arms ────────────────────────────────────

# Garments that are sleeveless BY DEFINITION. Naming one is an unambiguous
# statement about the arms, in the same way "tank top" always has been.
NEWLY_BARE_ARMS = [
    "Summer in a sports bra and leggings at the gym",
    "Summer in a bralette and high-waisted jeans",
    "Summer in a vest top on the balcony",
    "Summer in a strappy top at dinner",
    "Summer in a dress with spaghetti straps",
    "Summer in a halter neck dress",
    "Summer in a halterneck top",
    "Summer in a singlet at the gym",
]

# Already understood before this work; listed so a regression is caught here.
# These two also bare the NECK, which is long-standing and deliberate — a tank
# top does expose the throat. The new vocabulary above makes no neck claim.
PREEXISTING_BARE_ARMS = [
    "Summer in a sleeveless top",
    "Summer in a tank top",
]

DEFINITELY_BARE_ARMS = NEWLY_BARE_ARMS + PREEXISTING_BARE_ARMS

# Garments that USUALLY bare the arms but are not a statement about sleeves:
# a crop top is about length, a sundress about cut. Bare arms unless the scene
# says otherwise.
USUALLY_BARE_ARMS = [
    "Summer in a crop top and jeans",
    "Summer in a sundress in the garden",
]

# The same garments with sleeves named. The conditional tier must yield.
SLEEVED_VERSIONS = [
    "Summer in a long-sleeved crop top and jeans",
    "Summer in a long-sleeved sundress in the garden",
]

# Scenes that must NOT read as bare arms. The first two are the previously
# fixed "vest" false positive; the third proves the new "strappy top" entry
# cannot be reached by unrelated strappy things.
STILL_COVERED = [
    "Summer at a formal dinner in a long-sleeved suit and tie",
    "Summer in a three-piece suit with a suit vest",
    "Summer wearing strappy sandals and a long-sleeved shirt",
    "Summer in a wool coat and a scarf",
    "Summer in her office",
    # "halter" is no longer a bare noun — a horse is led by its halter.
    "Summer leading a horse by its halter across the field",
]

# Scenes naming a definitionally sleeveless garment AND an arm-covering one.
# Credible evidence both ways: neither reading may win. See the invariant
# correction in test_contradictory_layers_resolve_to_ambiguous.
CONTRADICTORY_LAYERS = [
    "Summer in a sports bra under a heavy winter parka",
    "Summer in a bralette under a long-sleeved cardigan",
    "Summer in a singlet vest under a hoodie",
    "Summer in a long-sleeved vest top",
    "Summer in a jacket over a tank top",
    "Summer in a tank top and a wool overcoat",
]


class TestGarmentsThatBareTheArms:
    @pytest.mark.parametrize("prompt", DEFINITELY_BARE_ARMS + USUALLY_BARE_ARMS)
    def test_both_arm_segments_are_bare(self, prompt):
        upper, fore = arm_exposure_states(prompt.lower())
        assert upper == "exposed", prompt
        assert fore == "exposed", prompt

    @pytest.mark.parametrize("prompt", NEWLY_BARE_ARMS + USUALLY_BARE_ARMS)
    def test_new_vocabulary_bares_the_arms_and_nothing_else(self, prompt):
        """A sleeveless top says nothing about the chest, legs or throat.

        Over-claiming is how a covered region gets a marking painted onto it,
        so this vocabulary stays confined to the arms. Under-claiming is safe:
        an unclaimed region is simply never asserted bare.
        """
        states = scene_region_states(prompt.lower())
        assert states["upper_arms"] == "exposed"
        assert states["forearms"] == "exposed"
        for region in ("torso", "back", "neck", "legs"):
            assert states[region] != "exposed", f"{prompt} wrongly bared {region}"

    @pytest.mark.parametrize("prompt", PREEXISTING_BARE_ARMS)
    def test_preexisting_vocabulary_keeps_its_semantics(self, prompt):
        """Tank top / sleeveless bare the arms AND the throat, as they always
        have. The torso and legs stay unclaimed."""
        states = scene_region_states(prompt.lower())
        assert states["upper_arms"] == "exposed"
        assert states["forearms"] == "exposed"
        assert states["neck"] == "exposed"
        for region in ("torso", "back", "legs"):
            assert states[region] != "exposed", f"{prompt} wrongly bared {region}"

    @pytest.mark.parametrize("prompt", SLEEVED_VERSIONS)
    def test_named_sleeves_beat_a_usually_bare_garment(self, prompt):
        upper, fore = arm_exposure_states(prompt.lower())
        assert upper == "covered_explicit", prompt
        assert fore == "covered_explicit", prompt

    @pytest.mark.parametrize("prompt", STILL_COVERED)
    def test_covered_scenes_stay_covered(self, prompt):
        upper, _fore = arm_exposure_states(prompt.lower())
        assert upper != "exposed", prompt

    @pytest.mark.parametrize("prompt", CONTRADICTORY_LAYERS)
    def test_contradictory_layers_resolve_to_ambiguous(self, prompt):
        """INVARIANT CORRECTION. This class of scene previously asserted BARE
        ARMS, and that requirement has been demonstrated unsafe.

        The old rule was "a definitionally sleeveless garment outranks any cover
        word", justified by "jacket over a tank top". It has no notion of layer
        order, so the inverse phrasing resolved identically: "a sports bra under
        a heavy winter parka" read as bare arms, routed a mark crop, asserted
        bare skin, and invited ink onto a parka sleeve — every failure mode this
        work exists to prevent.

        Credible evidence both ways now means NEITHER wins. Ambiguous routes no
        crop, asserts no bare skin, and asserts no explicit coverage either. The
        cost is under-rendering a genuinely bare arm in a contradictory
        sentence; the alternative is printing a tattoo on a coat.
        """
        upper, fore = arm_exposure_states(prompt.lower())
        assert upper == "ambiguous", prompt
        assert fore == "ambiguous", prompt

    def test_ambiguous_arms_route_no_crop_and_assert_no_bare_skin(self):
        prompt = "Summer in a sports bra under a heavy winter parka"
        _urls, meta = route_canon_refs(prompt, _summer())
        assert meta.mark_crops == 0
        out = compile_canon_prompt(_summer(), prompt).lower()
        for overclaim in ("butterflies and wildflowers", "black-and-white ballerina",
                          "permanently inked into skin"):
            assert overclaim not in out, overclaim

    def test_ambiguous_arms_do_not_claim_explicit_coverage(self):
        """Unresolved is not the same as covered: asserting coverage on a scene
        that never resolved it would suppress bare cards a genuinely sleeveless
        scene needs."""
        states = scene_region_states("summer in a sports bra under a heavy winter parka")
        assert states["upper_arms"] == "ambiguous"
        assert states["forearms"] == "ambiguous"

    def test_rolled_sleeves_are_not_a_contradiction(self):
        """A long-sleeved shirt with the sleeves rolled up is not two
        conflicting claims — it is how a forearm becomes bare. The
        contradiction rule must not swallow it."""
        upper, fore = arm_exposure_states(
            "summer in a long-sleeved shirt with the sleeves rolled up")
        assert upper == "covered_explicit"
        assert fore == "exposed"

    def test_sports_bra_scene_routes_both_marks(self):
        """The exact failing scene: both marks must reach the provider."""
        _urls, meta = route_canon_refs(
            "Summer in a sports bra and leggings at the gym", _summer())
        assert meta.mark_crops == 2
        assert {b.body_region for b in meta.mark_crop_bindings} == {
            "left_full_arm", "right_forearm"}
        assert {b.side for b in meta.mark_crop_bindings} == {"left", "right"}

    def test_router_and_coverage_engine_never_disagree(self):
        """One vocabulary. Two engines reading it apart is how drift starts."""
        for prompt in (DEFINITELY_BARE_ARMS + USUALLY_BARE_ARMS
                       + SLEEVED_VERSIONS + STILL_COVERED
                       + CONTRADICTORY_LAYERS):
            upper, fore = arm_exposure_states(prompt.lower())
            states = scene_region_states(prompt.lower())
            assert states["upper_arms"] == upper, prompt
            assert states["forearms"] == fore, prompt


# ── B. Explicit mark request, clothing unspecified ────────────────────

class TestExplicitMarkRequest:
    def test_each_mark_is_bound_to_its_own_side_and_region(self):
        """Each design must be named AND tied to its own anatomy.

        Naming the regions alone cannot prevent the observed failure: with two
        marks and two arms, "left arm, right forearm" is satisfied by the swap.
        """
        out = compile_canon_prompt(_summer(), EMPHASIS).lower()
        left_at = out.index(BUTTERFLY["label"].lower())
        right_at = out.index(BALLERINA["label"].lower())
        assert "left arm" in out[left_at:right_at]
        assert "right forearm" in out[right_at:]

    def test_the_opposite_arm_is_explicitly_excluded(self):
        """The observed failure was a swap, not an omission."""
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "never the right arm" in out
        assert "never the left arm" in out

    def test_visibility_is_never_asserted(self):
        """Knowing where a mark lives is not a claim that it is on show.

        The scene named no garment, so the compiler must not decide it is bare.
        """
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "only where this scene's own clothing leaves that skin bare" in out
        canon_text = out.replace(EMPHASIS, "").lower()
        for overclaim in (
            "markings are visible", "tattoos are visible", "marking is visible",
            "arms are bare", "skin is bare", "bare arms", "shirtless",
            "sleeveless", "wearing a",
        ):
            assert overclaim not in canon_text, f"compiler asserted {overclaim!r}"

    def test_marks_may_not_be_printed_on_clothing(self):
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "never printed, traced or echoed onto the garment" in out

    def test_marks_may_not_migrate_to_whatever_skin_is_visible(self):
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "never moved onto skin that is visible instead" in out

    def test_no_invented_marks(self):
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "never add a marking that is not listed above" in out

    def test_scene_without_mark_language_is_unchanged(self):
        """Byte-for-byte: unrelated prompts must not pay for this fix."""
        canon = _summer()
        out = compile_canon_prompt(canon, PLAIN_OFFICE)
        assert "canonical anatomy is fixed" not in out
        assert out.endswith(PLAIN_OFFICE)

    def test_asking_does_not_uncover_an_explicitly_covered_mark(self):
        """Requesting tattoos must not name — or reveal — a hidden design.

        Naming a covered design is what made a provider cut a garment open.
        """
        covered = ("Summer at a formal dinner in a long-sleeved suit and tie, "
                   "show her tattoos")
        out = compile_canon_prompt(_summer(), covered)
        assert "butterflies and wildflowers" not in out.lower()
        assert "black-and-white ballerina" not in out.lower()
        assert "stay under the fabric" in out

    def test_exposed_scene_states_each_mark_exactly_once(self):
        """No double-block: the exposed clause already owns a bare-armed scene."""
        out = compile_canon_prompt(_summer(), "Summer in a sleeveless top, tattoos visible")
        assert out.lower().count("butterflies and wildflowers") == 1
        assert out.lower().count("black-and-white ballerina") == 1

    def test_partially_exposed_scene_binds_the_covered_half(self):
        """A t-shirt bares the forearms only.

        The left-arm piece spans both segments, so it is exposed and gets the
        geometry block; nothing is left ambiguous, so no binding line is added.
        """
        out = compile_canon_prompt(_summer(), "Summer in a t-shirt at a bar, tattoos visible")
        assert out.lower().count("butterflies and wildflowers") == 1

    @pytest.mark.parametrize("word,expected", [
        ("tattoo", True), ("tattoos", True), ("tattooed", True),
        ("inked", True), ("markings", True), ("body art", True),
        ("birthmark", True),
        ("scarf", False), ("thinking", False), ("drinking", False),
        ("scarves", False), ("inkling", False),
        # INVARIANT CORRECTION: bare "ink", bare singular "marking" and bare
        # "scar(s)" no longer count. They are ordinary English about pens,
        # paperwork and masonry far more often than about skin, and this
        # predicate now also gates a reference slot — see the class below.
        # The personal senses stay reachable via the possessive form.
        ("ink", False), ("marking", False), ("scars", False), ("scar", False),
    ])
    def test_only_real_mark_language_counts(self, word, expected):
        """Substring matching would read "scarf" as "scar"."""
        assert scene_requests_marks(f"Summer with a {word} in the park") is expected

    @pytest.mark.parametrize("scene,expected", [
        # Possessive forms recover the personal sense of the narrowed words.
        ("Summer at home, show her ink", True),
        ("Summer at the beach, her scars are visible", True),
        ("a close look at the character's markings", True),
        # Ordinary English that is not about anybody's skin.
        ("Summer writing with an ink pen at her desk", False),
        ("Summer marking papers in her study", False),
        ("an ink drawing on the wall behind her", False),
        ("the scars of the old city wall behind her", False),
        # Negated requests must not emphasise markings.
        ("Summer in her office, no tattoos visible", False),
        ("Summer in her office with no visible tattoos", False),
        ("Summer at dinner, her tattoos hidden under her sleeves", False),
        # A place is not a request about this character's skin.
        ("Summer visiting a tattoo parlour with a friend", False),
        ("Summer talking to a tattoo artist about a design", False),
        # ...but an actual request inside such a scene still counts.
        ("Summer in a tattoo parlour, show her own tattoos", True),
    ])
    def test_mark_language_must_be_about_this_character(self, scene, expected):
        """The trigger costs a clause AND a reference slot, so it must be narrow."""
        assert scene_requests_marks(scene) is expected

    def test_portrait_closeup_gets_no_body_bindings(self):
        out = compile_canon_prompt(
            _summer(), "close-up portrait of Summer, showing her tattoos")
        assert "canonical anatomy is fixed" not in out

    def test_bindings_come_from_canon_not_from_summer(self):
        """Mirror anatomy on a different character must mirror the wording."""
        mirrored = _canon([_mark("right_full_arm", "right", "Serpent sleeve"),
                           _mark("left_forearm", "left", "Compass tattoo")])
        out = compile_canon_prompt(mirrored, "Alec in his office, show his tattoos")
        assert "right arm" in out and "never the left arm" in out
        assert "left forearm" in out and "never the right arm" in out

    def test_markless_canon_says_nothing(self):
        out = compile_canon_prompt(_canon([]), EMPHASIS)
        assert "canonical anatomy is fixed" not in out


class TestSideEvidenceWithoutBareBodyEvidence:
    """Words are a weak carrier for left/right. The fix is scoped crops, not a
    bare whole-body sheet.

    INVARIANT CORRECTION. An earlier iteration kept the bare body_map against
    the S24I suppression gate whenever a scene mentioned markings, because the
    map is the only reference that shows which design sits on which side, and a
    sampled test swapped two designs across arms without it.

    That reintroduced bare whole-body evidence — torso, back and legs included —
    into scenes whose wardrobe was never stated, which is precisely the
    reference contamination the card-coverage engine exists to prevent. Each
    mark's own crop carries the same side information, scoped to one region, so
    the sheet exception was deleted. (The sampled swap was also measured before
    any anatomy binding existed in the prompt at all.)
    """

    def test_the_bare_sheet_is_never_kept_just_because_marks_were_mentioned(self):
        _urls, meta = route_canon_refs(EMPHASIS, _summer())
        assert meta.body_map_suppressed is True

    def test_side_evidence_still_reaches_the_provider_per_mark(self):
        """What replaced the sheet: one scoped crop per mark, each bound to its
        own region and side."""
        _urls, meta = route_canon_refs(EMPHASIS, _summer())
        assert meta.mark_crops == 2
        assert {(b.body_region, b.side) for b in meta.mark_crop_bindings} == {
            ("left_full_arm", "left"), ("right_forearm", "right")}
        assert all(b.visibility == "unresolved" for b in meta.mark_crop_bindings)

    def test_unresolved_crops_never_lead_and_keep_a_body_anchor(self):
        urls, meta = route_canon_refs(EMPHASIS, _summer())
        assert meta.route_slots[0] != "mark_crop"
        assert meta.route_slots[0].startswith("face")
        assert any(s.startswith("body") for s in meta.route_slots)
        assert len(urls) <= 6

    def test_an_explicitly_covered_mark_still_routes_nothing(self):
        """The hard invariant: asking for tattoos cannot route a covered mark."""
        _urls, meta = route_canon_refs(
            "Summer at a formal dinner in a long-sleeved suit, show her tattoos",
            _summer())
        assert meta.mark_crops == 0
        assert meta.body_map_suppressed is True

    def test_ambiguous_clothing_routes_nothing_even_when_asked(self):
        _urls, meta = route_canon_refs(
            "Summer in a sports bra under a heavy winter parka, show her tattoos",
            _summer())
        assert meta.mark_crops == 0

    def test_scene_that_never_mentions_marks_routes_no_unresolved_crops(self):
        _urls, meta = route_canon_refs(PLAIN_OFFICE, _summer())
        assert meta.body_map_suppressed is True
        assert meta.mark_crops == 0

    def test_ordinary_ink_language_routes_nothing(self):
        """The narrowed trigger matters here: a false positive would spend a
        reference slot on a scene about stationery."""
        _urls, meta = route_canon_refs(
            "Summer writing with an ink pen at her desk", _summer())
        assert meta.mark_crops == 0


class TestPromptStaysWhole:
    """The scene is the one thing that cannot be reconstructed from canon.

    Adding per-mark bindings pushed a nine-mark character past the prompt cap,
    and the old tail-cut deleted the occlusion clause, the clean-skin clause
    and the user's own sentence — keeping boilerplate and discarding the
    request. These pin the fit policy: invariants and scene survive, design
    detail is what gets sacrificed.
    """

    def _many_marks(self, n=14):
        regions = ["chest", "back", "neck", "left_upper_arm", "right_upper_arm",
                   "left_forearm", "right_forearm", "abdomen", "ribs", "left_thigh",
                   "right_thigh", "left_calf", "right_calf", "upper_back"]
        return _canon([
            _mark(regions[i % len(regions)], "centre",
                  label=f"Mark {i} " + "x" * 60,
                  description="y" * 400)
            for i in range(n)
        ])

    def test_the_users_scene_is_never_dropped(self):
        out = compile_canon_prompt(self._many_marks(), EMPHASIS)
        assert out.rstrip().endswith(EMPHASIS)

    def test_anti_migration_and_occlusion_invariants_survive(self):
        out = compile_canon_prompt(self._many_marks(), EMPHASIS)
        assert "Clean-skin truth" in out
        assert ("Wherever clothing covers" in out) or ("Opaque clothing covers" in out)

    def test_overflowing_marks_are_summarised_not_silently_dropped(self):
        out = compile_canon_prompt(self._many_marks(), EMPHASIS)
        assert "canonical region and side" in out

    def test_a_small_canon_still_names_every_mark(self):
        out = compile_canon_prompt(_summer(), EMPHASIS)
        assert "further permanent marking" not in out


# ── C. Segment-blind crops (documented limitation) ────────────────────

class TestSegmentBlindCrops:
    """A full-arm mark carries ONE crop, and nothing records which segment it
    shows.

    Summer's butterfly piece spans shoulder to wrist but both of its stored
    images frame the upper arm. Under a short sleeve only her forearm is bare,
    so the routed crop depicts the covered half. It has not produced a wrong
    image — the whole-body cards lead and the design vocabulary is the same
    along the arm — but nothing in the schema makes that a guarantee.

    These tests pin the CURRENT contract so that a future segment-aware crop
    field changes them deliberately rather than silently. They deliberately do
    not assert that the behaviour is correct.
    """

    def test_partial_exposure_still_routes_the_marks_only_crop(self):
        _urls, meta = route_canon_refs("Summer in a bar wearing a t-shirt", _summer())
        binding = next(b for b in meta.mark_crop_bindings
                       if b.body_region == "left_full_arm")
        assert binding.url == CROP
        assert binding.side == "left"

    def test_a_mark_has_exactly_one_crop_and_no_segment_metadata(self):
        fields = set(PermanentBodyMark.model_fields)
        assert {"detail_crop_url", "reference_image_url"} <= fields
        assert not {f for f in fields if "segment" in f}, (
            "a segment field now exists — update the routing contract above"
        )

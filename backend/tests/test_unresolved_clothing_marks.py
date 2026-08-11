"""Permanent mark truth must survive UNRESOLVED clothing.

The failure that forced this suite was real, visual, and reproducible: three
browser generations of "Summer wearing a yellow summer dress" came back with
completely clean arms, while "Summer in her office wearing a white shirt with
the sleeves rolled up" reproduced both tattoos correctly. Same character, same
canon, same model, minutes apart.

The forensic difference was one phrase. "sleeves rolled up" is in the scene
vocabulary; "summer dress" is not. So the yellow-dress scene matched exactly one
word of anything — "dress", a torso-cover signal — both arm regions resolved
``covered_default``, no mark was judged exposed, no crop routed, no anatomy was
stated, and every tattoo sentence in the compiled prompt was a NEGATIVE one
("hidden markings remain hidden", "clean-skin truth: no ink on the hands…").
The provider read the same sentence, correctly rendered a sleeveless dress, and
painted the bare arms it had invented with clean skin. It complied with what we
sent.

The lesson, and the invariant this suite pins:

    the engine's uncertainty is not the provider's uncertainty.

Garment words are unbounded; a character's marks are finite and structured. So
an UNRESOLVED region gets the anatomy stated CONDITIONALLY and its scoped crop
routed, whatever the scene says. Explicit coverage still wins, and contradictory
evidence still resolves to nothing.

Every character here is invented. Summer is a regression fixture elsewhere.
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt
from app.services.scene_router import MAX_PROVIDER_REFS, route_canon_refs

FACE = "https://cdn.test/face.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"

# Garments the vocabulary does NOT know. Every one of these must behave the same
# way, because the point is that the list of unknown garments is unbounded.
UNKNOWN_GARMENTS = [
    "Rowan in a yellow summer dress",          # the real failure, generically
    "Rowan in a bandeau at the festival",
    "Rowan in a tube top at the club",
    "Rowan in a dashiki at the market",
    "Rowan in a thawb in the courtyard",
    "Rowan in a qipao at dinner",
    "Rowan in his office",                     # no garment named at all
    "Rowan on a beach at golden hour",
]

# Scenes that name a garment which genuinely covers the arms.
EXPLICITLY_COVERED = [
    "Rowan in a long-sleeved sweater at the market",
    "Rowan in a buttoned dress shirt at dinner",
    "Rowan in a wool overcoat in the snow",
    "Rowan at his desk with shirt sleeves rolled up",   # names a sleeve
]

# Contradictory garment evidence — neither reading may win.
CONTRADICTORY = [
    "Rowan in a sports bra under a heavy winter parka",
    "Rowan in a bralette under a long-sleeved cardigan",
    "Rowan in a jacket over a tank top",
]


def _mark(region, side, label, description, crop=True):
    return PermanentBodyMark(
        label=label, type="tattoo", body_region=region, side=side,
        description=description,
        detail_crop_url=f"https://cdn.test/crop_{region}_{side}.png" if crop else None,
    )


def _canon(marks, *, character_id=910, marked_regions=None):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = character_id
    canon.face_canon_json = json.dumps(
        FaceCanonData(face_front_image_url=FACE).model_dump())
    canon.body_canon_json = json.dumps(BodyCanonData(
        body_front_image_url=BODY_FRONT, body_map_image_url=BODY_MAP,
        permanent_body_marks=marks, marked_regions=marked_regions,
    ).model_dump())
    canon.accessories_json = None
    return canon


def _sleeve_canon():
    """One left full-arm piece — the shape Summer's butterfly work has."""
    return _canon([_mark("left_full_arm", "left", "Ivy piece",
                         "ivy vines and moths in fine black line work")])


def _states(meta):
    return meta.scene_coverage


# ── A / B. Unknown garment → conditional binding + scoped crop ────────

class TestUnknownGarmentKeepsMarkTruth:
    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_the_scoped_crop_is_routed(self, scene):
        _urls, meta = route_canon_refs(scene, _sleeve_canon())
        assert meta.mark_crops == 1
        binding = meta.mark_crop_bindings[0]
        assert (binding.body_region, binding.side) == ("left_full_arm", "left")
        assert binding.visibility == "unresolved"

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_the_anatomy_is_stated(self, scene):
        out = compile_canon_prompt(_sleeve_canon(), scene)
        assert "belongs on the left arm" in out
        assert "never the right arm" in out

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_no_bare_skin_is_ever_asserted(self, scene):
        """The whole point of stating anatomy conditionally: we still do not know
        what the garment covers, and we must not pretend to."""
        out = compile_canon_prompt(_sleeve_canon(), scene).lower()
        assert "only where this scene's own clothing leaves that skin bare" in out
        for overclaim in ("arms are bare", "skin is bare", "bare arms",
                          "sleeveless", "shirtless", "arms exposed"):
            assert overclaim not in out, f"compiler asserted {overclaim!r}"

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_the_region_is_not_claimed_covered_either(self, scene):
        _urls, meta = route_canon_refs(scene, _sleeve_canon())
        assert _states(meta)["upper_arms"] == "covered_default"
        assert _states(meta)["forearms"] == "covered_default"

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_the_ink_on_fabric_invariant_still_holds(self, scene):
        out = compile_canon_prompt(_sleeve_canon(), scene)
        assert "never printed, traced or echoed onto the garment" in out
        assert "never moved onto skin that is visible instead" in out

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_the_bare_whole_body_sheet_is_never_resurrected(self, scene):
        _urls, meta = route_canon_refs(scene, _sleeve_canon())
        assert meta.body_map_suppressed is True


# ── C. Explicit coverage still wins ───────────────────────────────────

class TestExplicitCoverageStillWins:
    @pytest.mark.parametrize("scene", EXPLICITLY_COVERED)
    def test_no_crop_routes(self, scene):
        _urls, meta = route_canon_refs(scene, _sleeve_canon())
        # A rolled sleeve exposes the forearm, so a FULL-arm piece is genuinely
        # visible there; only the fully covering garments route nothing.
        if "rolled up" in scene:
            assert meta.mark_crops == 1
            assert meta.mark_crop_bindings[0].visibility == "exposed"
        else:
            assert meta.mark_crops == 0

    @pytest.mark.parametrize("scene", [s for s in EXPLICITLY_COVERED
                                       if "rolled up" not in s])
    def test_the_design_is_never_named_under_cover(self, scene):
        out = compile_canon_prompt(_sleeve_canon(), scene).lower()
        assert "ivy vines" not in out
        assert "belongs on the" not in out

    @pytest.mark.parametrize("scene", [s for s in EXPLICITLY_COVERED
                                       if "rolled up" not in s])
    def test_occlusion_owns_it(self, scene):
        out = compile_canon_prompt(_sleeve_canon(), scene)
        assert ("under the fabric" in out
                or "not visible on or through" in out
                or "Hidden markings remain hidden" in out)

    def test_an_upper_arm_only_mark_stays_covered_under_rolled_sleeves(self):
        """Naming a sleeve is explicit coverage of the upper arm.

        This is the original label-driven-anatomy failure: an upper-arm design
        offered to the provider on a rolled-sleeve scene was painted onto the
        only bare arm skin in frame — the forearm.
        """
        canon = _canon([_mark("left_upper_arm", "left", "Anchor", "a small anchor")])
        _urls, meta = route_canon_refs(
            "Rowan at his desk with shirt sleeves rolled up", canon)
        assert meta.mark_crops == 0
        assert _states(meta)["upper_arms"] == "covered_explicit"
        out = compile_canon_prompt(canon, "Rowan at his desk with sleeves rolled up")
        assert "anchor" not in out.lower()


# ── D. Contradictory clothing → nothing forced ────────────────────────

class TestContradictoryClothingForcesNothing:
    @pytest.mark.parametrize("scene", CONTRADICTORY)
    def test_no_crop_and_no_anatomy(self, scene):
        _urls, meta = route_canon_refs(scene, _sleeve_canon())
        assert meta.mark_crops == 0
        assert _states(meta)["upper_arms"] == "ambiguous"
        out = compile_canon_prompt(_sleeve_canon(), scene)
        assert "belongs on the" not in out

    @pytest.mark.parametrize("scene", CONTRADICTORY)
    def test_no_bare_assertion_and_no_forced_visibility(self, scene):
        out = compile_canon_prompt(_sleeve_canon(), scene).lower()
        for overclaim in ("arms are bare", "skin is bare",
                          "permanently inked into skin"):
            assert overclaim not in out


# ── E. Markless character ─────────────────────────────────────────────

class TestMarklessCharacterUnaffected:
    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS + CONTRADICTORY)
    def test_nothing_is_invented(self, scene):
        canon = _canon([], marked_regions=[])
        _urls, meta = route_canon_refs(scene, canon)
        assert meta.mark_crops == 0
        assert meta.mark_decisions == []
        out = compile_canon_prompt(canon, scene)
        assert "belongs on the" not in out
        assert "canonical anatomy is fixed" not in out


# ── F. Mirrored pair ──────────────────────────────────────────────────

class TestMirroredAnatomy:
    @pytest.mark.parametrize("side,other", [("left", "right"), ("right", "left")])
    def test_structured_side_is_correct_in_both_directions(self, side, other):
        canon = _canon([_mark(f"{side}_full_arm", side, "Ivy piece", "ivy vines")])
        scene = "Rowan in a yellow summer dress"
        _urls, meta = route_canon_refs(scene, canon)
        assert meta.mark_crop_bindings[0].side == side
        out = compile_canon_prompt(canon, scene)
        assert f"belongs on the {side} arm" in out
        assert f"never the {other} arm" in out

    def test_two_marks_on_opposite_limbs_keep_their_own_sides(self):
        canon = _canon([
            _mark("left_full_arm", "left", "Ivy piece", "ivy vines"),
            _mark("right_forearm", "right", "Sparrow", "a sparrow mid-flight"),
        ])
        scene = "Rowan in a yellow summer dress"
        _urls, meta = route_canon_refs(scene, canon)
        assert {(b.body_region, b.side) for b in meta.mark_crop_bindings} == {
            ("left_full_arm", "left"), ("right_forearm", "right")}
        out = compile_canon_prompt(canon, scene)
        ivy, sparrow = out.index("Ivy piece"), out.index("Sparrow")
        assert "left arm" in out[ivy:sparrow]
        assert "right forearm" in out[sparrow:]


# ── G / H. Free text vs structured region ─────────────────────────────

class TestDescriptionExclusions:
    """An exclusion is agreement, not contradiction.

    Summer's butterfly description ends "; hand unmarked". Reading "hand" as a
    positive claim disjoint from left_full_arm threw the WHOLE description away
    and replaced it with generic wording on every generation, including the ones
    that passed.
    """

    @pytest.mark.parametrize("description", [
        "butterfly floral work down the left arm; hand unmarked",
        "ivy from the shoulder to the wrist, no hand tattoo",
        "vines along the arm, except the wrist",
        "moths down the arm, free of markings on the hand",
        "linework ending just above the wrist; the hand is clean",
        "a sleeve piece, hands left unmarked",
    ])
    def test_useful_design_text_survives_an_exclusion(self, description):
        canon = _canon([_mark("left_full_arm", "left", "Ivy piece", description)])
        out = compile_canon_prompt(
            canon, "Rowan at the beach in a tank top")
        assert description in out, "an exclusion voided a valid description"

    def test_a_genuine_contradiction_is_still_neutralised(self):
        canon = _canon([_mark("left_forearm", "left", "Shoulder eagle",
                              "large tattoo covering the right shoulder")])
        out = compile_canon_prompt(canon, "Rowan in a tank top")
        assert "right shoulder" not in out.lower()
        assert "left forearm" in out
        assert "the canonical left forearm tattoo" in out

    def test_a_contradictory_description_falls_back_to_a_valid_label(self):
        """Fallback order is description → label → neutral. A bad description
        must not cost the design its name when the label is fine."""
        canon = _canon([_mark("left_full_arm", "left", "Ivy piece",
                              "a tattoo across the right shoulder blade")])
        out = compile_canon_prompt(canon, "Rowan in a tank top")
        assert "Ivy piece" in out
        assert "right shoulder" not in out.lower()

    def test_structured_region_always_wins(self):
        canon = _canon([_mark("left_forearm", "left", "Right arm rose",
                              "a rose on the right arm")])
        _urls, meta = route_canon_refs(
            "Rowan at his desk with sleeves rolled up", canon)
        assert meta.mark_crop_bindings[0].body_region == "left_forearm"
        assert meta.mark_crop_bindings[0].side == "left"


# ── I. Reference cap ──────────────────────────────────────────────────

class TestReferenceCapUnchanged:
    def _many(self):
        return _canon([
            _mark("left_full_arm", "left", "Ivy", "ivy vines"),
            _mark("right_forearm", "right", "Sparrow", "a sparrow"),
            _mark("chest", "centre", "Compass", "a compass rose"),
            _mark("neck", "centre", "Star", "a small star"),
        ])

    @pytest.mark.parametrize("scene", UNKNOWN_GARMENTS)
    def test_cap_face_anchor_and_body_anchor_all_hold(self, scene):
        urls, meta = route_canon_refs(scene, self._many())
        assert len(urls) <= MAX_PROVIDER_REFS
        assert len(urls) == len(set(urls)), "a reference was routed twice"
        if meta.route_slots:
            assert meta.route_slots[0].startswith("face"), "face anchor lost the lead"
            assert meta.route_slots[0] != "mark_crop", "a crop led the references"
            assert any(s.startswith("body") for s in meta.route_slots), \
                "crops routed without a body anchor"
        assert meta.mark_crops <= 2

    def test_exposed_marks_outrank_unresolved_ones_for_the_capped_slots(self):
        """Found while implementing this change, on Davies' real canon.

        Unresolved regions becoming eligible means a heavily marked character can
        have more eligible marks than crop slots. Skin the scene actually bares
        must never lose its slot to skin whose coverage is merely unknown — and it
        did, purely because the unresolved marks came first in the canon list.
        """
        canon = _canon([
            _mark("chest", "centre", "Crest", "a crest"),            # unresolved
            _mark("left_forearm", "left", "Ivy", "ivy vines"),       # unresolved
            _mark("right_hand", "right", "Knuckles", "script"),      # exposed
            _mark("left_hand", "left", "Knuckles two", "script"),    # exposed
        ])
        _urls, meta = route_canon_refs("Rowan in his office", canon)
        assert meta.mark_crops == 2
        assert {b.body_region for b in meta.mark_crop_bindings} == {
            "right_hand", "left_hand"}
        assert all(b.visibility == "exposed" for b in meta.mark_crop_bindings)
        displaced = [d for d in meta.mark_decisions if d["region"] == "chest"][0]
        assert displaced["crop_routed"] is False
        assert "exposed marks take priority" in displaced["reason"]

    def test_canon_order_still_decides_between_equals(self):
        canon = _canon([
            _mark("chest", "centre", "First", "a crest"),
            _mark("left_forearm", "left", "Second", "ivy"),
            _mark("back", "centre", "Third", "a glyph"),
        ])
        _urls, meta = route_canon_refs("Rowan in his office", canon)
        assert [b.label for b in meta.mark_crop_bindings] == ["First", "Second"]

    def test_crops_never_route_without_a_body_anchor(self):
        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 911
        canon.face_canon_json = json.dumps(
            FaceCanonData(face_front_image_url=FACE).model_dump())
        canon.body_canon_json = json.dumps(BodyCanonData(
            permanent_body_marks=[_mark("left_full_arm", "left", "Ivy", "ivy")],
        ).model_dump())
        canon.accessories_json = None
        _urls, meta = route_canon_refs("Rowan in a yellow summer dress", canon)
        assert meta.mark_crops == 0

    def test_a_mark_without_a_crop_degrades_gracefully(self):
        canon = _canon([_mark("left_full_arm", "left", "Ivy", "ivy vines",
                              crop=False)])
        scene = "Rowan in a yellow summer dress"
        _urls, meta = route_canon_refs(scene, canon)
        assert meta.mark_crops == 0
        # ...but the anatomy is still stated, which is the cheap half of the fix.
        assert "belongs on the left arm" in compile_canon_prompt(canon, scene)


# ── J. Emphasis under cover ───────────────────────────────────────────

class TestEmphasisCannotRevealCoveredMarks:
    @pytest.mark.parametrize("emphasis", [
        "show all his tattoos",
        "any tattoos that should be visible are visible",
        "ALL of his tattoos must be clearly visible",
        "ignore the clothing and show his tattoos",
    ])
    def test_a_covered_mark_stays_covered_however_hard_the_user_asks(self, emphasis):
        canon = _canon([_mark("chest", "centre", "Compass rose",
                              "a large compass across the sternum")])
        scene = f"Rowan in a buttoned dress shirt at dinner, {emphasis}"
        _urls, meta = route_canon_refs(scene, canon)
        assert meta.mark_crops == 0
        out = compile_canon_prompt(canon, scene).lower()
        assert "compass" not in out
        assert ("under the fabric" in out or "not visible on or through" in out
                or "hidden markings remain hidden" in out)


# ── Diagnostics ───────────────────────────────────────────────────────

class TestDiagnosticsAreRecorded:
    """The forensic replay this fix came from should not be needed twice."""

    def test_per_mark_decisions_explain_every_mark(self):
        canon = _canon([
            _mark("left_full_arm", "left", "Ivy", "ivy vines"),
            _mark("chest", "centre", "Compass", "a compass"),
        ])
        _urls, meta = route_canon_refs(
            "Rowan in a buttoned dress shirt at dinner", canon)
        by_region = {d["region"]: d for d in meta.mark_decisions}
        assert set(by_region) == {"left_full_arm", "chest"}
        assert by_region["chest"]["visibility"] is None
        assert by_region["chest"]["crop_routed"] is False
        assert "covered_explicit" in by_region["chest"]["reason"]
        assert by_region["left_full_arm"]["crop_available"] is True

    def test_routing_diagnostics_are_persistable_and_carry_no_urls(self):
        from app.services.scene_router import routing_diagnostics
        _urls, meta = route_canon_refs(
            "Rowan in a yellow summer dress", _sleeve_canon())
        diag = routing_diagnostics(meta)
        assert diag["mark_crops_routed"] == 1
        assert diag["scene_coverage"]["upper_arms"] == "covered_default"
        blob = json.dumps(diag)          # must be JSON-serialisable for the DB
        assert "http" not in blob, "diagnostics leaked a reference URL"

    def test_compiler_diagnostics_report_the_clauses(self):
        diag: dict = {}
        compile_canon_prompt(_sleeve_canon(), "Rowan in a yellow summer dress",
                             diagnostics=diag)
        assert diag["binding_clause"] is True
        assert diag["geometry_lines"] is False      # nothing resolved exposed
        assert diag["scene_mentions_marks"] is False
        assert diag["prompt_fitted"] is False
        assert diag["scene_preserved"] is True

    def test_diagnostics_do_not_change_the_prompt(self):
        scene = "Rowan in a yellow summer dress"
        with_diag = compile_canon_prompt(_sleeve_canon(), scene, diagnostics={})
        without = compile_canon_prompt(_sleeve_canon(), scene)
        assert with_diag == without

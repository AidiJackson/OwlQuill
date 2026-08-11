"""PHASE 1 permanent-mark completion — hands/face truth + occlusion gap.

Three concrete gaps closed here, all found after the production QA where
Davies appeared with clean hands in two images and with chest artwork printed
on his shirt in a third:

  1. hands/face had no scene region STATE, so a declared hand tattoo could
     only ever be denied by the clean-skin clause, never positively asserted.
  2. registering structured marks silently DELETED the region-named occlusion
     clause (it was gated to markless canons), downgrading the exact wording
     that made the white-shirt scene pass.
  3. a scene naming no garment ("... any tattoos that should be visible are
     visible") produced covered_default everywhere, so no occlusion wording
     fired at all while the prompt pushed the model to render torso ink.
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt
from app.services.card_coverage import scene_region_states
from app.services.scene_router import _mark_region_exposed, route_canon_refs

FACE_FRONT = "https://cdn.test/face_front.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"
HAND_CROP = "https://cdn.test/hand_crop.png"

OFFICE = "Davies in his office"
EMPHASIS = "Davies in his office - any tattoos that should be visible are visible"
WHITE_SHIRT = "Davies in his office wearing a white shirt"
SHIRTLESS = "Davies shirtless in his office"


def _mark(region, side="centre", label="mark", crop=None):
    return PermanentBodyMark(
        label=label, type="tattoo", body_region=region, side=side,
        description=f"{label} design", detail_crop_url=crop,
    )


def _canon(*, marks=None, marked_regions=None, coverage=None):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 38
    face = FaceCanonData(face_front_image_url=FACE_FRONT)
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP,
        permanent_body_marks=marks or [],
        marked_regions=marked_regions,
        card_coverage=coverage or {},
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


# ── 1/2: hands + face positive region states ──────────────────────────

class TestHandsAndFaceRegionStates:
    def test_hands_and_face_default_to_exposed(self):
        # Inverse of every other region: absence of a signal means VISIBLE.
        states = scene_region_states(OFFICE.lower())
        assert states["hands"] == "exposed"
        assert states["face"] == "exposed"

    def test_gloves_cover_hands(self):
        states = scene_region_states("wearing leather gloves in his office")
        assert states["hands"] == "covered_explicit"

    def test_mask_covers_face(self):
        states = scene_region_states("wearing a mask in his office")
        assert states["face"] == "covered_explicit"

    def test_hands_face_do_not_affect_card_conflicts(self):
        # They are deliberately outside _TRACKED — coverage/suppression must be
        # byte-identical to before this change.
        from app.services.card_coverage import _TRACKED
        assert "hands" not in _TRACKED and "face" not in _TRACKED

    def test_hand_mark_exposed_unless_gloved(self):
        assert _mark_region_exposed("right_hand", OFFICE.lower()) is True
        assert _mark_region_exposed("knuckles", OFFICE.lower()) is True
        assert _mark_region_exposed("right_hand", "wearing gloves") is False

    def test_face_mark_exposed_unless_masked(self):
        assert _mark_region_exposed("right_cheek", OFFICE.lower()) is True
        assert _mark_region_exposed("right_cheek", "wearing a helmet") is False

    def test_registered_hand_mark_positively_asserted(self):
        # Gap 1: previously impossible — hands had no state, so the presence
        # clause could never name them.
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso", "hands"]), OFFICE
        )
        presence = prompt.split("carry their permanent markings")[0]
        assert "carry their permanent markings" in prompt
        assert "hands" in presence

    def test_no_hand_mark_keeps_clean_hand_authority(self):
        prompt = compile_canon_prompt(_canon(marked_regions=["torso"]), OFFICE)
        clean = prompt.split("Clean-skin truth")[1]
        assert "hands" in clean

    def test_declared_hands_are_never_called_clean(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso", "hands"]), OFFICE
        )
        if "Clean-skin truth" in prompt:
            clean = prompt.split("Clean-skin truth")[1].split("—")[0]
            assert "hands" not in clean
            assert "knuckles" not in clean


# ── 3: tattoo-emphasis / unstated-scene occlusion ─────────────────────

class TestUnstatedSceneOcclusion:
    def test_emphasis_prompt_gets_conditional_invariant(self):
        # THE production failure: chest artwork printed onto the shirt.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")], marked_regions=["torso"]), EMPHASIS
        )
        assert "Wherever clothing covers" in prompt
        assert "never printed" in prompt

    def test_conditional_never_asserts_the_character_is_clothed(self):
        # It must be an implication, or shirtless/fantasy scenes break.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")], marked_regions=["torso"]), EMPHASIS
        )
        assert "are fully covered by opaque clothing" not in prompt

    def test_shirtless_scene_gets_no_occlusion_at_all(self):
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")], marked_regions=["torso"]), SHIRTLESS
        )
        assert "Wherever clothing covers" not in prompt
        assert "Opaque clothing covers" not in prompt

    def test_explicit_scene_keeps_region_named_absolute_clause(self):
        # Gap 2: registering marks must not delete this wording.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")], marked_regions=["torso"]), WHITE_SHIRT
        )
        assert "Opaque clothing covers" in prompt
        assert "chest and torso" in prompt

    def test_absolute_and_conditional_never_both_fire(self):
        # Same invariant at two confidence levels — emitting both is bloat.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")], marked_regions=["torso"]), WHITE_SHIRT
        )
        assert not ("Opaque clothing covers" in prompt and "Wherever clothing covers" in prompt)

    def test_legacy_undeclared_canon_gets_no_conditional(self):
        # Angelo-shaped: no marks, no declaration → byte-stable prompts.
        prompt = compile_canon_prompt(_canon(), OFFICE)
        assert "Wherever clothing covers" not in prompt

    def test_conditional_needs_bare_card_evidence(self):
        # No bare evidence → nothing to migrate → stay silent.
        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 1
        canon.face_canon_json = json.dumps(
            FaceCanonData(face_front_image_url=FACE_FRONT).model_dump())
        canon.body_canon_json = json.dumps(BodyCanonData(
            body_front_image_url=BODY_FRONT,
            marked_regions=["torso"],
            card_coverage={"body_front": {"coverage_type": "fully_clothed"}},
        ).model_dump())
        canon.accessories_json = None
        assert "Wherever clothing covers" not in compile_canon_prompt(canon, OFFICE)

    def test_conditional_only_names_marked_regions(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso"]), OFFICE
        )
        conditional = prompt.split("Wherever clothing covers the")[1].split(" in this scene")[0]
        assert "torso" in conditional
        assert "legs" not in conditional


# ── Detail-crop routing with structured marks ─────────────────────────

class TestDetailCropRouting:
    def test_exposed_forearm_crop_routes_on_rolled_sleeves(self):
        canon = _canon(marks=[_mark("right_forearm", "right", "band", HAND_CROP)])
        _urls, meta = route_canon_refs(
            "Davies at his desk, front view, sleeves rolled up", canon)
        assert meta.mark_crops >= 1
        assert any(b.body_region == "right_forearm" for b in meta.mark_crop_bindings)

    def test_covered_arm_crop_suppressed_in_long_sleeves(self):
        canon = _canon(marks=[_mark("right_upper_arm", "right", "sleeve", HAND_CROP)])
        _urls, meta = route_canon_refs(
            "Davies front view in a long-sleeved suit and tie", canon)
        assert meta.mark_crops == 0

    def test_hand_crop_routes_when_hands_visible(self):
        canon = _canon(marks=[_mark("right_hand", "right", "rosette", HAND_CROP)])
        _urls, meta = route_canon_refs("Davies front view at his desk", canon)
        assert any(b.body_region == "right_hand" for b in meta.mark_crop_bindings)

    def test_hand_crop_suppressed_when_gloved(self):
        canon = _canon(marks=[_mark("right_hand", "right", "rosette", HAND_CROP)])
        _urls, meta = route_canon_refs(
            "Davies front view wearing gloves", canon)
        assert meta.mark_crops == 0

    def test_face_reference_still_leads(self):
        canon = _canon(marks=[_mark("right_hand", "right", "rosette", HAND_CROP)])
        _urls, meta = route_canon_refs("Davies front view at his desk", canon)
        assert meta.route_slots[0].startswith("face_")

    def test_markless_canon_routes_no_crops(self):
        _urls, meta = route_canon_refs("Davies front view at his desk", _canon())
        assert meta.mark_crops == 0


# ── Ambiguous/fallback-path crop routing ──────────────────────────────
#
# A vague natural prompt detects no camera, and the crop splice used to exist
# only on the camera path — so the most common real user prompt received no
# structured mark evidence at all. These pin the fix and, just as importantly,
# the limits that keep it from weakening grounding or leaking covered marks.

class TestAmbiguousPromptCropRouting:
    def _hand_canon(self, **kw):
        return _canon(marks=[_mark("right_hand", "right", "rosette", HAND_CROP)], **kw)

    def test_vague_prompt_routes_exposed_hand_crop(self):
        _urls, meta = route_canon_refs(OFFICE, self._hand_canon())
        assert meta.camera == "unknown"
        assert meta.mark_crops == 1
        assert meta.mark_crop_bindings[0].body_region == "right_hand"

    def test_vague_prompt_keeps_face_anchor_leading(self):
        # Reference grounding must not be weakened: face identity still leads
        # and a real body anchor is still present behind it.
        _urls, meta = route_canon_refs(OFFICE, self._hand_canon())
        assert meta.route_slots[0] == "face_front"
        assert "body_front" in meta.route_slots

    def test_crop_never_leads_the_reference_list(self):
        _urls, meta = route_canon_refs(OFFICE, self._hand_canon())
        assert meta.route_slots.index("mark_crop") > 0

    def test_unresolved_mark_routes_on_vague_prompt_with_occlusion_stated(self):
        """INVARIANT CORRECTION, forced by real visual QA — read the risk note.

        This asserted that a chest mark must NOT route on a vague office prompt,
        because the torso is not exposed. Real generations then proved the
        opposite failure is worse and more common: three "Summer wearing a yellow
        summer dress" images came back with completely clean arms, because an
        unresolved region routed no mark evidence and the prompt stated no
        anatomy while the provider rendered bare skin from the same words.

        ``covered_default`` means UNKNOWN, not covered. It now routes the scoped
        crop and states anatomy conditionally.

        RISK, recorded deliberately: for a TORSO mark on a vague prompt the
        provider will usually render clothing, so this is the region where
        print-through (the Davies failure) is most likely. Two explicit clauses
        now accompany the crop — asserted below — and the crop is region-scoped
        rather than a bare whole-body card. If print-through reappears on torso
        marks in visual QA, this is the trade to revisit first, and the fix would
        be a per-region visibility prior, not a return to silence.
        """
        canon = _canon(marks=[_mark("chest", "centre", "crest", HAND_CROP)])
        _urls, meta = route_canon_refs(OFFICE, canon)
        assert meta.mark_crops == 1
        assert meta.mark_crop_bindings[0].visibility == "unresolved"

        prompt = compile_canon_prompt(canon, OFFICE)
        # The mark is never asserted visible...
        assert "only where this scene's own clothing leaves that skin bare" in prompt
        # ...and ink-on-fabric is forbidden twice, generally and by region.
        assert "never printed, traced or echoed onto the garment" in prompt
        assert "Wherever clothing covers the chest and torso" in prompt

    def test_gloves_suppress_hand_crop_on_vague_prompt(self):
        _urls, meta = route_canon_refs(
            "Davies in his office wearing gloves", self._hand_canon())
        assert meta.mark_crops == 0

    def test_shirtless_vague_prompt_routes_chest_crop(self):
        # Exposure promotion makes this camera=front; asserted here so the two
        # paths stay consistent about which marks are eligible.
        canon = _canon(marks=[_mark("chest", "centre", "crest", HAND_CROP)])
        _urls, meta = route_canon_refs("Davies shirtless in his office", canon)
        assert meta.mark_crops == 1

    def test_route_slots_populated_only_when_crops_spliced(self):
        # Otherwise a crop URL reverse-maps to "unknown" and diagnostics
        # misreport the reference set.
        _urls, with_crops = route_canon_refs(OFFICE, self._hand_canon())
        assert with_crops.route_slots
        _urls2, without = route_canon_refs(OFFICE, _canon())
        assert without.route_slots == []

    def test_static_fallback_unchanged_for_markless_canon(self):
        from app.services.canon_compiler import collect_canon_reference_urls
        canon = _canon()
        urls, meta = route_canon_refs("standing in a sunny field", canon)
        assert urls == collect_canon_reference_urls(canon)
        assert meta.mark_crops == 0

    def test_mark_without_crop_image_routes_nothing(self):
        canon = _canon(marks=[_mark("right_hand", "right", "rosette", None)])
        _urls, meta = route_canon_refs(OFFICE, canon)
        assert meta.mark_crops == 0

    def test_crops_capped_and_reference_count_not_inflated(self):
        from app.services.scene_router import MAX_PROVIDER_REFS
        canon = _canon(marks=[
            _mark("right_hand", "right", "r", HAND_CROP),
            _mark("left_hand", "left", "l", HAND_CROP),
            _mark("knuckles", "centre", "k", HAND_CROP),
        ])
        urls, meta = route_canon_refs(OFFICE, canon)
        assert meta.mark_crops <= 2
        assert len(urls) <= MAX_PROVIDER_REFS

    def test_no_crop_without_a_body_anchor(self):
        # The anchor guarantee holds on this path too: a crop must have anatomy
        # to bind onto or it reads as a floating symbol.
        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 1
        canon.face_canon_json = json.dumps(
            FaceCanonData(face_front_image_url=FACE_FRONT).model_dump())
        canon.body_canon_json = json.dumps(BodyCanonData(
            permanent_body_marks=[_mark("right_hand", "right", "r", HAND_CROP)],
        ).model_dump())
        canon.accessories_json = None
        _urls, meta = route_canon_refs(OFFICE, canon)
        assert meta.mark_crops == 0

    def test_bindings_align_with_routed_crop_count(self):
        canon = _canon(marks=[
            _mark("right_hand", "right", "r", HAND_CROP),
            _mark("left_hand", "left", "l", HAND_CROP),
        ])
        _urls, meta = route_canon_refs(OFFICE, canon)
        assert len(meta.mark_crop_bindings) == meta.mark_crops

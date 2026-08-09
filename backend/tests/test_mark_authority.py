"""PERMANENT-MARK CANON sprint — mark-location authority tests.

The production Davies follow-up failure: after the coverage fix stopped chest
tattoos printing through his shirt, the office generation invented NEW
tattoos around his neck/collar and on his hands. Root cause: skin VISIBILITY
(face/hands/neck above a collar are visible) was conflated with permanent-mark
LOCATION AUTHORITY (where marks are allowed to exist). These tests pin the
separation:

  * mark_location_authority — derivation, union, veto semantics
  * _clean_region_clause    — scene-relevant clean-skin negatives
  * _legacy_mark_presence_clause — positive truth for enriched legacy canons
  * schema validation for marked_regions
  * model profiles (input_fidelity / max refs) — capability facts per model
"""
import json

import pytest
from unittest.mock import MagicMock

from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import (
    BodyCanonData,
    BodyCanonUpdate,
    FaceCanonData,
    PermanentBodyMark,
)
from app.services.canon_compiler import compile_canon_prompt
from app.services.card_coverage import mark_location_authority

FACE_FRONT = "https://cdn.test/face_front.png"
BODY_FRONT = "https://cdn.test/body_front.png"
BODY_MAP = "https://cdn.test/body_map.png"

SUIT_SCENE = "in his office wearing an opaque white dress shirt and suit"
GYM_SCENE = "shirtless in the gym"


def _mark(region="chest", side="centre", label="Chest script"):
    return PermanentBodyMark(
        label=label, type="tattoo", body_region=region, side=side,
        description=f"{label} tattoo",
    )


def _canon(*, marks=None, marked_regions=None, with_body_map=True):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 38
    face = FaceCanonData(face_front_image_url=FACE_FRONT)
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP if with_body_map else None,
        permanent_body_marks=marks or [],
        marked_regions=marked_regions,
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


# ── Authority derivation ──────────────────────────────────────────────

class TestMarkLocationAuthority:
    def test_no_marks_no_declaration_is_none(self):
        body = BodyCanonData(body_front_image_url=BODY_FRONT)
        assert mark_location_authority(body) is None

    def test_declaration_alone_is_authoritative(self):
        body = BodyCanonData(marked_regions=["torso", "forearms"])
        assert mark_location_authority(body) == frozenset({"torso", "forearms"})

    def test_empty_declaration_means_unmarked(self):
        body = BodyCanonData(marked_regions=[])
        assert mark_location_authority(body) == frozenset()

    def test_structured_marks_derive_authority(self):
        body = BodyCanonData(permanent_body_marks=[_mark("chest")])
        assert mark_location_authority(body) == frozenset({"torso"})

    def test_structured_marks_union_with_declaration(self):
        # An under-declaration can never suppress a registered mark.
        body = BodyCanonData(
            permanent_body_marks=[_mark("left_forearm", side="left")],
            marked_regions=["torso"],
        )
        assert mark_location_authority(body) == frozenset({"torso", "forearms"})

    def test_face_and_hand_mark_regions_map(self):
        body = BodyCanonData(permanent_body_marks=[
            _mark("right_cheek", side="right"), _mark("left_hand", side="left"),
        ])
        assert mark_location_authority(body) == frozenset({"face", "hands"})

    def test_unmappable_mark_region_vetoes_authority(self):
        # A clean-skin claim that might contradict a registered mark is worse
        # than making no claim at all.
        body = BodyCanonData(
            permanent_body_marks=[_mark("somewhere strange")],
            marked_regions=["torso"],
        )
        assert mark_location_authority(body) is None

    def test_none_body_is_none(self):
        assert mark_location_authority(None) is None


# ── Clean-skin clause — anti-migration ────────────────────────────────

class TestCleanSkinClause:
    def test_legacy_canon_unchanged(self):
        # Matrix #9/#11: marks=[] and no declaration → no clean-skin claims,
        # byte-identical prompt behaviour for legacy canons.
        prompt = compile_canon_prompt(_canon(), SUIT_SCENE)
        assert "Clean-skin truth" not in prompt

    def test_enriched_legacy_office_protects_neck_and_hands(self):
        # THE Davies fix: chest/arm authority declared → neck+hands+face are
        # asserted clean even though they are VISIBLE in a suit scene.
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso", "back", "upper_arms", "forearms"]),
            SUIT_SCENE,
        )
        assert "Clean-skin truth" in prompt
        assert "neck" in prompt
        assert "hands" in prompt
        assert "face" in prompt
        # Authority regions are never named clean.
        assert "no tattoos, markings, or ink on the" in prompt
        clean = prompt.split("Clean-skin truth")[1]
        assert "chest" not in clean.split("—")[0]

    def test_chest_mark_does_not_authorise_neck(self):
        # Matrix #2: chest tattoo + visible neck (open shirt) → neck clean.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")]), "open shirt at the beach",
        )
        assert "Clean-skin truth" in prompt
        assert "neck" in prompt.split("Clean-skin truth")[1]

    def test_arm_mark_does_not_authorise_hands(self):
        # Matrix #3: arm tattoos + visible hands → hands/fingers clean.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("left_full_arm", side="left")]),
            "sleeveless tank top at the gym",
        )
        clean = prompt.split("Clean-skin truth")[1]
        assert "hands" in clean and "fingers" in clean
        # Arms carry authority — not named clean.
        assert "forearms" not in clean.split("—")[0]

    def test_covered_regions_not_named_clean(self):
        # A suit-covered torso is owned by the occlusion machinery; the clean
        # clause names only scene-relevant (visible) clean regions.
        prompt = compile_canon_prompt(
            _canon(marked_regions=["legs"]), SUIT_SCENE,
        )
        clean = prompt.split("Clean-skin truth")[1]
        assert "chest" not in clean.split("—")[0]
        # face/neck/hands are visible → named.
        assert "face" in clean and "neck" in clean

    def test_explicit_neck_cover_drops_neck(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso"]), "wearing a turtleneck sweater",
        )
        clean = prompt.split("Clean-skin truth")[1]
        assert "neck" not in clean.split("—")[0]

    def test_portrait_reduces_to_face_and_neck(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso"]), "close-up portrait headshot",
        )
        clean = prompt.split("Clean-skin truth")[1].split("—")[0]
        assert "face" in clean and "neck" in clean
        assert "legs" not in clean and "hands" not in clean

    def test_fully_marked_character_emits_nothing_clean_for_body(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=[
                "torso", "back", "upper_arms", "forearms", "neck",
                "hands", "face", "legs",
            ]),
            GYM_SCENE,
        )
        assert "Clean-skin truth" not in prompt

    def test_never_names_a_design(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso"]), SUIT_SCENE,
        )
        clean = prompt.split("Clean-skin truth")[1]
        for word in ("gothic", "script", "dragon", "skull"):
            assert word not in clean.lower()


# ── Positive presence for enriched legacy canons ──────────────────────

class TestLegacyMarkPresence:
    def test_exposed_authority_regions_asserted(self):
        # Matrix #4: shirtless scene keeps torso truth available — the
        # enriched legacy canon asserts its markings exist, defined by refs.
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso", "forearms"]), GYM_SCENE,
        )
        assert "carry their permanent markings exactly as shown" in prompt

    def test_no_presence_when_covered(self):
        prompt = compile_canon_prompt(
            _canon(marked_regions=["torso"]), SUIT_SCENE,
        )
        assert "carry their permanent markings" not in prompt

    def test_structured_marks_use_their_own_lines(self):
        # Structured marks keep the per-mark geometry block — no duplication.
        prompt = compile_canon_prompt(
            _canon(marks=[_mark("chest")]), GYM_SCENE,
        )
        assert "Permanent markings are immutable skin-bound anatomy" in prompt
        assert "carry their permanent markings exactly as shown" not in prompt


# ── Schema validation ─────────────────────────────────────────────────

class TestMarkedRegionsSchema:
    def test_valid_regions_accepted(self):
        body = BodyCanonData(marked_regions=["torso", "hands", "face"])
        assert body.marked_regions == ["torso", "hands", "face"]

    def test_unknown_region_rejected(self):
        with pytest.raises(ValueError):
            BodyCanonData(marked_regions=["torso", "elbow"])

    def test_update_schema_validates_regions(self):
        with pytest.raises(ValueError):
            BodyCanonUpdate(marked_regions=["nonsense"])

    def test_old_json_without_marked_regions_parses(self):
        raw = {"body_front_image_url": BODY_FRONT}
        body = BodyCanonData(**raw)
        assert body.marked_regions is None

    def test_round_trip(self):
        body = BodyCanonData(marked_regions=["neck"])
        reloaded = BodyCanonData(**json.loads(json.dumps(body.model_dump())))
        assert reloaded.marked_regions == ["neck"]


# ── Model profiles (matrix #14/#15) ───────────────────────────────────

class TestModelProfiles:
    def test_gpt_image_2_rejects_input_fidelity(self):
        from app.services.model_profiles import supports_input_fidelity
        assert supports_input_fidelity("gpt-image-1.5") is True
        assert supports_input_fidelity("gpt-image-1") is True
        assert supports_input_fidelity("gpt-image-2") is False

    def test_versioned_model_ids_resolve_by_prefix(self):
        from app.services.model_profiles import model_profile
        assert model_profile("openai", "gpt-image-2-2026-04-21").supports_input_fidelity is False
        assert model_profile("openai", "gpt-image-1.5-preview").supports_input_fidelity is True

    def test_openai_reference_hard_limit_is_16(self):
        from app.services.model_profiles import model_profile
        assert model_profile("openai", "gpt-image-2").max_reference_images == 16

    def test_google_has_no_documented_reference_limit(self):
        from app.services.model_profiles import model_profile
        assert model_profile("google", "gemini-3.1-flash-image").max_reference_images is None

    def test_unknown_model_gets_conservative_default(self):
        from app.services.model_profiles import model_profile
        p = model_profile("openai", "gpt-image-99-hypothetical")
        # 99 doesn't prefix-match 1/1.5/2 → conservative default.
        assert p.supports_input_fidelity is False

    def test_app_ref_budget_never_exceeds_hard_limits(self):
        # The routing budget must stay inside every provider's documented cap.
        from app.services.model_profiles import _PROFILES
        from app.services.scene_router import MAX_PROVIDER_REFS
        for profile in _PROFILES.values():
            if profile.max_reference_images is not None:
                assert MAX_PROVIDER_REFS <= profile.max_reference_images

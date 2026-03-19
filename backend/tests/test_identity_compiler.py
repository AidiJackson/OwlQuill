"""Unit tests for the identity prompt compiler."""
import pytest

from app.schemas.character_visual import (
    CharacterIdentitySpec,
    IdentityCore,
    IdentityBuild,
    IdentityMarksAccessories,
    WardrobeSpec,
)
from app.services.identity_compiler import (
    NEUTRAL_STUDIO_OUTFIT,
    compile_identity_prompt,
    compile_identity_lock_string,
    identity_prompt_hash,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_grace_spec(**overrides) -> CharacterIdentitySpec:
    """Build the 'Grace' acceptance-criteria spec."""
    defaults = dict(
        style="realistic",
        gender="female",
        age_band="26-35",
        identity=IdentityCore(
            hair_color="brunette",
            hair_length="long",
            eye_color="hazel",
            skin_tone="tan",
            face_features=["soft features"],
        ),
        build=IdentityBuild(body_type="slim", height_band="average"),
        marks_accessories=None,
        wardrobe=WardrobeSpec(
            outfit_type="dress",
            primary_color="black",
            secondary_color="",
            footwear="heels",
            accessory="",
            notes="fitted",
        ),
        extra_notes="",
    )
    defaults.update(overrides)
    return CharacterIdentitySpec(**defaults)


# ── Neutral studio outfit is always enforced in prompts ──────────────

class TestNeutralOutfitEnforced:

    def test_neutral_outfit_in_prompt(self):
        """Neutral studio outfit must appear in every identity prompt."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "neutral studio outfit" in prompt.lower()

    def test_wardrobe_colors_not_in_prompt(self):
        """Wardrobe colors from spec are ignored — must not appear in prompt."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        # "black dress" from wardrobe spec must not leak into the generation prompt
        assert "black dress" not in prompt.lower()

    def test_wardrobe_footwear_not_in_prompt(self):
        """Footwear from spec is ignored — must not appear in identity prompt."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "heels" not in prompt.lower()

    def test_wardrobe_notes_not_in_prompt(self):
        """Wardrobe notes from spec are ignored."""
        spec = _make_grace_spec(
            wardrobe=WardrobeSpec(
                outfit_type="suit",
                primary_color="crimson",
                secondary_color="",
                footwear="oxford",
                accessory="monocle",
                notes="double-breasted with gold buttons",
            )
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        # wardrobe-specific notes must not leak into prompt
        assert "crimson" not in prompt.lower()
        assert "oxford" not in prompt.lower()
        assert "monocle" not in prompt.lower()
        assert "gold buttons" not in prompt.lower()

    def test_outfit_canonical_lock_present(self):
        """The canonical outfit enforcement lock must be present."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "keep this exact outfit unchanged" in prompt.lower()

    def test_different_wardrobe_specs_same_prompt(self):
        """Different wardrobe specs must produce identical prompts (wardrobe is ignored)."""
        spec_a = _make_grace_spec(
            wardrobe=WardrobeSpec(
                outfit_type="dress",
                primary_color="black",
                secondary_color="",
                footwear="heels",
                accessory="",
                notes="fitted",
            )
        )
        spec_b = _make_grace_spec(
            wardrobe=WardrobeSpec(
                outfit_type="suit",
                primary_color="navy",
                secondary_color="gold",
                footwear="boots",
                accessory="watch",
                notes="tailored",
            )
        )
        prompt_a = compile_identity_prompt(spec_a, "anchor_front")
        prompt_b = compile_identity_prompt(spec_b, "anchor_front")
        assert prompt_a == prompt_b, "Wardrobe differences must not affect identity prompt"


# ── Identity anchors appear in correct order ─────────────────────────

class TestIdentityAnchors:

    def test_gender_anchor_present(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "adult woman" in prompt.lower()

    def test_age_band_anchor_present(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "age range 26-35" in prompt.lower()

    def test_style_anchor_present(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "realistic style" in prompt.lower()

    def test_identity_core_before_outfit(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")

        identity_pos = prompt.lower().find("brunette")
        outfit_pos = prompt.lower().find("neutral studio outfit")

        assert identity_pos != -1, "identity core not found in prompt"
        assert outfit_pos != -1, "neutral studio outfit not found in prompt"
        assert identity_pos < outfit_pos, "Identity core must appear before outfit"

    def test_outfit_before_extra_notes(self):
        spec = _make_grace_spec(extra_notes="mysterious lighting, moody atmosphere")
        prompt = compile_identity_prompt(spec, "anchor_front")

        outfit_pos = prompt.lower().find("neutral studio outfit")
        notes_pos = prompt.lower().find("mysterious lighting")

        assert outfit_pos != -1, "neutral studio outfit not found in prompt"
        if notes_pos != -1:
            assert outfit_pos < notes_pos, (
                f"Outfit (pos {outfit_pos}) must appear before extra_notes (pos {notes_pos})"
            )

    def test_identity_before_build(self):
        spec = _make_grace_spec(extra_notes="warm lighting")
        prompt = compile_identity_prompt(spec, "anchor_front")

        identity_pos = prompt.lower().find("brunette")
        build_pos = prompt.lower().find("slim build")

        assert identity_pos != -1, "identity core not found in prompt"
        if build_pos != -1:
            assert identity_pos < build_pos


# ── Role changes only the shot line ──────────────────────────────────

class TestRoleChanges:

    def test_different_roles_same_identity(self):
        spec = _make_grace_spec()
        front = compile_identity_prompt(spec, "anchor_front")
        full = compile_identity_prompt(spec, "anchor_full_body")

        # Both should have same identity core
        assert "brunette" in front.lower()
        assert "brunette" in full.lower()
        assert "hazel eyes" in front.lower()
        assert "hazel eyes" in full.lower()

        # Both should have neutral studio outfit
        assert "neutral studio outfit" in front.lower()
        assert "neutral studio outfit" in full.lower()

        # The canonical identity consistency anchor must be present in both.
        # Both shots should have the consistency anchor and outfit lock
        assert "same person across all shots" in front.lower()
        assert "same person across all shots" in full.lower()
        assert "keep this exact outfit unchanged" in front.lower()
        assert "keep this exact outfit unchanged" in full.lower()

    def test_role_shot_description_present(self):
        spec = _make_grace_spec()
        for role in ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"]:
            prompt = compile_identity_prompt(spec, role)
            assert len(prompt) > 0


# ── Cap is 800 and trimming keeps neutral outfit intact ───────────────

class TestPromptCap:

    def test_prompt_within_800(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800

    def test_long_marks_trimmed_neutral_outfit_kept(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(
                items=["intricate tribal tattoo on left arm"] * 30,
            ),
            extra_notes="warm moody atmospheric cinematic lighting with depth",
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800
        # Neutral outfit must survive trimming
        assert "neutral studio outfit" in prompt.lower()

    def test_many_sections_trimmed_neutral_outfit_survives(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(
                items=["ornate dragon tattoo covering entire back and shoulders"] * 20,
            ),
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800
        assert "neutral studio outfit" in prompt.lower()


# ── Regression: prompts are stable across regenerate calls ───────────

class TestPromptStability:

    def test_hash_stable(self):
        """The same identity spec must produce the same prompt hash."""
        spec = _make_grace_spec()
        hash1 = identity_prompt_hash(spec)
        hash2 = identity_prompt_hash(spec)
        assert hash1 == hash2

    def test_prompt_deterministic(self):
        """Regenerating with the same spec must produce the identical prompt."""
        spec = _make_grace_spec()
        prompt1 = compile_identity_prompt(spec, "anchor_front")
        prompt2 = compile_identity_prompt(spec, "anchor_front")
        assert prompt1 == prompt2

    def test_neutral_outfit_consistent(self):
        """Neutral outfit must be the same regardless of wardrobe spec."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert NEUTRAL_STUDIO_OUTFIT in prompt

    def test_lock_string_stable(self):
        spec = _make_grace_spec()
        lock1 = compile_identity_lock_string(spec)
        lock2 = compile_identity_lock_string(spec)
        assert lock1 == lock2
        assert "brunette" in lock1.lower()


# ── Failsafe mode still generates a valid prompt ─────────────────────

class TestFailsafeMode:

    def test_failsafe_neutral_outfit_present(self):
        """Failsafe mode still uses the neutral studio outfit."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front", failsafe=True)
        assert "neutral studio outfit" in prompt.lower()

    def test_failsafe_no_wardrobe_colors(self):
        """Failsafe mode must not include wardrobe colors."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front", failsafe=True)
        assert "black dress" not in prompt.lower()

    def test_failsafe_keeps_identity_core(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front", failsafe=True)
        assert "brunette" in prompt.lower()
        assert "hazel eyes" in prompt.lower()


# ── Identity lock string ─────────────────────────────────────────────

class TestIdentityLockString:

    def test_contains_key_features(self):
        spec = _make_grace_spec()
        lock = compile_identity_lock_string(spec)
        assert "brunette" in lock.lower()
        assert "hazel eyes" in lock.lower()
        assert "tan skin" in lock.lower()

    def test_includes_marks(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(items=["glasses", "scar"]),
        )
        lock = compile_identity_lock_string(spec)
        assert "glasses" in lock.lower()
        assert "scar" in lock.lower()

    def test_empty_spec(self):
        spec = CharacterIdentitySpec(gender="female", age_band="18-25")
        lock = compile_identity_lock_string(spec)
        assert lock == ""


# ── Schema validation: gender and age_band are required ──────────────

class TestSchemaValidation:

    def test_missing_gender_raises(self):
        with pytest.raises(Exception):
            CharacterIdentitySpec(age_band="18-25")

    def test_missing_age_band_raises(self):
        with pytest.raises(Exception):
            CharacterIdentitySpec(gender="female")

    def test_invalid_gender_raises(self):
        with pytest.raises(Exception):
            CharacterIdentitySpec(gender="Unknown", age_band="18-25")

    def test_invalid_age_band_raises(self):
        with pytest.raises(Exception):
            CharacterIdentitySpec(gender="female", age_band="15-20")

    def test_canonical_gender_values_accepted(self):
        """Canonical lowercase values are accepted and stored as-is."""
        for gender, expected in [("female", "female"), ("male", "male"), ("other", "other")]:
            spec = CharacterIdentitySpec(gender=gender, age_band="18-25")
            assert spec.gender == expected

    def test_alias_gender_values_normalise(self):
        """Alias values (display labels, old enum) normalise to canonical."""
        for alias, expected in [
            ("Woman", "female"), ("Man", "male"), ("Non-binary", "other"),
            ("woman", "female"), ("man", "male"), ("MALE", "male"),
            ("FEMALE", "female"), ("nonbinary", "other"),
        ]:
            spec = CharacterIdentitySpec(gender=alias, age_band="18-25")
            assert spec.gender == expected, f"{alias!r} → expected {expected!r}, got {spec.gender!r}"

    def test_valid_age_bands_accepted(self):
        for age_band in ["18-25", "26-35", "36-50", "50+"]:
            spec = CharacterIdentitySpec(gender="female", age_band=age_band)
            assert spec.age_band == age_band

    def test_gender_in_prompt(self):
        """Gender maps to gendered noun: male→man, female→woman, other→person."""
        for gender, expected_token in [
            ("female", "adult woman"),
            ("male", "adult man"),
            ("other", "adult person"),
            # aliases should also produce the canonical noun form
            ("Woman", "adult woman"),
            ("Man", "adult man"),
        ]:
            spec = CharacterIdentitySpec(gender=gender, age_band="26-35")
            prompt = compile_identity_prompt(spec, "anchor_front")
            assert expected_token in prompt.lower(), (
                f"gender={gender!r}: expected {expected_token!r} in prompt"
            )


# ── B11: Species tells in identity prompts ───────────────────────────

class TestSpeciesInPrompt:

    def test_human_species_not_in_prompt(self):
        """Human (default) must not add any species text to the prompt."""
        spec = _make_grace_spec(species="human")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "human" not in prompt.lower() or "non-human" not in prompt.lower()
        # Specifically: should not mention 'human character' verbatim
        assert "human character" not in prompt.lower()

    def test_vampire_species_in_prompt(self):
        """vampire species must appear in the prompt."""
        spec = _make_grace_spec(species="vampire", species_tells=[])
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "vampire" in prompt.lower()

    def test_vampire_with_tells_in_prompt(self):
        """Tells must appear (with underscores replaced by spaces) when specified."""
        spec = _make_grace_spec(
            species="vampire",
            species_tells=["subtle_fangs", "predatory_gaze"],
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "vampire" in prompt.lower()
        assert "subtle fangs" in prompt.lower()
        assert "predatory gaze" in prompt.lower()

    def test_werewolf_species_in_prompt(self):
        spec = _make_grace_spec(species="werewolf", species_tells=["golden_eyes"])
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "werewolf" in prompt.lower()
        assert "golden eyes" in prompt.lower()

    def test_species_prompt_in_all_roles(self):
        """Species must appear in every pack role, not just anchor_front."""
        spec = _make_grace_spec(species="fae", species_tells=["pointed_ears"])
        for role in ("anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"):
            prompt = compile_identity_prompt(spec, role)
            assert "fae" in prompt.lower(), f"fae missing from role={role}"
            assert "pointed ears" in prompt.lower(), f"tell missing from role={role}"


# ── B15: Hair texture, hair style, eyebrow shape in identity prompts ──

class TestB15FieldsInPrompt:

    def test_hair_texture_in_prompt(self):
        """hair_texture must appear in the identity prompt."""
        spec = _make_grace_spec(hair_texture="wavy")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "wavy" in prompt.lower(), f"'wavy' not found in prompt: {prompt!r}"

    def test_hair_style_in_prompt(self):
        """hair_style must appear in the identity prompt."""
        spec = _make_grace_spec(hair_style="loose")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "loose" in prompt.lower(), f"'loose' not found in prompt: {prompt!r}"

    def test_hair_style_with_underscore_expanded(self):
        """tied_back must appear as 'tied back' (underscore → space) in prompt."""
        spec = _make_grace_spec(hair_style="tied_back")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "tied back" in prompt.lower(), f"'tied back' not found in prompt: {prompt!r}"

    def test_eyebrow_shape_in_prompt(self):
        """eyebrow_shape must appear in the identity prompt."""
        spec = _make_grace_spec(eyebrow_shape="arched")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "arched eyebrows" in prompt.lower(), f"'arched eyebrows' not found in prompt: {prompt!r}"

    def test_eyebrow_shape_thin_in_prompt(self):
        """eyebrow_shape=thin must appear as 'thin eyebrows'."""
        spec = _make_grace_spec(eyebrow_shape="thin")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "thin eyebrows" in prompt.lower()

    def test_wide_set_eye_spacing_in_prompt(self):
        """eye_spacing=wide_set must appear as 'wide set eyes' in prompt."""
        spec = _make_grace_spec(eye_spacing="wide_set")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "wide set eyes" in prompt.lower()

    def test_close_set_eye_spacing_in_prompt(self):
        """eye_spacing=close_set must appear in prompt."""
        spec = _make_grace_spec(eye_spacing="close_set")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "close set eyes" in prompt.lower()

    def test_average_eye_spacing_not_in_prompt(self):
        """eye_spacing=average (the default) must not add redundant text."""
        spec = _make_grace_spec(eye_spacing="average")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "average eyes" not in prompt.lower()

    def test_natural_hair_description_combined(self):
        """hair_length + hair_style + hair_texture + hair_color must form a natural phrase."""
        spec = _make_grace_spec(
            hair_texture="wavy",
            hair_style="loose",
            identity=CharacterIdentitySpec.__fields__['identity'].default,  # type: ignore[attr-defined]
        )
        # Rebuild with full identity so hair_color is set
        from app.schemas.character_visual import IdentityCore
        spec = _make_grace_spec(
            hair_texture="wavy",
            hair_style="loose",
            identity=IdentityCore(
                hair_color="brunette",
                hair_length="long",
                eye_color="hazel",
                skin_tone="tan",
                face_features=[],
            ),
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        # All four components must appear in proximity
        assert "wavy" in prompt.lower()
        assert "loose" in prompt.lower()
        assert "brunette" in prompt.lower()

    def test_b15_fields_within_cap(self):
        """Prompt with all B15 fields must still be within 800-char cap."""
        spec = _make_grace_spec(
            hair_texture="curly",
            hair_style="side_parted",
            eyebrow_shape="thick",
            eye_spacing="wide_set",
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800, f"Prompt over cap: {len(prompt)} chars"


# ── B16: Body morphology (Height + Build) ────────────────────────────

def _make_morphology_spec(body_height=None, body_build=None, **overrides) -> CharacterIdentitySpec:
    """Build a spec with optional body_height and body_build fields."""
    base = dict(
        style="realistic",
        gender="female",
        age_band="26-35",
        identity=IdentityCore(
            hair_color="brunette",
            hair_length="long",
            eye_color="hazel",
            skin_tone="tan",
        ),
    )
    base.update(overrides)
    spec = CharacterIdentitySpec(**base)
    spec.body_height = body_height
    spec.body_build = body_build
    return spec


class TestBodyMorphologyPrompt:
    """B16: body_height and body_build are injected with mapped descriptors."""

    def test_height_short_in_prompt(self):
        spec = _make_morphology_spec(body_height="short")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "short stature" in prompt

    def test_height_medium_in_prompt(self):
        spec = _make_morphology_spec(body_height="medium")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "average height" in prompt

    def test_height_tall_in_prompt(self):
        spec = _make_morphology_spec(body_height="tall")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "tall stature" in prompt

    def test_build_slim_in_prompt(self):
        spec = _make_morphology_spec(body_build="slim")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "slim build, narrow shoulders, lean frame" in prompt

    def test_build_athletic_in_prompt(self):
        spec = _make_morphology_spec(body_build="athletic")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "athletic build, defined shoulders, balanced physique" in prompt

    def test_build_muscular_in_prompt(self):
        spec = _make_morphology_spec(body_build="muscular")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "muscular build, broad shoulders, powerful chest and arms" in prompt

    def test_build_stocky_in_prompt(self):
        spec = _make_morphology_spec(body_build="stocky")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "stocky muscular build" in prompt

    def test_build_heavy_in_prompt(self):
        spec = _make_morphology_spec(body_build="heavy")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "large heavy build" in prompt

    def test_height_and_build_together(self):
        """Both height and build appear in the same prompt."""
        spec = _make_morphology_spec(body_height="tall", body_build="muscular")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "tall stature" in prompt
        assert "muscular build, broad shoulders, powerful chest and arms" in prompt

    def test_no_morphology_no_raw_keywords(self):
        """When body_height/body_build are None the mapped phrases must not appear."""
        spec = _make_morphology_spec()  # no body fields
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "stature" not in prompt
        assert "average height" not in prompt

    def test_morphology_prompt_within_cap(self):
        """Prompt with all B16 fields must remain within 800-char cap."""
        spec = _make_morphology_spec(body_height="tall", body_build="stocky")
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert len(prompt) <= 800, f"Prompt over cap: {len(prompt)} chars"


class TestBodyMorphologyLockString:
    """B16: body_height and body_build appear in the identity lock string (for scene consistency)."""

    def test_height_in_lock_string(self):
        spec = _make_morphology_spec(body_height="short")
        lock = compile_identity_lock_string(spec)
        assert "short stature" in lock

    def test_build_in_lock_string(self):
        spec = _make_morphology_spec(body_build="athletic")
        lock = compile_identity_lock_string(spec)
        assert "athletic build, defined shoulders, balanced physique" in lock

    def test_height_and_build_in_lock_string(self):
        spec = _make_morphology_spec(body_height="tall", body_build="slim")
        lock = compile_identity_lock_string(spec)
        assert "tall stature" in lock
        assert "slim build, narrow shoulders, lean frame" in lock

    def test_no_morphology_not_in_lock_string(self):
        spec = _make_morphology_spec()
        lock = compile_identity_lock_string(spec)
        assert "stature" not in lock
        assert "build" not in lock


class TestBodyMorphologyDefaults:
    """B16: schema defaults and validator behaviour."""

    def test_body_height_default_is_none(self):
        """Without body_height the field defaults to None (no morphology injected)."""
        spec = CharacterIdentitySpec(
            style="realistic",
            gender="female",
            age_band="26-35",
        )
        assert spec.body_height is None

    def test_body_build_default_is_none(self):
        spec = CharacterIdentitySpec(
            style="realistic",
            gender="female",
            age_band="26-35",
        )
        assert spec.body_build is None

    def test_body_height_medium_accepted(self):
        spec = CharacterIdentitySpec(
            style="realistic",
            gender="female",
            age_band="26-35",
            body_height="medium",
        )
        assert spec.body_height == "medium"

    def test_body_build_athletic_accepted(self):
        spec = CharacterIdentitySpec(
            style="realistic",
            gender="female",
            age_band="26-35",
            body_build="athletic",
        )
        assert spec.body_build == "athletic"

    def test_invalid_body_height_raises(self):
        import pytest
        with pytest.raises(Exception):
            CharacterIdentitySpec(
                style="realistic",
                gender="female",
                age_band="26-35",
                body_height="gigantic",
            )

    def test_invalid_body_build_raises(self):
        import pytest
        with pytest.raises(Exception):
            CharacterIdentitySpec(
                style="realistic",
                gender="female",
                age_band="26-35",
                body_build="ripped",
            )


# ── B21: Facial geometry in identity prompts and lock string ──────────


class TestFacialGeometryInPrompt:
    """B21: B14 facial geometry fields are injected into identity prompts for generic-face hardening."""

    def test_face_shape_in_prompt(self):
        """face_shape must appear in the identity prompt."""
        spec = _make_grace_spec(face_shape="oval")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "oval" in prompt.lower(), f"face_shape 'oval' not in prompt: {prompt!r}"
        assert "face shape" in prompt.lower(), f"'face shape' label missing: {prompt!r}"

    def test_jaw_type_in_prompt(self):
        """jaw_type must appear in the identity prompt."""
        spec = _make_grace_spec(jaw_type="sharp")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "sharp" in prompt.lower(), f"jaw_type 'sharp' not in prompt: {prompt!r}"
        assert "jaw" in prompt.lower(), f"'jaw' label missing: {prompt!r}"

    def test_cheekbone_type_in_prompt(self):
        """cheekbone_type must appear in the identity prompt."""
        spec = _make_grace_spec(cheekbone_type="high")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "high" in prompt.lower()
        assert "cheekbone" in prompt.lower(), f"'cheekbones' missing: {prompt!r}"

    def test_eye_shape_in_prompt(self):
        """eye_shape must appear in the identity prompt."""
        spec = _make_grace_spec(eye_shape="almond")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "almond" in prompt.lower(), f"eye_shape 'almond' not in prompt: {prompt!r}"

    def test_eye_shape_deep_set_expanded(self):
        """deep_set must appear as 'deep set' (underscore → space)."""
        spec = _make_grace_spec(eye_shape="deep_set")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "deep set" in prompt.lower(), f"'deep set' not found in prompt: {prompt!r}"

    def test_nose_type_in_prompt(self):
        """nose_type must appear in the identity prompt."""
        spec = _make_grace_spec(nose_type="straight")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "straight" in prompt.lower()
        assert "nose" in prompt.lower(), f"'nose' label missing: {prompt!r}"

    def test_nose_type_roman_in_prompt(self):
        """nose_type=roman must appear."""
        spec = _make_grace_spec(nose_type="roman")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "roman" in prompt.lower()
        assert "nose" in prompt.lower()

    def test_lip_type_in_prompt(self):
        """lip_type must appear in the identity prompt."""
        spec = _make_grace_spec(lip_type="full")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "full" in prompt.lower()
        assert "lips" in prompt.lower(), f"'lips' label missing: {prompt!r}"

    def test_lip_type_cupid_bow_expanded(self):
        """cupid_bow must appear as 'cupid bow' (underscore → space)."""
        spec = _make_grace_spec(lip_type="cupid_bow")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "cupid bow" in prompt.lower(), f"'cupid bow' not found in prompt: {prompt!r}"

    def test_hairline_type_in_prompt(self):
        """hairline_type must appear in the identity prompt."""
        spec = _make_grace_spec(hairline_type="widows_peak")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "widows peak" in prompt.lower(), f"'widows peak' not found: {prompt!r}"
        assert "hairline" in prompt.lower()

    def test_facial_hair_stubble_in_prompt(self):
        """facial_hair_type=stubble must appear in the identity prompt."""
        spec = _make_grace_spec(facial_hair_type="stubble")
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "stubble" in prompt.lower(), f"'stubble' not in prompt: {prompt!r}"

    def test_facial_hair_none_not_injected(self):
        """facial_hair_type=none must NOT add any text to the prompt."""
        spec = _make_grace_spec(facial_hair_type="none")
        prompt_with_none = compile_identity_prompt(spec, "anchor_front")
        spec_no_fh = _make_grace_spec()
        prompt_no_field = compile_identity_prompt(spec_no_fh, "anchor_front")
        # 'none' as a facial hair value must not inject the word 'none' into prompt
        # (prompts are identical since neither has meaningful facial hair)
        assert "none" not in prompt_with_none.split("neutral")[0].lower()

    def test_all_geometry_fields_within_cap(self):
        """Full set of facial geometry fields must remain within 800-char cap."""
        spec = _make_grace_spec(
            face_shape="oval",
            jaw_type="sharp",
            cheekbone_type="high",
            eye_shape="almond",
            nose_type="straight",
            lip_type="full",
            hairline_type="widows_peak",
            facial_hair_type="stubble",
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800, f"Prompt over cap: {len(prompt)} chars — {prompt!r}"

    def test_geometry_in_all_roles(self):
        """Face geometry must appear in every pack role, not just anchor_front."""
        spec = _make_grace_spec(face_shape="square", nose_type="broad")
        for role in ("anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"):
            prompt = compile_identity_prompt(spec, role)
            assert "square" in prompt.lower(), f"face_shape missing from role={role}"
            assert "broad" in prompt.lower(), f"nose_type missing from role={role}"

    def test_no_geometry_no_extra_text(self):
        """When no B14 geometry fields are set, no geometry text is added to the prompt."""
        spec = _make_grace_spec()  # no face_shape, jaw, nose, etc.
        prompt = compile_identity_prompt(spec, "anchor_front")
        # None of these geometry labels should appear when fields are unset
        assert "face shape" not in prompt.lower()
        assert " jaw" not in prompt.lower()
        assert "cheekbone" not in prompt.lower()
        assert " nose" not in prompt.lower()
        assert " lips" not in prompt.lower()
        assert "hairline" not in prompt.lower()


class TestFacialGeometryInLockString:
    """B21: core face geometry fields appear in the identity lock string for scene consistency."""

    def test_face_shape_in_lock_string(self):
        spec = _make_grace_spec(face_shape="oval")
        lock = compile_identity_lock_string(spec)
        assert "oval" in lock.lower(), f"face_shape 'oval' not in lock: {lock!r}"
        assert "face" in lock.lower()

    def test_jaw_type_in_lock_string(self):
        spec = _make_grace_spec(jaw_type="sharp")
        lock = compile_identity_lock_string(spec)
        assert "sharp" in lock.lower()
        assert "jaw" in lock.lower()

    def test_nose_type_in_lock_string(self):
        spec = _make_grace_spec(nose_type="straight")
        lock = compile_identity_lock_string(spec)
        assert "straight" in lock.lower()
        assert "nose" in lock.lower(), f"'nose' missing from lock: {lock!r}"

    def test_lip_type_in_lock_string(self):
        spec = _make_grace_spec(lip_type="full")
        lock = compile_identity_lock_string(spec)
        assert "full" in lock.lower()
        assert "lip" in lock.lower(), f"'lips' missing from lock: {lock!r}"

    def test_no_geometry_no_geometry_in_lock_string(self):
        """When no face geometry is set, no geometry terms appear in the lock string."""
        spec = _make_grace_spec()  # default Grace spec — no face_shape, jaw, etc.
        lock = compile_identity_lock_string(spec)
        assert "face shape" not in lock.lower()
        assert " jaw" not in lock.lower()
        assert " nose" not in lock.lower()
        assert " lips" not in lock.lower()

    def test_geometry_lock_string_stable(self):
        """Lock strings with geometry fields must be deterministic."""
        spec = _make_grace_spec(face_shape="oval", jaw_type="sharp", nose_type="straight")
        lock1 = compile_identity_lock_string(spec)
        lock2 = compile_identity_lock_string(spec)
        assert lock1 == lock2

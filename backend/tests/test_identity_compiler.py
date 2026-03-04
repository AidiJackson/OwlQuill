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

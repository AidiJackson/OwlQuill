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
    compile_identity_prompt,
    compile_identity_lock_string,
    identity_prompt_hash,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_grace_spec(**overrides) -> CharacterIdentitySpec:
    """Build the 'Grace' acceptance-criteria spec."""
    defaults = dict(
        style="realistic",
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


# ── Compiled prompt includes wardrobe color + outfit type ────────────

class TestWardrobeInPrompt:

    def test_wardrobe_color_and_type_present(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "black" in prompt.lower()
        assert "dress" in prompt.lower()

    def test_wardrobe_with_secondary_color(self):
        spec = _make_grace_spec(
            wardrobe=WardrobeSpec(
                outfit_type="suit",
                primary_color="navy",
                secondary_color="gold",
                footwear="",
                accessory="",
                notes="",
            ),
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "navy" in prompt.lower()
        assert "gold" in prompt.lower()
        assert "suit" in prompt.lower()

    def test_wardrobe_footwear_included(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_full_body")
        assert "heels" in prompt.lower()

    def test_wardrobe_notes_included(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "fitted" in prompt.lower()


# ── Wardrobe appears before vibe traits in prompt ────────────────────

class TestWardrobeOrdering:

    def test_wardrobe_before_extra_notes(self):
        spec = _make_grace_spec(extra_notes="mysterious lighting, moody atmosphere")
        prompt = compile_identity_prompt(spec, "anchor_front")

        wardrobe_pos = prompt.lower().find("black dress")
        notes_pos = prompt.lower().find("mysterious lighting")

        assert wardrobe_pos != -1, "wardrobe not found in prompt"
        assert notes_pos != -1, "extra_notes not found in prompt"
        assert wardrobe_pos < notes_pos, (
            f"Wardrobe (pos {wardrobe_pos}) must appear before extra_notes (pos {notes_pos})"
        )

    def test_wardrobe_before_build_section(self):
        spec = _make_grace_spec(extra_notes="warm lighting")
        prompt = compile_identity_prompt(spec, "anchor_front")

        wardrobe_pos = prompt.lower().find("black dress")
        build_pos = prompt.lower().find("slim build")

        assert wardrobe_pos != -1, "wardrobe not found in prompt"
        assert build_pos != -1, "build not found in prompt"
        assert wardrobe_pos < build_pos, (
            f"Wardrobe (pos {wardrobe_pos}) must appear before build (pos {build_pos})"
        )

    def test_identity_before_wardrobe(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")

        identity_pos = prompt.lower().find("brunette")
        wardrobe_pos = prompt.lower().find("black dress")

        assert identity_pos != -1
        assert wardrobe_pos != -1
        assert identity_pos < wardrobe_pos


# ── Role changes only the shot line ──────────────────────────────────

class TestRoleChanges:

    def test_different_roles_same_identity_and_wardrobe(self):
        spec = _make_grace_spec()
        front = compile_identity_prompt(spec, "anchor_front")
        full = compile_identity_prompt(spec, "anchor_full_body")

        # Both should have same identity core
        assert "brunette" in front.lower()
        assert "brunette" in full.lower()
        assert "hazel eyes" in front.lower()
        assert "hazel eyes" in full.lower()

        # Both should have same wardrobe
        assert "black dress" in front.lower()
        assert "black dress" in full.lower()

        # Shot descriptions should differ
        assert "headshot" in front.lower()
        assert "full-body" in full.lower()

    def test_role_shot_description_present(self):
        spec = _make_grace_spec()
        for role in ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"]:
            prompt = compile_identity_prompt(spec, role)
            # Each role should have its specific shot framing
            assert len(prompt) > 0


# ── Cap is 800 and trimming keeps wardrobe intact ────────────────────

class TestPromptCap:

    def test_prompt_within_800(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800

    def test_long_marks_trimmed_wardrobe_kept(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(
                items=["intricate tribal tattoo on left arm"] * 30,
            ),
            extra_notes="warm moody atmospheric cinematic lighting with depth",
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800
        # Wardrobe must survive trimming
        assert "black" in prompt.lower()
        assert "dress" in prompt.lower()

    def test_many_sections_trimmed_wardrobe_survives(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(
                items=["ornate dragon tattoo covering entire back and shoulders"] * 20,
            ),
        )
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert len(prompt) <= 800
        assert "black" in prompt.lower()
        assert "dress" in prompt.lower()


# ── Regression: black dress stays black across regenerate calls ──────

class TestPromptStability:

    def test_black_dress_hash_stable(self):
        """The same identity spec must produce the same prompt hash."""
        spec = _make_grace_spec()
        hash1 = identity_prompt_hash(spec)
        hash2 = identity_prompt_hash(spec)
        assert hash1 == hash2

    def test_black_dress_prompt_deterministic(self):
        """Regenerating with the same spec must produce the identical prompt."""
        spec = _make_grace_spec()
        prompt1 = compile_identity_prompt(spec, "anchor_front")
        prompt2 = compile_identity_prompt(spec, "anchor_front")
        assert prompt1 == prompt2

    def test_black_dress_stays_black_not_white(self):
        """Black dress spec must compile to a prompt containing 'black dress',
        not 'white blazer' or any other wardrobe drift."""
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front")
        assert "black" in prompt.lower()
        assert "dress" in prompt.lower()
        assert "white blazer" not in prompt.lower()

    def test_lock_string_stable(self):
        spec = _make_grace_spec()
        lock1 = compile_identity_lock_string(spec)
        lock2 = compile_identity_lock_string(spec)
        assert lock1 == lock2
        assert "brunette" in lock1.lower()
        assert "black dress" in lock1.lower()


# ── Failsafe mode softens wardrobe ───────────────────────────────────

class TestFailsafeMode:

    def test_failsafe_keeps_outfit_type(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front", failsafe=True)
        assert "dress" in prompt.lower()

    def test_failsafe_drops_colors(self):
        spec = _make_grace_spec()
        prompt = compile_identity_prompt(spec, "anchor_front", failsafe=True)
        # In failsafe, colors are dropped, "simple dress" used instead
        assert "simple dress" in prompt.lower()

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
        assert "black dress" in lock.lower()

    def test_includes_marks(self):
        spec = _make_grace_spec(
            marks_accessories=IdentityMarksAccessories(items=["glasses", "scar"]),
        )
        lock = compile_identity_lock_string(spec)
        assert "glasses" in lock.lower()
        assert "scar" in lock.lower()

    def test_empty_spec(self):
        spec = CharacterIdentitySpec()
        lock = compile_identity_lock_string(spec)
        assert lock == ""

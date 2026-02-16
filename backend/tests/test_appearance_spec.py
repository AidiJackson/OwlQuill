"""Unit tests for the appearance-spec rewrite pipeline."""
import pytest

from app.services.appearance_spec import (
    build_appearance_spec,
    build_generation_prompt,
    PromptBlockedError,
)


# ── build_appearance_spec: soft rewrites ─────────────────────────────

class TestSoftRewrites:

    def test_sexy_tight_dress(self):
        spec, meta = build_appearance_spec("sexy tight dress")
        assert "sexy" not in spec.lower()
        assert "tight" not in spec.lower()
        assert "confident" in spec.lower()
        assert "fitted" in spec.lower()
        assert meta["did_rewrite"] is True

    def test_bikini_model(self):
        spec, meta = build_appearance_spec("bikini model")
        assert "bikini" not in spec.lower()
        assert "swimsuit" in spec.lower()
        assert meta["did_rewrite"] is True

    def test_strappy_dress(self):
        spec, meta = build_appearance_spec("strappy fitted dress")
        assert "strappy" not in spec.lower()
        assert "sleek" in spec.lower()

    def test_lingerie(self):
        spec, meta = build_appearance_spec("red lingerie")
        assert "lingerie" not in spec.lower()
        assert "eveningwear" in spec.lower()

    def test_model_thin_rewrite(self):
        spec, meta = build_appearance_spec("model thin nose, full lips")
        assert "model thin" not in spec.lower()
        assert "model-like" in spec.lower() or "slender nose" in spec.lower()
        assert "full lips" not in spec.lower()
        assert "defined lips" in spec.lower()

    def test_thin_nose_rewrite(self):
        spec, _ = build_appearance_spec("thin nose, blue eyes")
        assert "thin nose" not in spec.lower()
        assert "slender nose" in spec.lower()

    def test_preserves_safe_input(self):
        safe = "adult, long brunette hair, hazel eyes, elegant dress"
        spec, meta = build_appearance_spec(safe)
        # Should not alter an already-safe prompt significantly
        assert "brunette hair" in spec
        assert "hazel eyes" in spec

    def test_empty_input(self):
        spec, meta = build_appearance_spec("")
        assert spec == ""
        assert meta["did_rewrite"] is False

    def test_none_like_input(self):
        spec, meta = build_appearance_spec("   ")
        assert spec == ""
        assert meta["did_rewrite"] is False


# ── build_appearance_spec: adult anchor ──────────────────────────────

class TestAdultAnchor:

    def test_adds_adult_anchor(self):
        spec, meta = build_appearance_spec("long hair, blue eyes")
        assert spec.lower().startswith("adult")

    def test_preserves_existing_adult(self):
        spec, _ = build_appearance_spec("adult woman, long hair")
        # Should not double-add
        assert spec.lower().count("adult") == 1


# ── build_appearance_spec: ethnicity parenthetical removal ───────────

class TestEthnicityStrip:

    def test_white_american_removed(self):
        spec, meta = build_appearance_spec(
            "28yrs old, brunette hair, tanned skin (white american)"
        )
        assert "(white american)" not in spec
        assert "tanned skin" in spec
        assert "ethnicity_parenthetical_removed" in meta["reasons"]

    def test_mixed_race_removed(self):
        spec, _ = build_appearance_spec("curly hair (mixed race heritage)")
        assert "(mixed race heritage)" not in spec

    def test_non_ethnicity_parens_kept(self):
        spec, _ = build_appearance_spec("long hair (shoulder length)")
        assert "(shoulder length)" in spec

    def test_standalone_white_american_removed(self):
        """Standalone 'White American' (no parentheses) must be stripped."""
        spec, meta = build_appearance_spec(
            "Naturally beautiful with tanned skin. White American. "
            "Brunette hair long with slight curl."
        )
        assert "white american" not in spec.lower()
        assert "tanned skin" in spec
        assert "brunette hair" in spec.lower()
        assert "ethnicity_standalone_removed" in meta["reasons"]

    def test_standalone_black_woman_removed(self):
        spec, meta = build_appearance_spec(
            "Black woman, long braids, dark skin, elegant dress"
        )
        assert "black woman" not in spec.lower()
        assert "dark skin" in spec

    def test_standalone_asian_american_removed(self):
        spec, meta = build_appearance_spec(
            "Asian American, dark hair, brown eyes, casual outfit"
        )
        assert "asian american" not in spec.lower()
        assert "dark hair" in spec


# ── build_appearance_spec: blocked content ───────────────────────────

class TestBlocked:

    def test_nude_blocked(self):
        with pytest.raises(PromptBlockedError) as exc_info:
            build_appearance_spec("nude portrait")
        assert exc_info.value.reason == "explicit_content"

    def test_topless_blocked(self):
        with pytest.raises(PromptBlockedError):
            build_appearance_spec("topless on beach")

    def test_nsfw_blocked(self):
        with pytest.raises(PromptBlockedError):
            build_appearance_spec("nsfw glamour shot")

    def test_teen_blocked(self):
        with pytest.raises(PromptBlockedError) as exc_info:
            build_appearance_spec("teen girl in dress")
        assert exc_info.value.reason == "minor_content"

    def test_schoolgirl_blocked(self):
        with pytest.raises(PromptBlockedError):
            build_appearance_spec("schoolgirl uniform")

    def test_age_18_blocked(self):
        with pytest.raises(PromptBlockedError) as exc_info:
            build_appearance_spec("18yr old woman")
        assert exc_info.value.reason == "underage_age"

    def test_age_15_blocked(self):
        with pytest.raises(PromptBlockedError):
            build_appearance_spec("15 years old girl")

    def test_age_21_allowed(self):
        spec, _ = build_appearance_spec("21yr old woman, elegant")
        assert "21" in spec

    def test_age_28_allowed(self):
        spec, _ = build_appearance_spec("28yrs old, brunette hair")
        assert "28" in spec


# ── build_appearance_spec: conservative mode ─────────────────────────

class TestConservativeMode:

    def test_strips_outfit_words(self):
        spec, meta = build_appearance_spec(
            "28yrs old, long hair, hazel eyes, sexy tight dress, tanned skin",
            conservative=True,
        )
        assert "dress" not in spec.lower()
        assert "fitted" not in spec.lower()
        assert "long hair" in spec
        assert "hazel eyes" in spec
        assert "tanned skin" in spec

    def test_keeps_identity_features(self):
        spec, _ = build_appearance_spec(
            "adult, blonde hair, green eyes, olive skin, athletic build",
            conservative=True,
        )
        assert "blonde hair" in spec
        assert "green eyes" in spec
        assert "olive skin" in spec


# ── build_appearance_spec: height removal ────────────────────────────

class TestHeightRemoval:

    def test_height_59_removed(self):
        spec, meta = build_appearance_spec(
            "5'9 height. Brunette hair, hazel eyes"
        )
        assert "5'9" not in spec
        assert "brunette hair" in spec.lower()
        assert "height_removed" in meta["reasons"]

    def test_height_62_removed(self):
        spec, meta = build_appearance_spec(
            "Long hair, 6'2 tall, blue eyes"
        )
        assert "6'2" not in spec
        assert "blue eyes" in spec

    def test_non_height_numbers_kept(self):
        spec, _ = build_appearance_spec("28yrs old, size 8 dress")
        assert "28" in spec


# ── build_appearance_spec: failsafe mode ─────────────────────────────

class TestFailsafeMode:

    def test_failsafe_keeps_identity_core(self):
        spec, meta = build_appearance_spec(
            "Naturally beautiful with tanned skin. White American. "
            "Brunette hair long with slight curl. 5'9 height. "
            "Elegant black dress. Model thin nose, full lips. Hazel eyes.",
            failsafe=True,
        )
        assert "failsafe_extract" in meta["reasons"]
        # Should keep identity features
        assert "hazel eyes" in spec.lower()
        assert "tanned skin" in spec.lower()
        # Should not contain ethnicity
        assert "white american" not in spec.lower()

    def test_failsafe_returns_adult_anchor_on_empty(self):
        """Even with unrecognisable input, failsafe returns *something*."""
        spec, meta = build_appearance_spec(
            "xyz foo bar baz",
            failsafe=True,
        )
        assert "failsafe_extract" in meta["reasons"]
        assert "adult" in spec.lower()
        assert len(spec) > 0

    def test_failsafe_implies_conservative(self):
        spec, meta = build_appearance_spec(
            "sexy tight dress, blonde hair, blue eyes",
            failsafe=True,
        )
        assert "sexy" not in spec.lower()
        assert "dress" not in spec.lower()


# ── build_generation_prompt ──────────────────────────────────────────

class TestBuildGenerationPrompt:

    def test_includes_safety_prefix(self):
        prompt = build_generation_prompt(
            "confident, fitted dress",
            ["Ash Valkyr", "human", "feminine"],
            "front-facing portrait",
        )
        assert "non-explicit" in prompt
        assert "fully clothed" in prompt
        assert "tasteful" in prompt
        # Safety prefix should be at the start
        assert prompt.startswith("adult, fully clothed")

    def test_respects_250_char_cap(self):
        long_spec = "a" * 200
        prompt = build_generation_prompt(
            long_spec,
            ["Character Name", "human"],
            "front-facing head-and-shoulders portrait",
        )
        assert len(prompt) <= 250

    def test_combines_all_parts(self):
        prompt = build_generation_prompt(
            "brunette, hazel eyes",
            ["Ash Valkyr", "human"],
            "front-facing portrait",
        )
        assert "Ash Valkyr" in prompt
        assert "brunette" in prompt
        assert "front-facing portrait" in prompt

    def test_empty_spec(self):
        prompt = build_generation_prompt(
            "",
            ["Ash Valkyr"],
            "front-facing portrait",
        )
        assert "Ash Valkyr" in prompt
        assert "front-facing portrait" in prompt

    def test_default_style_realistic(self):
        prompt = build_generation_prompt(
            "brunette",
            ["Test"],
            "portrait",
        )
        assert "realistic" in prompt.lower()

    def test_style_anime(self):
        prompt = build_generation_prompt(
            "silver hair",
            ["Test"],
            "portrait",
            style="anime",
        )
        assert "anime" in prompt.lower()
        # Should NOT include the realistic token
        assert "cinematic portrait, realistic" not in prompt.lower()

    def test_style_respects_250_cap(self):
        long_spec = "a" * 200
        prompt = build_generation_prompt(
            long_spec,
            ["Name"],
            "portrait",
            style="illustration",
        )
        assert len(prompt) <= 250


# ── Integration: the exact failing prompt from production ────────────

class TestRealWorldPrompts:

    def test_production_failing_prompt(self):
        """The exact prompt that triggered moderation blocks in production."""
        raw = (
            "28yrs old, long thick brunette hair, hazel eyes, "
            "naturally beautiful, strappy tight dress, "
            "tanned skin (white american)"
        )
        spec, meta = build_appearance_spec(raw)

        # Should not be blocked
        assert "strappy" not in spec
        assert "tight" not in spec
        assert "(white american)" not in spec
        assert "brunette hair" in spec
        assert "hazel eyes" in spec
        assert "tanned skin" in spec
        assert meta["did_rewrite"] is True

        # Should produce a valid generation prompt
        prompt = build_generation_prompt(
            spec,
            ["Test Character", "human", "feminine"],
            "front-facing head-and-shoulders portrait",
        )
        assert len(prompt) <= 250
        assert "non-explicit" in prompt

    def test_new_failing_prompt_from_issue(self):
        """The exact prompt from the current issue that fails in <5s."""
        raw = (
            "Naturally beautiful with tanned skin. White American. "
            "Brunette hair long with slight curl. 5'9 height. "
            "Elegant black dress. Model thin nose, full lips. Hazel eyes."
        )
        spec, meta = build_appearance_spec(raw)

        # Must not be blocked
        assert "white american" not in spec.lower()
        assert "5'9" not in spec
        assert "model thin" not in spec.lower()
        assert "full lips" not in spec.lower()
        # Identity preserved
        assert "tanned skin" in spec
        assert "hazel eyes" in spec.lower()
        assert meta["did_rewrite"] is True

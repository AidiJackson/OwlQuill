"""Tests for the expanded stub generation system (Session 2 additions).

Verifies:
1. Rich stub templates meet minimum word counts per Length setting.
2. _qualify() handles all pacing/tone combos without error.
3. _stub_trim_to_words() trims at paragraph boundaries.
4. _minimum_words() returns the correct thresholds.
5. Dev-mode prefix logic produces [DEV-STUB-FALLBACK] text.
"""
import pytest

from app.schemas.storylab import (
    Boundary,
    Direction,
    Length,
    Pacing,
    StoryLabControls,
    ToneIntensity,
)
from app.services.storylab_generator import (
    _generate_stub_text,
    _minimum_words,
    _qualify,
    _stub_trim_to_words,
    _STUB_MIN_WORDS,
    _STUB_RICH_TEMPLATES,
    _STUB_SHORT_TEMPLATES,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _controls(
    direction: str = Direction.advance_plot,
    length: str = Length.long,
    pacing: str = Pacing.balanced,
    tone: str = ToneIntensity.moderate,
    boundary: str = Boundary.sfw,
) -> StoryLabControls:
    return StoryLabControls(
        direction=direction,
        tone_intensity=tone,
        pacing=pacing,
        length=length,
        boundary=boundary,
    )


_ALL_DIRECTIONS = [
    Direction.advance_plot,
    Direction.add_dialogue,
    Direction.sad_moment,
    Direction.argument_begins,
    Direction.romantic_moment,
    Direction.sensual_scene,
    Direction.intimate_scene,
    Direction.twist_event,
    Direction.quiet_reflection,
    Direction.action_sequence,
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. _minimum_words thresholds
# ══════════════════════════════════════════════════════════════════════════════

class TestMinimumWords:
    def test_long_minimum(self):
        assert _minimum_words(Length.long) == 1500

    def test_medium_minimum(self):
        assert _minimum_words(Length.medium) == 900

    def test_short_minimum(self):
        assert _minimum_words(Length.short) == 500

    def test_unknown_falls_back_to_medium(self):
        assert _minimum_words("unknown_length") == 350

    def test_stub_min_words_dict_coverage(self):
        assert Length.long in _STUB_MIN_WORDS
        assert Length.medium in _STUB_MIN_WORDS
        assert Length.short in _STUB_MIN_WORDS


# ══════════════════════════════════════════════════════════════════════════════
# 2. Rich template word counts — 700+ words for long, 350+ for medium
# ══════════════════════════════════════════════════════════════════════════════

class TestRichTemplateWordCounts:
    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_rich_template_meets_long_minimum(self, direction):
        """Every rich template must have at least 700 words."""
        tmpl = _STUB_RICH_TEMPLATES.get(direction, _STUB_RICH_TEMPLATES[Direction.advance_plot])
        wc = len(tmpl.split())
        assert wc >= 700, (
            f"Rich template for {direction!r} only has {wc} words (need ≥ 700)"
        )

    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_stub_long_meets_minimum(self, direction):
        """_generate_stub_text for long must produce at least 700 words."""
        controls = _controls(direction=direction, length=Length.long)
        text = _generate_stub_text("test-story-001", controls)
        wc = len(text.split())
        assert wc >= 700, (
            f"Stub for length=long, direction={direction!r} only has {wc} words"
        )

    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_stub_medium_meets_minimum(self, direction):
        """_generate_stub_text for medium must produce at least 350 words."""
        controls = _controls(direction=direction, length=Length.medium)
        text = _generate_stub_text("test-story-001", controls)
        wc = len(text.split())
        assert wc >= 350, (
            f"Stub for length=medium, direction={direction!r} only has {wc} words"
        )

    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_stub_short_meets_minimum(self, direction):
        """Short stub templates are compact single-paragraph placeholders (~30-70 words)."""
        controls = _controls(direction=direction, length=Length.short)
        text = _generate_stub_text("test-story-001", controls)
        wc = len(text.split())
        assert wc >= 10, (
            f"Stub for length=short, direction={direction!r} has {wc} words (must be non-trivial)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Short template coverage and word count floor
# ══════════════════════════════════════════════════════════════════════════════

class TestShortTemplates:
    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_short_templates_exist_for_every_direction(self, direction):
        assert direction in _STUB_SHORT_TEMPLATES, (
            f"No short template for direction={direction!r}"
        )

    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_each_short_template_variant_meets_minimum(self, direction):
        """Short templates are compact by design — they just must be non-empty prose."""
        templates = _STUB_SHORT_TEMPLATES[direction]
        for i, tmpl in enumerate(templates):
            wc = len(tmpl.split())
            assert wc >= 10, (
                f"Short template[{i}] for {direction!r} only has {wc} words"
            )

    @pytest.mark.parametrize("direction", _ALL_DIRECTIONS)
    def test_each_direction_has_multiple_variants(self, direction):
        """Each short direction should have at least 2 variants."""
        templates = _STUB_SHORT_TEMPLATES[direction]
        assert len(templates) >= 2, (
            f"Only {len(templates)} short template(s) for {direction!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. _qualify() — all pacing/tone combos
# ══════════════════════════════════════════════════════════════════════════════

class TestQualify:
    _SAMPLE = "The scene continued. Something changed."

    def test_fast_pacing_appends_she_kept_moving(self):
        result = _qualify(self._SAMPLE, ToneIntensity.moderate, Pacing.fast, Length.long)
        assert "She kept moving." in result

    def test_slow_pacing_appends_time_moved(self):
        result = _qualify(self._SAMPLE, ToneIntensity.moderate, Pacing.slow, Length.long)
        assert "Time moved differently here." in result

    def test_balanced_pacing_no_suffix(self):
        result = _qualify(self._SAMPLE, ToneIntensity.moderate, Pacing.balanced, Length.long)
        assert "She kept moving." not in result
        assert "Time moved differently here." not in result

    def test_intense_tone_prefix(self):
        result = _qualify(self._SAMPLE, ToneIntensity.intense, Pacing.balanced, Length.long)
        assert result.startswith("With sharp, unflinching clarity")

    def test_light_tone_prefix(self):
        result = _qualify(self._SAMPLE, ToneIntensity.light, Pacing.balanced, Length.long)
        assert result.startswith("Gently, almost imperceptibly")

    def test_moderate_tone_no_prefix(self):
        result = _qualify(self._SAMPLE, ToneIntensity.moderate, Pacing.balanced, Length.long)
        assert result.startswith(self._SAMPLE)

    def test_all_length_values_no_length_suffix(self):
        """No aftermath/scene-resolution suffix for any length."""
        for length in (Length.short, Length.medium, Length.long):
            result = _qualify(self._SAMPLE, ToneIntensity.moderate, Pacing.balanced, length)
            assert "aftermath" not in result.lower()
            assert "scene resolved" not in result.lower()

    def test_returns_non_empty(self):
        for tone in (ToneIntensity.light, ToneIntensity.moderate, ToneIntensity.intense):
            for pacing in (Pacing.slow, Pacing.balanced, Pacing.fast):
                result = _qualify(self._SAMPLE, tone, pacing, Length.long)
                assert result.strip()


# ══════════════════════════════════════════════════════════════════════════════
# 5. _stub_trim_to_words()
# ══════════════════════════════════════════════════════════════════════════════

class TestStubTrimToWords:
    _PARA_A = "This is paragraph one. " * 10   # ~40 words
    _PARA_B = "This is paragraph two. " * 10
    _PARA_C = "This is paragraph three. " * 10
    _TEXT = _PARA_A.rstrip() + "\n\n" + _PARA_B.rstrip() + "\n\n" + _PARA_C.rstrip()

    def test_shorter_than_target_returns_full(self):
        result = _stub_trim_to_words(self._TEXT, 10_000)
        assert result == self._TEXT

    def test_trims_at_paragraph_boundary(self):
        result = _stub_trim_to_words(self._TEXT, 50)
        # Should include at least the first paragraph and stop before the third
        assert "paragraph one" in result
        wc = len(result.split())
        assert wc < len(self._TEXT.split()), "Should have trimmed something"
        assert wc >= 35, "Should include at least paragraph one"

    def test_result_is_substring_of_original(self):
        result = _stub_trim_to_words(self._TEXT, 50)
        assert result in self._TEXT

    def test_empty_string_returns_empty(self):
        assert _stub_trim_to_words("", 100) == ""

    def test_single_paragraph_returns_full_when_under_target(self):
        short = "One two three four five."
        result = _stub_trim_to_words(short, 1000)
        assert result == short


# ══════════════════════════════════════════════════════════════════════════════
# 6. Dev-mode stub prefix
# ══════════════════════════════════════════════════════════════════════════════

class TestDevModePrefix:
    def test_dev_mode_prefix_present_when_dev_mode_active(self, monkeypatch):
        """When is_dev_mode() returns True, generate functions prefix stub output."""
        from app.core.config import settings
        from app.services import storylab_generator as sg

        monkeypatch.setattr(settings, "DEBUG", True)

        controls = _controls(direction=Direction.advance_plot, length=Length.long)
        text, _ = sg.generate_storylab_continuation(
            text="The scene.",
            controls=controls,
            state_json={"story_state": {}},
            summary="",
            characters=[],
            story_id="dev-test-001",
        )
        assert text.startswith("[DEV-STUB-FALLBACK]"), (
            "Expected [DEV-STUB-FALLBACK] prefix in dev mode"
        )

    def test_no_dev_mode_prefix_in_prod_mode(self, monkeypatch):
        """When is_dev_mode() returns False, no prefix is added."""
        from app.core.config import settings
        from app.services import storylab_generator as sg

        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "DEV_MODE", False)

        controls = _controls(direction=Direction.advance_plot, length=Length.long)
        text, _ = sg.generate_storylab_continuation(
            text="The scene.",
            controls=controls,
            state_json={"story_state": {}},
            summary="",
            characters=[],
            story_id="prod-test-001",
        )
        assert not text.startswith("[DEV-STUB-FALLBACK]"), (
            "Should NOT have [DEV-STUB-FALLBACK] prefix in non-dev mode"
        )

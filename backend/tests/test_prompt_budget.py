"""Regression tests for identity prompt budget hardening.

Root cause: _build_strict_identity_prompt used a combined[:800] hard cap.
With identity_lock_string consuming ~720 chars, body_canon_str was
truncated mid-sentence and sleeve_enforcement_str was eliminated entirely.

Fix: raised cap to _STRICT_IDENTITY_PROMPT_MAX_CHARS = 2000 and replaced
the blind truncation with a section-aware join that never cuts a section.
"""
import pytest

from app.api.routes.image_generator import (
    _build_strict_identity_prompt,
    _STRICT_IDENTITY_PROMPT_MAX_CHARS,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _anchor_data(lock_string: str = "") -> dict:
    return {"identity_lock_string": lock_string}


_LONG_LOCK = (
    "Blonde hair, Blue eyes, Fair skin, Facial hair, angular face, "
    "square jaw, broad nose, balanced lips, tall stature, athletic build, "
    "defined shoulders, balanced physique"
)  # 167 chars — Leonardo's actual lock string

_BODY_CANON = (
    "BODY MARKINGS: large right arm tribal wolf mark tattoo covering full right arm; "
    "full sleeve left arm gothic script sleeve tattoo covering full left arm"
)

_SLEEVE = (
    "SLEEVE IDENTITY: left arm: left arm gothic script sleeve tattoo "
    "from shoulder to wrist — must be present if left arm is visible"
)

_CANONICAL_PROMPT = (
    "Leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts, "
    "silver chain necklace (neck)"
)


# ── Test 1: canonical garden t-shirt prompt ──────────────────────────


class TestCanonicalGardenTshirt:
    """The exact prompt that previously produced zero tattoo signal."""

    def _build(self) -> str:
        return _build_strict_identity_prompt(
            base_prompt=_CANONICAL_PROMPT,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=True,
            character_id=41,
        )

    def test_right_arm_tribal_wolf_present(self):
        assert "tribal wolf" in self._build()

    def test_right_arm_full_coverage_present(self):
        assert "full right arm" in self._build()

    def test_left_arm_gothic_script_present(self):
        assert "gothic script" in self._build()

    def test_left_arm_full_coverage_present(self):
        assert "full left arm" in self._build()

    def test_sleeve_enforcement_present(self):
        assert "SLEEVE IDENTITY" in self._build()

    def test_sleeve_left_arm_enforcement_sentence(self):
        assert "must be present if left arm is visible" in self._build()


# ── Test 2: no mid-section truncation ────────────────────────────────


class TestNoMidSectionTruncation:
    """Final prompt must never end halfway through BODY MARKINGS."""

    def test_body_markings_not_truncated(self):
        prompt = _build_strict_identity_prompt(
            base_prompt=_CANONICAL_PROMPT,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=True,
        )
        # If body_canon_str is in the prompt, the full string must be there —
        # not a truncated prefix ending mid-tattoo-description.
        assert "BODY MARKINGS" in prompt
        # The right-arm marking must be fully present (not cut at "full right arm")
        assert "full right arm" in prompt
        # The left-arm marking must be present (was previously cut)
        assert "full left arm" in prompt

    def test_prompt_does_not_end_mid_sentence_in_body_markings(self):
        prompt = _build_strict_identity_prompt(
            base_prompt=_CANONICAL_PROMPT,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str="",
            scene_complex=True,
        )
        # Must not end mid-word or mid-token from body_canon_str
        assert not prompt.endswith("full right arm")  # the old truncation point
        assert not prompt.endswith("right arm")


# ── Test 3: long lock string does not evict body canon ───────────────


class TestLongLockStringPreservesBodyCanon:
    """Even with a 300-char identity_lock_string, body canon and sleeve survive."""

    _EXTRA_LONG_LOCK = (
        "Platinum blonde hair, bright ice blue eyes, very fair Nordic skin, "
        "light stubble, angular razor jaw, pronounced Nordic cheekbones, "
        "narrow straight nose, thin lips, towering stature, lean muscular build, "
        "wide-set eyes, prominent brow ridge, elongated neck, square forehead, "
        "distinctive widow's peak hairline, defined trapezius muscles"
    )  # ~300 chars

    def test_body_canon_preserved_with_extra_long_lock(self):
        prompt = _build_strict_identity_prompt(
            base_prompt="Character standing at a bar",
            anchor_data=_anchor_data(self._EXTRA_LONG_LOCK),
            character_name="Test Character",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=False,
        )
        assert "BODY MARKINGS" in prompt, "body_canon_str absent from prompt"
        assert "full left arm" in prompt, "left arm tattoo truncated"
        assert "SLEEVE IDENTITY" in prompt, "sleeve_enforcement_str absent"

    def test_sleeve_preserved_with_extra_long_lock(self):
        prompt = _build_strict_identity_prompt(
            base_prompt="Character standing at a bar",
            anchor_data=_anchor_data(self._EXTRA_LONG_LOCK),
            character_name="Test Character",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=False,
        )
        assert _SLEEVE.strip() in prompt, "sleeve enforcement sentence not found verbatim"


# ── Test 4: scene remains first ──────────────────────────────────────


class TestSceneIsFirst:
    """The user scene prompt must always be the first token in the final prompt."""

    def test_scene_is_first_with_body_canon(self):
        scene = "Leonardo at a rooftop pool party in sunset light"
        prompt = _build_strict_identity_prompt(
            base_prompt=scene,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=True,
        )
        assert prompt.startswith(scene), (
            f"Scene is not first. Prompt starts with: {prompt[:60]!r}"
        )

    def test_scene_is_first_without_body_canon(self):
        scene = "Leonardo standing in a dimly lit hallway"
        prompt = _build_strict_identity_prompt(
            base_prompt=scene,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str="",
            sleeve_enforcement_str="",
            scene_complex=False,
        )
        assert prompt.startswith(scene)


# ── Test 5: cap respected ────────────────────────────────────────────


class TestCapRespected:
    """Final prompt must not exceed _STRICT_IDENTITY_PROMPT_MAX_CHARS."""

    def test_canonical_prompt_within_cap(self):
        prompt = _build_strict_identity_prompt(
            base_prompt=_CANONICAL_PROMPT,
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str=_BODY_CANON,
            sleeve_enforcement_str=_SLEEVE,
            scene_complex=True,
        )
        assert len(prompt) <= _STRICT_IDENTITY_PROMPT_MAX_CHARS, (
            f"Prompt length {len(prompt)} exceeds cap {_STRICT_IDENTITY_PROMPT_MAX_CHARS}"
        )

    def test_no_body_canon_within_cap(self):
        prompt = _build_strict_identity_prompt(
            base_prompt="Standing in a dark room",
            anchor_data=_anchor_data(_LONG_LOCK),
            character_name="Leonardo Baptiste",
            body_canon_str="",
            sleeve_enforcement_str="",
            scene_complex=False,
        )
        assert len(prompt) <= _STRICT_IDENTITY_PROMPT_MAX_CHARS

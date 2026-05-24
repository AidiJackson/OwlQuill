"""Regression tests for RP Turn Ownership Engine v1.

Verifies that:
- Hard godmod violations (partner dialogue, climax, consent, inner state) are detected.
- Selected character's own speech and climax are NOT flagged as violations.
- TURN_BOUNDARY_FOOTER appears in every RP reply prompt.
- StoryLab chapter/story prompts are not contaminated with RP-only symbols.
"""
import inspect

import pytest

from app.services.godmod_validator import detect_godmod_violations
from app.services.rp_behavior_engine import TURN_BOUNDARY_FOOTER


# ── Godmod detection tests ─────────────────────────────────────────────────────

def test_godmod_partner_dialogue_rejected():
    """Cross-gender dialogue in output → hard severity."""
    # SC is male (he), partner is female (she) — both attributed speech present.
    reply = (
        'He stepped closer. "You can\'t run from me," he said.\n'
        '"I don\'t want to," she whispered back, voice trembling.'
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    assert result["severity"] == "hard", f"Expected hard, got {result['severity']}: {result}"
    assert any("dialogue" in v["type"] for v in result["violations"])


def test_godmod_partner_climax_rejected():
    """Partner climax narration → hard violation."""
    reply = (
        "He moved against her, relentless. She climaxed hard, her whole body shuddering "
        "as release tore through her."
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    assert result["severity"] == "hard", f"Expected hard, got {result['severity']}: {result}"
    assert any("climax" in v["type"] for v in result["violations"])


def test_godmod_partner_consent_rejected():
    """Partner voiced consent → hard violation."""
    reply = (
        'He leaned in. "I\'m all in," she whispered, fingers curling around his collar.'
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    assert result["severity"] == "hard", f"Expected hard, got {result['severity']}: {result}"
    assert any("consent" in v["type"] for v in result["violations"])


def test_godmod_partner_inner_state_rejected():
    """Repeated partner inner-state verbs → hard violation."""
    reply = (
        "She knew this was wrong. She wanted him anyway. She felt her resolve crumbling. "
        "She realized she had already decided. She hoped he would not stop."
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    assert result["severity"] == "hard", f"Expected hard, got {result['severity']}: {result}"
    inner_state_violations = [v for v in result["violations"] if "inner_state" in v["type"]]
    assert len(inner_state_violations) >= 1


def test_godmod_selected_character_speech_allowed():
    """SC's own attributed dialogue must not be flagged as a violation."""
    # SC is male (he/him) — single block of his own speech.
    reply = (
        'He crossed the room slowly. "I told you I\'d come back," he said, voice low. '
        "He studied her face, waiting."
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    assert result["severity"] in ("none", "soft"), (
        f"SC's own speech should not be hard godmod, got {result['severity']}: {result}"
    )


def test_godmod_sc_climax_not_flagged_when_pronouns_clear():
    """SC's own climax when SC is he/him and partner is she/her → not a violation."""
    reply = (
        "He drove harder, his own release cresting, and he came with a rough exhale "
        "against her throat."
    )
    result = detect_godmod_violations(reply, selected_pronouns=["he", "him"], partner_pronouns=["she", "her"])
    # SC (he) climaxing is allowed — only partner (she) climax is forbidden.
    assert result["severity"] in ("none", "soft"), (
        f"SC climax (he) should not be hard godmod, got {result['severity']}: {result}"
    )


# ── Turn boundary footer in prompts ───────────────────────────────────────────

def test_turn_boundary_footer_in_every_prompt():
    """build_rp_reply_prompt output must contain the turn boundary footer."""
    from app.services.storylab_generator import build_rp_reply_prompt

    messages = build_rp_reply_prompt(
        partner_reply="She smiled and turned away.",
        response_length="match",
        style_match="off",
        perspective="third_person_limited",
        formatting="plain",
        intensity="standard",
        instructions=None,
        character_name="",
        heat_level="flame",
    )
    full_text = " ".join(
        m["content"] if isinstance(m["content"], str) else str(m["content"])
        for m in messages
    )
    assert "partner can respond" in full_text, (
        "TURN_BOUNDARY_FOOTER ('partner can respond') not found in prompt output"
    )


def test_turn_boundary_footer_present_with_character_name():
    """Footer appears even when a character_name is provided."""
    from app.services.storylab_generator import build_rp_reply_prompt

    messages = build_rp_reply_prompt(
        partner_reply="She reached for him.",
        response_length="short",
        style_match="soft",
        perspective="first_person",
        formatting="plain",
        intensity="standard",
        instructions="Keep it slow.",
        character_name="Leonardo",
        heat_level="embers",
    )
    full_text = " ".join(
        m["content"] if isinstance(m["content"], str) else str(m["content"])
        for m in messages
    )
    assert "partner can respond" in full_text, (
        "TURN_BOUNDARY_FOOTER missing from prompt with character_name='Leonardo'"
    )


# ── StoryLab isolation (contamination guard) ──────────────────────────────────

def test_turn_boundary_not_in_storylab_chapter_prompt():
    """build_chapter_prompt source must not contain TURN_BOUNDARY_FOOTER text."""
    import app.services.storylab_generator as sg

    src = inspect.getsource(sg.build_chapter_prompt)
    assert "partner can respond" not in src, (
        "TURN_BOUNDARY_FOOTER text leaked into build_chapter_prompt source"
    )
    assert "Do not complete the partner" not in src


def test_turn_ownership_framing_not_in_storylab_chapter_continuation():
    """build_chapter_prompt must not contain RP turn-ownership framing."""
    import app.services.storylab_generator as sg

    src = inspect.getsource(sg.build_chapter_prompt)
    assert "partner's turn is complete" not in src.lower(), (
        "RP turn-ownership framing leaked into build_chapter_prompt"
    )

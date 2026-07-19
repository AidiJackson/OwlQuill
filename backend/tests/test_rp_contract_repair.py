"""RP Engine Contract Repair — regression tests.

Verifies the 6 surgical changes from the Contract Repair Sprint:
  1. PARTNER_CONTROL_PROTECTION_BLOCK no longer teaches ALLOWED physical reactions.
  2. Pronoun-based physical reaction detection: she/he/they + reaction verb → hard.
  3. Name-anchored physical reaction: PartnerName + reaction verb → hard.
  4. Causal constructions: eliciting X from her, causing her to verb, making him verb → hard.
  5. `felt` added to inner state verbs → caught by inner state detector.
  6. Inner state threshold lowered to 2 (was 3).
  7. Godmod gate fires even when a prior retry already set retry_triggered.
  8. SC internal thoughts, actions, perceptions remain allowed (regression guard).
"""

from app.services.godmod_validator import detect_godmod_violations
from app.services.rp_behavior_engine import PARTNER_CONTROL_PROTECTION_BLOCK


# ── Change 1: PARTNER_CONTROL_PROTECTION_BLOCK no longer allows physical reactions ──

def test_protection_block_no_longer_allows_shudder():
    """ALLOWED section must be gone; shudder is now explicitly forbidden."""
    assert "ALLOWED minimal implied physical reactions" not in PARTNER_CONTROL_PROTECTION_BLOCK, (
        "Old ALLOWED section still present in PARTNER_CONTROL_PROTECTION_BLOCK"
    )
    assert "she shuddered" in PARTNER_CONTROL_PROTECTION_BLOCK.lower() or \
           "shuddered" in PARTNER_CONTROL_PROTECTION_BLOCK, (
        "'shuddered' should appear in the FORBIDDEN examples list"
    )


def test_protection_block_forbids_causal_framing():
    """Block must explicitly call out causal framing as forbidden."""
    block = PARTNER_CONTROL_PROTECTION_BLOCK.lower()
    assert "eliciting" in block or "causing" in block, (
        "PARTNER_CONTROL_PROTECTION_BLOCK must reference causal constructions"
    )


# ── Change 2: Pronoun-based physical reaction detection ──────────────────────

def test_she_shuddered_hard():
    """'She shuddered' alone (partner is she) → hard violation."""
    reply = "He stepped closer. She shuddered against him, unable to move away."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'she shuddered', got {result['severity']}: {result['violations']}"
    )
    assert any("physical_reaction" in v["type"] for v in result["violations"])


def test_he_trembled_hard():
    """'He trembled' when SC is she → hard violation."""
    reply = "She advanced on him. He trembled beneath her gaze."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["she", "her"],
        partner_pronouns=["he", "him"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'he trembled', got {result['severity']}: {result['violations']}"
    )
    assert any("physical_reaction" in v["type"] for v in result["violations"])


def test_they_flinched_hard():
    """'They flinched' authored for partner → hard violation."""
    reply = "She reached out. They flinched at the touch."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["she", "her"],
        partner_pronouns=["they", "them"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'they flinched', got {result['severity']}: {result['violations']}"
    )


def test_she_gasped_hard():
    """'She gasped' (partner pronoun, no quote) → hard violation."""
    reply = "His hand curved around her throat. She gasped, pupils blown wide."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'she gasped', got {result['severity']}: {result['violations']}"
    )


# ── Change 3: Name-anchored physical reaction ─────────────────────────────────

def test_partner_name_gasped_hard():
    """Partner name + 'gasped' → hard violation (name-anchored)."""
    reply = "Lennox gasped as he pressed her against the wall."
    result = detect_godmod_violations(
        reply,
        partner_character_name="Lennox",
        selected_character_name="Damien",
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'Lennox gasped', got {result['severity']}: {result['violations']}"
    )
    assert any("physical_reaction" in v["type"] for v in result["violations"])


def test_partner_name_trembled_hard():
    """Partner name + 'trembled' → hard violation."""
    reply = "He watched Aria trembled under the weight of it."
    result = detect_godmod_violations(
        reply,
        partner_character_name="Aria",
        selected_character_name="Marcus",
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'Aria trembled', got {result['severity']}: {result['violations']}"
    )


# ── Change 4: Causal construction detection ───────────────────────────────────

def test_eliciting_shudder_from_her_hard():
    """'Eliciting a shudder from her' — causal construction → hard violation."""
    reply = "He traced a finger down her spine, eliciting a shudder from her."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for causal 'eliciting a shudder from her', "
        f"got {result['severity']}: {result['violations']}"
    )
    assert any("physical_reaction" in v["type"] for v in result["violations"])


def test_causing_her_to_tremble_hard():
    """'Causing her to tremble' causal construction → hard violation."""
    reply = "The proximity was calculated, deliberate — causing her to tremble."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'causing her to tremble', got {result['severity']}: {result['violations']}"
    )


def test_making_him_gasp_hard():
    """'Making him gasp' causal construction → hard violation."""
    reply = "She tightened her grip, making him gasp against her palm."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["she", "her"],
        partner_pronouns=["he", "him"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'making him gasp', got {result['severity']}: {result['violations']}"
    )


def test_drawing_whimper_from_them_hard():
    """'Drawing a whimper from them' → hard violation."""
    reply = "She pressed closer, drawing a soft whimper from them."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["she", "her"],
        partner_pronouns=["they", "them"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'drawing a whimper from them', got {result['severity']}: {result['violations']}"
    )


def test_provoking_a_shiver_from_her_hard():
    """'Provoking a shiver from her' causal construction → hard."""
    reply = "His touch was cold, calculated — provoking a shiver from her."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'provoking a shiver from her', got {result['severity']}: {result['violations']}"
    )


# ── Change 4 + 5 combined: felt as inner state ────────────────────────────────

def test_she_felt_counted_in_inner_state():
    """'she felt' must now be counted as an inner-state match."""
    # Two instances should trigger threshold (>= 2)
    reply = "She felt the weight of it. She felt her certainty dissolve."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 2× 'she felt', got {result['severity']}: {result['violations']}"
    )
    assert result["partner_inner_state_count"] >= 2


# ── Change 6: Inner state threshold 3 → 2 ────────────────────────────────────

def test_inner_state_two_matches_now_hard():
    """Two partner inner-state verbs → hard (threshold lowered from 3 to 2)."""
    reply = "She knew this was wrong. She wanted to stop him."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard with 2 inner-state matches, got {result['severity']}: {result['violations']}"
    )
    assert result["partner_inner_state_count"] >= 2


def test_inner_state_one_match_not_hard_without_name():
    """Single inner-state match without partner name anchor → soft or none (ambiguous)."""
    reply = "She knew this would change everything."
    result = detect_godmod_violations(reply)
    assert result["severity"] in ("none", "soft"), (
        f"Single ambiguous inner-state should not be hard, got {result['severity']}: {result['violations']}"
    )


# ── Change 7: Godmod gate fires after prior retry ────────────────────────────

def test_godmod_retry_triggered_boolean_is_separate():
    """storylab_generator source must use godmod_retry_triggered, not retry_triggered, for the gate."""
    import inspect
    import app.services.storylab_generator as sg

    src = inspect.getsource(sg._call_generate_rp_reply if hasattr(sg, '_call_generate_rp_reply') else sg.generate_rp_reply)
    # Check that godmod_retry_triggered is defined separately from retry_triggered
    assert "godmod_retry_triggered" in src, (
        "godmod_retry_triggered boolean not found in generate_rp_reply source — "
        "godmod gate will be blocked by prior retries"
    )
    assert "not godmod_retry_triggered" in src, (
        "godmod gate condition must check 'not godmod_retry_triggered', not 'not retry_triggered'"
    )


# ── Change 8: Regression guard — SC actions remain allowed ───────────────────

def test_sc_physical_action_not_flagged():
    """Selected character's own physical actions must not be flagged."""
    # SC is he/him — 'he shuddered' near SC name should be allowed
    reply = "Marcus shuddered at the cold and stepped through the threshold."
    result = detect_godmod_violations(
        reply,
        selected_character_name="Marcus",
        partner_character_name="Aria",
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] in ("none", "soft"), (
        f"SC's own physical action should not be hard, got {result['severity']}: {result['violations']}"
    )


def test_sc_inner_thought_not_flagged():
    """SC's own inner thought must not be flagged as a violation."""
    reply = 'He thought about the weight of what she had said. "We need to talk," he said quietly.'
    result = detect_godmod_violations(
        reply,
        selected_character_name="Damien",
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] in ("none", "soft"), (
        f"SC inner thought should not be hard, got {result['severity']}: {result['violations']}"
    )


def test_partner_let_him_consent_hard():
    """'She let him' partner consent → hard (existing regression)."""
    reply = "He reached for her hand. She let him, fingers curling around his."
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Expected hard for 'she let him', got {result['severity']}: {result['violations']}"
    )


def test_partner_dialogue_hard_regression():
    """Cross-gender dialogue remains hard (existing regression)."""
    reply = (
        '"You can\'t hide from me," he said.\n'
        '"Watch me," she whispered back.'
    )
    result = detect_godmod_violations(
        reply,
        selected_pronouns=["he", "him"],
        partner_pronouns=["she", "her"],
    )
    assert result["severity"] == "hard", (
        f"Cross-gender dialogue must remain hard, got {result['severity']}"
    )

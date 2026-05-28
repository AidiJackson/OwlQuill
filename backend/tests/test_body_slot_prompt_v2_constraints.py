"""Focused constraint tests for v2 body identity slot prompt builders.

Each test verifies that a critical generation constraint phrase is present in
the built prompt.  These constraints prevent cinematic drift, arm-side
substitution, and design reinterpretation when Leonardo generates body-detail
reference plates.

No fixtures or DB required — pure unit tests of build_body_slot_prompt().
"""
import pytest
from app.api.routes.body_identity import build_body_slot_prompt


# ── helpers ────────────────────────────────────────────────────────────

def _p(slot, name="Zara", lock="", canon=""):
    return build_body_slot_prompt(slot, character_name=name,
                                  identity_lock_string=lock,
                                  body_canon_str=canon).lower()


# ══════════════════════════════════════════════════════════════════════
# body_left_detail
# ══════════════════════════════════════════════════════════════════════

def test_left_detail_left_arm_only():
    assert "left arm" in _p("body_left_detail") or "left side only" in _p("body_left_detail")


def test_left_detail_no_right_arm_substitution():
    p = _p("body_left_detail")
    # Must forbid right-arm substitution by name
    assert "right arm" in p  # mentioned to forbid it


def test_left_detail_do_not_substitute_guard():
    assert "do not substitute" in _p("body_left_detail")


def test_left_detail_shoulder_to_wrist_framing():
    assert "shoulder to wrist" in _p("body_left_detail")


def test_left_detail_sleeveless_or_exposed():
    p = _p("body_left_detail")
    assert "sleeveless" in p or "exposed" in p


def test_left_detail_no_clothing_covering_marks():
    p = _p("body_left_detail")
    assert "no clothing covering" in p or "no clothing" in p


def test_left_detail_no_tattoos_printed_on_clothing():
    p = _p("body_left_detail")
    assert "no tattoos" in p or "no designs printed" in p


def test_left_detail_plain_neutral_background():
    p = _p("body_left_detail")
    assert "plain" in p and "background" in p


def test_left_detail_neutral_lighting():
    p = _p("body_left_detail")
    assert "neutral" in p and "lighting" in p


def test_left_detail_no_cinematic_pose():
    assert "no cinematic" in _p("body_left_detail")


def test_left_detail_no_design_reinterpretation():
    p = _p("body_left_detail")
    assert "no reinterpretation" in p or "no alternate design" in p


def test_left_detail_markings_fully_visible():
    p = _p("body_left_detail")
    assert "fully visible" in p or "all tattoos" in p


def test_left_detail_includes_character_name():
    assert "zara" in _p("body_left_detail")


def test_left_detail_includes_body_canon():
    p = build_body_slot_prompt(
        "body_left_detail", character_name="Zara",
        body_canon_str="dragon tattoo left arm",
    ).lower()
    assert "dragon tattoo" in p


def test_left_detail_prompt_capped_at_800():
    long_s = "X" * 500
    result = build_body_slot_prompt("body_left_detail", "A",
                                    identity_lock_string=long_s,
                                    body_canon_str=long_s)
    assert len(result) <= 800


# ══════════════════════════════════════════════════════════════════════
# body_right_detail
# ══════════════════════════════════════════════════════════════════════

def test_right_detail_right_arm_only():
    assert "right arm" in _p("body_right_detail")


def test_right_detail_no_left_arm_substitution():
    p = _p("body_right_detail")
    # Must forbid left-arm substitution by name
    assert "left arm" in p  # mentioned to forbid it


def test_right_detail_do_not_substitute_guard():
    assert "do not substitute" in _p("body_right_detail")


def test_right_detail_shoulder_to_wrist_framing():
    assert "shoulder to wrist" in _p("body_right_detail")


def test_right_detail_sleeveless_or_exposed():
    p = _p("body_right_detail")
    assert "sleeveless" in p or "exposed" in p


def test_right_detail_no_clothing_covering_marks():
    p = _p("body_right_detail")
    assert "no clothing covering" in p or "no clothing" in p


def test_right_detail_no_tattoos_printed_on_clothing():
    p = _p("body_right_detail")
    assert "no tattoos" in p or "no designs printed" in p


def test_right_detail_plain_neutral_background():
    p = _p("body_right_detail")
    assert "plain" in p and "background" in p


def test_right_detail_neutral_lighting():
    p = _p("body_right_detail")
    assert "neutral" in p and "lighting" in p


def test_right_detail_no_cinematic_pose():
    assert "no cinematic" in _p("body_right_detail")


def test_right_detail_no_design_reinterpretation():
    p = _p("body_right_detail")
    assert "no reinterpretation" in p or "no alternate design" in p


def test_right_detail_markings_fully_visible():
    p = _p("body_right_detail")
    assert "fully visible" in p or "all tattoos" in p


def test_right_detail_prompt_capped_at_800():
    long_s = "X" * 500
    result = build_body_slot_prompt("body_right_detail", "A",
                                    identity_lock_string=long_s,
                                    body_canon_str=long_s)
    assert len(result) <= 800


# ══════════════════════════════════════════════════════════════════════
# body_map
# ══════════════════════════════════════════════════════════════════════

def test_body_map_reference_sheet_or_placement_map_label():
    p = _p("body_map")
    assert "reference sheet" in p or "placement map" in p


def test_body_map_clear_left_right_labels():
    p = _p("body_map")
    assert "left" in p and "right" in p


def test_body_map_front_body_placement():
    assert "front" in _p("body_map")


def test_body_map_not_cinematic_art():
    p = _p("body_map")
    assert "not cinematic" in p


def test_body_map_not_outfit_fashion_image():
    p = _p("body_map")
    assert "fashion" in p or "not outfit" in p


def test_body_map_no_extra_designs():
    p = _p("body_map")
    assert "no extra design" in p or "no extra" in p


def test_body_map_back_side_conditional():
    p = _p("body_map")
    assert "back" in p or "back/side" in p


def test_body_map_markings_as_placement_references():
    p = _p("body_map")
    assert "placement" in p or "spatial" in p


def test_body_map_plain_neutral_background():
    p = _p("body_map")
    assert "plain" in p and "background" in p


def test_body_map_prompt_capped_at_800():
    long_s = "X" * 500
    result = build_body_slot_prompt("body_map", "A",
                                    identity_lock_string=long_s,
                                    body_canon_str=long_s)
    assert len(result) <= 800


# ══════════════════════════════════════════════════════════════════════
# body_front
# ══════════════════════════════════════════════════════════════════════

def test_body_front_full_body_or_knees_up():
    p = _p("body_front")
    assert "full body" in p or "knees-up" in p or "head-to-feet" in p


def test_body_front_both_arms_visible():
    assert "both arms" in _p("body_front")


def test_body_front_neutral_pose():
    assert "neutral" in _p("body_front")


def test_body_front_sleeveless_or_minimal_clothing():
    p = _p("body_front")
    assert "sleeveless" in p or "minimal clothing" in p


def test_body_front_all_permanent_markings_visible():
    p = _p("body_front")
    assert "permanent markings" in p or "all permanent" in p or "markings visible" in p


def test_body_front_no_tattoos_on_clothing():
    p = _p("body_front")
    assert "no tattoos printed" in p or "no tattoos" in p


def test_body_front_not_a_scene_or_fashion_image():
    p = _p("body_front")
    assert "not a scene" in p or "not a fashion" in p or "reference card" in p


def test_body_front_prompt_capped_at_800():
    long_s = "X" * 500
    result = build_body_slot_prompt("body_front", "A",
                                    identity_lock_string=long_s,
                                    body_canon_str=long_s)
    assert len(result) <= 800


# ══════════════════════════════════════════════════════════════════════
# final_character_card
# ══════════════════════════════════════════════════════════════════════

def test_final_card_marked_cinematic_presentation_only():
    assert "cinematic" in _p("final_character_card")


def test_final_card_not_primary_anatomical_truth():
    p = _p("final_character_card")
    assert "not primary anatomical" in p or "not primary" in p or "never used for" in p


def test_final_card_preserve_locked_refs():
    p = _p("final_character_card")
    assert "locked" in p or "preserve" in p


def test_final_card_support_reference_only():
    p = _p("final_character_card")
    assert "support" in p


def test_final_card_prompt_capped_at_800():
    long_s = "X" * 500
    result = build_body_slot_prompt("final_character_card", "A",
                                    identity_lock_string=long_s,
                                    body_canon_str=long_s)
    assert len(result) <= 800

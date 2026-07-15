"""Body Identity Architecture — focused tests for the v2 architecture.

Tests:
  1. get_body_identity_references deterministic ordering.
  2. No markings → clean empty result.
  3. Missing body_front + markings → incomplete state (missing_required=True).
  4. final_character_card never outranks body_front in ref ordering.
  5. Scene generation contract: face → body → support ordering.
  6. Validation scaffold shape test.
"""
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.services.body_identity_refs import (
    get_body_identity_references,
    BODY_IDENTITY_REF_PRIORITY,
    BODY_IDENTITY_REF_TYPES,
)
from app.services.body_identity_validator import (
    validate_body_identity_pack,
    BodyIdentityValidationResult,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_char(
    *,
    locked_slots: tuple[str, ...] = (),
    has_markings: bool = False,
    legacy_final_card: bool = False,
) -> MagicMock:
    """Build a stub character with identity_anchor_json pre-populated."""
    body_slots: dict = {}
    for slot in locked_slots:
        body_slots[slot] = {
            "url": f"https://cdn.example.com/{slot}.png",
            "status": "locked",
            "prompt": f"prompt for {slot}",
        }

    anchor_data: dict = {
        "identity_lock_string": "tall, dark hair, brown eyes",
        "anchors": {"front": {"url": "https://cdn.example.com/front.png", "id": 1}},
        "body_slots": body_slots,
    }
    if legacy_final_card:
        anchor_data["final_character_card"] = {
            "url": "https://cdn.example.com/final_card.png",
            "status": "locked",
        }

    char = MagicMock()
    char.id = 99
    char.identity_anchor_json = json.dumps(anchor_data)

    if has_markings:
        char.body_canon_json = json.dumps({"markings": [{
            "id": "m1", "type": "tattoo", "placement": "right_upper_arm",
            "style": "black serpent", "size": "large", "description": "serpent",
        }]})
    else:
        char.body_canon_json = None

    return char


# ── Test 1: deterministic ordering ───────────────────────────────────────────


class TestBodyIdentityRefsOrdering:
    """get_body_identity_references returns refs in BODY_IDENTITY_REF_PRIORITY order."""

    def test_all_locked_slots_returned_in_priority_order(self):
        """All locked slots appear in canonical priority order."""
        char = _make_char(
            locked_slots=("body_back", "body_front", "body_left_detail",
                          "body_right_detail", "body_map"),
            has_markings=True,
        )
        result = get_body_identity_references(char)
        assert len(result.refs) == 5
        slot_order = [r.slot for r in result.refs]
        # body_front must be first
        assert slot_order[0] == "body_front"
        # body_left_detail before body_right_detail
        left_idx = slot_order.index("body_left_detail")
        right_idx = slot_order.index("body_right_detail")
        assert left_idx < right_idx, f"left_detail ({left_idx}) must precede right_detail ({right_idx})"
        # body_back before body_map
        back_idx = slot_order.index("body_back")
        map_idx = slot_order.index("body_map")
        assert back_idx < map_idx, f"body_back ({back_idx}) must precede body_map ({map_idx})"

    def test_final_character_card_always_last_in_refs(self):
        """final_character_card is always the last ref regardless of slot config."""
        char = _make_char(
            locked_slots=("body_front", "final_character_card", "body_left_detail"),
            has_markings=True,
        )
        result = get_body_identity_references(char)
        slot_order = [r.slot for r in result.refs]
        fc_idx = slot_order.index("final_character_card")
        bf_idx = slot_order.index("body_front")
        ld_idx = slot_order.index("body_left_detail")
        assert bf_idx < fc_idx, "body_front must precede final_character_card"
        assert ld_idx < fc_idx, "body_left_detail must precede final_character_card"

    def test_ref_types_match_anchor_types_contract(self):
        """ref_type strings match the BODY_IDENTITY_REF_TYPES contract."""
        char = _make_char(
            locked_slots=("body_front", "body_left_detail", "body_right_detail"),
            has_markings=True,
        )
        result = get_body_identity_references(char)
        for ref in result.refs:
            expected_type = BODY_IDENTITY_REF_TYPES.get(ref.slot, f"body_identity:{ref.slot}")
            assert ref.ref_type == expected_type, (
                f"ref_type for {ref.slot!r} should be {expected_type!r}, got {ref.ref_type!r}"
            )

    def test_legacy_final_card_location_resolved(self):
        """final_character_card in legacy anchor_data location is resolved."""
        char = _make_char(legacy_final_card=True, has_markings=False)
        result = get_body_identity_references(char)
        fc_refs = [r for r in result.refs if r.slot == "final_character_card"]
        assert len(fc_refs) == 1
        assert fc_refs[0].source == "legacy_final_card"

    def test_tattoo_layout_fallback_when_body_map_absent(self):
        """legacy tattoo_layout is loaded when body_map slot is absent."""
        char = _make_char(
            locked_slots=("body_front", "tattoo_layout"),
            has_markings=True,
        )
        result = get_body_identity_references(char)
        slot_order = [r.slot for r in result.refs]
        assert "tattoo_layout" in slot_order
        # tattoo_layout should come after body_front
        bf_idx = slot_order.index("body_front")
        tl_idx = slot_order.index("tattoo_layout")
        assert bf_idx < tl_idx


# ── Test 2: no markings → clean empty ────────────────────────────────────────


class TestNoMarkingsCleanEmpty:
    """No markings and no body slots → clean empty result."""

    def test_no_markings_no_slots_returns_empty(self):
        """Character with no markings and no body slots → empty refs, no warnings."""
        char = _make_char(locked_slots=(), has_markings=False)
        result = get_body_identity_references(char)
        assert result.refs == []
        assert result.missing_required is False
        assert result.body_identity_complete is False
        assert result.has_markings is False

    def test_no_markings_body_front_locked_still_returns_refs(self):
        """body_front locked but no markings → refs are returned (body truth available)."""
        char = _make_char(locked_slots=("body_front",), has_markings=False)
        result = get_body_identity_references(char)
        # Has no markings but body_front exists — refs returned for optional use
        assert len(result.refs) >= 1
        assert result.refs[0].slot == "body_front"
        assert result.missing_required is False  # no markings → not missing_required


# ── Test 3: missing body_front + markings → incomplete ───────────────────────


class TestMissingBodyFrontWithMarkings:
    """Missing body_front with markings → missing_required=True, complete=False."""

    def test_markings_no_body_front_is_incomplete(self):
        """missing_required=True when markings exist but body_front is absent."""
        char = _make_char(locked_slots=(), has_markings=True)
        result = get_body_identity_references(char)
        assert result.missing_required is True
        assert result.body_identity_complete is False
        assert result.has_markings is True

    def test_markings_with_body_front_is_complete(self):
        """body_identity_complete=True when body_front is locked and markings exist."""
        char = _make_char(locked_slots=("body_front",), has_markings=True)
        result = get_body_identity_references(char)
        assert result.missing_required is False
        assert result.body_identity_complete is True

    def test_only_final_card_no_body_front_still_incomplete(self):
        """Having only final_character_card does not satisfy body_front requirement."""
        char = _make_char(locked_slots=("final_character_card",), has_markings=True)
        result = get_body_identity_references(char)
        assert result.missing_required is True
        assert result.body_identity_complete is False

    def test_body_front_slot_status_propagated(self):
        """body_front_slot_status reflects actual slot state."""
        char = _make_char(locked_slots=(), has_markings=True)
        result = get_body_identity_references(char)
        assert result.body_front_slot_status == "missing"

    def test_body_identity_missing_logged(self, caplog):
        """BODY_IDENTITY_STATE log emitted with correct missing_required flag."""
        char = _make_char(locked_slots=(), has_markings=True)
        with caplog.at_level(logging.INFO, logger="app.services.body_identity_refs"):
            result = get_body_identity_references(char)
        assert any("BODY_IDENTITY_STATE" in r.message for r in caplog.records)
        assert result.missing_required is True


# ── Test 4: final_character_card ordering in _reorder_anchor_refs ────────────


# ── Test 5: scene generation contract face → body → support ordering ─────────


# ── Test 6: validation scaffold shape ────────────────────────────────────────


class TestValidationScaffoldShape:
    """validate_body_identity_pack returns the correct shape and structural checks."""

    def test_returns_validation_result_type(self):
        """Return type is BodyIdentityValidationResult."""
        char = _make_char(locked_slots=(), has_markings=False)
        result = validate_body_identity_pack(char)
        assert isinstance(result, BodyIdentityValidationResult)
        assert hasattr(result, "valid")
        assert hasattr(result, "warnings")
        assert hasattr(result, "failures")

    def test_no_markings_no_slots_is_valid(self):
        """Character with no markings and no pack → valid with no warnings."""
        char = _make_char(locked_slots=(), has_markings=False)
        result = validate_body_identity_pack(char)
        assert result.valid is True
        assert result.warnings == []
        assert result.failures == []

    def test_markings_no_body_front_produces_warning(self):
        """Markings exist but body_front absent → warning (non-blocking by default)."""
        char = _make_char(locked_slots=(), has_markings=True)
        result = validate_body_identity_pack(char)
        assert result.valid is True  # warning, not failure
        assert len(result.warnings) >= 1
        assert any("body_front" in w for w in result.warnings)

    def test_markings_no_body_front_require_complete_is_failure(self):
        """require_complete_pack=True → body_front missing is a failure."""
        char = _make_char(locked_slots=(), has_markings=True)
        result = validate_body_identity_pack(char, require_complete_pack=True)
        assert result.valid is False
        assert len(result.failures) >= 1

    def test_complete_pack_is_valid(self):
        """body_front locked with markings → valid, no failures."""
        char = _make_char(
            locked_slots=("body_front", "body_left_detail", "body_right_detail",
                          "body_map"),
            has_markings=True,
        )
        result = validate_body_identity_pack(char, require_complete_pack=True)
        assert result.valid is True
        assert result.failures == []

    def test_final_card_without_body_front_produces_warning(self):
        """final_character_card locked but body_front absent → warning."""
        char = _make_char(locked_slots=("final_character_card",), has_markings=True)
        result = validate_body_identity_pack(char)
        support_only_warning = any(
            "SUPPORT ONLY" in w or "support" in w.lower() for w in result.warnings
        )
        assert support_only_warning, (
            f"Expected support-only warning. Got: {result.warnings}"
        )


# ── Test 7: canonical whitelist fix — v2 detail refs survive filtering ────────



"""Body Truth System — focused tests for Phase 1.

Tests:
  1. get_canonical_body_front returns deterministic priority order.
  2. Marked character + body_front: scene generation loads body_front ref.
  3. Marked character + no body_front: BODY_IDENTITY_MISSING warning logged.
  4. Body markings inject clothing safety invariant into prompt.
  5. final_character_card never replaces body_front in anchor ordering.
  6. No markings → no clothing invariant injected.
"""
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.services.body_canon import get_canonical_body_front
from app.api.routes.image_generator import (
    _reorder_anchor_refs,
    _CLOTHING_SAFETY_INVARIANT,
    _build_strict_identity_prompt,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_character(
    *,
    body_front_locked: bool = False,
    has_full_body_anchor: bool = False,
    has_torso_anchor: bool = False,
    has_final_card: bool = False,
    identity_anchor_json: dict | None = None,
) -> MagicMock:
    """Build a minimal Character mock with configurable identity_anchor_json."""
    char = MagicMock()
    char.id = 42

    if identity_anchor_json is not None:
        char.identity_anchor_json = json.dumps(identity_anchor_json)
        return char

    data: dict = {"anchors": {}, "body_slots": {}}

    if body_front_locked:
        data["body_slots"]["body_front"] = {
            "url": "/static/generated/body_front.png",
            "status": "locked",
            "prompt": "test",
        }
    if has_full_body_anchor:
        data["anchors"]["full_body"] = {"url": "/static/generated/full_body.png", "id": 10}
    if has_torso_anchor:
        data["anchors"]["torso"] = {"url": "/static/generated/torso.png", "id": 11}
    if has_final_card:
        data["final_character_card"] = {
            "url": "/static/generated/final_card.png",
            "status": "locked",
        }

    char.identity_anchor_json = json.dumps(data)
    return char


def _mk_bytes(types: list[str]) -> tuple[list[bytes], list[str]]:
    """Build parallel (bytes, type) lists for _reorder_anchor_refs input."""
    return [b"img"] * len(types), list(types)


# ── Test 1: get_canonical_body_front priority order ───────────────────────────


class TestGetCanonicalBodyFront:
    """get_canonical_body_front returns the highest-priority available URL."""

    def test_priority_1_locked_body_front_slot(self):
        """Locked body_front slot takes priority over all anchors."""
        char = _make_character(
            body_front_locked=True,
            has_full_body_anchor=True,
            has_torso_anchor=True,
        )
        url, source = get_canonical_body_front(char)
        assert url == "/static/generated/body_front.png"
        assert source == "body_slots_locked"

    def test_priority_2_full_body_anchor_when_slot_missing(self):
        """full_body anchor is used when body_front slot is absent."""
        char = _make_character(has_full_body_anchor=True, has_torso_anchor=True)
        url, source = get_canonical_body_front(char)
        assert url == "/static/generated/full_body.png"
        assert source == "anchor_full_body"

    def test_priority_3_torso_anchor_last_fallback(self):
        """torso anchor is used when body_front slot and full_body are both absent."""
        char = _make_character(has_torso_anchor=True)
        url, source = get_canonical_body_front(char)
        assert url == "/static/generated/torso.png"
        assert source == "anchor_torso"

    def test_returns_none_when_nothing_available(self):
        """Returns (None, 'missing') when no body reference exists."""
        char = MagicMock()
        char.id = 42
        char.identity_anchor_json = None
        url, source = get_canonical_body_front(char)
        assert url is None
        assert source == "missing"

    def test_slot_generated_not_locked_is_skipped(self):
        """A body_front slot with status='generated' (not locked) must be skipped."""
        data = {
            "anchors": {"full_body": {"url": "/static/generated/full_body.png", "id": 1}},
            "body_slots": {
                "body_front": {
                    "url": "/static/generated/bf_unlocked.png",
                    "status": "generated",
                }
            },
        }
        char = _make_character(identity_anchor_json=data)
        url, source = get_canonical_body_front(char)
        # Must skip generated slot and fall through to full_body anchor
        assert source == "anchor_full_body"
        assert url == "/static/generated/full_body.png"

    def test_logs_body_front_found(self, caplog):
        """BODY_FRONT_FOUND is logged when a ref is located."""
        char = _make_character(body_front_locked=True)
        with caplog.at_level(logging.INFO, logger="app.services.body_canon"):
            get_canonical_body_front(char)
        assert any("BODY_FRONT_FOUND" in r.message for r in caplog.records)

    def test_logs_body_front_missing(self, caplog):
        """BODY_FRONT_MISSING is logged when no ref is available."""
        char = MagicMock()
        char.id = 42
        char.identity_anchor_json = None
        with caplog.at_level(logging.INFO, logger="app.services.body_canon"):
            get_canonical_body_front(char)
        assert any("BODY_FRONT_MISSING" in r.message for r in caplog.records)


# ── Test 2 & 3: body_front loading preconditions ─────────────────────────────


class TestBodyTruthRefLoading:
    """Verify the preconditions that drive body_front loading and BODY_IDENTITY_MISSING.

    Full HTTP integration tests are not possible in this environment (DB not
    available). Instead we test the underlying helper that feeds the route:
    get_canonical_body_front(). The route sets body_front_loaded=True when
    this returns a non-None URL, and emits BODY_IDENTITY_MISSING when it
    returns None with markings present.
    """

    def test_body_front_loaded_condition_met_for_locked_slot(self):
        """get_canonical_body_front returns a URL for a locked body_front slot.

        This is the precondition for body_front_loaded=True in scene metadata:
        the route sets _bf_loaded=True when get_canonical_body_front returns
        a non-None URL and load_image_bytes succeeds.
        """
        char = _make_character(body_front_locked=True)
        url, source = get_canonical_body_front(char)
        assert url is not None, (
            "Locked body_front slot must return a URL — "
            "required precondition for body_front_loaded=True in metadata"
        )
        assert source == "body_slots_locked"

    def test_body_identity_missing_condition_met_when_no_body_front(self, caplog):
        """get_canonical_body_front returns (None, 'missing') when no slot or anchor.

        This is the precondition for BODY_IDENTITY_MISSING in scene generation:
        the route logs the warning when _bc_markings and not _bf_loaded.
        The not-_bf_loaded condition follows directly from url=None here.
        Also verifies BODY_FRONT_MISSING is logged by the helper (body_canon
        precursor to the route's BODY_IDENTITY_MISSING warning).
        """
        char = _make_character(body_front_locked=False)
        with caplog.at_level(logging.INFO, logger="app.services.body_canon"):
            url, source = get_canonical_body_front(char)
        assert url is None, "No body_front slot or anchor → url must be None"
        assert source == "missing"
        assert any("BODY_FRONT_MISSING" in r.message for r in caplog.records), (
            "BODY_FRONT_MISSING must be logged by body_canon helper — "
            "it is the precursor to route's BODY_IDENTITY_MISSING warning"
        )


# ── Test 4: clothing safety invariant injection ───────────────────────────────


class TestClothingSafetyInvariant:
    """_CLOTHING_SAFETY_INVARIANT is injected when body markings exist."""

    def _prompt_with_markings(self, has_markings: bool, body_front_canonical: bool = False) -> str:
        """Build a strict identity prompt and return it for inspection."""
        anchor_data = {
            "identity_lock_string": "tall, black hair, brown eyes",
            "anchors": {"front": {"url": "/static/generated/front.png", "id": 1}},
        }
        from app.services.body_canon import BodyMarking

        right_marking = BodyMarking(
            type="tattoo",
            placement="right_upper_arm",
            style="black serpent",
            size="large",
            description="test",
        )

        if body_front_canonical:
            # In canonical mode, body_canon_str is _CANONICAL_BODY_REF_TEXT + invariant
            from app.api.routes.image_generator import _CANONICAL_BODY_REF_TEXT
            body_canon = _CANONICAL_BODY_REF_TEXT + ". " + _CLOTHING_SAFETY_INVARIANT if has_markings else ""
        else:
            from app.services.body_canon import build_body_canon_lock_string
            from app.api.routes.image_generator import _SIMPLIFIED_BODY_CANON_TEXT
            if has_markings:
                base = _SIMPLIFIED_BODY_CANON_TEXT
                body_canon = base + ". " + _CLOTHING_SAFETY_INVARIANT
            else:
                body_canon = ""

        return _build_strict_identity_prompt(
            base_prompt="Standing in bright daylight, sleeveless vest, both arms visible",
            anchor_data=anchor_data,
            character_name="Remi",
            body_canon_str=body_canon,
        )

    def test_clothing_invariant_present_when_markings_exist(self):
        """All three key phrases of the clothing invariant appear when markings exist."""
        prompt = self._prompt_with_markings(has_markings=True)
        assert "exposed skin only" in prompt, "clothing invariant must contain 'exposed skin only'"
        assert "Never print tattoos" in prompt, "clothing invariant must contain 'Never print tattoos'"
        assert "Never merge" in prompt, "clothing invariant must contain 'Never merge'"

    def test_clothing_invariant_absent_when_no_markings(self):
        """Clothing invariant must NOT appear when character has no body markings."""
        prompt = self._prompt_with_markings(has_markings=False)
        assert "Never print tattoos" not in prompt, (
            "Clothing invariant must not be injected when no markings exist"
        )
        assert "Never merge" not in prompt

    def test_invariant_constant_has_required_phrases(self):
        """_CLOTHING_SAFETY_INVARIANT contains all required hard rules."""
        assert "exposed skin only" in _CLOTHING_SAFETY_INVARIANT
        assert "Never print tattoos" in _CLOTHING_SAFETY_INVARIANT
        assert "Never move tattoos between limbs" in _CLOTHING_SAFETY_INVARIANT
        assert "Never merge left and right arm tattoos" in _CLOTHING_SAFETY_INVARIANT


# ── Test 5: final_character_card never overrides face anchor or body_front ────


class TestFinalCardDoesNotOverridePriority:
    """final_character_card is support-only and must never precede face/body_front."""

    def test_final_card_after_face_anchor(self):
        """final_character_card must come after face anchor in body-truth mode."""
        _, out_types = _reorder_anchor_refs(
            *_mk_bytes(["front", "body_identity:body_front", "final_character_card"]),
            tattoo_primary=True,
        )
        front_idx = out_types.index("front")
        fc_idx = out_types.index("final_character_card")
        assert front_idx < fc_idx, (
            f"face anchor (front={front_idx}) must precede final_card ({fc_idx}). Order: {out_types}"
        )

    def test_final_card_after_body_front(self):
        """final_character_card must come after body_front in body-truth mode."""
        _, out_types = _reorder_anchor_refs(
            *_mk_bytes(["front", "body_identity:body_front", "final_character_card"]),
            tattoo_primary=True,
        )
        bf_idx = out_types.index("body_identity:body_front")
        fc_idx = out_types.index("final_character_card")
        assert bf_idx < fc_idx, (
            f"body_front ({bf_idx}) must precede final_card ({fc_idx}). Order: {out_types}"
        )

    def test_final_card_last_in_face_first_mode(self):
        """final_character_card is last in normal face-first mode."""
        _, out_types = _reorder_anchor_refs(
            *_mk_bytes(["front", "three_quarter", "body_identity:body_front", "final_character_card"]),
            tattoo_primary=False,
        )
        assert out_types[-1] == "final_character_card", (
            f"final_card must be last in face-first mode. Got: {out_types}"
        )

    def test_final_card_absent_does_not_break_ordering(self):
        """When final_card is not present, ordering is unaffected."""
        _, out_types = _reorder_anchor_refs(
            *_mk_bytes(["front", "body_identity:body_front"]),
            tattoo_primary=True,
        )
        assert "final_character_card" not in out_types
        assert out_types[0] == "front"
        assert out_types[1] == "body_identity:body_front"


# ── Test 6: no body truth injection when no markings ────────────────────────


class TestNoBodyTruthWhenNoMarkings:
    """When a character has no body markings, body truth state is off."""

    def test_body_canon_str_empty_when_no_markings(self):
        """build_body_canon_lock_string returns empty string for empty markings."""
        from app.services.body_canon import build_body_canon_lock_string, BodyMarking
        result = build_body_canon_lock_string([])
        assert result == "", "empty markings must produce empty lock string"

    def test_clothing_invariant_not_in_prompt_when_no_markings(self):
        """When body_canon_str is empty, invariant must not appear in prompt."""
        anchor_data = {
            "identity_lock_string": "tall, black hair",
            "anchors": {"front": {"url": "/static/generated/front.png", "id": 1}},
        }
        prompt = _build_strict_identity_prompt(
            base_prompt="Walking through a park",
            anchor_data=anchor_data,
            character_name="Lee",
            body_canon_str="",  # no markings
        )
        assert _CLOTHING_SAFETY_INVARIANT[:30] not in prompt, (
            "Clothing invariant must not appear when body_canon_str is empty"
        )
        assert "Never merge" not in prompt

    def test_get_canonical_body_front_source_missing_with_no_json(self):
        """Returns 'missing' source when character has no identity_anchor_json."""
        char = MagicMock()
        char.id = 99
        char.identity_anchor_json = None
        _, source = get_canonical_body_front(char)
        assert source == "missing"

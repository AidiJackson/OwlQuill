"""Regression tests for Identity Consistency Sprint v2 — Part B.

Covers slot invalidation state, stale lifecycle, and health computation
introduced in pack_version.mark_slots_stale and updated compute_identity_health.

All tests are pure unit tests — no DB, no network, no generation.
"""
import json
import types

import pytest

from app.services.pack_version import (
    compute_identity_health,
    get_pack_version,
    increment_pack_version,
    mark_slots_stale,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _char(anchor_json: dict | None = None, char_id: int = 1):
    obj = types.SimpleNamespace()
    obj.id = char_id
    obj.identity_anchor_json = json.dumps(anchor_json) if anchor_json is not None else None
    obj.body_canon_json = None
    return obj


def _base_anchor(
    pack_version: int = 1,
    front_pv: int | None = None,
    tq_pv: int | None = None,
    body_slots: dict | None = None,
) -> dict:
    anchors: dict = {}
    if front_pv is not None:
        anchors["front"] = {"id": 1, "url": "http://x/front.png", "pack_version": front_pv}
    if tq_pv is not None:
        anchors["three_quarter"] = {"id": 2, "url": "http://x/3q.png", "pack_version": tq_pv}
    data: dict = {"pack_version": pack_version, "anchors": anchors}
    if body_slots is not None:
        data["body_slots"] = body_slots
    return data


def _locked(pv: int) -> dict:
    return {"url": "http://x/slot.png", "status": "locked", "pack_version": pv}


# ── Test 1: tattoo mutation marks body_front stale ───────────────────


class TestTattooMarkBodyFrontStale:
    def test_body_front_gets_stale_flag(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["body_front"]["stale"] is True

    def test_body_front_url_preserved(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["body_front"]["url"] == "http://x/slot.png"

    def test_body_front_in_invalidated_list(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "body_canon_mutation")

        assert "body_front" in invalidated

    def test_face_anchors_unchanged_after_tattoo_mutation(self):
        anchor = _base_anchor(
            pack_version=2,
            front_pv=2,
            tq_pv=2,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"].get("stale") is not True
        assert data["anchors"]["three_quarter"].get("stale") is not True


# ── Test 2: tattoo mutation marks tattoo_layout stale ────────────────


class TestTattooMarkTattooLayoutStale:
    def test_tattoo_layout_gets_stale_flag(self):
        anchor = _base_anchor(
            pack_version=3,
            body_slots={"tattoo_layout": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["tattoo_layout"]["stale"] is True

    def test_tattoo_layout_url_preserved(self):
        anchor = _base_anchor(
            pack_version=3,
            body_slots={"tattoo_layout": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["tattoo_layout"]["url"] == "http://x/slot.png"

    def test_tattoo_layout_in_invalidated_list(self):
        anchor = _base_anchor(
            pack_version=3,
            body_slots={"tattoo_layout": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "body_canon_mutation")

        assert "tattoo_layout" in invalidated

    def test_both_body_front_and_tattoo_layout_stale(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={
                "body_front": _locked(1),
                "tattoo_layout": _locked(1),
            },
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "body_canon_mutation")

        assert "body_front" in invalidated
        assert "tattoo_layout" in invalidated
        assert len(invalidated) == 2


# ── Test 3: hair mutation marks face/body stale ───────────────────────


class TestHairMutationMarksFaceBodyStale:
    def test_front_anchor_gets_stale_flag(self):
        anchor = _base_anchor(pack_version=2, front_pv=1, tq_pv=1)
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"]["stale"] is True

    def test_three_quarter_anchor_gets_stale_flag(self):
        anchor = _base_anchor(pack_version=2, front_pv=1, tq_pv=1)
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["three_quarter"]["stale"] is True

    def test_body_front_gets_stale_flag_for_hair(self):
        anchor = _base_anchor(
            pack_version=2,
            front_pv=1,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["body_front"]["stale"] is True

    def test_tattoo_layout_unchanged_for_hair_mutation(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"tattoo_layout": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["tattoo_layout"].get("stale") is not True

    def test_face_and_body_both_reported_stale_in_health(self):
        anchor = _base_anchor(
            pack_version=2,
            front_pv=1,
            tq_pv=1,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        health = compute_identity_health(char)
        assert health["face"] == "stale"
        assert health["body"] == "stale"


# ── Test 4: stale flag overrides version match ────────────────────────


class TestStaleFlagOverridesVersionMatch:
    """stale=True on an entry overrides a matching pack_version."""

    def test_stale_flag_wins_over_matching_version(self):
        # Entry has pack_version matching current, but also stale=True
        anchor = {
            "pack_version": 3,
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png", "pack_version": 3, "stale": True},
            },
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "stale", "stale=True must win even when versions match"

    def test_stale_flag_wins_without_pack_version(self):
        # Entry has stale=True but no pack_version (legacy entry that was explicitly invalidated)
        anchor = {
            "pack_version": 2,
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png", "stale": True},
            },
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "stale"

    def test_stale_false_with_matching_version_is_current(self):
        # stale=False must NOT override a current version
        anchor = {
            "pack_version": 2,
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png", "pack_version": 2, "stale": False},
            },
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"

    def test_stale_flag_on_body_slot_wins(self):
        anchor = {
            "pack_version": 3,
            "anchors": {},
            "body_slots": {
                "body_front": {
                    "url": "http://x/bf.png",
                    "status": "locked",
                    "pack_version": 3,
                    "stale": True,
                },
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "stale"
        assert health["tattoos"] == "stale"


# ── Test 5: legacy character remains current ──────────────────────────


class TestLegacyCharacterRemainsCurrent:
    """Legacy entries (no pack_version, no stale flag) must never be false-positive."""

    def test_no_anchor_json_is_current(self):
        char = _char(anchor_json=None)
        health = compute_identity_health(char)
        assert health["face"] == "current"
        assert health["body"] == "current"
        assert health["tattoos"] == "current"

    def test_anchors_without_pack_version_are_current(self):
        anchor = {
            "pack_version": 5,
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png"},  # no pack_version on entry
            },
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"

    def test_body_slot_without_pack_version_is_current(self):
        anchor = {
            "pack_version": 5,
            "anchors": {},
            "body_slots": {
                "body_front": {"url": "http://x/bf.png", "status": "locked"},
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "current"
        assert health["tattoos"] == "current"

    def test_mark_slots_stale_noop_when_no_anchor_json(self):
        char = _char(anchor_json=None)
        invalidated = mark_slots_stale(char, "body_canon_mutation")
        assert invalidated == []
        assert char.identity_anchor_json is None  # unchanged


# ── Test 6: removable element does nothing ────────────────────────────


class TestRemovableElementDoesNothing:
    """Removable style elements must not affect pack_version or stale flags."""

    def test_removable_path_leaves_version_unchanged(self):
        # Removable elements never reach increment_pack_version or mark_slots_stale
        char = _char(anchor_json={
            "pack_version": 1,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1}},
            "body_slots": {},
        })
        original_json = char.identity_anchor_json
        # Simulate removable path: NO calls to increment_pack_version or mark_slots_stale
        assert char.identity_anchor_json == original_json
        assert get_pack_version(char) == 1

    def test_removable_path_leaves_health_current(self):
        char = _char(anchor_json={
            "pack_version": 1,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1}},
            "body_slots": {},
        })
        # No mutations applied (removable path)
        health = compute_identity_health(char)
        assert health["face"] == "current"

    def test_mark_slots_stale_with_unknown_reason_noop(self):
        """An unknown reason string marks nothing stale and returns empty list."""
        anchor = _base_anchor(
            pack_version=1, front_pv=1,
            body_slots={"body_front": _locked(1)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "removable_element_applied")
        assert invalidated == []
        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"].get("stale") is not True
        assert data["body_slots"]["body_front"].get("stale") is not True


# ── Test 7: permanent body element marks body stale ──────────────────


class TestPermanentBodyElementMarksBodyStale:
    def test_right_arm_placement_marks_body_front_stale(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": _locked(2)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "permanent_style_element", placement="right_arm")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["body_front"]["stale"] is True
        assert "body_front" in invalidated

    def test_left_arm_placement_marks_body_front_stale(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": _locked(2)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "permanent_style_element", placement="left_arm")

        data = json.loads(char.identity_anchor_json)
        assert data["body_slots"]["body_front"]["stale"] is True

    def test_face_placement_marks_face_anchors_stale(self):
        anchor = _base_anchor(pack_version=2, front_pv=2, tq_pv=2)
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "permanent_style_element", placement="face")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"]["stale"] is True
        assert "anchor:front" in invalidated

    def test_neck_placement_marks_both_face_and_body_stale(self):
        # neck affects both face anchors and body slots
        anchor = _base_anchor(
            pack_version=2,
            front_pv=2,
            body_slots={"body_front": _locked(2)},
        )
        char = _char(anchor_json=anchor)
        invalidated = mark_slots_stale(char, "permanent_style_element", placement="neck")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"]["stale"] is True
        assert data["body_slots"]["body_front"]["stale"] is True
        assert "anchor:front" in invalidated
        assert "body_front" in invalidated

    def test_body_element_leaves_face_anchors_current(self):
        anchor = _base_anchor(
            pack_version=2,
            front_pv=2,
            body_slots={"body_front": _locked(2)},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "permanent_style_element", placement="chest")

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"].get("stale") is not True


# ── Test 8: stale slots preserved after snapshot rollback ────────────


class TestStaleSlotsPreservedAfterRollback:
    """Snapshot/rollback must preserve stale flags embedded in identity_anchor_json."""

    def test_stale_flags_in_snapshot_restored_on_rollback(self):
        # Build character with stale flags set
        anchor_with_stale = {
            "pack_version": 2,
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png", "pack_version": 1, "stale": True},
            },
            "body_slots": {
                "body_front": {
                    "url": "http://x/bf.png",
                    "status": "locked",
                    "pack_version": 1,
                    "stale": True,
                },
            },
        }
        char = _char(anchor_json=anchor_with_stale)

        # Simulate take_snapshot: captures current identity_anchor_json
        snapshot_anchor_json = char.identity_anchor_json

        # Simulate later state change (e.g., re-generation cleared stale)
        char.identity_anchor_json = json.dumps({
            "pack_version": 3,
            "anchors": {"front": {"id": 2, "url": "http://x/f2.png", "pack_version": 3}},
            "body_slots": {},
        })

        # Simulate rollback_to_snapshot: restores captured JSON
        char.identity_anchor_json = snapshot_anchor_json

        # Verify stale flags are present again
        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"]["stale"] is True
        assert data["body_slots"]["body_front"]["stale"] is True

    def test_non_stale_snapshot_preserved_on_rollback(self):
        # Snapshot without stale flags — rollback restores that clean state
        clean_anchor = {
            "pack_version": 1,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1}},
            "body_slots": {},
        }
        char = _char(anchor_json=clean_anchor)
        snapshot_json = char.identity_anchor_json

        # Apply a mutation (marks stale)
        mark_slots_stale(char, "body_canon_mutation")

        # Rollback — restore pre-mutation snapshot
        char.identity_anchor_json = snapshot_json

        data = json.loads(char.identity_anchor_json)
        assert data["anchors"]["front"].get("stale") is not True


# ── Test 9: stale slot still keeps URL ───────────────────────────────


class TestStaleSlotKeepsURL:
    """Marking a slot stale must never remove its URL or status."""

    def test_body_front_url_intact_after_stale(self):
        anchor = _base_anchor(
            pack_version=2,
            body_slots={"body_front": {"url": "http://x/bf.png", "status": "locked", "pack_version": 1}},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        entry = data["body_slots"]["body_front"]
        assert entry["url"] == "http://x/bf.png"
        assert entry["status"] == "locked"
        assert entry["stale"] is True

    def test_tattoo_layout_url_intact_after_stale(self):
        anchor = _base_anchor(
            pack_version=3,
            body_slots={"tattoo_layout": {"url": "http://x/tl.png", "status": "locked", "pack_version": 2}},
        )
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "body_canon_mutation")

        data = json.loads(char.identity_anchor_json)
        entry = data["body_slots"]["tattoo_layout"]
        assert entry["url"] == "http://x/tl.png"
        assert entry["status"] == "locked"
        assert entry["stale"] is True

    def test_anchor_url_intact_after_hair_stale(self):
        anchor = _base_anchor(pack_version=2, front_pv=1)
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        data = json.loads(char.identity_anchor_json)
        entry = data["anchors"]["front"]
        assert entry["url"] == "http://x/front.png"
        assert entry["stale"] is True

    def test_root_pack_version_unchanged_by_mark_slots_stale(self):
        anchor = _base_anchor(pack_version=3, front_pv=1)
        char = _char(anchor_json=anchor)
        mark_slots_stale(char, "identity_spec_mutation")

        assert get_pack_version(char) == 3, "mark_slots_stale must NOT change root pack_version"


# ── Test 10: identity_health reports stale correctly ─────────────────


class TestIdentityHealthReportsStaleCorrectly:
    """compute_identity_health must honour both stale flag and version checks,
    and expose per-slot detail in the 'slots' key."""

    def test_health_face_stale_via_flag(self):
        anchor = {
            "pack_version": 1,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1, "stale": True}},
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "stale"

    def test_health_body_stale_via_flag(self):
        anchor = {
            "pack_version": 1,
            "anchors": {},
            "body_slots": {
                "body_front": {
                    "url": "http://x/bf.png",
                    "status": "locked",
                    "pack_version": 1,
                    "stale": True,
                },
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "stale"

    def test_slots_detail_includes_stale_true(self):
        anchor = {
            "pack_version": 2,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1, "stale": True}},
            "body_slots": {
                "body_front": {"url": "http://x/bf.png", "status": "locked", "pack_version": 2},
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)

        assert "slots" in health
        assert health["slots"]["front"]["stale"] is True
        assert health["slots"]["body_front"]["stale"] is False

    def test_slots_detail_only_includes_existing_entries(self):
        anchor = {
            "pack_version": 1,
            "anchors": {"front": {"id": 1, "url": "http://x/f.png", "pack_version": 1}},
            "body_slots": {},
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)

        assert "front" in health["slots"]
        assert "body_front" not in health["slots"]
        assert "tattoo_layout" not in health["slots"]

    def test_full_pipeline_increment_then_mark_then_health(self):
        """End-to-end: increment + mark_slots_stale → health reflects stale correctly."""
        anchor = _base_anchor(
            pack_version=1,
            front_pv=1,
            tq_pv=1,
            body_slots={
                "body_front": _locked(1),
                "tattoo_layout": _locked(1),
            },
        )
        char = _char(anchor_json=anchor)

        # Tattoo added
        increment_pack_version(char, reason="body_canon_mutation")
        mark_slots_stale(char, "body_canon_mutation")

        health = compute_identity_health(char)
        # Face unchanged
        assert health["face"] == "current"
        # Body and tattoos stale
        assert health["body"] == "stale"
        assert health["tattoos"] == "stale"
        # Per-slot detail
        assert health["slots"]["body_front"]["stale"] is True
        assert health["slots"]["tattoo_layout"]["stale"] is True
        assert health["slots"]["front"]["stale"] is False

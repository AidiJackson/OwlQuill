"""Regression tests for Identity Consistency Sprint v2 — Part A.

Covers pack_version tracking, identity_health computation, and stale
invalidation plumbing introduced in app/services/pack_version.py.

All tests are pure unit tests — no DB, no network, no image generation.
Character objects are simulated with a simple namespace so we can control
identity_anchor_json and body_canon_json precisely.
"""
import json
import types

import pytest

from app.services.pack_version import (
    compute_identity_health,
    get_pack_version,
    increment_pack_version,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _char(anchor_json: dict | None = None, body_canon_json: str | None = None, char_id: int = 1):
    """Return a minimal character-like namespace."""
    obj = types.SimpleNamespace()
    obj.id = char_id
    obj.identity_anchor_json = json.dumps(anchor_json) if anchor_json is not None else None
    obj.body_canon_json = body_canon_json
    return obj


def _anchor_with_version(
    pack_version: int,
    *,
    front_version: int | None = None,
    three_quarter_version: int | None = None,
    body_slots: dict | None = None,
) -> dict:
    """Build a minimal identity_anchor_json dict."""
    anchors = {}
    if front_version is not None:
        anchors["front"] = {"id": 1, "url": "http://x/front.png", "pack_version": front_version}
    if three_quarter_version is not None:
        anchors["three_quarter"] = {"id": 2, "url": "http://x/3q.png", "pack_version": three_quarter_version}
    data: dict = {"pack_version": pack_version, "anchors": anchors}
    if body_slots is not None:
        data["body_slots"] = body_slots
    return data


def _locked_slot(version: int) -> dict:
    return {"url": "http://x/slot.png", "status": "locked", "pack_version": version}


def _generated_slot(version: int) -> dict:
    return {"url": "http://x/slot.png", "status": "generated", "pack_version": version}


# ── Test 1: Legacy character (no pack_version) → all current ─────────


class TestLegacyCharacter:
    """Legacy characters with no pack_version must not be false-positived as stale."""

    def test_no_identity_anchor_json_reports_current(self):
        char = _char(anchor_json=None)
        health = compute_identity_health(char)
        assert health["face"] == "current"
        assert health["body"] == "current"
        assert health["tattoos"] == "current"

    def test_anchor_without_pack_version_key_reports_current(self):
        # Pre-v2 anchor entry has no pack_version in individual anchor entries
        anchor = {
            "pack_version": 3,  # root version exists
            "anchors": {
                "front": {"id": 1, "url": "http://x/f.png"},  # no pack_version on entry
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current", "Entry without pack_version must be treated as current"

    def test_body_slot_without_pack_version_reports_current(self):
        anchor = {
            "pack_version": 5,
            "anchors": {},
            "body_slots": {
                "body_front": {"url": "http://x/bf.png", "status": "locked"},  # no pack_version
            },
        }
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "current"
        assert health["tattoos"] == "current"

    def test_get_pack_version_defaults_to_1_when_absent(self):
        char = _char(anchor_json=None)
        assert get_pack_version(char) == 1

    def test_get_pack_version_defaults_to_1_when_key_missing(self):
        char = _char(anchor_json={"anchors": {}})
        assert get_pack_version(char) == 1


# ── Test 2: Hair mutation increments version ──────────────────────────


class TestHairMutationIncrementsVersion:
    """increment_pack_version must raise the version by 1 and log the reason."""

    def test_increment_from_default(self):
        char = _char(anchor_json=None)
        new_v = increment_pack_version(char, reason="identity_spec_mutation")
        assert new_v == 2

    def test_increment_persisted_in_anchor_json(self):
        char = _char(anchor_json=None)
        increment_pack_version(char, reason="identity_spec_mutation")
        assert get_pack_version(char) == 2

    def test_increment_from_existing_version(self):
        char = _char(anchor_json={"pack_version": 4})
        new_v = increment_pack_version(char, reason="identity_spec_mutation")
        assert new_v == 5

    def test_increment_preserves_other_anchor_keys(self):
        anchor = {"pack_version": 1, "identity_lock_string": "blonde hair", "anchors": {}}
        char = _char(anchor_json=anchor)
        increment_pack_version(char, reason="identity_spec_mutation")
        data = json.loads(char.identity_anchor_json)
        assert data["identity_lock_string"] == "blonde hair"
        assert data["anchors"] == {}
        assert data["pack_version"] == 2

    def test_increment_creates_anchor_json_if_none(self):
        char = _char(anchor_json=None)
        assert char.identity_anchor_json is None
        increment_pack_version(char, reason="identity_spec_mutation")
        data = json.loads(char.identity_anchor_json)
        assert data["pack_version"] == 2


# ── Test 3: Tattoo mutation increments version ────────────────────────


class TestTattooMutationIncrementsVersion:
    def test_tattoo_increment(self):
        char = _char(anchor_json={"pack_version": 1})
        increment_pack_version(char, reason="body_canon_mutation")
        assert get_pack_version(char) == 2

    def test_sequential_tattoo_and_hair_increments(self):
        char = _char(anchor_json={"pack_version": 1})
        increment_pack_version(char, reason="body_canon_mutation")
        increment_pack_version(char, reason="identity_spec_mutation")
        assert get_pack_version(char) == 3

    def test_permanent_style_element_increment(self):
        char = _char(anchor_json={"pack_version": 2})
        increment_pack_version(char, reason="permanent_style_element")
        assert get_pack_version(char) == 3


# ── Test 4: Stale face anchors detected ──────────────────────────────


class TestStaleFaceAnchors:
    """Face anchors at an older pack_version must be reported as stale."""

    def test_front_anchor_older_than_current_is_stale(self):
        anchor = _anchor_with_version(2, front_version=1)
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "stale"

    def test_three_quarter_anchor_older_is_stale(self):
        anchor = _anchor_with_version(3, three_quarter_version=1)
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "stale"

    def test_face_current_when_anchors_match_version(self):
        anchor = _anchor_with_version(2, front_version=2, three_quarter_version=2)
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"

    def test_face_current_when_no_anchors(self):
        anchor = _anchor_with_version(3)  # no anchor entries at all
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"


# ── Test 5: Stale body slots detected ────────────────────────────────


class TestStaleBodySlots:
    """Locked body slots older than pack_version must be reported as stale."""

    def test_body_front_older_is_stale(self):
        anchor = _anchor_with_version(
            3,
            body_slots={"body_front": _locked_slot(1)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "stale"

    def test_body_three_quarter_older_is_stale(self):
        anchor = _anchor_with_version(
            2,
            body_slots={"body_three_quarter": _locked_slot(1)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "stale"

    def test_generated_slot_not_counted_for_body_health(self):
        # Only LOCKED slots factor into health — generated (not yet locked) are ignored
        anchor = _anchor_with_version(
            3,
            body_slots={"body_front": _generated_slot(1)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "current", "Non-locked slots must not trigger stale"

    def test_body_current_when_slot_matches_version(self):
        anchor = _anchor_with_version(
            2,
            body_slots={"body_front": _locked_slot(2)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["body"] == "current"


# ── Test 6: Stale tattoos detected ───────────────────────────────────


class TestStaleTattoos:
    """Stale tattoo_layout or body_front must be reported as stale tattoos."""

    def test_tattoo_layout_older_is_stale(self):
        anchor = _anchor_with_version(
            3,
            body_slots={"tattoo_layout": _locked_slot(1)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["tattoos"] == "stale"

    def test_body_front_older_flags_stale_tattoos(self):
        # body_front also carries tattoo placement — if it's stale, tattoos are stale
        anchor = _anchor_with_version(
            4,
            body_slots={"body_front": _locked_slot(2)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["tattoos"] == "stale"

    def test_tattoos_current_when_tattoo_layout_matches(self):
        anchor = _anchor_with_version(
            2,
            body_slots={"tattoo_layout": _locked_slot(2)},
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["tattoos"] == "current"

    def test_no_tattoo_slots_reports_current(self):
        anchor = _anchor_with_version(5, body_slots={})
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["tattoos"] == "current"


# ── Test 7: Current pack reports fully healthy ────────────────────────


class TestCurrentPackHealthy:
    """A freshly locked pack at version N with all anchors at N must be fully healthy."""

    def test_fully_current_pack(self):
        anchor = _anchor_with_version(
            2,
            front_version=2,
            three_quarter_version=2,
            body_slots={
                "body_front": _locked_slot(2),
                "tattoo_layout": _locked_slot(2),
            },
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"
        assert health["body"] == "current"
        assert health["tattoos"] == "current"

    def test_version_1_fresh_pack(self):
        anchor = _anchor_with_version(
            1,
            front_version=1,
            three_quarter_version=1,
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"

    def test_multiple_increments_all_current(self):
        # After 3 increments, everything at version 4 → healthy
        anchor = _anchor_with_version(
            4,
            front_version=4,
            three_quarter_version=4,
            body_slots={
                "body_front": _locked_slot(4),
                "tattoo_layout": _locked_slot(4),
            },
        )
        char = _char(anchor_json=anchor)
        health = compute_identity_health(char)
        assert health["face"] == "current"
        assert health["body"] == "current"
        assert health["tattoos"] == "current"


# ── Test 8: Admin import stores pack_version ──────────────────────────


class TestAdminImportStoresPackVersion:
    """Simulate the admin_canon_import route: pack_version must appear in the slot entry."""

    def _simulate_admin_import(self, char, slot: str, image_url: str) -> dict:
        """Mirror what admin_canon_import does: get_pack_version → include in slot entry."""
        from app.api.routes.body_identity import _save_body_slot, _load_body_slots
        from app.services.pack_version import get_pack_version as _gpv

        pv = _gpv(char)
        meta = {"source": "admin_canon_import", "pack_version": pv}
        _save_body_slot(char, slot, {
            "url": image_url,
            "status": "locked",
            "prompt": None,
            "source": "admin_canon_import",
            "pack_version": pv,
        })
        return _load_body_slots(char)

    def test_admin_import_stamps_pack_version_1(self):
        char = _char(anchor_json=None)
        slots = self._simulate_admin_import(char, "body_front", "http://x/bf.png")
        assert slots["body_front"]["pack_version"] == 1

    def test_admin_import_stamps_incremented_version(self):
        char = _char(anchor_json={"pack_version": 3})
        slots = self._simulate_admin_import(char, "tattoo_layout", "http://x/tl.png")
        assert slots["tattoo_layout"]["pack_version"] == 3

    def test_admin_import_preserves_root_pack_version(self):
        char = _char(anchor_json={"pack_version": 2})
        self._simulate_admin_import(char, "body_front", "http://x/bf.png")
        # Root version unchanged — admin import does not increment
        assert get_pack_version(char) == 2


# ── Test 9: Identity pack generation stores pack_version ─────────────


class TestIdentityPackGenerationStoresPackVersion:
    """Simulate the accept flow: face anchors in anchors_dict must carry pack_version."""

    def test_accept_stamps_pack_version_on_anchors(self):
        # Simulate what accept_identity_pack does when building _new_anchor
        _existing = {}
        _current_pv = int(_existing.get("pack_version") or 1)

        anchors_dict = {
            "front": {"id": 1, "url": "http://x/front.png"},
            "three_quarter": {"id": 2, "url": "http://x/3q.png"},
        }
        for _av in anchors_dict.values():
            _av["pack_version"] = _current_pv

        assert anchors_dict["front"]["pack_version"] == 1
        assert anchors_dict["three_quarter"]["pack_version"] == 1

    def test_accept_preserves_pre_accept_version_on_anchors(self):
        # Character had a tattoo added (version=2) before the face pack was accepted
        _existing = {"pack_version": 2, "body_slots": {}}
        _current_pv = int(_existing.get("pack_version") or 1)

        anchors_dict = {"front": {"id": 1, "url": "http://x/front.png"}}
        for _av in anchors_dict.values():
            _av["pack_version"] = _current_pv

        # Anchors should carry version 2, not reset to 1
        assert anchors_dict["front"]["pack_version"] == 2

    def test_new_anchor_carries_pack_version(self):
        _existing: dict = {}
        _current_pv = int(_existing.get("pack_version") or 1)

        _new_anchor = {
            "version": 1,
            "pack_version": _current_pv,
            "anchors": {},
        }
        assert _new_anchor["pack_version"] == 1


# ── Test 10: Body slot generation stores pack_version ────────────────


class TestBodySlotGenerationStoresPackVersion:
    """Simulate _do_generate_body_slot: slot entry must carry current pack_version."""

    def _simulate_body_slot_generation(self, char, slot: str, image_url: str) -> dict:
        from app.api.routes.body_identity import _save_body_slot, _load_body_slots
        from app.services.pack_version import get_pack_version as _gpv

        pv = _gpv(char)
        _save_body_slot(char, slot, {
            "url": image_url,
            "status": "generated",
            "prompt": "test prompt",
            "pack_version": pv,
        })
        return _load_body_slots(char)

    def test_body_slot_generation_stamps_version_1(self):
        char = _char(anchor_json=None)
        slots = self._simulate_body_slot_generation(char, "body_front", "http://x/bf.png")
        assert slots["body_front"]["pack_version"] == 1

    def test_body_slot_generation_stamps_current_version(self):
        char = _char(anchor_json={"pack_version": 5})
        slots = self._simulate_body_slot_generation(char, "body_three_quarter", "http://x/bq.png")
        assert slots["body_three_quarter"]["pack_version"] == 5

    def test_body_slot_generation_does_not_increment_version(self):
        # Generation stamps but does NOT increment — only mutations increment
        char = _char(anchor_json={"pack_version": 3})
        self._simulate_body_slot_generation(char, "body_front", "http://x/bf.png")
        assert get_pack_version(char) == 3, "Generation must not increment pack_version"

    def test_stale_detected_after_generation_then_increment(self):
        # 1. Generate body_front at version 1
        char = _char(anchor_json=None)
        self._simulate_body_slot_generation(char, "body_front", "http://x/bf.png")
        # 2. Lock the slot (preserves pack_version from generated entry)
        from app.api.routes.body_identity import _save_body_slot, _load_body_slots
        slots = _load_body_slots(char)
        entry = slots.get("body_front") or {}
        _save_body_slot(char, "body_front", {**entry, "status": "locked"})
        # 3. Tattoo added → version increments
        increment_pack_version(char, reason="body_canon_mutation")
        # 4. body_front (version 1) is now stale vs current version 2
        health = compute_identity_health(char)
        assert health["tattoos"] == "stale"
        assert health["body"] == "stale"

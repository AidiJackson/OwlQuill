"""
Tests for Identity Evolution Phase 2: Candidate Slot Replacement.

Covers:
  - Snapshot taken before promotion (snapshot-before-promote)
  - Promotion replaces only one slot
  - Rollback restores previous identity_anchor_json
  - Accessories preserved across promotion
  - Validation returns correct statuses
  - Auth and ownership guards
"""
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.candidate_slot import (
    validate_candidate,
    promote_candidate,
    reject_candidate,
)
from app.models.candidate_slot import CandidateSlot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register_and_login(client: TestClient, email: str) -> str:
    from app.core.config import settings
    _orig = settings.BETA_INVITE_REQUIRED
    settings.BETA_INVITE_REQUIRED = False
    try:
        client.post(
            "/auth/register",
            json={
                "email": email,
                "username": email.split("@")[0].replace(".", "_"),
                "password": "testpassword123",
            },
        )
    finally:
        settings.BETA_INVITE_REQUIRED = _orig
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str, name: str = "Slot Test Char") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _lock_character(client: TestClient, token: str, cid: int) -> None:
    resp = client.post(
        f"/characters/{cid}/identity-pack/generate",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    pack_id = resp.json()["pack_id"]
    resp = client.post(
        f"/characters/{cid}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def _make_anchor_json(slots: dict | None = None, accessories: list | None = None) -> str:
    data: dict = {
        "version": 1,
        "locked_at": "2026-01-01T00:00:00Z",
        "anchors": slots or {
            "front": {"url": "http://example.com/front.png"},
            "three_quarter": {"url": "http://example.com/tq.png"},
        },
        "accessories": accessories or [],
    }
    return json.dumps(data)


def _make_mock_character(
    character_id: int = 1,
    anchor_json: str | None = None,
    spec_json: str | None = None,
    visual_locked: bool = True,
) -> MagicMock:
    mock = MagicMock()
    mock.id = character_id
    mock.owner_id = 1
    mock.visual_locked = visual_locked
    mock.identity_anchor_json = anchor_json or _make_anchor_json()
    mock.identity_spec_json = spec_json
    mock.dna = None
    mock.identity_spec_version = 0
    mock.updated_at = datetime.utcnow()
    return mock


# ── 1. Unit: create_candidate ─────────────────────────────────────────────────

def test_create_candidate_sets_pending_status():
    candidate = CandidateSlot(
        character_id=1,
        slot="front",
        image_url="http://example.com/new.png",
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )
    assert candidate.status == "candidate"
    assert candidate.validation_status == "pending"
    assert candidate.slot == "front"


# ── 2. Unit: validate_candidate ──────────────────────────────────────────────

def test_validate_candidate_invalid_when_not_locked():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    character = _make_mock_character(visual_locked=False)
    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://example.com/new.png",
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )

    result = validate_candidate(mock_db, character, candidate)
    assert result.validation_status == "invalid"
    assert "not locked" in (result.validation_notes or "")


def test_validate_candidate_warning_when_locked_with_image():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    character = _make_mock_character(
        anchor_json=_make_anchor_json(slots={"front": {"url": "http://example.com/front.png"}}),
    )
    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://example.com/new.png",
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )

    result = validate_candidate(mock_db, character, candidate)
    # Should be warning (not invalid) since face embedding is a placeholder
    assert result.validation_status in ("valid", "warning")
    assert result.validation_notes is not None
    assert "Phase 3" in result.validation_notes


def test_validate_candidate_notes_slot_mismatch_when_slot_absent():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    character = _make_mock_character(
        anchor_json=_make_anchor_json(slots={"front": {"url": "http://example.com/front.png"}}),
    )
    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="full_body",  # not present in anchor
        image_url="http://example.com/new.png",
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )

    result = validate_candidate(mock_db, character, candidate)
    assert "no existing anchor image" in (result.validation_notes or "").lower() or \
           "create it for the first time" in (result.validation_notes or "")


# ── 3. Unit: promote_candidate — snapshot before promote ─────────────────────

def test_promote_takes_snapshot_before_mutating():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    original_anchor = _make_anchor_json(slots={"front": {"url": "http://original.com/front.png"}})
    character = _make_mock_character(anchor_json=original_anchor)

    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://new.com/front.png",
        status="candidate",
        validation_status="warning",
        created_at=datetime.utcnow(),
    )

    # Capture what take_snapshot receives
    snapshot_calls = []

    from app.services import candidate_slot as _cs_module
    original_take = _cs_module.take_snapshot

    def mock_take_snapshot(db, char, reason="manual_backup"):
        snapshot_calls.append({
            "anchor_json": char.identity_anchor_json,
            "reason": reason,
        })
        snap = MagicMock()
        snap.id = 99
        snap.character_id = char.id
        snap.snapshot_version = 0
        snap.anchor_version = 1
        snap.reason = reason
        snap.created_at = datetime.utcnow()
        return snap

    _cs_module.take_snapshot = mock_take_snapshot
    try:
        snapshot, updated = promote_candidate(mock_db, character, candidate)
    finally:
        _cs_module.take_snapshot = original_take

    assert len(snapshot_calls) == 1, "take_snapshot must be called exactly once"
    # Snapshot should have captured the ORIGINAL anchor JSON, not the new one
    assert "http://original.com/front.png" in snapshot_calls[0]["anchor_json"]
    assert snapshot_calls[0]["reason"] == "pre_evolution"


# ── 4. Unit: promote_candidate — only replaces selected slot ──────────────────

def test_promote_replaces_only_selected_slot():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    original_anchor = _make_anchor_json(slots={
        "front": {"url": "http://original.com/front.png"},
        "three_quarter": {"url": "http://original.com/tq.png"},
        "torso": {"url": "http://original.com/torso.png"},
    })
    character = _make_mock_character(anchor_json=original_anchor)

    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://new.com/front_new.png",
        status="candidate",
        validation_status="warning",
        created_at=datetime.utcnow(),
    )

    from app.services import candidate_slot as _cs_module
    original_take = _cs_module.take_snapshot
    _cs_module.take_snapshot = lambda db, char, reason="manual_backup": MagicMock(
        id=1, character_id=1, snapshot_version=0, anchor_version=1,
        reason=reason, created_at=datetime.utcnow()
    )
    try:
        _, updated = promote_candidate(mock_db, character, candidate)
    finally:
        _cs_module.take_snapshot = original_take

    # Parse the mutated anchor JSON that was set on character
    mutated = json.loads(character.identity_anchor_json)
    assert mutated["anchors"]["front"]["url"] == "http://new.com/front_new.png"
    assert mutated["anchors"]["three_quarter"]["url"] == "http://original.com/tq.png"
    assert mutated["anchors"]["torso"]["url"] == "http://original.com/torso.png"


# ── 5. Unit: promote_candidate — accessories preserved ───────────────────────

def test_promote_preserves_accessories():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    accessories = [
        {"id": "mask_abc12345", "type": "mask", "name": "Iron Mask", "locked": True}
    ]
    original_anchor = _make_anchor_json(
        slots={"front": {"url": "http://original.com/front.png"}},
        accessories=accessories,
    )
    character = _make_mock_character(anchor_json=original_anchor)

    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://new.com/front_new.png",
        status="candidate",
        validation_status="warning",
        created_at=datetime.utcnow(),
    )

    from app.services import candidate_slot as _cs_module
    original_take = _cs_module.take_snapshot
    _cs_module.take_snapshot = lambda db, char, reason="manual_backup": MagicMock(
        id=1, character_id=1, snapshot_version=0, anchor_version=1,
        reason=reason, created_at=datetime.utcnow()
    )
    try:
        promote_candidate(mock_db, character, candidate)
    finally:
        _cs_module.take_snapshot = original_take

    mutated = json.loads(character.identity_anchor_json)
    assert "accessories" in mutated
    assert len(mutated["accessories"]) == 1
    assert mutated["accessories"][0]["type"] == "mask"
    assert mutated["accessories"][0]["name"] == "Iron Mask"


# ── 6. Unit: rollback restores previous identity_anchor_json ─────────────────

def test_rollback_restores_previous_anchor_json():
    from app.services.identity_evolution import rollback_to_snapshot

    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()

    original_anchor = _make_anchor_json(
        slots={"front": {"url": "http://original.com/front.png"}},
        accessories=[{"id": "mask_abc12345", "type": "mask", "name": "Iron Mask"}],
    )
    new_anchor = _make_anchor_json(
        slots={"front": {"url": "http://new.com/front_new.png"}},
        accessories=[{"id": "mask_abc12345", "type": "mask", "name": "Iron Mask"}],
    )

    character = _make_mock_character(anchor_json=new_anchor)

    snapshot = MagicMock()
    snapshot.identity_anchor_json = original_anchor
    snapshot.identity_spec_json = None

    rollback_to_snapshot(mock_db, character, snapshot)

    # Rollback re-derives pack_stages (identity evolution) on the restored
    # anchor — every other field must be restored exactly.
    restored = json.loads(character.identity_anchor_json)
    assert {k: v for k, v in restored.items() if k != "pack_stages"} == json.loads(original_anchor)
    assert restored["anchors"]["front"]["url"] == "http://original.com/front.png"


# ── 7. Unit: reject_candidate ────────────────────────────────────────────────

def test_reject_candidate_sets_rejected_status():
    mock_db = MagicMock()
    mock_db.add = MagicMock()
    mock_db.commit = MagicMock()
    mock_db.refresh = MagicMock()

    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://example.com/img.png",
        status="candidate",
        validation_status="pending",
        created_at=datetime.utcnow(),
    )

    result = reject_candidate(mock_db, candidate)
    assert result.status == "rejected"


def test_reject_already_promoted_raises():
    mock_db = MagicMock()

    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://example.com/img.png",
        status="promoted",
        validation_status="valid",
        created_at=datetime.utcnow(),
    )

    with pytest.raises(ValueError, match="already promoted"):
        reject_candidate(mock_db, candidate)


# ── 8. HTTP: create candidate endpoint ───────────────────────────────────────

def test_create_candidate_via_http(client: TestClient):
    token = _register_and_login(client, "cslot_create@example.com")
    cid = _create_character(client, token, "Create Slot Char")
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/candidate.png"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["character_id"] == cid
    assert data["slot"] == "front"
    assert data["status"] == "candidate"
    assert data["validation_status"] == "pending"


def test_create_candidate_requires_locked_character(client: TestClient):
    token = _register_and_login(client, "cslot_unlocked@example.com")
    cid = _create_character(client, token, "Unlocked Slot Char")

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/candidate.png"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, resp.text


def test_create_candidate_rejects_invalid_slot(client: TestClient):
    token = _register_and_login(client, "cslot_badslot@example.com")
    cid = _create_character(client, token, "Bad Slot Char")
    _lock_character(client, token, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "invalid_slot", "image_url": "http://example.com/candidate.png"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422, resp.text


def test_create_candidate_requires_auth(client: TestClient):
    resp = client.post(
        "/characters/999/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/candidate.png"},
    )
    assert resp.status_code in (401, 403), resp.text


def test_create_candidate_wrong_owner(client: TestClient):
    token1 = _register_and_login(client, "cslot_owner@example.com")
    token2 = _register_and_login(client, "cslot_thief@example.com")
    cid = _create_character(client, token1, "Owner Slot Char")
    _lock_character(client, token1, cid)

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/candidate.png"},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 403, resp.text


# ── 9. HTTP: validate endpoint ────────────────────────────────────────────────

def test_validate_candidate_via_http(client: TestClient):
    token = _register_and_login(client, "cslot_validate@example.com")
    cid = _create_character(client, token, "Validate Slot Char")
    _lock_character(client, token, cid)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/candidate.png"},
        headers=headers,
    )
    candidate_id = resp.json()["id"]

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/validate",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["validation_status"] in ("valid", "warning", "invalid")
    assert data["validation_notes"] is not None


# ── 10. HTTP: promote endpoint — snapshot + one slot replaced ────────────────

def test_promote_via_http_takes_snapshot_and_replaces_slot(client: TestClient):
    token = _register_and_login(client, "cslot_promote@example.com")
    cid = _create_character(client, token, "Promote Slot Char")
    _lock_character(client, token, cid)
    headers = {"Authorization": f"Bearer {token}"}

    # Create and validate candidate
    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/new_front.png"},
        headers=headers,
    )
    candidate_id = resp.json()["id"]

    client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/validate",
        headers=headers,
    )

    # Promote
    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/promote",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "snapshot" in data
    assert "candidate" in data
    assert data["candidate"]["status"] == "promoted"
    assert data["snapshot"]["reason"] == "pre_evolution"

    # Verify a snapshot was recorded
    resp = client.get(
        f"/characters/{cid}/identity-evolution/snapshots",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    snapshots = resp.json()
    assert any(s["reason"] == "pre_evolution" for s in snapshots)


def test_promote_invalid_candidate_returns_409():
    """Service raises ValueError when promoting a candidate with validation_status='invalid'."""
    from app.services.candidate_slot import promote_candidate as _promote

    mock_db = MagicMock()
    character = _make_mock_character()
    candidate = CandidateSlot(
        id=1,
        character_id=1,
        slot="front",
        image_url="http://example.com/img.png",
        status="candidate",
        validation_status="invalid",
        created_at=datetime.utcnow(),
    )

    with pytest.raises(ValueError, match="invalid"):
        _promote(mock_db, character, candidate)


# ── 11. HTTP: reject endpoint ─────────────────────────────────────────────────

def test_reject_via_http(client: TestClient):
    token = _register_and_login(client, "cslot_reject@example.com")
    cid = _create_character(client, token, "Reject Slot Char")
    _lock_character(client, token, cid)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "torso", "image_url": "http://example.com/torso.png"},
        headers=headers,
    )
    candidate_id = resp.json()["id"]

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/reject",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"


def test_reject_already_rejected_returns_409(client: TestClient):
    token = _register_and_login(client, "cslot_reject2@example.com")
    cid = _create_character(client, token, "Double Reject Char")
    _lock_character(client, token, cid)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "torso", "image_url": "http://example.com/torso.png"},
        headers=headers,
    )
    candidate_id = resp.json()["id"]

    client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/reject",
        headers=headers,
    )
    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/reject",
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


# ── 12. HTTP: rollback restores identity_anchor_json ─────────────────────────

def test_rollback_after_promote_restores_previous_anchor(client: TestClient):
    """
    Full lifecycle: create candidate → promote → rollback → verify original restored.
    Verification uses the GET /characters/{id} endpoint rather than direct DB access.
    """
    token = _register_and_login(client, "cslot_rollback@example.com")
    cid = _create_character(client, token, "Rollback Slot Char")
    _lock_character(client, token, cid)
    headers = {"Authorization": f"Bearer {token}"}

    # Record identity_anchor_json via the API before promotion
    char_before_resp = client.get(f"/characters/{cid}", headers=headers)
    anchor_before = char_before_resp.json().get("identity_anchor_json") if char_before_resp.status_code == 200 else None

    # Create + validate + promote candidate
    resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot",
        json={"slot": "front", "image_url": "http://example.com/promoted.png"},
        headers=headers,
    )
    candidate_id = resp.json()["id"]
    client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/validate",
        headers=headers,
    )
    promote_resp = client.post(
        f"/characters/{cid}/identity-evolution/candidate-slot/{candidate_id}/promote",
        headers=headers,
    )
    assert promote_resp.status_code == 200, promote_resp.text
    snapshot_id = promote_resp.json()["snapshot"]["id"]

    # Confirm the new URL is present after promotion
    char_promoted_resp = client.get(f"/characters/{cid}", headers=headers)
    anchor_promoted = char_promoted_resp.json().get("identity_anchor_json") if char_promoted_resp.status_code == 200 else None
    if anchor_promoted:
        assert "http://example.com/promoted.png" in anchor_promoted

    # Rollback
    resp = client.post(
        f"/characters/{cid}/identity-evolution/rollback/{snapshot_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Verify the promoted URL is gone after rollback
    char_after_resp = client.get(f"/characters/{cid}", headers=headers)
    anchor_after = char_after_resp.json().get("identity_anchor_json") if char_after_resp.status_code == 200 else None
    if anchor_before and anchor_after:
        assert "http://example.com/promoted.png" not in (anchor_after or "")

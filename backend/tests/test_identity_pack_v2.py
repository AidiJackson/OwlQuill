"""Tests for Identity Pack v2: snapshot safety, pack stages, admin canon import."""
import io
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import auth_headers, get_auth_token

# Minimal 1x1 PNG
_STUB_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

_ADMIN_EMAIL = "admin_v2_test@test.com"


# ── Helpers ────────────────────────────────────────────────────────────

def _make_user(client, email, username):
    client.post("/auth/register", json={"email": email, "username": username, "password": "testpass!123"})
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return auth_headers(resp.json()["access_token"])


def _create_character(client, headers, name="V2TestChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_admin_headers(client, monkeypatch):
    """Create a user whose email is in ADMIN_EMAILS and return their headers."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")
    return _make_user(client, _ADMIN_EMAIL, "adminv2user")


def _set_body_canon(db_session, character_id, markings):
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == character_id).first()
    char.body_canon_json = json.dumps({"markings": markings})
    db_session.commit()


def _set_body_slot_locked(db_session, character_id, slot, url="http://example.com/img.png"):
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == character_id).first()
    data = {}
    if char.identity_anchor_json:
        try:
            data = json.loads(char.identity_anchor_json)
        except (ValueError, TypeError):
            pass
    data.setdefault("body_slots", {})[slot] = {"url": url, "status": "locked"}
    char.identity_anchor_json = json.dumps(data)
    db_session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Snapshot model — body_canon_json column
# ══════════════════════════════════════════════════════════════════════════════

def test_identity_snapshot_model_has_body_canon_json():
    from app.models.identity_snapshot import IdentitySnapshot
    assert hasattr(IdentitySnapshot, "body_canon_json")


# ══════════════════════════════════════════════════════════════════════════════
# 2. take_snapshot copies body_canon_json
# ══════════════════════════════════════════════════════════════════════════════

def test_take_snapshot_copies_body_canon_json(client, db_session):
    headers = _make_user(client, "snap_bc@test.com", "snapbcuser")
    char_id = _create_character(client, headers, "SnapBCChar")

    marking_data = {"markings": [{"id": "bm_aaa", "type": "tattoo", "placement": "left_full_arm",
                                   "style": "black serpent sleeve", "size": "full_sleeve",
                                   "description": "desc", "coverage": None,
                                   "anchor_image_url": None, "anchor_status": "missing",
                                   "anchor_prompt": None}]}
    _set_body_canon(db_session, char_id, marking_data["markings"])

    # Lock character so snapshot endpoint works
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    char.visual_locked = True
    db_session.commit()

    resp = client.post(f"/characters/{char_id}/identity-evolution/snapshot", headers=headers)
    assert resp.status_code == 201, resp.text

    from app.models.identity_snapshot import IdentitySnapshot
    snap = db_session.query(IdentitySnapshot).filter(
        IdentitySnapshot.character_id == char_id
    ).order_by(IdentitySnapshot.id.desc()).first()
    assert snap is not None
    assert snap.body_canon_json is not None
    bc = json.loads(snap.body_canon_json)
    assert len(bc["markings"]) == 1
    assert bc["markings"][0]["id"] == "bm_aaa"


# ══════════════════════════════════════════════════════════════════════════════
# 3. rollback_to_snapshot restores body_canon_json
# ══════════════════════════════════════════════════════════════════════════════

def test_rollback_restores_body_canon_json():
    from app.models.character import Character
    from app.models.identity_snapshot import IdentitySnapshot
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    char = MagicMock(spec=Character)
    char.identity_anchor_json = '{"version": 1}'
    char.identity_spec_json = None
    char.body_canon_json = '{"markings": [{"id": "bm_after"}]}'

    snap = MagicMock(spec=IdentitySnapshot)
    snap.identity_anchor_json = '{"version": 1}'
    snap.identity_spec_json = None
    snap.body_canon_json = '{"markings": [{"id": "bm_before"}]}'

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    assert char.body_canon_json == '{"markings": [{"id": "bm_before"}]}'


def test_rollback_skips_body_canon_when_snapshot_is_null():
    """If snapshot was taken before bc02 migration, body_canon_json is None — don't overwrite."""
    from app.models.character import Character
    from app.models.identity_snapshot import IdentitySnapshot
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    char = MagicMock(spec=Character)
    char.body_canon_json = '{"markings": [{"id": "bm_current"}]}'
    char.identity_anchor_json = None
    char.identity_spec_json = None

    snap = MagicMock(spec=IdentitySnapshot)
    snap.identity_anchor_json = None
    snap.identity_spec_json = None
    snap.body_canon_json = None  # legacy snapshot

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    # body_canon_json must be untouched
    assert char.body_canon_json == '{"markings": [{"id": "bm_current"}]}'


# ══════════════════════════════════════════════════════════════════════════════
# 4. compute_pack_stages unit tests
# ══════════════════════════════════════════════════════════════════════════════

def _make_char(visual_locked=False, identity_anchor_json=None, body_canon_json=None):
    from unittest.mock import MagicMock
    from app.models.character import Character
    char = MagicMock(spec=Character)
    char.id = 1
    char.visual_locked = visual_locked
    char.identity_anchor_json = identity_anchor_json
    char.body_canon_json = body_canon_json
    return char


def test_compute_pack_stages_all_missing():
    from app.services.identity_evolution import compute_pack_stages
    char = _make_char()
    stages = compute_pack_stages(char)
    assert stages == {"face": "missing", "body": "missing", "marks": "missing"}


def test_compute_pack_stages_face_locked():
    from app.services.identity_evolution import compute_pack_stages
    char = _make_char(visual_locked=True)
    stages = compute_pack_stages(char)
    assert stages["face"] == "locked"


def test_compute_pack_stages_body_partial():
    from app.services.identity_evolution import compute_pack_stages
    anchor_json = json.dumps({"body_slots": {"body_front": {"url": "http://x.com/img.png", "status": "generated"}}})
    char = _make_char(identity_anchor_json=anchor_json)
    stages = compute_pack_stages(char)
    assert stages["body"] == "partial"


def test_compute_pack_stages_body_locked():
    from app.services.identity_evolution import compute_pack_stages
    anchor_json = json.dumps({"body_slots": {"body_front": {"url": "http://x.com/img.png", "status": "locked"}}})
    char = _make_char(identity_anchor_json=anchor_json)
    stages = compute_pack_stages(char)
    assert stages["body"] == "locked"


def test_compute_pack_stages_marks_partial_no_tattoo_layout():
    from app.services.identity_evolution import compute_pack_stages
    bc_json = json.dumps({"markings": [{"id": "bm_01"}]})
    char = _make_char(body_canon_json=bc_json)
    stages = compute_pack_stages(char)
    assert stages["marks"] == "partial"


def test_compute_pack_stages_marks_locked():
    from app.services.identity_evolution import compute_pack_stages
    bc_json = json.dumps({"markings": [{"id": "bm_01"}]})
    anchor_json = json.dumps({"body_slots": {"tattoo_layout": {"url": "http://x.com/tl.png", "status": "locked"}}})
    char = _make_char(identity_anchor_json=anchor_json, body_canon_json=bc_json)
    stages = compute_pack_stages(char)
    assert stages["marks"] == "locked"


def test_compute_pack_stages_marks_missing_empty_markings():
    from app.services.identity_evolution import compute_pack_stages
    bc_json = json.dumps({"markings": []})
    anchor_json = json.dumps({"body_slots": {"tattoo_layout": {"url": "http://x.com/tl.png", "status": "locked"}}})
    char = _make_char(identity_anchor_json=anchor_json, body_canon_json=bc_json)
    stages = compute_pack_stages(char)
    assert stages["marks"] == "missing"


# ══════════════════════════════════════════════════════════════════════════════
# 5. write_pack_stages persists into identity_anchor_json
# ══════════════════════════════════════════════════════════════════════════════

def test_write_pack_stages_creates_pack_stages_key():
    from app.services.identity_evolution import write_pack_stages
    char = _make_char(visual_locked=True, identity_anchor_json='{"version": 1}')
    stages = write_pack_stages(char)
    assert stages["face"] == "locked"
    data = json.loads(char.identity_anchor_json)
    assert "pack_stages" in data
    assert data["pack_stages"]["face"] == "locked"


def test_write_pack_stages_preserves_existing_fields():
    from app.services.identity_evolution import write_pack_stages
    char = _make_char(identity_anchor_json='{"version": 1, "identity_lock_string": "LOCK: test"}')
    write_pack_stages(char)
    data = json.loads(char.identity_anchor_json)
    assert data["identity_lock_string"] == "LOCK: test"
    assert "pack_stages" in data


def test_write_pack_stages_initialises_from_null_json():
    from app.services.identity_evolution import write_pack_stages
    char = _make_char(identity_anchor_json=None)
    write_pack_stages(char)
    data = json.loads(char.identity_anchor_json)
    assert "pack_stages" in data


# ══════════════════════════════════════════════════════════════════════════════
# 6. pack_stages written on body-slot lock
# ══════════════════════════════════════════════════════════════════════════════

def test_body_slot_lock_writes_pack_stages(client, db_session):
    headers = _make_user(client, "packstage_lock@test.com", "packstagelock")
    char_id = _create_character(client, headers, "PackStageLock")

    # Manually set a generated body_front slot
    _set_body_slot_locked(db_session, char_id, "body_front")
    # Reset to "generated" so the lock endpoint is callable
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    data = json.loads(char.identity_anchor_json or "{}")
    data.setdefault("body_slots", {})["body_front"] = {"url": "http://x.com/img.png", "status": "generated"}
    char.identity_anchor_json = json.dumps(data)
    db_session.commit()

    resp = client.post(f"/characters/{char_id}/identity/body-slots/body_front/lock", headers=headers)
    assert resp.status_code == 200, resp.text

    db_session.refresh(char)
    anchor_data = json.loads(char.identity_anchor_json or "{}")
    assert "pack_stages" in anchor_data
    assert anchor_data["pack_stages"]["body"] == "locked"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Admin canon import — access control
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_canon_import_rejects_non_admin(client, db_session, monkeypatch):
    headers = _make_user(client, "nonadmin_ci@test.com", "nonadminci")
    char_id = _create_character(client, headers, "NonAdminChar")

    resp = client.post(
        f"/characters/{char_id}/identity/canon-import",
        headers=headers,
        data={"target_slot": "body_front"},
        files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
    )
    assert resp.status_code == 403, resp.text


def test_admin_canon_import_rejects_invalid_slot(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminInvalidSlot")

    resp = client.post(
        f"/characters/{char_id}/identity/canon-import",
        headers=hdrs,
        data={"target_slot": "body_back"},  # not an allowed import slot
        files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
    )
    assert resp.status_code == 422, resp.text


def test_admin_canon_import_rejects_bad_content_type(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminBadCT")

    resp = client.post(
        f"/characters/{char_id}/identity/canon-import",
        headers=hdrs,
        data={"target_slot": "body_front"},
        files={"file": ("doc.txt", io.BytesIO(b"not an image"), "text/plain")},
    )
    assert resp.status_code == 422, resp.text


def test_admin_canon_import_rejects_unknown_character(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)

    resp = client.post(
        "/characters/999999/identity/canon-import",
        headers=hdrs,
        data={"target_slot": "body_front"},
        files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
    )
    assert resp.status_code == 404, resp.text


# ══════════════════════════════════════════════════════════════════════════════
# 8. Admin canon import — happy path (body_front)
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_canon_import_body_front_success(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportBody")

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/canon.png"):
        resp = client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "body_front"},
            files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["target_slot"] == "body_front"
    assert data["url"] == "http://cdn.test/canon.png"
    assert "image_id" in data
    assert "pack_stages" in data
    assert data["pack_stages"]["body"] == "locked"


def test_admin_canon_import_tattoo_layout_success(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportTattoo")

    # Add a marking so marks stage is meaningful
    _set_body_canon(db_session, char_id, [
        {"id": "bm_x1", "type": "tattoo", "placement": "right_full_arm",
         "style": "tribal", "size": "large", "description": "desc",
         "coverage": None, "anchor_image_url": None, "anchor_status": "missing", "anchor_prompt": None}
    ])

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/tl.png"):
        resp = client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "tattoo_layout"},
            files={"file": ("tl.png", io.BytesIO(_STUB_PNG), "image/png")},
        )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["target_slot"] == "tattoo_layout"
    assert data["pack_stages"]["marks"] == "locked"


def test_admin_canon_import_creates_character_image_record(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportCIRecord")

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/ci.png"):
        resp = client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "body_front", "source_note": "artist render v1"},
            files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
        )
    assert resp.status_code == 201, resp.text
    image_id = resp.json()["image_id"]

    from app.models.character_image import CharacterImage, ImageKindEnum
    ci = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
    assert ci is not None
    assert ci.kind == ImageKindEnum.IDENTITY_BODY_FRONT
    assert ci.provider == "admin_upload"
    meta = ci.metadata_json or {}
    assert meta.get("source") == "admin_canon_import"
    assert meta.get("source_note") == "artist render v1"


def test_admin_canon_import_archives_previous_active_image(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportArchive")

    from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum

    # Insert an existing active IDENTITY_BODY_FRONT image
    existing = CharacterImage(
        character_id=char_id,
        kind=ImageKindEnum.IDENTITY_BODY_FRONT,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="generated",
        prompt_summary="prior body front",
        file_path="http://cdn.test/prior.png",
    )
    db_session.add(existing)
    db_session.commit()
    prior_id = existing.id

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/new.png"):
        resp = client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "body_front"},
            files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
        )
    assert resp.status_code == 201, resp.text

    db_session.refresh(existing)
    assert existing.status == ImageStatusEnum.ARCHIVED


def test_admin_canon_import_locks_body_slot_in_anchor_json(client, db_session, monkeypatch):
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportAnchorJSON")

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/bf.png"):
        client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "body_front"},
            files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
        )

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)
    anchor = json.loads(char.identity_anchor_json or "{}")
    bf = anchor.get("body_slots", {}).get("body_front", {})
    assert bf.get("status") == "locked"
    assert bf.get("url") == "http://cdn.test/bf.png"
    assert bf.get("source") == "admin_canon_import"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Admin canon import — does NOT touch body_canon_json
# ══════════════════════════════════════════════════════════════════════════════

def test_admin_canon_import_does_not_reset_body_canon(client, db_session, monkeypatch):
    """Importing a body_front image must not delete or modify body_canon_json."""
    hdrs = _make_admin_headers(client, monkeypatch)
    char_id = _create_character(client, hdrs, "AdminImportNoBC")

    markings = [{"id": "bm_safe", "type": "tattoo", "placement": "neck",
                  "style": "vine", "size": "medium", "description": "desc",
                  "coverage": None, "anchor_image_url": None, "anchor_status": "missing",
                  "anchor_prompt": None}]
    _set_body_canon(db_session, char_id, markings)

    with patch("app.api.routes.body_identity.save_image", return_value="http://cdn.test/bf2.png"):
        client.post(
            f"/characters/{char_id}/identity/canon-import",
            headers=hdrs,
            data={"target_slot": "body_front"},
            files={"file": ("img.png", io.BytesIO(_STUB_PNG), "image/png")},
        )

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)
    bc = json.loads(char.body_canon_json or "{}")
    assert len(bc.get("markings", [])) == 1
    assert bc["markings"][0]["id"] == "bm_safe"


# ══════════════════════════════════════════════════════════════════════════════
# 10. pack_stages written on face lock (visual)
# ══════════════════════════════════════════════════════════════════════════════

def test_pack_stages_written_when_face_locked(client, db_session):
    """After accepting an identity pack, pack_stages.face must be 'locked'."""
    headers = _make_user(client, "facelock_ps@test.com", "facelockps")
    char_id = _create_character(client, headers, "FaceLockPS")

    # Simulate a locked character with identity_anchor_json already set
    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    char.visual_locked = True
    char.identity_anchor_json = json.dumps({"version": 1, "identity_lock_string": "IDENTITY: test"})
    db_session.commit()

    from app.services.identity_evolution import compute_pack_stages
    stages = compute_pack_stages(char)
    assert stages["face"] == "locked"


# ══════════════════════════════════════════════════════════════════════════════
# 11. Rollback pack-stage regression — write_pack_stages called after restore
# ══════════════════════════════════════════════════════════════════════════════

def _rollback_char(visual_locked=True, identity_anchor_json=None, body_canon_json=None):
    """Build a MagicMock Character for rollback tests."""
    from unittest.mock import MagicMock
    from app.models.character import Character
    char = MagicMock(spec=Character)
    char.id = 99
    char.visual_locked = visual_locked
    char.identity_anchor_json = identity_anchor_json
    char.body_canon_json = body_canon_json
    return char


def _rollback_snap(identity_anchor_json=None, identity_spec_json=None, body_canon_json=None):
    """Build a MagicMock IdentitySnapshot for rollback tests."""
    from unittest.mock import MagicMock
    from app.models.identity_snapshot import IdentitySnapshot
    snap = MagicMock(spec=IdentitySnapshot)
    snap.identity_anchor_json = identity_anchor_json
    snap.identity_spec_json = identity_spec_json
    snap.body_canon_json = body_canon_json
    return snap


def test_rollback_body_slot_removed_stage_updates_to_missing():
    """After rolling back to a snapshot with no body_front slot, pack_stages.body = 'missing'."""
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    # Current state: body was locked; stale pack_stages baked into live JSON
    char = _rollback_char(
        visual_locked=True,
        identity_anchor_json=json.dumps({
            "body_slots": {"body_front": {"url": "http://x/old.png", "status": "locked"}},
            "pack_stages": {"face": "locked", "body": "locked", "marks": "missing"},
        }),
        body_canon_json=None,
    )

    # Snapshot: taken before body was locked — no body_front slot, stale stages in JSON
    snap = _rollback_snap(
        identity_anchor_json=json.dumps({
            "pack_stages": {"face": "locked", "body": "locked", "marks": "missing"},
        }),
        body_canon_json=None,
    )

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    data = json.loads(char.identity_anchor_json)
    assert data["pack_stages"]["body"] == "missing", (
        "pack_stages.body must be 'missing' after rolling back to a snapshot with no body_front slot"
    )


def test_rollback_tattoo_layout_removed_marks_stage_updates():
    """After rolling back to a snapshot without tattoo_layout, pack_stages.marks = 'partial'."""
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    bc_json = json.dumps({"markings": [{"id": "bm_x1"}]})

    char = _rollback_char(
        visual_locked=True,
        identity_anchor_json=json.dumps({
            "body_slots": {
                "body_front": {"url": "http://x/body.png", "status": "locked"},
                "tattoo_layout": {"url": "http://x/tl.png", "status": "locked"},
            },
            "pack_stages": {"face": "locked", "body": "locked", "marks": "locked"},
        }),
        body_canon_json=bc_json,
    )

    # Snapshot: has body_front locked but no tattoo_layout
    snap = _rollback_snap(
        identity_anchor_json=json.dumps({
            "body_slots": {"body_front": {"url": "http://x/body.png", "status": "locked"}},
            "pack_stages": {"face": "locked", "body": "locked", "marks": "locked"},
        }),
        body_canon_json=bc_json,
    )

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    data = json.loads(char.identity_anchor_json)
    assert data["pack_stages"]["marks"] == "partial", (
        "marks must be 'partial' when markings exist but tattoo_layout slot is absent"
    )
    assert data["pack_stages"]["body"] == "locked", "body slot still present — must stay locked"


def test_rollback_to_face_only_snapshot_body_and_marks_missing():
    """Rolling back to a face-only snapshot leaves body and marks as 'missing'."""
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    char = _rollback_char(
        visual_locked=True,
        identity_anchor_json=json.dumps({
            "body_slots": {
                "body_front": {"url": "http://x/body.png", "status": "locked"},
                "tattoo_layout": {"url": "http://x/tl.png", "status": "locked"},
            },
            "pack_stages": {"face": "locked", "body": "locked", "marks": "locked"},
        }),
        body_canon_json=json.dumps({"markings": [{"id": "bm_y1"}]}),
    )

    # Face-only snapshot: no body_slots, no body_canon markings
    snap = _rollback_snap(
        identity_anchor_json=json.dumps({"identity_lock_string": "IDENTITY: v1"}),
        body_canon_json=json.dumps({"markings": []}),
    )

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    data = json.loads(char.identity_anchor_json)
    assert data["pack_stages"]["face"] == "locked", "face must remain locked (visual_locked not touched)"
    assert data["pack_stages"]["body"] == "missing", "body must be missing — no body_front slot in snapshot"
    assert data["pack_stages"]["marks"] == "missing", "marks must be missing — no markings in restored body_canon"


def test_rollback_preserves_locked_stages_when_slots_still_present():
    """Rolling back to a snapshot with locked slots keeps pack_stages correct."""
    from app.services.identity_evolution import rollback_to_snapshot
    from unittest.mock import MagicMock

    bc_json = json.dumps({"markings": [{"id": "bm_z1"}]})

    char = _rollback_char(
        visual_locked=True,
        identity_anchor_json=json.dumps({"pack_stages": {"face": "locked", "body": "missing", "marks": "missing"}}),
        body_canon_json=None,
    )

    # Snapshot: body_front and tattoo_layout both locked, markings present
    snap = _rollback_snap(
        identity_anchor_json=json.dumps({
            "body_slots": {
                "body_front": {"url": "http://x/body.png", "status": "locked"},
                "tattoo_layout": {"url": "http://x/tl.png", "status": "locked"},
            },
            "pack_stages": {"face": "locked", "body": "locked", "marks": "locked"},
        }),
        body_canon_json=bc_json,
    )

    db = MagicMock()
    rollback_to_snapshot(db, char, snap)

    data = json.loads(char.identity_anchor_json)
    assert data["pack_stages"]["face"] == "locked"
    assert data["pack_stages"]["body"] == "locked", "body slot still locked in restored snapshot"
    assert data["pack_stages"]["marks"] == "locked", "marks still locked — slot + markings both present"

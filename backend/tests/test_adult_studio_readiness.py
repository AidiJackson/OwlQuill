"""Tests for the admin-only Adult Studio training-readiness endpoint.

GET /admin/adult-studio/characters/{id}/readiness — read-only ready_to_train +
blocking_reasons over locked-canon preconditions, prepared identity state, and per-mark
references.

No provider, training, or generation; readiness reads canon + adult_identity_* only.
Test fixtures set up canon state (allowed); the readiness service itself writes nothing.
"""
from fastapi.testclient import TestClient

from app.models.adult_identity import AdultIdentityModel
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services.adult_identity_preparation import prepare_adult_identity
from tests.canon_test_utils import setup_canon

_ADMIN_EMAIL = "as-ready-admin@ficshon.com"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str, username: str, password="pass12345") -> str:
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client) -> str:
    return _register_and_login(client, _ADMIN_EMAIL, "asreadyadmin")


def _create_character(client, token, name="Summer") -> int:
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _readiness_url(cid: int) -> str:
    return f"/admin/adult-studio/characters/{cid}/readiness"


def _summer_marks() -> list[dict]:
    return [
        {
            "label": "Butterfly floral sleeve", "type": "tattoo",
            "body_region": "right_upper_arm", "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
        },
        {
            "label": "Black-and-white ballerina tattoo", "type": "tattoo",
            "body_region": "left_forearm", "side": "left",
            "description": "Left forearm black-and-white ballerina tattoo",
            "reference_image_url": "static/generated/mark_left.png",
        },
    ]


def _ready_summer(client, db, monkeypatch, *, marks=None):
    """Build a fully training-ready character (locked canon + prepared identity)."""
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    setup_canon(db, cid, marks=marks if marks is not None else _summer_marks(),
                lock=True, with_images=True)
    prepare_adult_identity(cid, db)
    return token, cid


def _canon(db, cid) -> CharacterIdentityCanon:
    return db.query(CharacterIdentityCanon).filter(CharacterIdentityCanon.character_id == cid).first()


# ── Access control ───────────────────────────────────────────────────────────


def test_readiness_requires_authentication(client):
    resp = client.get(_readiness_url(1))
    assert resp.status_code in (401, 403)


def test_readiness_non_admin_forbidden(client, db_session):
    token = _register_and_login(client, "plain-ready@test.com", "plainready")
    cid = _create_character(client, token)
    resp = client.get(_readiness_url(cid), headers=_headers(token))
    assert resp.status_code == 403


# ── Summer passes ────────────────────────────────────────────────────────────


def test_summer_passes(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is True
    assert data["blocking_reasons"] == []
    assert data["status"] == "prepared"
    assert data["stale"] is False
    assert all(data["checks"].values())
    assert data["canon_mark_count"] == 2
    assert data["mark_render_count"] == 2
    assert data["unreferenced_marks"] == []


# ── Precondition failures ────────────────────────────────────────────────────


def test_missing_face_lock_fails(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    canon = _canon(db_session, cid)
    canon.face_locked = False
    db_session.commit()

    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is False
    assert data["checks"]["face_locked"] is False
    assert any("face" in r for r in data["blocking_reasons"])


def test_missing_body_lock_fails(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    canon = _canon(db_session, cid)
    canon.body_locked = False
    db_session.commit()

    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is False
    assert data["checks"]["body_locked"] is False
    assert any("body" in r for r in data["blocking_reasons"])


def test_missing_mark_reference_fails(client, db_session, monkeypatch):
    # A permanent mark with no reference image (and no detail crop).
    marks = [{
        "label": "Plain scar", "type": "scar", "body_region": "left_knee",
        "side": "left", "description": "a small unreferenced scar",
    }]
    token, cid = _ready_summer(client, db_session, monkeypatch, marks=marks)

    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is False
    assert data["checks"]["mark_references_exist"] is False
    assert data["unreferenced_marks"]  # at least one
    assert any("reference" in r for r in data["blocking_reasons"])


def test_stale_identity_reported(client, db_session, monkeypatch):
    token, cid = _ready_summer(client, db_session, monkeypatch)
    model = db_session.query(AdultIdentityModel).filter(AdultIdentityModel.character_id == cid).first()
    model.status = "stale"
    db_session.commit()

    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is False
    assert data["stale"] is True
    assert data["checks"]["not_stale"] is False
    assert any("stale" in r for r in data["blocking_reasons"])


def test_no_identity_reports_not_prepared(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    # canon locked but never prepared → no AdultIdentityModel

    data = client.get(_readiness_url(cid), headers=_headers(token)).json()
    assert data["ready_to_train"] is False
    assert data["checks"]["identity_exists"] is False
    assert any("prepared" in r for r in data["blocking_reasons"])


def test_readiness_character_not_found(client, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    resp = client.get(_readiness_url(999999), headers=_headers(token))
    assert resp.status_code == 404

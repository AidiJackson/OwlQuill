"""Tests for the admin-only Adult Studio identity diagnostics endpoint.

GET /admin/adult-studio/characters/{id}/diagnostics — read-only visibility into the
identity lifecycle (prepared / stale / failed / ready), versions, training jobs, mark
routes, and the stale current-vs-trained fingerprint comparison.

No provider, training, generation, or canon access — diagnostics reads adult_identity_*
rows only.
"""
from fastapi.testclient import TestClient

from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
    AdultIdentityTrainingJob,
)

_ADMIN_EMAIL = "as-diag-admin@ficshon.com"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str, username: str, password="pass12345") -> str:
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(monkeypatch):
    """Configure ADMIN_EMAIL so _ADMIN_EMAIL is treated as an admin."""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client) -> str:
    return _register_and_login(client, _ADMIN_EMAIL, "asdiagadmin")


def _create_character(client, token, name="Summer") -> int:
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _diag_url(cid: int) -> str:
    return f"/admin/adult-studio/characters/{cid}/diagnostics"


def _model(db, cid, **kw) -> AdultIdentityModel:
    m = AdultIdentityModel(character_id=cid, trigger_token="fictest", **kw)
    db.add(m); db.commit(); db.refresh(m)
    return m


def _mark(db, identity_id, canon_mark_id, region, side, route, reason):
    db.add(AdultIdentityMarkRender(
        identity_id=identity_id, canon_mark_id=canon_mark_id, mark_type="tattoo",
        body_region=region, side=side, route=route, params_json={"reason": reason},
    ))
    db.commit()


def _version(db, identity_id, index, fingerprint, state="active") -> AdultIdentityModelVersion:
    v = AdultIdentityModelVersion(
        identity_id=identity_id, version_index=index, canon_fingerprint=fingerprint, state=state,
    )
    db.add(v); db.commit(); db.refresh(v)
    return v


# ── Access control ───────────────────────────────────────────────────────────


def test_diagnostics_requires_authentication(client):
    resp = client.get(_diag_url(1))
    assert resp.status_code in (401, 403)


def test_diagnostics_non_admin_forbidden(client, db_session):
    token = _register_and_login(client, "plainuser@test.com", "plainuser")
    cid = _create_character(client, token)
    _model(db_session, cid, status="prepared", canon_fingerprint="a" * 64)
    resp = client.get(_diag_url(cid), headers=_headers(token))
    assert resp.status_code == 403


def test_diagnostics_admin_allowed(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _model(db_session, cid, status="prepared", canon_fingerprint="a" * 64)
    resp = client.get(_diag_url(cid), headers=_headers(token))
    assert resp.status_code == 200, resp.text


def test_diagnostics_character_not_found(client, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    resp = client.get(_diag_url(999999), headers=_headers(token))
    assert resp.status_code == 404


# ── Prepared state + mark-route visibility ───────────────────────────────────


def test_diagnostics_prepared_state_and_mark_routes(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    m = _model(db_session, cid, status="prepared", canon_fingerprint="f" * 64)
    _mark(db_session, m.id, "pbm_right", "right_upper_arm", "right", "ip_adapter",
          "matched sleeve keyword → ip_adapter")
    _mark(db_session, m.id, "pbm_left", "left_forearm", "left", "controlnet_canny",
          "matched figural keyword 'ballerina' → controlnet_canny")

    data = client.get(_diag_url(cid), headers=_headers(token)).json()
    assert data["exists"] is True
    assert data["status"] == "prepared"
    assert data["model_status"] == "prepared"
    assert data["stale"] is False
    assert data["canon_fingerprint"] == "f" * 64
    assert data["active_version_id"] is None
    assert data["version_count"] == 0
    assert data["mark_render_count"] == 2
    routes = {(r["body_region"], r["route"]) for r in data["mark_routes"]}
    assert ("right_upper_arm", "ip_adapter") in routes
    assert ("left_forearm", "controlnet_canny") in routes
    # reasons surfaced from params_json
    assert any("ballerina" in (r["reason"] or "") for r in data["mark_routes"])
    # Not trained → trained fingerprint absent, no mismatch.
    assert data["fingerprint_comparison"]["trained_fingerprint"] is None
    assert data["fingerprint_comparison"]["mismatch"] is False


# ── Stale state + fingerprint comparison + version visibility ────────────────


def test_diagnostics_stale_state_fingerprint_mismatch_and_versions(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    m = _model(db_session, cid, status="stale", canon_fingerprint="current_fp")
    # An active trained version recorded the OLD canon it trained against.
    v = _version(db_session, m.id, index=1, fingerprint="trained_fp", state="active")
    m.active_version_id = v.id
    db_session.add(AdultIdentityTrainingJob(identity_id=m.id, provider="fake", state="completed"))
    db_session.commit()

    data = client.get(_diag_url(cid), headers=_headers(token)).json()
    assert data["status"] == "stale"
    assert data["stale"] is True
    assert data["active_version_id"] == v.id
    assert data["version_count"] == 1
    assert data["training_job_count"] == 1
    # version visibility
    ver = data["versions"][0]
    assert ver["version_index"] == 1
    assert ver["state"] == "active"
    assert ver["canon_fingerprint"] == "trained_fp"
    # comparison surfaces the mismatch driving the stale state
    cmp = data["fingerprint_comparison"]
    assert cmp["current_fingerprint"] == "current_fp"
    assert cmp["trained_fingerprint"] == "trained_fp"
    assert cmp["mismatch"] is True


def test_diagnostics_ready_state_no_mismatch(client, db_session, monkeypatch):
    """A freshly trained (ready) model: current fingerprint matches the trained one."""
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    m = _model(db_session, cid, status="ready", canon_fingerprint="same_fp")
    v = _version(db_session, m.id, index=1, fingerprint="same_fp", state="active")
    m.active_version_id = v.id
    db_session.commit()

    data = client.get(_diag_url(cid), headers=_headers(token)).json()
    assert data["status"] == "ready"
    assert data["stale"] is False
    assert data["fingerprint_comparison"]["mismatch"] is False
    assert data["active_version_id"] == v.id


# ── Failed state ─────────────────────────────────────────────────────────────


def test_diagnostics_failed_state_surfaces_last_error(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _model(db_session, cid, status="failed", canon_fingerprint="f" * 64,
           last_error="provider declined")

    data = client.get(_diag_url(cid), headers=_headers(token)).json()
    assert data["status"] == "failed"
    assert data["last_error"] == "provider declined"


# ── No model yet ─────────────────────────────────────────────────────────────


def test_diagnostics_no_model_returns_exists_false(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)  # no AdultIdentityModel created

    data = client.get(_diag_url(cid), headers=_headers(token)).json()
    assert data["exists"] is False
    assert data["status"] is None
    assert data["version_count"] == 0
    assert data["mark_render_count"] == 0
    assert data["mark_routes"] == []

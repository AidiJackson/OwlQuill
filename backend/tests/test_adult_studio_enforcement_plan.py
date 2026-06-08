"""Tests for the dry-run Adult Studio tattoo-enforcement PLAN validator (Phase 3, S6).

`build_enforcement_plan` assembles the full enforcement plan (identity + active LoRA
version + mark renders + reference crops + routes) and validates completeness WITHOUT
running anything: no generation, no inference, no training, no provider, no external
calls, no writes, no Canon Studio access.

Covers: Summer-shaped plan is ready_for_executor=True; and each critical gap
(missing active version, missing reference, unsupported route, not-ready status)
blocks with ready_for_executor=False.
"""
from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)
from app.services.adult_identity_enforcement_plan import build_enforcement_plan

_ARTIFACT = "https://replicate.delivery/xezq/abc/trained_model.tar"
_REF = "https://pub.r2.dev/generated/{}.png"

# Mirrors Summer's persisted routing reasons so the substring expectations match.
_SLEEVE_REASON = "matched sleeve/coverage keyword 'sleeve' → ip_adapter"
_BALLERINA_REASON = "matched figural keyword 'ballerina' → controlnet_canny"
SUMMER_EXPECTATIONS = {"sleeve": "ip_adapter", "ballerina": "controlnet_canny"}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_character(client, token, name="Summer") -> int:
    resp = client.post(
        "/characters/", json={"name": name, "visibility": "public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _token(client) -> str:
    client.post("/auth/register", json={
        "email": "ep-user@test.com", "username": "epuser", "password": "pass12345"})
    resp = client.post("/auth/login", json={
        "email": "ep-user@test.com", "password": "pass12345"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _model(db, cid, status="ready") -> AdultIdentityModel:
    m = AdultIdentityModel(character_id=cid, status=status, trigger_token="TOK")
    db.add(m); db.commit(); db.refresh(m)
    return m


def _version(db, identity_id, artifact=_ARTIFACT, index=1) -> AdultIdentityModelVersion:
    v = AdultIdentityModelVersion(
        identity_id=identity_id, version_index=index,
        lora_weights_uri=artifact, state="active",
    )
    db.add(v); db.commit(); db.refresh(v)
    return v


def _mark(db, identity_id, canon_mark_id, region, side, route, reason, reference=True):
    db.add(AdultIdentityMarkRender(
        identity_id=identity_id, canon_mark_id=canon_mark_id, mark_type="tattoo",
        body_region=region, side=side, route=route,
        reference_uri=(_REF.format(canon_mark_id) if reference else None),
        params_json={"reason": reason},
    ))
    db.commit()


def _summer_marks(db, identity_id):
    """The two Summer marks: butterfly sleeve → ip_adapter, ballerina → controlnet_canny."""
    _mark(db, identity_id, "pbm_8cff990d", "Right upper arm", "right",
          "ip_adapter", _SLEEVE_REASON)
    _mark(db, identity_id, "pbm_de30011b", "Left forearm", "left",
          "controlnet_canny", _BALLERINA_REASON)


def _build_summer(client, db, cid, status="ready", with_marks=True):
    m = _model(db, cid, status=status)
    v = _version(db, m.id)
    m.active_version_id = v.id
    db.commit()
    if with_marks:
        _summer_marks(db, m.id)
    return m


# ── Summer: complete plan is ready ────────────────────────────────────────────


def test_summer_plan_ready_for_executor(client, db_session):
    cid = _create_character(client, _token(client))
    _build_summer(client, db_session, cid)

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is True
    assert plan["blocking_reasons"] == []
    assert plan["executor_required"] is True
    assert plan["character_id"] == cid
    assert plan["status"] == "ready"
    assert plan["active_version_id"] is not None
    assert plan["model_artifact_uri"] == _ARTIFACT
    assert all(plan["checks"].values())

    # Plan exposes the two routed marks with references + reasons.
    by_region = {m["region"]: m for m in plan["marks"]}
    assert by_region["Right upper arm"]["route"] == "ip_adapter"
    assert by_region["Left forearm"]["route"] == "controlnet_canny"
    assert all(m["reference_uri"] for m in plan["marks"])
    assert "ballerina" in by_region["Left forearm"]["reason"]


def test_summer_butterfly_and_ballerina_route_expectations_enforced(client, db_session):
    """If a stored route contradicts the butterfly/ballerina expectation, it blocks."""
    cid = _create_character(client, _token(client))
    m = _model(db_session, cid, status="ready")
    v = _version(db_session, m.id); m.active_version_id = v.id; db_session.commit()
    # Ballerina mark wrongly routed to ip_adapter.
    _mark(db_session, m.id, "pbm_8cff990d", "Right upper arm", "right",
          "ip_adapter", _SLEEVE_REASON)
    _mark(db_session, m.id, "pbm_de30011b", "Left forearm", "left",
          "ip_adapter", _BALLERINA_REASON)

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["route_expectations_met"] is False
    assert any("ballerina" in r and "controlnet_canny" in r for r in plan["blocking_reasons"])


# ── Blocking conditions ───────────────────────────────────────────────────────


def test_missing_active_version_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    m = _model(db_session, cid, status="ready")
    # No version created, active_version_id stays None.
    _summer_marks(db_session, m.id)

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["active_version_present"] is False
    assert plan["checks"]["model_artifact_present"] is False
    assert plan["model_artifact_uri"] is None
    assert any("active version" in r for r in plan["blocking_reasons"])


def test_missing_mark_reference_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    m = _model(db_session, cid, status="ready")
    v = _version(db_session, m.id); m.active_version_id = v.id; db_session.commit()
    _mark(db_session, m.id, "pbm_8cff990d", "Right upper arm", "right",
          "ip_adapter", _SLEEVE_REASON, reference=True)
    _mark(db_session, m.id, "pbm_de30011b", "Left forearm", "left",
          "controlnet_canny", _BALLERINA_REASON, reference=False)  # <- no ref

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["all_references_present"] is False
    assert any("pbm_de30011b" in r and "reference_uri" in r for r in plan["blocking_reasons"])


def test_unsupported_route_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    m = _model(db_session, cid, status="ready")
    v = _version(db_session, m.id); m.active_version_id = v.id; db_session.commit()
    _mark(db_session, m.id, "pbm_8cff990d", "Right upper arm", "right",
          "ip_adapter", _SLEEVE_REASON)
    # "skip" is valid routing vocabulary but NOT an executor-runnable pass.
    _mark(db_session, m.id, "pbm_de30011b", "Left forearm", "left",
          "skip", "region not renderable → skip")

    plan = build_enforcement_plan(cid, db_session)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["all_routes_supported"] is False
    assert any("unsupported route" in r and "skip" in r for r in plan["blocking_reasons"])


def test_not_ready_status_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    # Everything else complete, but identity is still 'prepared' (not trained/ready).
    _build_summer(client, db_session, cid, status="prepared")

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["status_ready"] is False
    assert any("status is 'prepared'" in r for r in plan["blocking_reasons"])


def test_stale_status_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    _build_summer(client, db_session, cid, status="stale")

    plan = build_enforcement_plan(cid, db_session, route_expectations=SUMMER_EXPECTATIONS)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["status_ready"] is False
    assert any("status is 'stale'" in r for r in plan["blocking_reasons"])


def test_no_identity_returns_empty_blocked_plan(client, db_session):
    cid = _create_character(client, _token(client))  # no AdultIdentityModel

    plan = build_enforcement_plan(cid, db_session)

    assert plan["ready_for_executor"] is False
    assert plan["identity_id"] is None
    assert plan["marks"] == []
    assert any("no Adult Studio identity" in r for r in plan["blocking_reasons"])


def test_no_marks_blocks(client, db_session):
    cid = _create_character(client, _token(client))
    _build_summer(client, db_session, cid, with_marks=False)

    plan = build_enforcement_plan(cid, db_session)

    assert plan["ready_for_executor"] is False
    assert plan["checks"]["has_mark_renders"] is False
    assert any("no mark renders" in r for r in plan["blocking_reasons"])

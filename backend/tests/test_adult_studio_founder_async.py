"""Adult Studio FOUNDER ASYNC LITE — job service + endpoints (Phase 3, Sprint 13).

Fire-and-poll: POST launches ONE detached RunPod job (202), GET reconciles it from the
run_id-scoped driver report, the real final image is the RunPod 99_final (NOT a montage).
One active job at a time. All side effects (launcher / report reader / terminator / clock)
are injected or monkeypatched → zero spend, zero subprocess, zero network.
"""
import importlib.util
import pathlib
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core import config as cfg_module
from app.models.adult_founder_job import AdultFounderJob
from app.models.adult_identity import AdultIdentityModel, AdultIdentityModelVersion
from app.services import adult_founder_job_service as svc
from app.services import adult_identity_founder_generate as fg

_ADMIN_EMAIL = "founder-async-admin@ficshon.com"
_ARTIFACT = "https://replicate.delivery/xezq/abc/trained_model.tar"
_FINAL = "https://pub.r2.dev/proof/run/99_final.png"
_BASE = "https://pub.r2.dev/proof/run/01_base.png"


# ── Auth / fixture helpers ────────────────────────────────────────────────────


def _register_and_login(client, email, username, password="pass12345") -> str:
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client):
    return _register_and_login(client, _ADMIN_EMAIL, "founderasyncadmin")


def _create_character(client, token, name="Summer") -> int:
    resp = client.post("/characters/", json={"name": name, "visibility": "public"},
                       headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _point_summer_at(monkeypatch, cid):
    """Repoint every Summer-only guard (service + route module) at the test character."""
    import app.api.routes.adult_studio_admin as route_mod
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    monkeypatch.setattr(svc, "SUMMER_CHARACTER_ID", cid, raising=False)
    monkeypatch.setattr(route_mod, "SUMMER_CHARACTER_ID", cid)


def _build_summer(db, cid, *, status="ready", with_version=True):
    m = AdultIdentityModel(character_id=cid, status=status, trigger_token="TOK")
    db.add(m); db.commit(); db.refresh(m)
    if with_version:
        v = AdultIdentityModelVersion(identity_id=m.id, version_index=1,
                                      lora_weights_uri=_ARTIFACT, state="active")
        db.add(v); db.commit(); db.refresh(v)
        m.active_version_id = v.id; db.commit()
    return m


def _url(cid):
    return f"/admin/adult-studio/characters/{cid}/founder-generate"


def _job_url(cid):
    return f"/admin/adult-studio/characters/{cid}/founder-job"


# ── Report fixtures (mirror the driver's report shape) ─────────────────────────


def _completed_report():
    arts = [_BASE, "https://pub.r2.dev/proof/run/02_mask.png",
            "https://pub.r2.dev/proof/run/03_after_butterfly.png",
            "https://pub.r2.dev/proof/run/04_after_ballerina.png", _FINAL]
    return {
        "diffusion_pass": "completed", "success": True,
        "final_image_url": _FINAL,
        "image_urls": {"base": _BASE, "final": _FINAL, "artifacts": arts},
        "routes_executed": [{"route": "ip_adapter", "status": "executed"},
                            {"route": "controlnet_canny", "status": "executed"}],
        "spend_usd": 0.0141, "runtime_s": 317.5, "no_orphaned_pods": True,
        "pod_id": "pod-1", "pod_errors": [], "manual_review_required": True,
        "spend_cap_usd": 0.05,
    }


def _failed_report():
    return {
        "diffusion_pass": "failed", "success": False, "final_image_url": None,
        "image_urls": {"base": _BASE, "final": None, "artifacts": [_BASE]},
        "routes_executed": [], "spend_usd": 0.01, "runtime_s": 40.0,
        "no_orphaned_pods": True, "pod_id": "pod-2",
        "pod_errors": ["fatal: ballerina pass crashed"], "manual_review_required": True,
    }


def _orphan_report():
    r = _completed_report()
    r["no_orphaned_pods"] = False
    r["pod_id"] = "pod-leak"
    return r


# ── POST: launches a job, returns 202 ──────────────────────────────────────────


def test_post_launches_job_returns_202(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)

    calls = {"n": 0}
    monkeypatch.setattr(svc, "_default_launcher",
                        lambda run_id, prompt, model: calls.__setitem__("n", calls["n"] + 1))

    resp = client.post(_url(cid), json={"prompt": "summer poolside at sunset"},
                       headers=_headers(token))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["state"] == "running"
    assert body["job_id"] > 0
    assert body["manual_review_required"] is True
    assert calls["n"] == 1  # launcher invoked exactly once
    # Row persisted.
    row = db_session.query(AdultFounderJob).filter_by(id=body["job_id"]).first()
    assert row is not None and row.state == "running"


# ── Singleton: one active job at a time ────────────────────────────────────────


def test_singleton_second_launch_409(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)

    r1 = client.post(_url(cid), json={"prompt": "first"}, headers=_headers(token))
    assert r1.status_code == 202, r1.text
    r2 = client.post(_url(cid), json={"prompt": "second"}, headers=_headers(token))
    assert r2.status_code == 409, r2.text
    assert "already running" in r2.json()["detail"].lower()


# ── GET: reconcile running → completed (real 99_final, no montage) ─────────────


def test_get_reconciles_completed_with_final(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)
    client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))

    monkeypatch.setattr(svc, "_default_report_reader", lambda run_id: _completed_report())
    resp = client.get(_job_url(cid), headers=_headers(token))
    assert resp.status_code == 200, resp.text
    job = resp.json()["job"]
    assert job["state"] == "completed"
    assert job["final_image_url"] == _FINAL          # the real 99_final
    assert _FINAL not in job["intermediate_artifact_urls"]  # final is NOT a montage panel
    assert len(job["intermediate_artifact_urls"]) == 4
    assert job["manual_review_required"] is True
    assert job["cost"] == 0.0141
    assert {r["route"] for r in job["routes_executed"]} == {"ip_adapter", "controlnet_canny"}


def test_get_reconciles_failed_shows_error(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)
    client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))

    monkeypatch.setattr(svc, "_default_report_reader", lambda run_id: _failed_report())
    resp = client.get(_job_url(cid), headers=_headers(token))
    job = resp.json()["job"]
    assert job["state"] == "failed"
    assert job["final_image_url"] is None
    assert "ballerina" in (job["error"] or "")


def test_get_orphan_fails_run(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)
    client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))

    monkeypatch.setattr(svc, "_default_report_reader", lambda run_id: _orphan_report())
    resp = client.get(_job_url(cid), headers=_headers(token))
    job = resp.json()["job"]
    assert job["state"] == "failed"
    assert job["orphaned_workers"] == ["pod-leak"]


def test_get_returns_null_when_no_job(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _point_summer_at(monkeypatch, cid)
    resp = client.get(_job_url(cid), headers=_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"] is None


# ── Resume-on-refresh: a still-running job (no report yet) stays running ────────


def test_get_running_without_report_stays_running(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)
    client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))

    monkeypatch.setattr(svc, "_default_report_reader", lambda run_id: None)  # not terminal yet
    resp = client.get(_job_url(cid), headers=_headers(token))
    assert resp.json()["job"]["state"] == "running"


# ── Timeout backstop: stuck running job → failed + pod terminated ──────────────


def test_timeout_backstop_fails_and_terminates(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "o@test.com", "owner"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-timeout", pod_id="pod-stuck")
    db_session.add(job); db_session.commit()

    killed = []
    future = lambda: datetime.utcnow() + timedelta(seconds=99999)
    out = svc.get_latest_job(db_session, cid, report_reader=lambda r: None,
                             terminator=lambda pid: killed.append(pid), now_utc=future)
    assert out.state == "failed"
    assert "Timed out" in out.error
    assert killed == ["pod-stuck"]  # backstop kill in case the driver died with a live pod


# ── Cancel: terminate pod + mark failed ────────────────────────────────────────


def test_cancel_terminates_and_fails(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-cancel", pod_id="pod-cancel")
    db_session.add(job); db_session.commit()

    killed = []
    monkeypatch.setattr(svc, "_default_terminator", lambda pid: killed.append(pid))
    resp = client.post(f"{_job_url(cid)}/cancel", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "failed"
    assert killed == ["pod-cancel"]


def test_cancel_without_active_job_409(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _point_summer_at(monkeypatch, cid)
    resp = client.post(f"{_job_url(cid)}/cancel", headers=_headers(token))
    assert resp.status_code == 409, resp.text


# ── Gates still enforced on POST (no pod launched) ─────────────────────────────


def test_post_non_admin_403(client, db_session, monkeypatch):
    token = _register_and_login(client, "plain@test.com", "plain")
    resp = client.post(_url(60), json={"prompt": "x"}, headers=_headers(token))
    assert resp.status_code == 403, resp.text


def test_post_non_summer_409(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token, name="NotSummer")
    resp = client.post(_url(cid), json={"prompt": "x"}, headers=_headers(token))
    assert resp.status_code == 409, resp.text


def test_post_safety_block_400(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    monkeypatch.setattr(svc, "_default_launcher", lambda *a, **k: None)
    resp = client.post(_url(cid), json={"prompt": "a child on the beach"},
                       headers=_headers(token))
    assert resp.status_code == 400, resp.text


def test_launch_failure_marks_failed(db_session, client, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "o2@test.com", "owner2"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)

    def boom(run_id, prompt, model):
        raise RuntimeError("spawn failed")

    job = svc.start_founder_job(db_session, cid, "summer poolside", launcher=boom)
    assert job.state == "failed"
    assert "launch_failed" in job.error


# ── Report mapping unit (the real 99_final, never the montage) ─────────────────


def test_map_report_completed():
    out = svc._map_report_to_result(_completed_report())
    assert out["success"] is True
    assert out["final_image_url"] == _FINAL
    assert _FINAL not in out["intermediate_artifact_urls"]
    assert out["manual_review_required"] is True
    assert out["orphaned_workers"] == []


def test_map_report_orphan_forces_failure():
    out = svc._map_report_to_result(_orphan_report())
    assert out["success"] is False
    assert out["orphaned_workers"] == ["pod-leak"]
    assert any("orphaned workers" in b for b in out["blocking_reasons"])


# ── Sprint 13.1: _is_terminal fires ONLY on genuine end signals ────────────────


def _inprogress_report():
    """A still-loading pod report: the driver writes failed/false while in progress."""
    return {
        "diffusion_pass": "failed", "success": False, "final_image_url": None,
        "image_urls": {"base": None, "final": None, "artifacts": []},
        "routes_executed": [], "spend_usd": 0.0063, "runtime_s": 125.0,
        "no_orphaned_pods": True, "pod_id": "pod-x", "pod_errors": [],
        "pod_status_final": "load_pipeline", "manual_review_required": True,
    }


def test_is_terminal_inprogress_is_not_terminal():
    # diffusion_pass="failed" + success=False while pod_status_final="load_pipeline".
    assert svc._is_terminal(_inprogress_report()) is False


def test_is_terminal_completed():
    assert svc._is_terminal(_completed_report()) is True


def test_is_terminal_pod_errors_is_terminal():
    assert svc._is_terminal({"diffusion_pass": "failed", "pod_errors": ["fatal: x"],
                             "pod_status_final": "inpaint_ballerina"}) is True


def test_is_terminal_end_stages_are_terminal():
    for stage in ("done", "aborted_no_gpu", "rate_guard"):
        assert svc._is_terminal({"diffusion_pass": "failed", "pod_errors": [],
                                 "pod_status_final": stage}) is True


def test_reconcile_inprogress_report_stays_running(client, db_session, monkeypatch):
    """The original bug: a loading pod must NOT be marked failed and must NOT be killed."""
    cid = _create_character(client, _register_and_login(client, "ip@test.com", "ipuser"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-inprogress", pod_id="pod-x")
    db_session.add(job); db_session.commit()

    killed = []
    out = svc.get_latest_job(db_session, cid, report_reader=lambda r: _inprogress_report(),
                             terminator=lambda pid: killed.append(pid))
    assert out.state == "running"   # still loading — not failed
    assert out.final_image_url is None
    assert killed == []             # no premature pod termination


def test_reconcile_completed_report_marks_completed(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "cp@test.com", "cpuser"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-complete", pod_id="pod-c")
    db_session.add(job); db_session.commit()

    out = svc.get_latest_job(db_session, cid, report_reader=lambda r: _completed_report())
    assert out.state == "completed"
    assert out.final_image_url == _FINAL


def test_reconcile_pod_error_report_marks_failed(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "pe@test.com", "peuser"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-err", pod_id="pod-e")
    db_session.add(job); db_session.commit()

    out = svc.get_latest_job(db_session, cid, report_reader=lambda r: _failed_report())
    assert out.state == "failed"
    assert "ballerina" in (out.error or "")


def test_reconcile_aborted_no_gpu_marks_failed(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "ng@test.com", "nguser"))
    _build_summer(db_session, cid)
    _point_summer_at(monkeypatch, cid)
    job = AdultFounderJob(character_id=cid, prompt="x", state="running",
                          run_id="run-nogpu", pod_id=None)
    db_session.add(job); db_session.commit()

    report = {"diffusion_pass": "failed", "success": False, "final_image_url": None,
              "image_urls": {"base": None, "final": None, "artifacts": []},
              "routes_executed": [], "spend_usd": 0.0, "runtime_s": 0.0,
              "no_orphaned_pods": True, "pod_id": None,
              "pod_errors": ["fatal: no community GPU available"],
              "pod_status_final": "aborted_no_gpu", "manual_review_required": True}
    out = svc.get_latest_job(db_session, cid, report_reader=lambda r: report)
    assert out.state == "failed"


# ── Driver carries the $0.05 proof_lib safety profile ──────────────────────────


def test_driver_spend_cap_is_five_cents():
    repo = pathlib.Path(__file__).resolve().parents[2]
    path = repo / "scripts" / "founder_async_runpod_driver.py"
    spec = importlib.util.spec_from_file_location("founder_async_runpod_driver", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SPEND_CAP == 0.05
    assert mod.WATCHDOG_S == 700
    assert mod.TERMINATE_AT < mod.SPEND_CAP
    # Rate guard keeps the 700s watchdog worst-case under the cap.
    assert mod.MAX_SAFE_RATE == round(0.05 / (700 / 3600.0) * 0.95, 4)

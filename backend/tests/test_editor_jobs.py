"""Tests for Editor Studio Sprint E5 — async self_hosted jobs + quality gate.

Covers:
  1. Job creation returns 202 with a queued/running job (launcher mocked)
  2. Admin-only (403 for normal users)
  3. Provider restricted to self_hosted (422)
  4. Exactly one source image (422)
  5. Singleton: second start while active → 409
  6. Polling: running job + terminal report → completed with quality_status
  7. Polling: failed report → failed job with error
  8. /jobs/latest envelope (null and populated)
  9. Cancel: active → failed "Canceled by user.", terminator called with pod_id
 10. Cancel: terminal job → 409
 11. evaluate_quality: pass / needs_review / failed classifications
"""
import io

import pytest

from tests.conftest import auth_headers, get_auth_token

import app.core.config as cfg_module
import app.services.editor_job_service as job_svc
from app.services.editor_job_service import (
    evaluate_quality,
)

_ADMIN_EMAIL = "editor-jobs-admin@ficshon.com"


def _png_bytes(size=(64, 64)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (120, 90, 200)).save(buf, format="PNG")
    return buf.getvalue()


_PNG_64 = _png_bytes()


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    """Never launch the real driver from tests."""
    monkeypatch.setattr(job_svc, "_default_launcher", lambda run_id, job_id: None)


def _make_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client, monkeypatch):
    _make_admin(monkeypatch)
    return get_auth_token(client, _ADMIN_EMAIL, "editorjobsadmin")


def _create_character(client, token, name="Editor Jobs Char") -> int:
    resp = client.post("/characters/", json={"name": name, "species": "human"},
                       headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _png_file(name="src.png"):
    return ("images", (name, io.BytesIO(_PNG_64), "image/png"))


def _form(character_id: int, **overrides):
    data = {
        "character_id": str(character_id),
        "prompt": "Summer on the beach in a black bikini instead of the black dress.",
        "provider": "self_hosted",
        "strength": "0.25",
    }
    data.update({k: str(v) for k, v in overrides.items()})
    return data


# ── 1-5: job creation route ───────────────────────────────────────────


def test_job_creation_returns_202(client, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token)
    resp = client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                       headers=auth_headers(token))
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["state"] in ("queued", "running")
    assert body["provider"] == "self_hosted"
    assert body["run_id"].startswith("editor_job_")
    assert body["quality_status"] is None


def test_job_admin_only(client, monkeypatch):
    token = get_auth_token(client, "normal-editor-user@test.com", "normaleditor")
    cid = _create_character(client, token)
    resp = client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                       headers=auth_headers(token))
    assert resp.status_code == 403


def test_job_provider_restricted(client, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token)
    resp = client.post("/editor/jobs", data=_form(cid, provider="gpt-image"),
                       files=[_png_file()], headers=auth_headers(token))
    assert resp.status_code == 422
    assert "self_hosted" in resp.json()["detail"]


def test_job_requires_exactly_one_source(client, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token)
    resp = client.post("/editor/jobs", data=_form(cid),
                       files=[_png_file("a.png"), _png_file("b.png")],
                       headers=auth_headers(token))
    assert resp.status_code == 422
    assert "exactly 1" in resp.json()["detail"]


def test_job_singleton_409(client, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token)
    first = client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                        headers=auth_headers(token))
    assert first.status_code == 202
    second = client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                         headers=auth_headers(token))
    assert second.status_code == 409


# ── 6-8: polling/reconciliation ───────────────────────────────────────


def _start_service_job(db_session, client, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token)
    resp = client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                       headers=auth_headers(token))
    assert resp.status_code == 202, resp.text
    return token, cid, resp.json()["id"], resp.json()["run_id"]


def test_poll_completed_job(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)

    report = {
        "terminal": True, "success": True, "quality_status": "pass",
        "quality_reasons": [], "image_id": 4242,
        "final_image_url": "/static/generated/final.png",
        "stage_images": {"99_final": "https://r2/x/99_final.png"},
        "spend_usd": 0.007, "runtime_s": 150.0, "pod_id": "podabc",
        "no_orphaned_pods": True, "errors": [],
    }
    monkeypatch.setattr(job_svc, "_default_report_reader", lambda rid: report)

    resp = client.get(f"/editor/jobs/{job_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "completed"
    assert body["quality_status"] == "pass"
    assert body["final_image_url"] == "/static/generated/final.png"
    assert body["image_id"] == 4242
    assert body["result"]["spend_usd"] == 0.007
    assert body["error"] is None


def test_poll_needs_review_job_completes_with_flag(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)
    report = {
        "terminal": True, "success": True, "quality_status": "needs_review",
        "quality_reasons": ["harsh person/background seam (ratio 3.1)"],
        "image_id": 4243, "final_image_url": "/static/generated/f2.png",
        "pod_id": "podabc", "no_orphaned_pods": True, "errors": [],
    }
    monkeypatch.setattr(job_svc, "_default_report_reader", lambda rid: report)
    body = client.get(f"/editor/jobs/{job_id}", headers=auth_headers(token)).json()
    assert body["state"] == "completed"
    assert body["quality_status"] == "needs_review"
    assert body["result"]["quality_reasons"]


def test_poll_failed_job(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)
    report = {
        "terminal": True, "success": False, "quality_status": "failed",
        "error": "self_hosted edit aborted (spend cap)", "pod_id": "podabc",
        "errors": ["self_hosted edit aborted (spend cap)"],
    }
    monkeypatch.setattr(job_svc, "_default_report_reader", lambda rid: report)
    body = client.get(f"/editor/jobs/{job_id}", headers=auth_headers(token)).json()
    assert body["state"] == "failed"
    assert "spend cap" in body["error"]


def test_poll_running_no_report_stays_running(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)
    monkeypatch.setattr(job_svc, "_default_report_reader", lambda rid: None)
    body = client.get(f"/editor/jobs/{job_id}", headers=auth_headers(token)).json()
    assert body["state"] == "running"


def test_latest_envelope(client, db_session, monkeypatch):
    token = _admin_token(client, monkeypatch)
    cid = _create_character(client, token, name="Latest Env Char")
    empty = client.get(f"/editor/jobs/latest?character_id={cid}",
                       headers=auth_headers(token))
    assert empty.status_code == 200
    assert empty.json()["job"] is None

    client.post("/editor/jobs", data=_form(cid), files=[_png_file()],
                headers=auth_headers(token))
    monkeypatch.setattr(job_svc, "_default_report_reader", lambda rid: None)
    populated = client.get(f"/editor/jobs/latest?character_id={cid}",
                           headers=auth_headers(token)).json()
    assert populated["job"]["state"] == "running"


# ── 9-10: cancel ──────────────────────────────────────────────────────


def test_cancel_active_job(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)
    killed: list = []
    # Driver progress report published the pod id; cancel must terminate it.
    monkeypatch.setattr(job_svc, "_default_report_reader",
                        lambda rid: {"terminal": False, "pod_id": "pod-live-1"})
    monkeypatch.setattr(job_svc, "_default_terminator", killed.append)

    resp = client.post(f"/editor/jobs/{job_id}/cancel", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "failed"
    assert "Canceled" in body["error"]
    assert killed == ["pod-live-1"]


def test_cancel_terminal_job_409(client, db_session, monkeypatch):
    token, cid, job_id, run_id = _start_service_job(db_session, client, monkeypatch)
    monkeypatch.setattr(job_svc, "_default_report_reader",
                        lambda rid: {"terminal": True, "success": False,
                                     "quality_status": "failed", "error": "boom"})
    client.get(f"/editor/jobs/{job_id}", headers=auth_headers(token))  # reconcile → failed
    resp = client.post(f"/editor/jobs/{job_id}/cancel", headers=auth_headers(token))
    assert resp.status_code == 409


# ── 11: quality gate unit tests ───────────────────────────────────────


def test_quality_no_image_fails():
    status, reasons = evaluate_quality({}, None)
    assert status == "failed"
    assert reasons


def test_quality_corrupt_image_fails():
    status, _ = evaluate_quality({"quality": {}}, b"not a png at all")
    assert status == "failed"


def test_quality_dimension_mismatch_fails():
    status, reasons = evaluate_quality(
        {"quality": {"remnant_px_final": 0, "seam_ratio": 1.0}},
        _png_bytes((64, 64)), source_size=(128, 128))
    assert status == "failed"
    assert "does not match" in reasons[0]


def test_quality_clean_metrics_pass():
    status, reasons = evaluate_quality(
        {"quality": {"remnant_px_final": 12, "seam_ratio": 1.4}, "errors": []},
        _png_bytes((64, 64)), source_size=(64, 64))
    assert status == "pass"
    assert reasons == []


def test_quality_remnants_need_review():
    status, reasons = evaluate_quality(
        {"quality": {"remnant_px_final": 99999, "seam_ratio": 1.0}, "errors": []},
        _png_bytes((64, 64)), source_size=(64, 64))
    assert status == "needs_review"
    assert "remnant" in reasons[0]


def test_quality_harsh_seam_needs_review():
    status, reasons = evaluate_quality(
        {"quality": {"remnant_px_final": 0, "seam_ratio": 5.0}, "errors": []},
        _png_bytes((64, 64)), source_size=(64, 64))
    assert status == "needs_review"
    assert "seam" in reasons[0]


def test_quality_missing_metrics_needs_review():
    status, reasons = evaluate_quality({}, _png_bytes((64, 64)))
    assert status == "needs_review"
    assert "no quality metrics" in reasons[0]


def test_quality_lora_error_ignored():
    status, _ = evaluate_quality(
        {"quality": {"remnant_px_final": 0, "seam_ratio": 1.0},
         "errors": ["lora_load: SomeError('x')"]},
        _png_bytes((64, 64)))
    assert status == "pass"

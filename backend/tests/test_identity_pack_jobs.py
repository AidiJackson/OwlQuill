"""Sprint 35 — async Identity Pack (v2 canon pack) job tests.

Covers the Part J regression matrix: fast 202 submission, queued→running→
completed transitions, usable results, safe failure, duplicate/race protection,
poll safety, authorisation, refresh rediscovery, stale-job recovery, provider
isolation, and preservation of the synchronous pipeline inside job execution.

No test spawns a subprocess or contacts a live provider: the launcher is
stubbed and the pipeline is either a deterministic fake or a monkeypatched
build_v2_pack.
"""
import os
from datetime import datetime, timedelta

import pytest

from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token

from app.models.character_image import CharacterImage
from app.models.identity_pack_job import IdentityPackJob
from app.services import identity_pack_job_service as svc


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_character(client, token) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Jobbed Character", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture()
def stub_launcher(monkeypatch):
    """Replace the subprocess launcher with a recorder — no process ever spawns."""
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(svc, "_default_launcher", lambda pid, jid: calls.append((pid, jid)))
    return calls


def _fake_report(pack_id: str = "fakepack01") -> dict:
    cards = [
        {"slot": s, "section": "face" if s.startswith("face") else "body",
         "role": s, "url": f"static/generated/{s}.png", "status": "generated",
         "provider": "google"}
        for s in ("face_front", "face_left_3q", "body_front")
    ]
    return {
        "pack_id": pack_id, "dry_run": False, "cards": cards, "marks": [],
        "verdicts": {}, "regenerations": [], "openai_fallback": [],
        "gate_failed": [], "errors": [], "skipped": [], "stopped": None,
        "total_spend": 0.12, "image_count": len(cards), "clean_pass": True,
    }


def _fake_pipeline_ok(job, db, on_progress) -> dict:
    """Deterministic stand-in for build_v2_pack: emits real-shaped progress."""
    on_progress("card:face_front", 0, 13)
    on_progress("card:body_front", 5, 13)
    on_progress("mark_details", 13, 13)
    return _fake_report()


def _submit(client, token, char_id, key=None):
    body = {"max_spend": 8}
    if key is not None:
        body["idempotency_key"] = key
    return client.post(
        f"/characters/{char_id}/identity-canon/generate-v2-pack/jobs",
        json=body,
        headers=auth_headers(token),
    )


def _job_row_id(public_id: str) -> int:
    db = TestingSessionLocal()
    try:
        row = db.query(IdentityPackJob).filter(IdentityPackJob.public_id == public_id).one()
        return row.id
    finally:
        db.close()


def _run(public_id: str, pipeline=_fake_pipeline_ok) -> None:
    svc.run_identity_pack_job(
        _job_row_id(public_id), session_factory=TestingSessionLocal, pipeline=pipeline,
    )


# ── 1. Submission returns quickly with 202 ─────────────────────────────────


def test_submit_returns_202_and_queued(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)

    resp = _submit(client, token, char_id)
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["status"] == "queued"
    assert data["job_id"]
    assert data["reused"] is False
    assert data["result"] is None
    # The heavy pipeline did not run inside the request: the launcher was merely
    # invoked (stubbed), and no images exist.
    assert len(stub_launcher) == 1
    assert db_session.query(CharacterImage).count() == 0
    # Internal diagnostics are never serialised.
    assert "diag_json" not in data


# ── 2 + 3 + stage progress. queued → running → completed with usable result ─


def test_job_completes_with_usable_pack_result(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    observed_stages: list[tuple] = []

    def pipeline(job, db, on_progress):
        on_progress("card:face_front", 0, 13)
        # The stage must be visible on the row mid-run (truthful progress).
        db.refresh(job)
        observed_stages.append((job.status, job.stage, job.progress_message))
        return _fake_pipeline_ok(job, db, on_progress)

    _run(job_id, pipeline)

    assert observed_stages == [
        ("running", "card:face_front", "Generating front portrait (1/13)"),
    ]

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "completed"
    assert data["progress_percent"] == 100
    assert data["stage"] == "completed"
    # The embedded result is the exact shape the wizard's selection UI consumes.
    result = data["result"]
    assert result["pack_id"] == "fakepack01"
    assert [c["slot"] for c in result["cards"]] == ["face_front", "face_left_3q", "body_front"]
    assert result["clean_pass"] is True
    assert result["marks"] == []


# ── 4. Provider failure → failed with a safe message ───────────────────────


def test_pipeline_failure_is_safe(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    def exploding_pipeline(job, db, on_progress):
        raise RuntimeError("google_refused_image: raw provider secret ABC123")

    _run(job_id, exploding_pipeline)

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(token),
    )
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "pipeline_error"
    # Safe message only — the raw provider error must never surface.
    assert "ABC123" not in resp.text
    assert "google_refused_image" not in resp.text
    assert data["error_message"]
    # But it IS retained internally for diagnosis.
    db = TestingSessionLocal()
    try:
        row = db.query(IdentityPackJob).filter(IdentityPackJob.public_id == job_id).one()
        assert "ABC123" in (row.diag_json or {}).get("exception", "")
    finally:
        db.close()


# ── 5. Duplicate submissions return the same active job ────────────────────


def test_duplicate_submit_returns_same_job(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)

    first = _submit(client, token, char_id).json()
    second = _submit(client, token, char_id).json()

    assert second["job_id"] == first["job_id"]
    assert second["reused"] is True
    # Only one launch, one row.
    assert len(stub_launcher) == 1
    assert db_session.query(IdentityPackJob).count() == 1


def test_idempotency_key_covers_completed_job(client, db_session, stub_launcher):
    """Resubmitting the same click after completion returns the finished job."""
    token = get_auth_token(client)
    char_id = _make_character(client, token)

    first = _submit(client, token, char_id, key="click-abc").json()
    _run(first["job_id"])

    resub = _submit(client, token, char_id, key="click-abc").json()
    assert resub["job_id"] == first["job_id"]
    assert resub["reused"] is True
    assert resub["status"] == "completed"
    assert len(stub_launcher) == 1  # no second generation

    # A NEW key after completion is a genuine new attempt.
    fresh = _submit(client, token, char_id, key="click-def")
    assert fresh.status_code == 202
    assert fresh.json()["job_id"] != first["job_id"]


# ── 6. Two racing requests cannot create two active jobs ───────────────────


def test_db_level_single_active_job_per_character(client, db_session, stub_launcher):
    from sqlalchemy.exc import IntegrityError

    token = get_auth_token(client)
    char_id = _make_character(client, token)
    _submit(client, token, char_id)

    # Simulate the losing racer: its INSERT hits the partial unique index even
    # though it never saw the winner's row.
    db = TestingSessionLocal()
    try:
        db.add(IdentityPackJob(public_id="racer0000", user_id=1,
                               character_id=char_id, status="queued"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()

    # The service turns that race into "return the winner".
    db = TestingSessionLocal()
    try:
        job, reused = svc.start_identity_pack_job(
            db, character_id=char_id, user_id=1, params={},
            launcher=lambda *a: None,
        )
        assert reused is True
    finally:
        db.close()


# ── 7. Polling consumes nothing ────────────────────────────────────────────


def test_polling_has_no_side_effects(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    for _ in range(5):
        resp = client.get(
            f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
            headers=auth_headers(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    assert len(stub_launcher) == 1              # polling never relaunches
    assert db_session.query(IdentityPackJob).count() == 1
    assert db_session.query(CharacterImage).count() == 0  # nothing generated/charged

    # Polling a COMPLETED job never reruns it either.
    _run(job_id)
    for _ in range(3):
        resp = client.get(
            f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
            headers=auth_headers(token),
        )
        assert resp.json()["status"] == "completed"
    db = TestingSessionLocal()
    try:
        row = db.query(IdentityPackJob).filter(IdentityPackJob.public_id == job_id).one()
        assert row.attempt_count == 1
    finally:
        db.close()


# ── 8. Authorisation: jobs are invisible to non-owners ─────────────────────


def test_other_user_cannot_read_job(client, db_session, stub_launcher):
    owner = get_auth_token(client, email="jobowner@test.com", username="jobowner")
    char_id = _make_character(client, owner)
    job_id = _submit(client, owner, char_id).json()["job_id"]

    intruder = get_auth_token(client, email="intruder@test.com", username="intruder")
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(intruder),
    )
    assert resp.status_code == 404  # indistinguishable from nonexistent
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(intruder),
    )
    assert resp.status_code == 403
    # Unauthenticated → denied outright.
    assert client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}"
    ).status_code in (401, 403)


# ── 9. Browser refresh rediscovers the active job ──────────────────────────


def test_latest_endpoint_rediscovers_active_job(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)

    # No jobs yet → null, not an error.
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json() is None

    job_id = _submit(client, token, char_id).json()["job_id"]
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(token),
    )
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["status"] == "queued"

    # After completion the refreshed page can still recover the result.
    _run(job_id)
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(token),
    )
    assert resp.json()["status"] == "completed"
    assert resp.json()["result"]["pack_id"] == "fakepack01"


# ── 9b. Refresh recovery cannot surface a stale completed pack ─────────────


def test_latest_completed_job_superseded_after_canon_lock(client, db_session, stub_launcher):
    """Once the pack is accepted (canon locked), the completed job is flagged
    superseded so the wizard never re-adopts its snapshot on refresh."""
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]
    _run(job_id)

    # Fresh completion, canon unlocked → adoptable.
    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(token),
    )
    assert resp.json()["status"] == "completed"
    assert resp.json()["superseded"] is False

    # Accept: the v2 flow's Dossier step locks the canon (face_front must be
    # populated first, as it would be after a real generation).
    from app.services.canon_service import (
        assign_canon_slot_image,
        get_or_create_canon,
        lock_face_canon,
    )

    db = TestingSessionLocal()
    try:
        canon = get_or_create_canon(char_id, db)
        assign_canon_slot_image(canon, "face_front", "static/generated/ff.png")
        lock_face_canon(canon)
        db.commit()
    finally:
        db.close()

    for endpoint in (
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
    ):
        resp = client.get(endpoint, headers=auth_headers(token))
        assert resp.json()["status"] == "completed"
        assert resp.json()["superseded"] is True, endpoint


def test_latest_never_returns_older_completed_over_newer_job(client, db_session, stub_launcher):
    """An older completed job can never outrank a newer job in refresh recovery."""
    token = get_auth_token(client)
    char_id = _make_character(client, token)

    first_id = _submit(client, token, char_id, key="first").json()["job_id"]
    _run(first_id)

    second = _submit(client, token, char_id, key="second").json()
    assert second["job_id"] != first_id

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/latest",
        headers=auth_headers(token),
    )
    data = resp.json()
    assert data["job_id"] == second["job_id"]
    assert data["status"] == "queued"  # the active job, not the old completed one


# ── 10. Stale jobs recover per the documented policy ───────────────────────


def _age_job(public_id: str, *, status: str, created_s: int, updated_s: int) -> None:
    db = TestingSessionLocal()
    try:
        row = db.query(IdentityPackJob).filter(IdentityPackJob.public_id == public_id).one()
        row.status = status
        row.created_at = datetime.utcnow() - timedelta(seconds=created_s)
        row.updated_at = datetime.utcnow() - timedelta(seconds=updated_s)
        db.commit()
    finally:
        db.close()


def test_stale_running_job_marked_failed(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    # Dead driver: running, heartbeat older than the stall window.
    _age_job(job_id, status="running", created_s=700, updated_s=650)

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(token),
    )
    data = resp.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "stalled"
    assert "retry" in data["error_message"].lower()
    # Recovery frees the character for a fresh attempt.
    assert _submit(client, token, char_id).status_code == 202


def test_stale_queued_job_marked_failed(client, db_session, stub_launcher):
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    # Driver never started (e.g. process killed between insert and launch).
    _age_job(job_id, status="queued", created_s=200, updated_s=200)

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(token),
    )
    assert resp.json()["status"] == "failed"
    assert resp.json()["error_code"] == "launch_timeout"


def test_runner_skips_non_queued_jobs(client, db_session, stub_launcher):
    """A stray driver relaunch of a finished job is a no-op (no double spend)."""
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]
    _run(job_id)

    calls = []

    def counting_pipeline(job, db, on_progress):
        calls.append(1)
        return _fake_report()

    _run(job_id, counting_pipeline)  # second invocation
    assert calls == []               # pipeline never ran again


# ── 11. No live providers / production infrastructure reachable ────────────


def test_no_live_provider_credentials_in_test_env(client, stub_launcher):
    for var in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME", "R2_PUBLIC_URL",
        "OPENAI_API_KEY", "GOOGLE_AI_API_KEY", "TOGETHER_API_KEY",
        "REPLICATE_API_TOKEN", "RUNPOD_API_KEY", "FAL_KEY", "OPENROUTER_API_KEY",
    ):
        assert var not in os.environ, f"{var} present — tests could reach live infrastructure"
    from app.core.config import settings
    assert settings.USE_OBJECT_STORAGE is False


# ── 12. Job execution preserves the synchronous pipeline behaviour ─────────


def test_default_pipeline_invokes_build_v2_pack_unchanged(
    client, db_session, stub_launcher, monkeypatch,
):
    """run_identity_pack_job without an injected pipeline calls the SAME
    build_v2_pack the sync route uses, with equivalent parameters."""
    token = get_auth_token(client)
    char_id = _make_character(client, token)
    job_id = _submit(client, token, char_id).json()["job_id"]

    captured: dict = {}

    def capture_build(**kwargs):
        captured.update(kwargs)
        # Read scalars now — the ORM objects detach when the runner's session closes.
        captured["canon_character_id"] = kwargs["canon"].character_id
        return _fake_report("realpath01")

    import app.services.canon_pack_builder as builder
    monkeypatch.setattr(builder, "build_v2_pack", capture_build)

    svc.run_identity_pack_job(_job_row_id(job_id), session_factory=TestingSessionLocal)

    assert captured["dry_run"] is False
    assert captured["provider_option"] == "option2"
    assert captured["is_admin"] is False
    assert captured["admin_fallback"] is False
    assert captured["spend"].cap_usd == 8.0
    assert captured["canon_character_id"] == char_id
    assert callable(captured["on_progress"])

    resp = client.get(
        f"/characters/{char_id}/identity-canon/pack-jobs/{job_id}",
        headers=auth_headers(token),
    )
    assert resp.json()["status"] == "completed"
    assert resp.json()["result"]["pack_id"] == "realpath01"

"""google_audit persistence — the comparable record of what a runtime sent to Google.

A LIVE Google failure (Angelo, job 75: blockReason=OTHER) left only the block
reason and model on the job row; the prompt and reference hashes existed solely
in a driver log file that Cloud Run discards. These tests pin the fix: every
Google job, successful or failed, stores the same hash-only ``google_audit`` in
``image_generation_jobs.diag_json`` so a DEV run and a LIVE run can be diffed.

NON-SPENDING: the provider is a mock, no launcher subprocess is spawned, and
object storage is off for the suite (conftest).
"""
import base64
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.canon_test_utils import setup_canon, stub_png_bytes
from tests.conftest import TestingSessionLocal, auth_headers
from tests.test_founder_image_creation import (
    _create_character,
    _mock_provider,
    _register,
    _make_seeder,
)

PIPELINE = "app.services.image_generation_pipeline"
SECRET_KEY = "AIza-audit-persistence-test-key"
SECRET_PROMPT = "Zarnak quicksilver bellwether beneath the lighthouse"
GOOGLE_MODEL = "gemini-3.1-flash-image"


@pytest.fixture
def founder(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_API_KEY", SECRET_KEY)
    token = _register(client, "audit@example.com", "auditacct")
    _make_seeder("audit@example.com")
    cid = _create_character(client, token, "Audit One")
    db = TestingSessionLocal()
    try:
        setup_canon(db, cid)
    finally:
        db.close()
    return token, cid


def _google_provider(**overrides):
    provider = _mock_provider()
    provider.model_name = GOOGLE_MODEL
    for name, value in overrides.items():
        setattr(provider, name, value)
    return provider


def _run_job(client, token, cid, provider, key):
    """Queue one Google (option2) canon job and drive it in-process."""
    from app.models.image_generation_job import ImageGenerationJob
    from app.services import image_generation_job_service as svc

    real_start = svc.start_image_generation_job

    def _no_subprocess(db, **kw):
        return real_start(db, **kw, launcher=lambda pid, jid: None)

    with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
        resp = client.post(
            f"/characters/{cid}/image-generator/jobs",
            json={
                "prompt": SECRET_PROMPT,
                "idempotency_key": key,
                "include_character": True,
                "provider_option": "option2",
            },
            headers=auth_headers(token),
        )
    assert resp.status_code == 202, resp.text
    public_id = resp.json()["job_id"]

    db = TestingSessionLocal()
    try:
        row_id = (
            db.query(ImageGenerationJob.id)
            .filter(ImageGenerationJob.public_id == public_id)
            .scalar()
        )
    finally:
        db.close()

    with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
        svc.run_image_generation_job(row_id, session_factory=lambda: TestingSessionLocal())

    db = TestingSessionLocal()
    try:
        row = db.query(ImageGenerationJob).filter(ImageGenerationJob.id == row_id).one()
        state = {
            "status": row.status,
            "error_code": row.error_code,
            "diag": row.diag_json or {},
            "result": row.result_json,
        }
    finally:
        db.close()
    poll = client.get(
        f"/characters/{cid}/image-generator/jobs/{public_id}", headers=auth_headers(token)
    )
    return state, poll


def _reference_urls(cid) -> list[str]:
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.services.canon_service import load_face_canon

    db = TestingSessionLocal()
    try:
        canon = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == cid)
            .first()
        )
        face = load_face_canon(canon)
        return [
            u for u in (face.face_front_image_url, getattr(face, "face_side_image_url", None))
            if u
        ]
    finally:
        db.close()


def _assert_matches_what_was_sent(audit: dict, provider) -> None:
    """The audit's hashes are the hashes of the actual provider inputs."""
    call = provider.generate_with_anchors.call_args
    sent_prompt = call.kwargs["prompt"]
    sent_refs = call.kwargs["anchor_images"]

    assert audit["provider"] == "google"
    assert audit["model"] == GOOGLE_MODEL
    assert audit["cred_fp"] == hashlib.sha256(SECRET_KEY.encode()).hexdigest()[:12]
    assert audit["prompt_len"] == len(sent_prompt)
    assert audit["prompt_sha"] == hashlib.sha256(sent_prompt.encode()).hexdigest()[:8]
    assert audit["refs_requested"] == len(audit["refs"]) >= 1
    assert audit["refs_loaded"] == len(sent_refs)
    assert audit["refs_deduped"] == 0
    loaded = [r for r in audit["refs"] if r["loaded"]]
    assert [r["b"] for r in loaded] == [
        hashlib.sha256(b).hexdigest()[:8] for b in sent_refs
    ]
    assert [r["bytes"] for r in loaded] == [len(b) for b in sent_refs]
    assert all(r["mime"].startswith("image/") for r in loaded)
    assert all(len(r["h"]) == 8 for r in audit["refs"])
    assert audit["slots"] == [r["slot"] for r in audit["refs"]]
    assert {"camera", "routed", "exposure"} <= set(audit)


def _assert_private(diag: dict, cid) -> None:
    """Nothing sensitive in the serialised diag_json."""
    text = json.dumps(diag)
    assert SECRET_KEY not in text
    for token in ("Zarnak", "quicksilver", "bellwether", "lighthouse"):
        assert token not in text, f"prompt token {token!r} leaked"
    assert "adult, fully clothed" not in text  # canon_compiler safety prefix
    for url in _reference_urls(cid):
        assert url.split("?", 1)[0] not in text
    assert "://" not in text
    assert "static/" not in text
    assert base64.b64encode(stub_png_bytes())[:16].decode() not in text
    assert "iVBOR" not in text  # base64 PNG header
    # The audit itself: no URL scheme and no query string at all. (The wider
    # row legitimately carries "http_status" and provider text like "(HTTP 500)".)
    audit_text = json.dumps(diag.get("google_audit") or {})
    assert "http" not in audit_text.lower()
    assert "?" not in audit_text


# ── Failures ─────────────────────────────────────────────────────────────────


def test_provider_blocked_failure_persists_google_audit(client, founder):
    token, cid = founder
    provider = _google_provider(
        generate_with_anchors=MagicMock(side_effect=RuntimeError("google_prompt_blocked:OTHER:"))
    )
    state, poll = _run_job(client, token, cid, provider, "audit-blocked-01")

    assert state["status"] == "failed"
    assert state["error_code"] == "http_422"
    diag = state["diag"]
    assert diag["failure_kind"] == "provider_blocked"
    assert diag["block_reason"] == "OTHER"
    assert diag["safety_categories"] == []
    assert diag["finish_reason"] is None
    _assert_matches_what_was_sent(diag["google_audit"], provider)
    _assert_private(diag, cid)
    assert "google_audit" not in poll.text and "_google_audit" not in poll.text


def test_image_recitation_failure_persists_comparable_audit(client, founder):
    token, cid = founder
    provider = _google_provider(
        generate_with_anchors=MagicMock(
            side_effect=RuntimeError("google_refused_image: IMAGE_RECITATION")
        )
    )
    state, _ = _run_job(client, token, cid, provider, "audit-recit-001")

    diag = state["diag"]
    assert diag["failure_kind"] == "image_recitation"
    assert diag["finish_reason"] == "IMAGE_RECITATION"
    _assert_matches_what_was_sent(diag["google_audit"], provider)
    _assert_private(diag, cid)


def test_safety_categories_are_persisted_when_returned(client, founder):
    token, cid = founder
    provider = _google_provider(
        generate_with_anchors=MagicMock(side_effect=RuntimeError(
            "google_prompt_blocked:SAFETY:HARM_CATEGORY_DANGEROUS_CONTENT=HIGH"
        ))
    )
    state, _ = _run_job(client, token, cid, provider, "audit-safety-01")

    diag = state["diag"]
    assert diag["block_reason"] == "SAFETY"
    assert diag["safety_categories"] == ["HARM_CATEGORY_DANGEROUS_CONTENT=HIGH"]
    assert "google_audit" in diag


@pytest.mark.parametrize(
    "reason, finish_reason",
    [
        ("Google Gemini multi-reference failed (HTTP 500)", None),
        ("Google Gemini request failed: <urlopen error timed out>", None),
        (
            'Google Gemini multi-reference response contained no inlineData image: '
            '{"candidates": [{"finishReason": "PROHIBITED_CONTENT", "index": 0}]}',
            "PROHIBITED_CONTENT",
        ),
    ],
)
def test_unknown_or_transport_failure_persists_audit(client, founder, reason, finish_reason):
    token, cid = founder
    provider = _google_provider(generate_with_anchors=MagicMock(side_effect=RuntimeError(reason)))
    key = "audit-unk-" + hashlib.sha256(reason.encode()).hexdigest()[:8]
    state, _ = _run_job(client, token, cid, provider, key)

    diag = state["diag"]
    assert diag["failure_kind"] == "unknown"
    assert diag["finish_reason"] == finish_reason
    _assert_matches_what_was_sent(diag["google_audit"], provider)
    _assert_private(diag, cid)


# ── Success ──────────────────────────────────────────────────────────────────


def test_successful_google_job_persists_audit_only_in_diag(client, founder):
    token, cid = founder
    provider = _google_provider()
    state, poll = _run_job(client, token, cid, provider, "audit-success-1")

    assert state["status"] == "completed"
    _assert_matches_what_was_sent(state["diag"]["google_audit"], provider)
    _assert_private(state["diag"], cid)

    # Internal only: not in result_json, not in the owner-facing job API.
    assert "_google_audit" not in state["result"]
    assert "google_audit" not in state["result"]
    body = poll.json()
    assert poll.status_code == 200 and body["status"] == "completed"
    assert "_google_audit" not in poll.text and "google_audit" not in poll.text
    assert "diag" not in body


def test_success_and_failure_audits_share_one_schema(client, founder):
    """A DEV success and a LIVE failure must be diffable key for key."""
    token, cid = founder
    ok, _ = _run_job(client, token, cid, _google_provider(), "audit-schema-ok")
    blocked, _ = _run_job(
        client, token, cid,
        _google_provider(generate_with_anchors=MagicMock(
            side_effect=RuntimeError("google_prompt_blocked:OTHER:")
        )),
        "audit-schema-bad",
    )
    a, b = ok["diag"]["google_audit"], blocked["diag"]["google_audit"]
    assert set(a) == set(b)
    assert [set(r) for r in a["refs"]] == [set(r) for r in b["refs"]]
    # Same character, same prompt, same canon → identical inputs, identical hashes.
    for field in ("cred_fp", "model", "prompt_sha", "prompt_len", "slots"):
        assert a[field] == b[field], field
    assert [r["b"] for r in a["refs"]] == [r["b"] for r in b["refs"]]


# ── Diagnostics never change the outcome ─────────────────────────────────────


def test_audit_failure_never_masks_the_provider_failure(client, founder):
    token, cid = founder
    provider = _google_provider(
        generate_with_anchors=MagicMock(side_effect=RuntimeError("google_prompt_blocked:OTHER:"))
    )
    with patch(f"{PIPELINE}._ref_audit_entries", side_effect=RuntimeError("audit exploded")):
        state, poll = _run_job(client, token, cid, provider, "audit-boom-fail")

    assert state["status"] == "failed"
    assert state["error_code"] == "http_422"
    diag = state["diag"]
    assert diag["failure_kind"] == "provider_blocked"
    assert diag["block_reason"] == "OTHER"
    assert "google_audit" not in diag
    assert "audit exploded" not in json.dumps(diag)
    assert "audit exploded" not in poll.text


def test_audit_failure_never_masks_a_successful_generation(client, founder):
    token, cid = founder
    provider = _google_provider()
    with patch(f"{PIPELINE}._ref_audit_entries", side_effect=RuntimeError("audit exploded")):
        state, poll = _run_job(client, token, cid, provider, "audit-boom-ok01")

    assert state["status"] == "completed"
    assert "google_audit" not in state["diag"]
    assert poll.json()["status"] == "completed"
    provider.generate_with_anchors.assert_called_once()


# ── Behaviour unchanged ──────────────────────────────────────────────────────


def test_provider_receives_the_same_request_with_or_without_audit(client, founder):
    """The audit is built after the call and cannot alter prompt or references."""
    token, cid = founder
    with_audit = _google_provider()
    _run_job(client, token, cid, with_audit, "audit-same-req-1")
    without_audit = _google_provider()
    with patch(f"{PIPELINE}._build_google_audit", side_effect=RuntimeError("off")):
        _run_job(client, token, cid, without_audit, "audit-same-req-2")

    a = with_audit.generate_with_anchors.call_args.kwargs
    b = without_audit.generate_with_anchors.call_args.kwargs
    assert a["prompt"] == b["prompt"]
    assert a["anchor_images"] == b["anchor_images"]
    with_audit.generate_with_anchors.assert_called_once()
    without_audit.generate_with_anchors.assert_called_once()

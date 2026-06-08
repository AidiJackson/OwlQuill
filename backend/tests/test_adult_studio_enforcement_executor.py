"""Tests for the Adult Studio tattoo-enforcement EXECUTOR v1 (Phase 3, Sprint 7).

The executor consumes the DB enforcement plan, generates ONE base image (injected —
no network, no spend), dispatches each mark route to a handler that computes its real
conditioning artifact, composes a final preview, and emits a structured report.

All I/O is injected: a fake base generator (returns a fixed url + cost), a fake byte
fetcher (returns real in-memory PNGs so handlers actually run PIL), and a fake image
saver (returns deterministic fake URLs). Zero network, zero spend.
"""
import io

from PIL import Image

from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)
from app.services.adult_identity_enforcement_executor import (
    SUMMER_CHARACTER_ID,
    AdultIdentityEnforcementExecutor,
)

_ARTIFACT = "https://replicate.delivery/xezq/abc/trained_model.tar"
_REF = "https://pub.r2.dev/generated/{}.png"
_SLEEVE_REASON = "matched sleeve/coverage keyword 'sleeve' → ip_adapter"
_BALLERINA_REASON = "matched figural keyword 'ballerina' → controlnet_canny"


# ── Fakes (no network, no spend) ──────────────────────────────────────────────


def _png_bytes(color=(120, 90, 60), size=(64, 96)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeSaver:
    """Records saved images; returns a deterministic fake URL per call."""
    def __init__(self):
        self.saved = []

    def __call__(self, png_bytes: bytes) -> str:
        # Sanity: every saved artifact must be a valid PNG.
        Image.open(io.BytesIO(png_bytes)).verify()
        self.saved.append(len(png_bytes))
        return f"https://fake.local/artifact/{len(self.saved)}.png"


def _fake_fetch(_uri: str) -> bytes:
    return _png_bytes()


def _base_gen(cost=0.02, status="succeeded",
              url="https://replicate.delivery/base/out-0.png"):
    calls = {"n": 0}

    def gen(spend_cap):
        calls["n"] += 1
        return {"status": status, "image_url": url, "cost_usd": cost,
                "prompt": "a photo of TOK ...", "predict_time_s": 18.0, "error": None}

    gen.calls = calls
    return gen


# ── DB fixture builders ───────────────────────────────────────────────────────


def _create_character(client, name="Summer") -> int:
    client.post("/auth/register", json={
        "email": "ex-user@test.com", "username": "exuser", "password": "pass12345"})
    tok = client.post("/auth/login", json={
        "email": "ex-user@test.com", "password": "pass12345"}).json()["access_token"]
    resp = client.post("/characters/", json={"name": name, "visibility": "public"},
                       headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _build_summer(db, cid, status="ready", routes=("ip_adapter", "controlnet_canny"),
                  with_version=True, references=True):
    m = AdultIdentityModel(character_id=cid, status=status, trigger_token="TOK")
    db.add(m); db.commit(); db.refresh(m)
    if with_version:
        v = AdultIdentityModelVersion(identity_id=m.id, version_index=1,
                                      lora_weights_uri=_ARTIFACT, state="active")
        db.add(v); db.commit(); db.refresh(v)
        m.active_version_id = v.id; db.commit()
    specs = [
        ("pbm_8cff990d", "Right upper arm", "right", routes[0], _SLEEVE_REASON),
        ("pbm_de30011b", "Left forearm", "left", routes[1], _BALLERINA_REASON),
    ]
    for mid, region, side, route, reason in specs:
        db.add(AdultIdentityMarkRender(
            identity_id=m.id, canon_mark_id=mid, mark_type="tattoo",
            body_region=region, side=side, route=route,
            reference_uri=(_REF.format(mid) if references else None),
            params_json={"reason": reason}))
    db.commit()
    return m


def _executor(db, *, gen=None, saver=None, spend_cap=0.15):
    return AdultIdentityEnforcementExecutor(
        db, generate_base=gen or _base_gen(),
        fetch_bytes=_fake_fetch, save_image=saver or _FakeSaver(),
        spend_cap=spend_cap)


# Summer happens to be character_id=60 only in prod; tests build a fresh character and
# patch the executor's required id to that character so the Summer-only guard passes.
def _run_for(db, cid, **kw):
    ex = _executor(db, **kw)
    # Re-point the Summer-only guard at the freshly created character.
    import app.services.adult_identity_enforcement_executor as mod
    orig = mod.SUMMER_CHARACTER_ID
    mod.SUMMER_CHARACTER_ID = cid
    try:
        return ex.run(cid)
    finally:
        mod.SUMMER_CHARACTER_ID = orig


# ── Happy path: both routes execute, final produced, under cap ────────────────


def test_executor_runs_both_routes_and_produces_final(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid)
    saver = _FakeSaver()
    report = _run_for(db_session, cid, saver=saver)

    assert report["success"] is True, report["blocking_reasons"]
    assert report["manual_review_required"] is True
    assert report["enforcement_mode"] == "conditioning_preview"
    assert report["diffusion_pass"] == "deferred"

    # Plan consumed from DB.
    assert report["identity_id"] is not None
    assert report["active_version_id"] is not None
    assert report["model_version_id"] == report["active_version_id"]
    assert report["model_artifact_uri"] == _ARTIFACT

    # Both Summer routes executed with real artifacts.
    routes = {r["route"]: r for r in report["routes_executed"]}
    assert routes["ip_adapter"]["status"] == "prepared"
    assert routes["ip_adapter"]["artifact_kind"] == "ip_adapter_style_reference"
    assert routes["controlnet_canny"]["status"] == "prepared"
    assert routes["controlnet_canny"]["artifact_kind"] == "controlnet_edge_map"
    assert all(r["artifact_url"] for r in report["routes_executed"])

    # Final image produced + image URL bundle populated.
    assert report["final_image_url"] is not None
    assert report["image_urls"]["base"] == "https://replicate.delivery/base/out-0.png"
    assert report["image_urls"]["final"] == report["final_image_url"]
    assert len(report["image_urls"]["artifacts"]) == 2

    # Spend tracked and under cap.
    assert report["spend_usd"] == 0.02
    assert report["spend_usd"] < report["spend_cap_usd"]
    # base ref + ballerina edge + 2 artifacts re-read + final  → several saves.
    assert len(saver.saved) >= 3


# ── Cap enforcement: breach stops immediately, no route dispatch ──────────────


def test_cap_breach_stops_immediately_without_dispatch(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid)
    over = _base_gen(cost=0.20)  # single generation already over the $0.15 cap
    report = _run_for(db_session, cid, gen=over, spend_cap=0.15)

    assert report["success"] is False
    assert report["routes_executed"] == []  # never dispatched
    assert report["final_image_url"] is None
    assert any("SPEND CAP BREACH" in r for r in report["blocking_reasons"])
    # The cost was incurred but the run halted; spend recorded honestly.
    assert report["spend_usd"] == 0.20


# ── Plan gating: not-ready plan blocks before any spend ───────────────────────


def test_not_ready_plan_blocks_before_generation(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid, status="prepared")  # not 'ready'
    gen = _base_gen()
    report = _run_for(db_session, cid, gen=gen)

    assert report["success"] is False
    assert gen.calls["n"] == 0  # NEVER generated
    assert report["spend_usd"] == 0.0
    assert any("ready_for_executor" in r for r in report["blocking_reasons"])


def test_missing_reference_blocks_before_generation(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid, references=False)
    gen = _base_gen()
    report = _run_for(db_session, cid, gen=gen)

    assert report["success"] is False
    assert gen.calls["n"] == 0
    assert report["spend_usd"] == 0.0


# ── Base generation failure surfaces, routes not dispatched ───────────────────


def test_failed_base_generation_blocks(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid)
    gen = _base_gen(status="failed", url="")
    report = _run_for(db_session, cid, gen=gen)

    assert report["success"] is False
    assert report["routes_executed"] == []
    assert any("base image generation did not succeed" in r
               for r in report["blocking_reasons"])


# ── inpaint_direct handler is a stub (allowed) ────────────────────────────────


def test_inpaint_direct_route_is_stubbed(db_session):
    # Verified at the dispatch level: Summer's plan never routes a mark to
    # inpaint_direct, but the handler must exist as an accepted stub.
    ex = _executor(db_session)
    out = ex._dispatch({"canon_mark_id": "pbm_skin", "region": "Cheek", "side": None,
                        "route": "inpaint_direct", "reference_uri": _REF.format("skin"),
                        "reason": "type=mole → inpaint_direct"})
    assert out["status"] == "stub"
    assert out["artifact_url"] is None
    assert out["artifact_kind"] == "inpaint_direct_stub"


def test_unknown_route_marked_unsupported(db_session):
    ex = _executor(db_session)
    out = ex._dispatch({"canon_mark_id": "pbm_x", "region": "Arm", "side": "left",
                        "route": "hologram", "reference_uri": None, "reason": None})
    assert out["status"] == "unsupported"
    assert out["artifact_url"] is None
    assert "no handler" in out["error"]


# ── Summer-only guard ─────────────────────────────────────────────────────────


def test_non_summer_character_refused(client, db_session):
    cid = _create_character(client)
    _build_summer(db_session, cid)
    # Do NOT repoint the guard — run with the real Summer id (60) against a non-60 char.
    gen = _base_gen()
    ex = _executor(db_session, gen=gen)
    report = ex.run(cid)  # cid != 60

    assert report["success"] is False
    assert gen.calls["n"] == 0
    assert any("Summer-only" in r for r in report["blocking_reasons"])
    assert SUMMER_CHARACTER_ID == 60  # constant intact

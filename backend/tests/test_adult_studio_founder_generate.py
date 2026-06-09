"""Adult Studio FOUNDER GENERATE — Summer-only, admin-only (Phase 3, Sprint 8).

POST /admin/adult-studio/characters/{id}/founder-generate

Runs the VALIDATED pipeline (active LoRA + DB enforcement plan + tattoo-enforcement
executor + both Summer routes) — NOT the old OpenAI gpt-image path. Gates fire BEFORE
any generator is constructed, so the gating/auth tests never touch the network. The
happy path is exercised at the service level with injected fakes (zero spend, zero
network), exactly like the executor tests.
"""
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.core import config as cfg_module
from app.models.adult_identity import (
    AdultIdentityMarkRender,
    AdultIdentityModel,
    AdultIdentityModelVersion,
)
from app.services import adult_identity_founder_generate as fg
from app.services.adult_identity_enforcement_executor import (
    AdultIdentityEnforcementExecutor,
)

_ADMIN_EMAIL = "founder-gen-admin@ficshon.com"
_ARTIFACT = "https://replicate.delivery/xezq/abc/trained_model.tar"
_REF = "https://pub.r2.dev/generated/{}.png"
_SLEEVE_REASON = "matched sleeve/coverage keyword 'sleeve' → ip_adapter"
_BALLERINA_REASON = "matched figural keyword 'ballerina' → controlnet_canny"


# ── Auth helpers ────────────────────────────────────────────────────────────────


def _register_and_login(client: TestClient, email: str, username: str, password="pass12345") -> str:
    client.post("/auth/register", json={"email": email, "username": username, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")


def _admin_token(client) -> str:
    return _register_and_login(client, _ADMIN_EMAIL, "foundergenadmin")


def _create_character(client, token, name="Summer") -> int:
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _url(cid: int) -> str:
    return f"/admin/adult-studio/characters/{cid}/founder-generate"


# ── DB fixture: a ready Summer identity with both tattoo routes ──────────────────


def _build_summer(db, cid, *, status="ready", with_version=True, references=True):
    m = AdultIdentityModel(character_id=cid, status=status, trigger_token="TOK")
    db.add(m); db.commit(); db.refresh(m)
    if with_version:
        v = AdultIdentityModelVersion(identity_id=m.id, version_index=1,
                                      lora_weights_uri=_ARTIFACT, state="active")
        db.add(v); db.commit(); db.refresh(v)
        m.active_version_id = v.id; db.commit()
    specs = [
        ("pbm_8cff990d", "Right upper arm", "right", "ip_adapter", _SLEEVE_REASON),
        ("pbm_de30011b", "Left forearm", "left", "controlnet_canny", _BALLERINA_REASON),
    ]
    for mid, region, side, route, reason in specs:
        db.add(AdultIdentityMarkRender(
            identity_id=m.id, canon_mark_id=mid, mark_type="tattoo",
            body_region=region, side=side, route=route,
            reference_uri=(_REF.format(mid) if references else None),
            params_json={"reason": reason}))
    db.commit()
    return m


# ── Injected fakes (no network, no spend) ───────────────────────────────────────


def _png_bytes(color=(120, 90, 60), size=(64, 96)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _fake_fetch(_uri: str) -> bytes:
    return _png_bytes()


class _FakeSaver:
    def __init__(self):
        self.saved = []

    def __call__(self, png_bytes: bytes) -> str:
        Image.open(io.BytesIO(png_bytes)).verify()
        self.saved.append(len(png_bytes))
        return f"https://fake.local/artifact/{len(self.saved)}.png"


def _fake_base_gen(cost=0.02, status="succeeded",
                   url="https://replicate.delivery/base/out-0.png"):
    calls = {"n": 0}

    def gen(_remaining_cap):
        calls["n"] += 1
        return {"status": status, "image_url": url, "cost_usd": cost,
                "prompt": "a photo of TOK ...", "predict_time_s": 18.0, "error": None}

    gen.calls = calls
    return gen


class _FakeLifecycle:
    """Records terminate() calls; reports configurable orphans."""
    def __init__(self, orphans=None):
        self._orphans = list(orphans or [])
        self.terminated = 0
        self.terminate_reasons = []

    def terminate(self, reason: str) -> None:
        self.terminated += 1
        self.terminate_reasons.append(reason)

    def list_orphans(self):
        return list(self._orphans)


def _make_gen_factory(gen):
    def make_base_generator(_model, _prompt, _cap, _lifecycle):
        return gen
    return make_base_generator


def _fake_executor_factory(gen=None, saver=None):
    def factory(db, generate_base, spend_cap):
        return AdultIdentityEnforcementExecutor(
            db, generate_base=generate_base,
            fetch_bytes=_fake_fetch, save_image=saver or _FakeSaver(),
            spend_cap=spend_cap)
    return factory


def _service(db, cid, prompt, *, gen=None, lifecycle=None, saver=None, monkeypatch=None):
    """Run run_founder_generate against the freshly created (non-60) character.

    Repoints BOTH the service-level and executor-level Summer-only guards at ``cid``.
    """
    gen = gen or _fake_base_gen()
    import app.services.adult_identity_enforcement_executor as ex_mod
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    monkeypatch.setattr(ex_mod, "SUMMER_CHARACTER_ID", cid)
    return fg.run_founder_generate(
        db, cid, prompt,
        make_base_generator=_make_gen_factory(gen),
        executor_factory=_fake_executor_factory(gen, saver),
        worker_lifecycle=lifecycle or _FakeLifecycle())


# ── HTTP gating / auth tests (fire before any generation) ────────────────────────


def test_non_admin_blocked(client, db_session, monkeypatch):
    token = _register_and_login(client, "plain@test.com", "plainuser")
    resp = client.post(_url(60), json={"prompt": "summer at the beach"}, headers=_headers(token))
    assert resp.status_code == 403, resp.text


def test_non_summer_blocked(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token, name="NotSummer")  # not id 60
    resp = client.post(_url(cid), json={"prompt": "a portrait"}, headers=_headers(token))
    assert resp.status_code == 409, resp.text
    assert "Summer-only" in resp.json()["detail"]


def test_prompt_required(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    resp = client.post(_url(cid), json={"prompt": "   "}, headers=_headers(token))
    assert resp.status_code == 422, resp.text


def test_no_active_version_blocked(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid, status="ready", with_version=False)
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    resp = client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))
    assert resp.status_code == 409, resp.text
    assert "active" in resp.json()["detail"].lower()


def test_not_ready_blocked(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid, status="prepared")  # not 'ready'
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    resp = client.post(_url(cid), json={"prompt": "summer poolside"}, headers=_headers(token))
    assert resp.status_code == 409, resp.text
    assert "ready" in resp.json()["detail"].lower()


def test_safety_block_minor_terms(client, db_session, monkeypatch):
    _make_admin(monkeypatch)
    token = _admin_token(client)
    cid = _create_character(client, token)
    _build_summer(db_session, cid, status="ready")
    monkeypatch.setattr(fg, "SUMMER_CHARACTER_ID", cid)
    resp = client.post(_url(cid), json={"prompt": "a child on the beach"}, headers=_headers(token))
    assert resp.status_code == 400, resp.text
    assert "blocked" in resp.json()["detail"].lower()


# ── Service-level happy path + safety behaviours (mocked, zero spend) ─────────────


def test_happy_path_runs_validated_pipeline(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "owner@test.com", "owner"))
    _build_summer(db_session, cid, status="ready")
    saver = _FakeSaver()
    gen = _fake_base_gen()
    lifecycle = _FakeLifecycle()
    result = _service(db_session, cid, "summer relaxing poolside in a bikini",
                      gen=gen, lifecycle=lifecycle, saver=saver, monkeypatch=monkeypatch)

    assert result["success"] is True, result["blocking_reasons"]
    assert result["manual_review_required"] is True
    assert result["final_image_url"] is not None
    # Base image + both route artifacts are exposed as intermediate artifacts.
    assert result["intermediate_artifact_urls"][0] == "https://replicate.delivery/base/out-0.png"
    assert len(result["intermediate_artifact_urls"]) == 3
    # Both Summer tattoo routes executed.
    routes = {r["route"]: r for r in result["routes_executed"]}
    assert routes["ip_adapter"]["status"] == "prepared"
    assert routes["controlnet_canny"]["status"] == "prepared"
    # Cost tracked + under the founder cap; runtime present.
    assert result["cost"] == 0.02
    assert result["cost"] < fg.FOUNDER_SPEND_CAP_USD
    assert "runtime" in result
    # Generation actually ran once; worker terminated; no orphans.
    assert gen.calls["n"] == 1
    assert lifecycle.terminated == 1
    assert result["orphaned_workers"] == []


def test_worker_terminated_on_base_failure(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "owner2@test.com", "owner2"))
    _build_summer(db_session, cid, status="ready")
    gen = _fake_base_gen(status="failed", url="")
    lifecycle = _FakeLifecycle()
    result = _service(db_session, cid, "summer poolside", gen=gen,
                      lifecycle=lifecycle, monkeypatch=monkeypatch)

    assert result["success"] is False
    assert result["final_image_url"] is None
    # The worker is terminated even though generation failed.
    assert lifecycle.terminated == 1


def test_orphaned_workers_fail_the_run(client, db_session, monkeypatch):
    cid = _create_character(client, _register_and_login(client, "owner3@test.com", "owner3"))
    _build_summer(db_session, cid, status="ready")
    lifecycle = _FakeLifecycle(orphans=["pod-abc"])
    result = _service(db_session, cid, "summer poolside",
                      lifecycle=lifecycle, monkeypatch=monkeypatch)

    # Even a successful image is failed if a worker/pod leaked.
    assert result["success"] is False
    assert result["orphaned_workers"] == ["pod-abc"]
    assert any("orphaned workers" in r for r in result["blocking_reasons"])
    assert lifecycle.terminated == 1


def test_spend_cap_is_five_cents():
    assert fg.FOUNDER_SPEND_CAP_USD == 0.05


# NOTE: The live founder route is now ASYNC (Sprint 13). The synchronous montage path
# tested above via run_founder_generate() is retained for rollback but is no longer wired
# to the HTTP route. Async route + job-service behaviour (202, singleton, state machine,
# reconcile, cancel) is covered in test_adult_studio_founder_async.py.

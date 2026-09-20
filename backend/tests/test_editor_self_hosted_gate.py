"""Phase 6.3B — the self_hosted editor is admin-only and one-character-only.

Self Hosted Premium is an internal admin experiment whose whole pipeline
(LoRA, trigger token, subject phrase, segmentation heuristics) belongs to one
character. Two routes can reach it — the sync ``POST /editor/generate`` and
the async ``POST /editor/jobs`` — and both must refuse

  * any account that is not an admin (403), and
  * any character but SELF_HOSTED_EDITOR_CHARACTER_ID (422),

BEFORE anything costs money or leaves a row behind: no weekly-quota check, no
provider construction, no pod, no EditorJob, no R2 snapshot, no CharacterImage.

gpt-image and grok are untouched by this; their tests here are the regression
half of the same boundary.
"""
import io
from unittest.mock import MagicMock, patch

import pytest

import app.services.editor_studio as editor_studio_svc
from app.api.routes.editor_studio import SELF_HOSTED_INCOMPATIBLE_CHARACTER_DETAIL
from app.services.editor_studio import (
    SELF_HOSTED_EDITOR_CHARACTER_ID,
    self_hosted_editor_supports_character,
)
from tests.conftest import auth_headers, get_auth_token, make_admin, make_seeder

GENERATE = "/editor/generate"
JOBS = "/editor/jobs"

_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4e0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


@pytest.fixture(autouse=True)
def _no_subprocess(monkeypatch):
    import app.services.editor_job_service as job_svc

    monkeypatch.setattr(job_svc, "_default_launcher", lambda run_id, job_id: None)


def _png_file(name="src.png"):
    return ("images", (name, io.BytesIO(_PNG_BYTES), "image/png"))


def _form(character_id: int, provider: str = "self_hosted", **overrides):
    data = {
        "character_id": str(character_id),
        "prompt": "Same character on a beach",
        "provider": provider,
        "strength": "0.25",
    }
    data.update({k: str(v) for k, v in overrides.items()})
    return data


def _character(client, token, name="Gate Char") -> int:
    resp = client.post("/characters/", json={"name": name, "species": "human"},
                       headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _creator(client):
    token = get_auth_token(client, "gate-creator@test.com", "gatecreator")
    return token, _character(client, token)


def _seeder(client):
    token = get_auth_token(client, "gate-seeder@test.com", "gateseeder")
    make_seeder("gate-seeder@test.com")
    return token, _character(client, token)


def _admin(client, email="gate-admin@test.com", username="gateadmin"):
    token = get_auth_token(client, email, username)
    make_admin(email)
    return token, _character(client, token)


def _make_compatible(monkeypatch, cid: int) -> None:
    monkeypatch.setattr(editor_studio_svc, "SELF_HOSTED_EDITOR_CHARACTER_ID", cid)


def _mock_editor(provider="gpt-image", version="e1"):
    editor = MagicMock()
    editor.provider_name = provider
    editor.editor_version = version
    editor.edit = MagicMock(return_value=_PNG_BYTES)
    return editor


def _row_counts(db_session) -> tuple[int, int]:
    from app.models.character_image import CharacterImage
    from app.models.editor_job import EditorJob

    return db_session.query(EditorJob).count(), db_session.query(CharacterImage).count()


class _Boundaries:
    """Every cost or side effect between the gate and the provider, mocked.

    A refused request must touch NONE of them. Patched at the route module,
    which is where the route looks them up.
    """

    def __init__(self):
        self.quota = patch("app.api.routes.editor_studio.check_weekly_quota",
                           side_effect=AssertionError("quota checked before the gate"))
        self.editor = patch("app.api.routes.editor_studio.get_editor",
                            side_effect=AssertionError("provider constructed before the gate"))
        self.transient = patch("app.api.routes.editor_studio.put_transient_object",
                               side_effect=AssertionError("R2 snapshot before the gate"))
        self.start_job = patch("app.api.routes.editor_studio.start_editor_job",
                               side_effect=AssertionError("EditorJob created before the gate"))
        self.pod = patch("app.services.editor_self_hosted._launch",
                         side_effect=AssertionError("RunPod launch before the gate"))

    def __enter__(self):
        for p in (self.quota, self.editor, self.transient, self.start_job, self.pod):
            p.start()
        return self

    def __exit__(self, *exc):
        for p in (self.quota, self.editor, self.transient, self.start_job, self.pod):
            p.stop()
        return False


# ── the fact itself ──────────────────────────────────────────────────


def test_compatibility_constant_is_pinned():
    """One character, by id, and it is the one the pipeline was built for.

    If this fails because someone widened the predicate, that is the point:
    the pod prompt, LoRA and masks have not become character-aware just
    because the gate did.
    """
    assert SELF_HOSTED_EDITOR_CHARACTER_ID == 60
    assert self_hosted_editor_supports_character(60) is True
    for other in (1, 59, 61, 0, -60):
        assert self_hosted_editor_supports_character(other) is False


def test_lora_lookup_uses_the_same_constant():
    """editor_self_hosted.py must not carry its own copy of the number."""
    import inspect

    import app.services.editor_self_hosted as sh

    src = inspect.getsource(sh._default_lora_url)
    assert "SELF_HOSTED_EDITOR_CHARACTER_ID" in src
    assert "build_enforcement_plan(\n            60" not in src
    assert sh.SELF_HOSTED_EDITOR_CHARACTER_ID is SELF_HOSTED_EDITOR_CHARACTER_ID


def test_refusal_detail_names_no_internals():
    for secret in ("60", "Summer", "TOK", "LoRA", "lora", "http", "AdultIdentity"):
        assert secret not in SELF_HOSTED_INCOMPATIBLE_CHARACTER_DETAIL


# ── /editor/generate: admin gate ─────────────────────────────────────


def test_generate_unauthenticated_is_refused_as_today(client):
    # HTTPBearer: 403 for a missing Authorization header, 401 for a bad token
    # (same as test_editor_studio.test_auth_required). Either way nothing
    # about self_hosted is consulted — the request never reaches the route.
    with _Boundaries():
        missing = client.post(GENERATE, data=_form(1), files=[_png_file()])
        bad = client.post(GENERATE, data=_form(1), files=[_png_file()],
                          headers={"Authorization": "Bearer not-a-real-token"})
    assert missing.status_code in (401, 403)
    assert bad.status_code == 401


@pytest.mark.parametrize("who", ["creator", "seeder"])
def test_generate_non_admin_self_hosted_is_403_before_any_cost(client, db_session, who):
    token, cid = (_creator if who == "creator" else _seeder)(client)
    _row_counts(db_session)
    with _Boundaries():
        resp = client.post(GENERATE, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 403, resp.text
    assert _row_counts(db_session) == (0, 0)


def test_generate_non_admin_self_hosted_403_even_via_library_source(client, db_session):
    """The upload-ingress 403 must not be what is protecting this route.

    An ordinary creator can supply ``source_image_ids`` freely; the provider
    gate has to refuse them on its own.
    """
    token, cid = _creator(client)
    with _Boundaries():
        resp = client.post(GENERATE, data=_form(cid, source_image_ids="1"),
                           headers=auth_headers(token))
    assert resp.status_code == 403, resp.text
    assert "self-hosted" in resp.json()["detail"].lower() or "admin" in resp.json()["detail"].lower()
    assert _row_counts(db_session) == (0, 0)


# ── /editor/generate: character gate ─────────────────────────────────


def test_generate_admin_incompatible_character_is_422_before_any_cost(client, db_session):
    token, cid = _admin(client)
    assert cid != SELF_HOSTED_EDITOR_CHARACTER_ID  # a fresh test character, real constant
    with _Boundaries():
        resp = client.post(GENERATE, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == SELF_HOSTED_INCOMPATIBLE_CHARACTER_DETAIL
    assert _row_counts(db_session) == (0, 0)


def test_generate_admin_seeder_incompatible_character_is_422(client, db_session):
    token, cid = _admin(client, "gate-admin-seeder@test.com", "gateadminseeder")
    make_seeder("gate-admin-seeder@test.com")
    with _Boundaries():
        resp = client.post(GENERATE, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 422, resp.text
    assert _row_counts(db_session) == (0, 0)


def test_generate_admin_compatible_character_reaches_provider(client, db_session, monkeypatch):
    token, cid = _admin(client)
    _make_compatible(monkeypatch, cid)
    editor = _mock_editor("self_hosted", "e4")
    with patch("app.api.routes.editor_studio.get_editor", return_value=editor) as get_ed:
        resp = client.post(GENERATE, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    get_ed.assert_called_once_with("self_hosted")
    editor.edit.assert_called_once()
    assert resp.json()["image"]["metadata_json"]["editor_provider"] == "self_hosted"
    assert _row_counts(db_session) == (0, 1)


# ── /editor/jobs ─────────────────────────────────────────────────────


def test_jobs_non_admin_is_403_before_any_cost(client, db_session):
    token, cid = _seeder(client)
    with _Boundaries():
        resp = client.post(JOBS, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 403
    assert _row_counts(db_session) == (0, 0)


def test_jobs_admin_incompatible_character_is_422_before_any_cost(client, db_session):
    token, cid = _admin(client)
    assert cid != SELF_HOSTED_EDITOR_CHARACTER_ID
    with _Boundaries():
        resp = client.post(JOBS, data=_form(cid), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == SELF_HOSTED_INCOMPATIBLE_CHARACTER_DETAIL
    assert _row_counts(db_session) == (0, 0)


def test_jobs_admin_compatible_character_keeps_current_job_path(client, db_session, monkeypatch):
    token, cid = _admin(client)
    _make_compatible(monkeypatch, cid)
    resp = client.post(JOBS, data=_form(cid), files=[_png_file()],
                       headers=auth_headers(token))
    assert resp.status_code == 202, resp.text
    assert resp.json()["provider"] == "self_hosted"
    assert resp.json()["character_id"] == cid
    assert _row_counts(db_session)[0] == 1


def test_jobs_incompatible_character_is_refused_before_the_404_lookup(client):
    """Character gate precedes the existence lookup: a non-existent id is
    refused as incompatible, not reported as missing."""
    token, _ = _admin(client)
    with _Boundaries():
        resp = client.post(JOBS, data=_form(999999), files=[_png_file()],
                           headers=auth_headers(token))
    assert resp.status_code == 422


# ── the other providers are untouched ────────────────────────────────


def test_gpt_image_creator_path_unchanged(client, db_session):
    """An ordinary creator's gpt-image edit of their own library image still
    works, still consumes quota, still persists under the character."""
    token, cid = _creator(client)
    from app.models.character_image import CharacterImage, ImageKindEnum
    from app.services.asset_persistence import OwnedBy, persist_image_asset
    from app.models.character import Character

    character = db_session.query(Character).get(cid)
    src = persist_image_asset(db_session, content=_PNG_BYTES,
                              owner=OwnedBy.character(character),
                              kind=ImageKindEnum.GENERATED, provider="test",
                              prompt_summary="src", metadata={})
    db_session.commit()

    editor = _mock_editor()
    with patch("app.api.routes.editor_studio.get_editor", return_value=editor), \
         patch("app.api.routes.editor_studio.check_weekly_quota",
               return_value=None) as quota:
        resp = client.post(GENERATE, data=_form(cid, provider="gpt-image",
                                                source_image_ids=str(src.id)),
                           headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    quota.assert_called_once()
    editor.edit.assert_called_once()
    kwargs = editor.edit.call_args.kwargs
    assert kwargs["strength"] == 0.25 and len(kwargs["source_images"]) == 1
    assert db_session.query(CharacterImage).filter(
        CharacterImage.character_id == cid).count() == 2


def test_gpt_image_creator_cannot_upload_still(client):
    """The closed-beta upload boundary is unchanged for the default provider."""
    token, cid = _creator(client)
    with patch("app.api.routes.editor_studio.get_editor") as get_ed:
        resp = client.post(GENERATE, data=_form(cid, provider="gpt-image"),
                           files=[_png_file()], headers=auth_headers(token))
    assert resp.status_code == 403
    get_ed.assert_not_called()


def test_grok_seeder_and_admin_path_unchanged(client, db_session, monkeypatch):
    """grok never had an admin gate and still has none: a seeder upload edit
    goes through exactly as before, with the e2 provider."""
    token, cid = _seeder(client)
    editor = _mock_editor("grok", "e2")
    with patch("app.api.routes.editor_studio.get_editor", return_value=editor) as get_ed:
        resp = client.post(GENERATE, data=_form(cid, provider="grok"),
                           files=[_png_file()], headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    get_ed.assert_called_once_with("grok")
    meta = resp.json()["image"]["metadata_json"]
    assert meta["editor_provider"] == "grok" and meta["editor_mode"] == "edit"
    assert meta["input_fidelity"] is None


def test_gpt_image_and_grok_do_not_consult_the_character_gate(client, monkeypatch):
    """The compatibility predicate is self_hosted's alone."""
    token, cid = _seeder(client)
    called = []
    monkeypatch.setattr(editor_studio_svc, "self_hosted_editor_supports_character",
                        lambda c: called.append(c) or False)
    import app.api.routes.editor_studio as route
    monkeypatch.setattr(route, "self_hosted_editor_supports_character",
                        lambda c: called.append(c) or False)
    for provider in ("gpt-image", "grok"):
        with patch("app.api.routes.editor_studio.get_editor", return_value=_mock_editor(provider)):
            resp = client.post(GENERATE, data=_form(cid, provider=provider),
                               files=[_png_file()], headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
    assert called == []

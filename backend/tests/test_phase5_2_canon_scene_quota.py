"""Phase 5.2 — Canon scene generation obeys the weekly image allowance.

The Phase 5 audit found ``POST /identity-canon/scenes/generate`` reachable by an
ordinary owner without the ``check_weekly_quota`` gate every other generation
route uses. The SCENE_ONLY row it writes was ALREADY counted by the quota
(``QUOTA_COUNTED_IMAGE_KINDS``), so the route spent the allowance without ever
honouring it — an exhausted account could keep generating by calling the API.

These tests mirror ``test_b22_image_allowance.py`` (same helpers, same
``/images/quota`` ledger, same 429 shape) rather than inventing a Canon-specific
quota model. No paid provider is reachable: conftest strips every provider
credential, and the provider factories are patched where a call would matter.

Proven:
  1. an exhausted ordinary owner is refused with the established 429
  2. the refusal happens before ANY provider factory is consulted, and no row
     is written
  3. the 429 body has the shared ``quota_exceeded`` shape
  4. a successful generation is accounted exactly once in the shared ledger
  5. a provider failure follows the sibling scene route's contract — the
     placeholder outcome is persisted once and counted once
  6. ownership authorization still runs, and runs before quota
  7. founder/seeder exemption matches the existing policy (no Canon-specific
     allowance in either direction)
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, get_auth_token

_ROUTE = "/characters/{cid}/identity-canon/scenes/generate"
_BODY = {"prompt": "standing on a beach in daylight", "provider_option": "option2"}


def _login(client: TestClient, email: str) -> str:
    return get_auth_token(client, email=email, username=email.split("@")[0])


def _create_character(client: TestClient, token: str, name: str = "QuotaCanonChar") -> int:
    resp = client.post(
        "/characters/", json={"name": name, "visibility": "public"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _generate(client: TestClient, token: str, cid: int):
    return client.post(_ROUTE.format(cid=cid), json=_BODY, headers=auth_headers(token))


def _quota(client: TestClient, token: str) -> dict:
    resp = client.get("/images/quota", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _scene_rows(db_session, cid: int) -> int:
    from app.models.character_image import CharacterImage, ImageKindEnum

    db_session.expire_all()
    return (
        db_session.query(CharacterImage)
        .filter(CharacterImage.character_id == cid, CharacterImage.kind == ImageKindEnum.SCENE_ONLY)
        .count()
    )


# ── 1 + 3. Exhausted quota → established 429, via the Canon route itself ──


def test_exhausted_owner_cannot_bypass_quota_via_canon_scene_route(client, monkeypatch):
    """The Canon route's OWN successful generations exhaust the shared ledger,
    and the next direct call is refused with the shared 429 contract."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 2)
    token = _login(client, "p52_exhaust@example.com")
    cid = _create_character(client, token)

    assert _generate(client, token, cid).status_code == 200
    assert _generate(client, token, cid).status_code == 200

    resp = _generate(client, token, cid)
    assert resp.status_code == 429, resp.text
    data = resp.json()
    # Same shape ``images.py`` / ``scene_images.py`` return (B22 + B23 fields).
    assert data["error"] == "quota_exceeded"
    assert "detail" in data
    assert data["limit"] == 2
    assert isinstance(data["reset_in_seconds"], int) and data["reset_in_seconds"] > 0
    assert data["reset_at"] is not None


def test_quota_exhausted_by_another_generator_blocks_canon_route(client, monkeypatch):
    """One ledger: allowance spent on ``/api/images/generate`` refuses the Canon route."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)
    token = _login(client, "p52_shared@example.com")
    cid = _create_character(client, token)

    resp = client.post(
        "/api/images/generate", json={"prompt": "library image"}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text

    resp = _generate(client, token, cid)
    assert resp.status_code == 429, resp.text
    assert resp.json()["error"] == "quota_exceeded"


# ── 2. Rejection precedes every provider path; nothing is written ────


def test_quota_rejection_happens_before_any_provider_call(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)
    token = _login(client, "p52_noprov@example.com")
    cid = _create_character(client, token)
    assert _generate(client, token, cid).status_code == 200

    rows_before = _scene_rows(db_session, cid)
    used_before = _quota(client, token)["used"]

    primary = MagicMock(name="get_provider_for_option")
    fallback = MagicMock(name="get_fallback_provider")
    placeholder = MagicMock(name="render_placeholder_png")
    with (
        patch("app.api.routes.canon_api.get_provider_for_option", primary),
        patch("app.api.routes.canon_api.get_fallback_provider", fallback),
        patch("app.api.routes.canon_api.render_placeholder_png", placeholder),
    ):
        resp = _generate(client, token, cid)

    assert resp.status_code == 429, resp.text
    # No provider factory was consulted — the paid path is unreachable.
    primary.assert_not_called()
    fallback.assert_not_called()
    # Not even the free stub ran: the route returned before generation.
    placeholder.assert_not_called()
    # And nothing was persisted or charged.
    assert _scene_rows(db_session, cid) == rows_before
    assert _quota(client, token)["used"] == used_before


# ── 4. Success is accounted exactly once ─────────────────────────────


def test_successful_generation_is_accounted_exactly_once(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 5)
    token = _login(client, "p52_once@example.com")
    cid = _create_character(client, token)

    before = _quota(client, token)
    rows_before = _scene_rows(db_session, cid)

    resp = _generate(client, token, cid)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kind"] == "scene_only"

    after = _quota(client, token)
    assert after["used"] == before["used"] + 1
    assert after["remaining"] == before["remaining"] - 1
    assert _scene_rows(db_session, cid) == rows_before + 1


# ── 5. Provider failure follows the sibling scene route's contract ───


def test_provider_failure_persists_and_counts_once_like_scene_images(client, db_session, monkeypatch):
    """Every provider tier raises → the route falls through to the placeholder,
    which is persisted as SCENE_ONLY and therefore counted once — exactly what
    ``/scene-images/generate`` (Tier D stub) does. The quota was checked, the
    attempt produced a row, the row is the deduction."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 5)
    token = _login(client, "p52_provfail@example.com")
    cid = _create_character(client, token)

    failing = MagicMock()
    failing.generate_with_anchors.side_effect = RuntimeError("provider down")
    failing.generate_grounded_image.side_effect = RuntimeError("provider down")
    failing.generate_image.side_effect = RuntimeError("provider down")

    before = _quota(client, token)
    rows_before = _scene_rows(db_session, cid)
    with (
        patch("app.api.routes.canon_api.get_provider_for_option", return_value=failing),
        patch("app.api.routes.canon_api.get_fallback_provider", return_value=None),
    ):
        resp = _generate(client, token, cid)

    assert resp.status_code == 200, resp.text
    assert failing.generate_image.call_count == 1  # the text tier was reached and failed
    assert resp.json()["provider"] == "stub"
    assert _quota(client, token)["used"] == before["used"] + 1
    assert _scene_rows(db_session, cid) == rows_before + 1


# ── 6. Ownership still enforced, and ahead of quota ──────────────────


def test_non_owner_is_refused_before_quota_is_consulted(client, db_session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 5)
    owner = _login(client, "p52_owner@example.com")
    cid = _create_character(client, owner)
    intruder = _login(client, "p52_intruder@example.com")

    with patch("app.api.routes.canon_api.check_weekly_quota") as quota_gate:
        resp = _generate(client, intruder, cid)

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "You don't own this character."
    quota_gate.assert_not_called()
    assert _scene_rows(db_session, cid) == 0
    assert _quota(client, intruder)["used"] == 0


# ── 7. Founder/seeder exemption matches the existing policy ──────────


def test_admin_founder_is_exempt_exactly_as_elsewhere(client, monkeypatch):
    """``ADMIN_EMAILS`` account generates past the cap — the shared
    ``_is_quota_exempt`` policy, not a Canon-specific allowance."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)
    email = "p52_admin@ficshon.com"
    monkeypatch.setattr(settings, "ADMIN_EMAILS", email)

    token = _login(client, email)
    cid = _create_character(client, token)
    for _ in range(3):
        assert _generate(client, token, cid).status_code == 200
    assert _quota(client, token)["unlimited"] is True


def test_seeder_is_exempt_exactly_as_elsewhere(client, monkeypatch):
    """The seeder tier is exempt too — ``is_founder_account`` covers it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMAGE_WEEKLY_LIMIT", 1)
    email = "p52_seeder@ficshon.com"
    monkeypatch.setattr(settings, "SEEDER_EMAILS", email)

    token = _login(client, email)
    cid = _create_character(client, token)
    for _ in range(3):
        assert _generate(client, token, cid).status_code == 200

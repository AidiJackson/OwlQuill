"""Polish Phase 6.2 — retired legacy routes stay retired; their neighbours stay.

Two ordinary-user doors were removed:

* ``POST /images/generate`` — the characterless generator that made a stub
  placeholder PNG and spent the weekly allowance on it.
* ``POST /ai/character-bio`` / ``POST /ai/scene`` — the FakeAI string
  templates behind the roster's legacy Quick Create form.

The routes are gone from the router tables at both mount points (``/`` and
``/api``). Everything around them is untouched: the library listing, the
allowance endpoint, and the canonical character-scoped generator.
"""
import pytest

from app.main import app
from tests.conftest import get_auth_token, auth_headers


def _route_paths(methods: set[str] | None = None) -> set[str]:
    out = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", None) or set()
        if path is None:
            continue
        if methods is None or route_methods & methods:
            out.add(path)
    return out


# ── The retired routes are not registered ────────────────────────────────────

@pytest.mark.parametrize("path", ["/images/generate", "/api/images/generate"])
def test_characterless_generate_route_is_gone(path):
    assert path not in _route_paths({"POST"})


@pytest.mark.parametrize(
    "path",
    ["/ai/character-bio", "/api/ai/character-bio", "/ai/scene", "/api/ai/scene"],
)
def test_fakeai_routes_are_gone(path):
    assert path not in _route_paths()


def test_retired_routes_answer_404_not_403(client):
    """404, not 403: the route no longer exists, whoever asks. A creator (who
    would have passed the old require_creator guard) gets the same answer."""
    creator = get_auth_token(client, email="retired-routes@test.com", username="retiredroutes")
    client.post(
        "/characters/",
        json={"name": "Muse", "species": "human"},
        headers=auth_headers(creator),
    )
    for path in ("/images/generate", "/ai/character-bio", "/ai/scene"):
        resp = client.post(path, json={"prompt": "x", "name": "x"}, headers=auth_headers(creator))
        assert resp.status_code == 404, f"{path}: {resp.status_code} {resp.text}"


def test_fakeai_settings_are_gone():
    from app.core.config import settings

    assert not hasattr(settings, "AI_PROVIDER")
    assert not hasattr(settings, "AI_API_KEY")


# ── The neighbours remain ────────────────────────────────────────────────────

def test_library_listing_and_quota_remain(client):
    token = get_auth_token(client, email="library-remains@test.com", username="libraryremains")
    listing = client.get("/images/", headers=auth_headers(token))
    assert listing.status_code == 200, listing.text
    assert listing.json() == []
    quota = client.get("/images/quota", headers=auth_headers(token))
    assert quota.status_code == 200, quota.text
    assert "remaining" in quota.json()


def test_canonical_generator_route_remains():
    paths = _route_paths({"POST"})
    assert "/characters/{character_id}/image-generator/generate" in paths
    assert "/api/characters/{character_id}/image-generator/generate" in paths

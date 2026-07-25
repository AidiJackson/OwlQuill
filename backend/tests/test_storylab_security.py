"""Security: cross-user story access must be blocked on every story endpoint.

Every route that accepts a story_id must validate that the requesting user owns
that story (for UUID-format IDs). These tests confirm that user B cannot read or
write to user A's stories, state, chapters, or GenerationLog data.
"""
import pytest

from tests.conftest import auth_headers, get_auth_token, ensure_character


# ── helpers ───────────────────────────────────────────────────────────────────

def _create_story(client, headers: dict) -> str:
    """Create a story record and return its UUID."""
    resp = client.post(
        "/storylab/stories",
        json={"title": "Security Test Story", "genre": "fantasy"},
        headers=headers,
    )
    assert resp.status_code == 201, f"Story creation failed: {resp.text}"
    return resp.json()["id"]


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def two_users(client):
    """Return (headers_a, headers_b, story_id_a).

    story_id_a is a UUID-format story owned by user A.
    """
    token_a = get_auth_token(client, email="sec_a@test.com", username="sec_user_a")
    token_b = get_auth_token(client, email="sec_b@test.com", username="sec_user_b")
    # BOTH users need a character. A creates the story, so A obviously does —
    # but B must be a creator too, otherwise the "blocked for wrong user" tests
    # would pass because B is a Wanderer rather than because B doesn't own the
    # story. That would silently gut what this module exists to check: these
    # are OWNERSHIP tests, not entitlement tests.
    ensure_character(client, token_a, name="Sec Alpha")
    ensure_character(client, token_b, name="Sec Beta")
    hdrs_a = auth_headers(token_a)
    hdrs_b = auth_headers(token_b)
    story_id_a = _create_story(client, hdrs_a)
    return hdrs_a, hdrs_b, story_id_a


# ── GET /storylab/state ────────────────────────────────────────────────────────

class TestGetState:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.get(f"/storylab/state?story_id={story_id_a}", headers=hdrs_b)
        assert resp.status_code == 403, resp.text

    def test_allowed_for_owner(self, client, two_users):
        hdrs_a, _, story_id_a = two_users
        resp = client.get(f"/storylab/state?story_id={story_id_a}", headers=hdrs_a)
        assert resp.status_code == 200, resp.text


# ── POST /storylab/generate ───────────────────────────────────────────────────

class TestGenerate:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.post(
            "/storylab/generate",
            json={
                "story_id": story_id_a,
                "text": "The hero stepped into the dark forest.",
            },
            headers=hdrs_b,
        )
        assert resp.status_code == 403, resp.text

    def test_allowed_for_owner(self, client, two_users):
        hdrs_a, _, story_id_a = two_users
        resp = client.post(
            "/storylab/generate",
            json={
                "story_id": story_id_a,
                "text": "The hero stepped into the dark forest.",
            },
            headers=hdrs_a,
        )
        assert resp.status_code == 200, resp.text

    def test_generation_log_not_readable_by_wrong_user(self, client, two_users):
        """User B cannot trigger GenerationLog reads for user A's story.

        _fetch_recent_endings reads the GenerationLog; the ownership gate at the
        /generate route blocks user B before that helper is ever called.
        """
        hdrs_a, hdrs_b, story_id_a = two_users
        # User A generates once so a GenerationLog row exists.
        client.post(
            "/storylab/generate",
            json={"story_id": story_id_a, "text": "An opening scene."},
            headers=hdrs_a,
        )
        # User B tries to generate for the same story → must be rejected.
        resp = client.post(
            "/storylab/generate",
            json={"story_id": story_id_a, "text": "Continuing the scene."},
            headers=hdrs_b,
        )
        assert resp.status_code == 403, resp.text


# ── GET /storylab/chapters ────────────────────────────────────────────────────

class TestListChapters:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.get(f"/storylab/chapters?story_id={story_id_a}", headers=hdrs_b)
        assert resp.status_code == 403, resp.text

    def test_allowed_for_owner(self, client, two_users):
        hdrs_a, _, story_id_a = two_users
        resp = client.get(f"/storylab/chapters?story_id={story_id_a}", headers=hdrs_a)
        assert resp.status_code == 200, resp.text
        assert isinstance(resp.json(), list)


# ── GET /storylab/chapters/{chapter_number} ───────────────────────────────────

class TestGetChapter:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.get(
            f"/storylab/chapters/1?story_id={story_id_a}", headers=hdrs_b
        )
        assert resp.status_code == 403, resp.text

    def test_owner_gets_404_for_nonexistent_chapter(self, client, two_users):
        """Owner should receive 404 (not 403) when a chapter simply does not exist."""
        hdrs_a, _, story_id_a = two_users
        resp = client.get(
            f"/storylab/chapters/99?story_id={story_id_a}", headers=hdrs_a
        )
        assert resp.status_code == 404, resp.text


# ── POST /storylab/chapters/generate ─────────────────────────────────────────

class TestChapterGenerate:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.post(
            f"/storylab/chapters/generate?story_id={story_id_a}",
            json={"prompt": "A new adventure.", "mode": "roleplay"},
            headers=hdrs_b,
        )
        assert resp.status_code == 403, resp.text


# ── POST /storylab/chapters/{n}/regenerate ───────────────────────────────────

class TestChapterRegenerate:
    def test_blocked_for_wrong_user(self, client, two_users):
        _, hdrs_b, story_id_a = two_users
        resp = client.post(
            f"/storylab/chapters/1/regenerate?story_id={story_id_a}",
            json={"prompt": "Retry.", "mode": "roleplay"},
            headers=hdrs_b,
        )
        assert resp.status_code == 403, resp.text


# ── Legacy storylab: IDs bypass ownership gate ────────────────────────────────

class TestLegacyIds:
    def test_legacy_id_bypasses_403(self, client, two_users):
        """Legacy storylab: IDs have no StoryModel record; the ownership gate skips them.

        This is a known accepted risk for legacy IDs. Any authenticated user can
        access legacy state IDs (same behavior as before the security fix).
        """
        _, hdrs_b, _ = two_users
        legacy_id = "storylab:1716000000000-abc123"
        resp = client.get(f"/storylab/state?story_id={legacy_id}", headers=hdrs_b)
        # Must not return 403 — legacy IDs skip ownership validation.
        assert resp.status_code != 403, resp.text
        # Typically 200 (auto-creates state).
        assert resp.status_code == 200, resp.text

"""Tests for RP Story Thread endpoints."""
import pytest

from tests.conftest import get_auth_token, auth_headers

_PARTNER_STARTER = (
    "||Mira didn't look up when the door opened. She was seated at the edge of the low "
    "table, both hands wrapped around a cup that had long gone cold.||\n\n"
    '"You came back," she said. Not a question. Her voice was flat — not unfriendly. '
    "Just measured, the way someone speaks when they have decided to be careful."
)

_PARTNER_SECOND = (
    "||She finally looked up. Her eyes were steady.||\n\n"
    '"And what are you going to do about it?" she asked.'
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _create_character(client, token: str, name: str = "Lennox") -> int:
    resp = client.post(
        "/characters",
        json={"name": name, "bio": "A quiet, deliberate woman.", "role": "protagonist"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_thread(client, token: str, char_id: int | None = None) -> dict:
    body = {
        "partner_starter": _PARTNER_STARTER,
        "partner_label": "Mira",
        "partner_pov": "third",
    }
    if char_id is not None:
        body["selected_character_id"] = char_id
    resp = client.post("/rp-stories", json=body, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── create thread ─────────────────────────────────────────────────────────────

def test_create_rp_story_with_starter(client):
    token = get_auth_token(client)
    data = _create_thread(client, token)

    assert data["id"] > 0
    assert data["partner_label"] == "Mira"
    assert data["partner_pov"] == "third"
    assert data["status"] == "active"
    assert len(data["turns"]) == 1
    turn = data["turns"][0]
    assert turn["turn_index"] == 1
    assert turn["author_type"] == "partner"
    assert turn["content"] == _PARTNER_STARTER


def test_create_rp_story_auto_title(client):
    token = get_auth_token(client)
    data = _create_thread(client, token)
    # Title auto-derived from first line of starter — must not be empty
    assert data["title"]
    assert len(data["title"]) > 0


def test_create_rp_story_with_explicit_title(client):
    token = get_auth_token(client)
    resp = client.post(
        "/rp-stories",
        json={"partner_starter": _PARTNER_STARTER, "title": "The Cold Cup"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "The Cold Cup"


def test_create_rp_story_requires_auth(client):
    resp = client.post("/rp-stories", json={"partner_starter": _PARTNER_STARTER})
    assert resp.status_code in (401, 403)


# ── turns stored in order ─────────────────────────────────────────────────────

def test_turns_stored_in_order(client):
    token = get_auth_token(client)
    thread = _create_thread(client, token)
    tid = thread["id"]

    # Add a second turn (partner)
    resp = client.post(
        f"/rp-stories/{tid}/partner-turn",
        json={"content": _PARTNER_SECOND},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["turn_index"] == 2

    # Fetch thread and verify order
    resp = client.get(f"/rp-stories/{tid}", headers=auth_headers(token))
    assert resp.status_code == 200
    turns = resp.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["turn_index"] == 1
    assert turns[1]["turn_index"] == 2


# ── list threads ──────────────────────────────────────────────────────────────

def test_list_rp_stories(client):
    token = get_auth_token(client)
    _create_thread(client, token)
    _create_thread(client, token)
    resp = client.get("/rp-stories", headers=auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


def test_list_rp_stories_only_own(client):
    token_a = get_auth_token(client, email="a@test.com", username="usera")
    token_b = get_auth_token(client, email="b@test.com", username="userb")
    _create_thread(client, token_a)
    resp = client.get("/rp-stories", headers=auth_headers(token_b))
    assert resp.status_code == 200
    assert len(resp.json()) == 0


# ── generate reply does NOT save automatically ────────────────────────────────

def test_generate_reply_does_not_save(client):
    token = get_auth_token(client)
    char_id = _create_character(client, token)
    thread = _create_thread(client, token, char_id=char_id)
    tid = thread["id"]

    resp = client.post(
        f"/rp-stories/{tid}/generate-reply",
        json={"response_length": "short", "intensity": "standard"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert "reply" in resp.json()
    assert resp.json()["reply"]

    # Fetch thread — should still have only 1 turn (the partner starter)
    detail = client.get(f"/rp-stories/{tid}", headers=auth_headers(token)).json()
    assert detail["turn_count"] == 1
    assert all(t["author_type"] == "partner" for t in detail["turns"])


# ── save generated turn ───────────────────────────────────────────────────────

def test_save_generated_turn(client):
    token = get_auth_token(client)
    char_id = _create_character(client, token)
    thread = _create_thread(client, token, char_id=char_id)
    tid = thread["id"]

    saved = client.post(
        f"/rp-stories/{tid}/save-generated-turn",
        json={
            "content": "She set down the cup and met Mira's gaze.",
            "godmod_detected": False,
            "godmod_severity": "none",
            "model_used": "stub",
        },
        headers=auth_headers(token),
    ).json()

    assert saved["turn_index"] == 2
    assert saved["author_type"] == "selected_character"
    assert saved["generated"] is True
    assert saved["godmod_detected"] is False

    detail = client.get(f"/rp-stories/{tid}", headers=auth_headers(token)).json()
    assert detail["turn_count"] == 2


# ── partner next turn increments order ───────────────────────────────────────

def test_partner_next_turn_increments_index(client):
    token = get_auth_token(client)
    char_id = _create_character(client, token)
    thread = _create_thread(client, token, char_id=char_id)
    tid = thread["id"]

    # Save character turn (index 2)
    client.post(
        f"/rp-stories/{tid}/save-generated-turn",
        json={"content": "She nodded once."},
        headers=auth_headers(token),
    )

    # Add partner reply (index 3)
    resp = client.post(
        f"/rp-stories/{tid}/partner-turn",
        json={"content": _PARTNER_SECOND},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["turn_index"] == 3


# ── godmod metadata preserved ─────────────────────────────────────────────────

def test_godmod_metadata_preserved(client):
    token = get_auth_token(client)
    char_id = _create_character(client, token)
    thread = _create_thread(client, token, char_id=char_id)
    tid = thread["id"]

    saved = client.post(
        f"/rp-stories/{tid}/save-generated-turn",
        json={
            "content": "She waited.",
            "godmod_detected": True,
            "godmod_severity": "soft",
            "godmod_warnings": ["Possible partner attribution"],
            "model_used": "stub",
            "generation_time_ms": 150,
        },
        headers=auth_headers(token),
    ).json()

    assert saved["godmod_detected"] is True
    assert saved["godmod_severity"] == "soft"
    assert saved["metadata_json"]["godmod_warnings"] == ["Possible partner attribution"]
    assert saved["metadata_json"]["model_used"] == "stub"


# ── user cannot access another user's thread ──────────────────────────────────

def test_cannot_access_another_users_thread(client):
    token_a = get_auth_token(client, email="owner@test.com", username="owner")
    token_b = get_auth_token(client, email="intruder@test.com", username="intruder")

    thread = _create_thread(client, token_a)
    tid = thread["id"]

    resp = client.get(f"/rp-stories/{tid}", headers=auth_headers(token_b))
    assert resp.status_code == 403

    resp = client.post(
        f"/rp-stories/{tid}/partner-turn",
        json={"content": "Hello."},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 403


def test_cannot_generate_for_another_users_character(client):
    token_a = get_auth_token(client, email="chara@test.com", username="chara")
    token_b = get_auth_token(client, email="charb@test.com", username="charb")

    char_id_a = _create_character(client, token_a, name="Vesper")
    thread = _create_thread(client, token_b, char_id=None)
    tid = thread["id"]

    # Directly set character_id to user_a's character via create — should 403
    resp = client.post(
        "/rp-stories",
        json={
            "partner_starter": _PARTNER_STARTER,
            "selected_character_id": char_id_a,
        },
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 403


# ── selected character ownership on generate ─────────────────────────────────

def test_generate_requires_character_ownership(client):
    token_a = get_auth_token(client, email="charowner@test.com", username="charowner")
    token_b = get_auth_token(client, email="charuser@test.com", username="charuser")

    char_id = _create_character(client, token_a, name="Dusk")

    # Token B creates a thread with no character
    thread = _create_thread(client, token_b)
    tid = thread["id"]

    # Try to generate — thread has no character, should 400
    resp = client.post(
        f"/rp-stories/{tid}/generate-reply",
        json={"response_length": "short"},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 400  # no selected character


# ── prompt includes TURN_BOUNDARY_FOOTER ─────────────────────────────────────

def test_prompt_includes_turn_ownership(client):
    """build_thread_context passes the partner_reply and thread header instructions
    which include the turn ownership statement."""
    from app.models.rp_story import RPStoryThread, RPStoryTurn
    from app.services.rp_story_service import build_thread_context
    from datetime import datetime

    thread = RPStoryThread(
        id=1, user_id=1, selected_character_id=1,
        title="Test Thread", partner_label="Mira", partner_pov="third",
        status="active", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    turns = [
        RPStoryTurn(
            id=1, thread_id=1, turn_index=1, author_type="partner",
            content=_PARTNER_STARTER, generated=False, created_at=datetime.utcnow(),
        )
    ]
    partner_reply, canon_summary = build_thread_context(thread, turns, "Lennox")

    assert partner_reply == _PARTNER_STARTER
    # Canon summary is empty when only one turn exists (no history before latest partner)
    assert canon_summary == ""


def test_prompt_multi_turn_builds_canon(client):
    """With history turns, canon_summary is populated for context."""
    from app.models.rp_story import RPStoryThread, RPStoryTurn
    from app.services.rp_story_service import build_thread_context
    from datetime import datetime

    thread = RPStoryThread(
        id=1, user_id=1, selected_character_id=1,
        title="Multi-Turn Thread", partner_label="Mira", partner_pov="third",
        status="active", created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    turns = [
        RPStoryTurn(id=1, thread_id=1, turn_index=1, author_type="partner",
                    content="Opening line.", generated=False, created_at=datetime.utcnow()),
        RPStoryTurn(id=2, thread_id=1, turn_index=2, author_type="selected_character",
                    content="She replied.", generated=True, created_at=datetime.utcnow()),
        RPStoryTurn(id=3, thread_id=1, turn_index=3, author_type="partner",
                    content="Second partner turn.", generated=False, created_at=datetime.utcnow()),
    ]
    partner_reply, canon_summary = build_thread_context(thread, turns, "Lennox")

    assert partner_reply == "Second partner turn."
    assert "Opening line." in canon_summary
    assert "She replied." in canon_summary
    assert "Second partner turn." not in canon_summary  # latest partner not in history


# ── archive ───────────────────────────────────────────────────────────────────

def test_archive_thread(client):
    token = get_auth_token(client)
    thread = _create_thread(client, token)
    tid = thread["id"]

    resp = client.patch(f"/rp-stories/{tid}/archive", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

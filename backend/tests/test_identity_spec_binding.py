"""Regression tests for identity spec binding (Fix 1 + Fix 2).

Verifies that:
1. Generate A / Generate B / Accept A → committed spec == spec A, not spec B.
2. identity_spec_version does NOT increment on generate.
3. identity_spec_version increments to 1 on the first accept.
4. identity_anchor_json lock string and hash are derived from the accepted pack's spec.
"""
import json
from unittest.mock import patch

from tests.conftest import auth_headers


# ── Specs used in all tests ───────────────────────────────────────────────────

_SPEC_A = {
    "gender": "female",
    "age_band": "26-35",
    "style": "realistic",
    "identity": {
        "hair_color": "auburn",
        "hair_length": "long",
        "eye_color": "green",
        "skin_tone": "fair",
    },
}

_SPEC_B = {
    "gender": "female",
    "age_band": "26-35",
    "style": "realistic",
    "identity": {
        "hair_color": "blonde",
        "hair_length": "short",
        "eye_color": "blue",
        "skin_tone": "tan",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(client, email, username):
    client.post("/auth/register", json={"email": email, "username": username, "password": "testpass!123"})
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return auth_headers(resp.json()["access_token"])


def _create_character(client, headers, name="SpecBindChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _generate_pack(client, headers, char_id, spec):
    """POST identity-pack/generate with a structured spec. Returns pack_id.

    Patches generate_placeholder_png so no disk I/O is required.
    """
    with patch(
        "app.api.routes.character_visual.generate_placeholder_png",
        return_value="static/generated/stub_test.png",
    ):
        resp = client.post(
            f"/characters/{char_id}/identity-pack/generate",
            json={"identity_spec": spec},
            headers=headers,
        )
    assert resp.status_code == 200, f"generate failed: {resp.text}"
    return resp.json()["pack_id"]


def _accept_pack(client, headers, char_id, pack_id):
    """POST identity-pack/accept. Returns response JSON.

    The face-ref crop (load_image_bytes) raises FileNotFoundError for stub paths
    but that exception is caught inside accept_identity_pack — no patch needed.
    """
    resp = client.post(
        f"/characters/{char_id}/identity-pack/accept",
        json={"pack_id": pack_id},
        headers=headers,
    )
    assert resp.status_code == 200, f"accept failed: {resp.text}"
    return resp.json()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_accept_pack_a_after_generate_b_commits_spec_a(client, db_session):
    """Generate A → Generate B → Accept A: committed identity_spec_json must be spec A."""
    headers = _make_user(client, "bind_mismatch@test.com", "bindmismatch")
    char_id = _create_character(client, headers, "BindMismatchChar")

    pack_id_a = _generate_pack(client, headers, char_id, _SPEC_A)
    _generate_pack(client, headers, char_id, _SPEC_B)  # generates pack B, does NOT overwrite A's spec
    _accept_pack(client, headers, char_id, pack_id_a)  # accept pack A

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)

    assert char.identity_spec_json is not None, "identity_spec_json must be set after accept"
    committed = json.loads(char.identity_spec_json)
    assert committed.get("identity", {}).get("hair_color") == "auburn", (
        f"Committed spec must be spec A (auburn hair), got: {committed}"
    )
    # Spec B's hair color must not have leaked in
    assert committed.get("identity", {}).get("hair_color") != "blonde", (
        f"Spec B (blonde) must not be committed when pack A is accepted"
    )


def test_lock_string_derived_from_accepted_pack_spec(client, db_session):
    """Lock string in identity_anchor_json must reflect the accepted pack's spec, not spec B."""
    headers = _make_user(client, "lockstr_bind@test.com", "lockstrbind")
    char_id = _create_character(client, headers, "LockStrBindChar")

    pack_id_a = _generate_pack(client, headers, char_id, _SPEC_A)
    _generate_pack(client, headers, char_id, _SPEC_B)
    _accept_pack(client, headers, char_id, pack_id_a)

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)

    anchor = json.loads(char.identity_anchor_json or "{}")
    lock_string = anchor.get("identity_lock_string") or ""

    assert "auburn" in lock_string.lower(), (
        f"Lock string must contain spec A trait 'auburn', got: {lock_string!r}"
    )
    assert "blonde" not in lock_string.lower(), (
        f"Lock string must NOT contain spec B trait 'blonde', got: {lock_string!r}"
    )


def test_version_does_not_increment_on_generate(client, db_session):
    """identity_spec_version must remain 0 after generate calls (version tracks commits, not attempts)."""
    headers = _make_user(client, "ver_gen@test.com", "vergen")
    char_id = _create_character(client, headers, "VerGenChar")

    _generate_pack(client, headers, char_id, _SPEC_A)
    _generate_pack(client, headers, char_id, _SPEC_B)

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)

    assert char.identity_spec_version == 0, (
        f"identity_spec_version must be 0 after two generate calls (not yet accepted), "
        f"got {char.identity_spec_version}"
    )


def test_version_increments_on_accept(client, db_session):
    """identity_spec_version must be 1 after the first successful accept."""
    headers = _make_user(client, "ver_accept@test.com", "veraccept")
    char_id = _create_character(client, headers, "VerAcceptChar")

    pack_id_a = _generate_pack(client, headers, char_id, _SPEC_A)
    _generate_pack(client, headers, char_id, _SPEC_B)
    _accept_pack(client, headers, char_id, pack_id_a)

    from app.models.character import Character
    char = db_session.query(Character).filter(Character.id == char_id).first()
    db_session.refresh(char)

    assert char.identity_spec_version == 1, (
        f"identity_spec_version must be 1 after first accept, got {char.identity_spec_version}"
    )

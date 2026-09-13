"""Polish Phase 1 — C2: the creator can read back the Interview it stored.

``GET /characters/{id}/dna`` is the read half of the existing DNA upsert. It
exists so a draft can resume with the answers the creator already gave; it
returns what was stored, only to the owner, and 404s when nothing was stored.
"""
from fastapi.testclient import TestClient

from tests.conftest import auth_headers, get_auth_token

_SPEC = {
    "style": "realistic",
    "gender": "female",
    "age_band": "26-35",
    "species": "vampire",
    "species_tells": ["subtle_fangs"],
    "face_shape": "angular",
    "eye_shape": "almond",
    "hair_texture": "wavy",
    "identity": {"hair_color": "Auburn", "hair_length": "Long", "eye_color": "Green", "skin_tone": "Fair"},
}


def _character(client: TestClient, token: str, name: str = "Tatiana") -> int:
    resp = client.post("/characters/", json={"name": name, "species": "vampire"}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _store_interview(client: TestClient, token: str, cid: int) -> None:
    resp = client.post(
        f"/characters/{cid}/dna",
        json={
            "species": "vampire",
            "gender_presentation": "female",
            "visual_traits_json": {"personality_traits": ["Cunning", "Haunted"], "identity_spec": _SPEC},
            "structural_profile_json": {"age_band": "26-35"},
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_owner_reads_back_exactly_what_was_stored(client: TestClient):
    token = get_auth_token(client, email="p1dna@test.com", username="p1dna")
    cid = _character(client, token)
    _store_interview(client, token, cid)

    resp = client.get(f"/characters/{cid}/dna", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["character_id"] == cid
    assert body["species"] == "vampire"
    assert body["gender_presentation"] == "female"
    assert body["visual_traits_json"]["identity_spec"] == _SPEC
    assert body["visual_traits_json"]["personality_traits"] == ["Cunning", "Haunted"]
    assert body["structural_profile_json"] == {"age_band": "26-35"}


def test_no_dna_yet_is_404_not_an_empty_spec(client: TestClient):
    """The wizard must not be told an Interview exists when it does not."""
    token = get_auth_token(client, email="p1dna_none@test.com", username="p1dnanone")
    cid = _character(client, token)
    resp = client.get(f"/characters/{cid}/dna", headers=auth_headers(token))
    assert resp.status_code == 404, resp.text


def test_another_user_cannot_read_the_dna(client: TestClient):
    owner = get_auth_token(client, email="p1dna_owner@test.com", username="p1dnaowner")
    cid = _character(client, owner)
    _store_interview(client, owner, cid)

    stranger = get_auth_token(client, email="p1dna_stranger@test.com", username="p1dnastranger")
    resp = client.get(f"/characters/{cid}/dna", headers=auth_headers(stranger))
    assert resp.status_code == 403, resp.text
    assert "identity_spec" not in resp.text


def test_unknown_character_is_404(client: TestClient):
    token = get_auth_token(client, email="p1dna_404@test.com", username="p1dna404")
    resp = client.get("/characters/987654/dna", headers=auth_headers(token))
    assert resp.status_code == 404, resp.text


def test_read_requires_authentication(client: TestClient):
    token = get_auth_token(client, email="p1dna_anon@test.com", username="p1dnaanon")
    cid = _character(client, token)
    resp = client.get(f"/characters/{cid}/dna")
    assert resp.status_code in (401, 403), resp.text

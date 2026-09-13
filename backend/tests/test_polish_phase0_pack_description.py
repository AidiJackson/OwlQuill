"""Polish Phase 0 — C6 / C7: every interview answer reaches the V2 pack.

The Character Creator's Interview stores a ``CharacterIdentitySpec`` in
``CharacterDNA.visual_traits_json["identity_spec"]``. The V2 canon pack reads
it back through ``founder_identity_from_character`` → ``_spec_face_description``
and folds the result into every card prompt. Three answers used to be lost on
that path even though the interview asked for them and the sketch honoured
them:

* ``species`` (C6) — ``FounderIdentity`` has no species field, so a vampire
  whose creator chose no tells rendered as a human;
* ``eye_spacing`` and ``hairline_type`` (C7) — absent from the geometry tuple.

These tests pin that all three now appear, that "human" still contributes
nothing, and that the rest of the description is byte-for-byte what it was.
"""
from fastapi.testclient import TestClient

from app.services.canon_pack_builder import (
    _spec_face_description,
    founder_identity_from_character,
)
from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token


# ── Unit: _spec_face_description ─────────────────────────────────────────────


def test_eye_spacing_and_hairline_reach_the_face_description():
    desc = _spec_face_description({
        "face_shape": "oval",
        "eye_spacing": "wide_set",
        "hairline_type": "widows_peak",
        "identity": {},
    })
    assert "wide set eyes" in desc
    assert "widows peak hairline" in desc
    # Order is the geometry tuple's order: shape → eyes → hairline.
    assert desc.index("oval face") < desc.index("wide set eyes") < desc.index("widows peak hairline")


def test_non_human_species_reaches_the_face_description_without_tells():
    desc = _spec_face_description({"species": "vampire", "identity": {}})
    assert desc == "vampire character"


def test_species_and_tells_read_as_one_phrase_group():
    desc = _spec_face_description({
        "species": "werewolf",
        "species_tells": ["golden_eyes", "claw_scars"],
        "identity": {},
    })
    assert desc.endswith("werewolf character, golden eyes, claw scars")


def test_human_contributes_nothing_as_before():
    assert _spec_face_description({"species": "human", "face_shape": "round", "identity": {}}) == "round face"
    assert _spec_face_description({"face_shape": "round", "identity": {}}) == "round face"


def test_species_enum_instances_are_handled():
    from app.schemas.character_visual import SpeciesEnum

    desc = _spec_face_description({"species": SpeciesEnum.FAE, "identity": {}})
    assert desc == "fae character"


def test_previously_working_fields_are_unchanged():
    """Regression guard: the pre-existing description shape is untouched."""
    desc = _spec_face_description({
        "hair_texture": "wavy",
        "hair_style": "tied_back",
        "face_shape": "square",
        "jaw_type": "sharp",
        "cheekbone_type": "high",
        "eye_shape": "deep_set",
        "eyebrow_shape": "arched",
        "nose_type": "roman",
        "lip_type": "full",
        "facial_hair_type": "none",
        "identity": {
            "skin_tone": "Olive",
            "hair_length": "Long",
            "hair_color": "Black",
            "eye_color": "Brown",
            "face_features": [],
        },
    })
    assert desc == (
        "Olive skin, wavy Long Black hair, tied back hairstyle, Brown eyes, "
        "square face, sharp jaw, high cheekbones, deep set eyes, arched eyebrows, "
        "roman nose, full lips"
    )


# ── Integration: the interview → DNA → FounderIdentity path ─────────────────


def test_interview_answers_survive_into_the_founder_identity(client: TestClient):
    """The exact path the creation wizard takes: PUT /dna with the spec inside
    visual_traits_json, then the pack builder reads it back."""
    from app.models.character import Character
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.services.canon_service import get_or_create_canon

    token = get_auth_token(client, email="p0pack@test.com", username="p0pack")
    resp = client.post(
        "/characters/", json={"name": "Tatiana", "species": "vampire"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    resp = client.post(
        f"/characters/{cid}/dna",
        json={
            "species": "vampire",
            "gender_presentation": "female",
            "visual_traits_json": {
                "personality_traits": ["Cunning"],
                "identity_spec": {
                    "style": "realistic",
                    "gender": "female",
                    "age_band": "26-35",
                    "species": "vampire",
                    "species_tells": [],
                    "eye_spacing": "close_set",
                    "hairline_type": "receding",
                    "identity": {"hair_color": "Black", "eye_color": "Green"},
                },
            },
            "structural_profile_json": {"age_band": "26-35"},
        },
        headers=auth_headers(token),
    )
    assert resp.status_code in (200, 201), resp.text

    db = TestingSessionLocal()
    try:
        char = db.query(Character).filter(Character.id == cid).one()
        canon: CharacterIdentityCanon = get_or_create_canon(cid, db)
        identity = founder_identity_from_character(char, canon, db)
    finally:
        db.close()

    assert identity.face_description is not None
    assert "vampire character" in identity.face_description
    assert "close set eyes" in identity.face_description
    assert "receding hairline" in identity.face_description
    assert identity.gender == "female"
    assert identity.age_band == "26-35"

"""S24AN — v2 canon pack generation in the creation flow.

Verifies the self-serve POST /identity-canon/generate-v2-pack endpoint:
  * generates all 13 v2 canon slots (mocked provider — no real spend),
  * does NOT lock (locking is the explicit Dossier step),
  * does NOT create any legacy 4-anchor images,
  * dry-run plans without writing,
  * face/body lock succeeds afterwards,
  * pre-existing (legacy) locked canons still load.
"""
import json

import pytest

from tests.canon_test_utils import stub_png_bytes, setup_canon
from app.models.character import Character
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.character_image import CharacterImage, ImageKindEnum
from app.services import canon_service as cs


FACE_SLOTS = ["face_front", "face_left_3q", "face_right_3q", "face_profile", "face_expression"]
BODY_SLOTS = ["body_front", "body_left", "body_right", "body_back",
              "torso_front", "torso_side", "standing_relaxed", "seated_relaxed"]
ALL_SLOTS = FACE_SLOTS + BODY_SLOTS


class _FakeProvider:
    """Returns valid stub PNG bytes for every generation entry point."""
    provider_name = "fake"
    supports_multi_image_input = True

    def generate_with_anchors(self, prompt, anchor_images):
        return stub_png_bytes()

    def generate_grounded_image(self, prompt, reference_image_bytes):
        return stub_png_bytes()

    def generate_image(self, prompt):
        return stub_png_bytes()


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Force local-disk storage so save/load/stub helpers stay on the filesystem."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


@pytest.fixture
def _mock_providers(monkeypatch):
    fake = _FakeProvider()
    import app.services.canon_card_generator as ccg
    import app.services.image_provider as ip
    monkeypatch.setattr(ccg, "get_provider_for_option", lambda opt: fake)
    monkeypatch.setattr(ccg, "get_fallback_provider", lambda: fake)
    monkeypatch.setattr(ip, "get_provider_for_option", lambda opt: fake)
    monkeypatch.setattr(ip, "get_fallback_provider", lambda: fake)
    return fake


def _create_character(authed_client, db_session, name="Tessa"):
    resp = authed_client.post("/characters/", json={"name": name, "species": "human"})
    assert resp.status_code in (200, 201), resp.text
    cid = resp.json()["id"]
    # Give it a minimal identity spec so the preamble has description text.
    char = db_session.query(Character).get(cid)
    char.identity_spec_json = json.dumps({
        "gender": "female", "age_band": "26-35",
        "identity": {"hair_color": "auburn", "hair_length": "long",
                     "eye_color": "green", "skin_tone": "fair", "face_features": ["high cheekbones"]},
        "build": {"body_type": "athletic", "height_band": "tall"},
    })
    db_session.commit()
    return cid


def test_generate_v2_pack_populates_all_13_slots(authed_client, db_session, _mock_providers):
    cid = _create_character(authed_client, db_session)

    resp = authed_client.post(
        f"/characters/{cid}/identity-canon/generate-v2-pack",
        json={"dry_run": False, "max_spend": 8},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Response carries all 13 cards, each with a URL.
    assert len(data["cards"]) == 13
    slots = {c["slot"]: c for c in data["cards"]}
    assert set(slots) == set(ALL_SLOTS)
    for slot in ALL_SLOTS:
        assert slots[slot]["url"], f"{slot} has no url"
        assert slots[slot]["status"] in ("generated", "skipped")
    assert data["stopped"] is None

    # Canon storage actually populated for all 13 slots.
    db_session.expire_all()
    canon = db_session.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == cid).first()
    face = cs.load_face_canon(canon)
    body = cs.load_body_canon(canon)
    for slot in FACE_SLOTS:
        field = "face_front_image_url" if slot == "face_front" else f"{slot}_image_url"
        assert getattr(face, field), f"face slot {slot} empty"
    for slot in BODY_SLOTS:
        assert getattr(body, f"{slot}_image_url"), f"body slot {slot} empty"

    # Endpoint does NOT lock — that's the explicit Dossier step.
    assert canon.face_locked is False
    assert canon.body_locked is False


def test_generate_v2_pack_creates_no_legacy_anchors(authed_client, db_session, _mock_providers):
    cid = _create_character(authed_client, db_session, name="NoAnchors")
    authed_client.post(
        f"/characters/{cid}/identity-canon/generate-v2-pack",
        json={"dry_run": False, "max_spend": 8},
    )
    # No legacy 4-anchor images should exist — the bridge path is not used.
    anchor_kinds = [ImageKindEnum.ANCHOR_FRONT, ImageKindEnum.ANCHOR_THREE_QUARTER,
                    ImageKindEnum.ANCHOR_TORSO, ImageKindEnum.ANCHOR_FULL_BODY]
    anchors = db_session.query(CharacterImage).filter(
        CharacterImage.character_id == cid,
        CharacterImage.kind.in_(anchor_kinds),
    ).count()
    assert anchors == 0


def test_generate_v2_pack_dry_run_writes_nothing(authed_client, db_session, _mock_providers):
    cid = _create_character(authed_client, db_session, name="DryRun")
    resp = authed_client.post(
        f"/characters/{cid}/identity-canon/generate-v2-pack",
        json={"dry_run": True, "max_spend": 8},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["dry_run"] is True
    assert len(data["cards"]) == 13
    assert all(c["status"] == "planned" for c in data["cards"])
    assert data["total_spend"] == 0
    assert data.get("estimated_cost") is not None

    # No slots written.
    canon = db_session.query(CharacterIdentityCanon).filter(
        CharacterIdentityCanon.character_id == cid).first()
    if canon:
        face = cs.load_face_canon(canon)
        assert face is None or not face.face_front_image_url


def test_lock_succeeds_after_v2_pack(authed_client, db_session, _mock_providers):
    cid = _create_character(authed_client, db_session, name="Lockable")
    authed_client.post(
        f"/characters/{cid}/identity-canon/generate-v2-pack",
        json={"dry_run": False, "max_spend": 8},
    )
    r1 = authed_client.post(f"/characters/{cid}/identity-canon/face/lock")
    r2 = authed_client.post(f"/characters/{cid}/identity-canon/body/lock")
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r2.json()["face_locked"] is True
    assert r2.json()["body_locked"] is True
    assert r2.json()["status"] == "locked"


def test_legacy_locked_canon_still_loads(authed_client, db_session):
    """A pre-existing legacy-style canon (front anchors only) must still load."""
    cid = _create_character(authed_client, db_session, name="LegacyChar")
    setup_canon(db_session, cid, lock=True, with_images=True)  # legacy: front face/body only
    resp = authed_client.get(f"/characters/{cid}/identity-canon")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["face_locked"] is True
    assert body["body_locked"] is True
    assert body["face_canon"]["face_front_image_url"]
    # The v2-only slots are simply absent/None on a legacy canon — no error.
    assert body["face_canon"].get("face_profile_image_url") in (None, "")

"""Adult Studio Phase 2, Sprint 1 — bridge legacy flow onto AdultIdentityModel.

Covers the Sprint 1 acceptance criteria:
  - prepare route drives prepare_adult_identity() → new AdultIdentityModel.
  - status is served from AdultIdentityModel with the additive Phase 2 fields.
  - legacy 'ready' maps to new 'prepared' (NOT 'ready') on backfill.
  - train/generate return 409 while disabled, with NO provider constructed.
  - the legacy adult_studio_identities table is left untouched (no writes).

No provider, no training, no generation, no external call, no canon writes.
"""
from unittest.mock import patch

from app.core.config import settings
from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from app.models.adult_studio import AdultStudioIdentity
from app.services.adult_identity_preparation import prepare_adult_identity
from app.services.adult_identity_backfill import (
    LEGACY_TO_NEW_STATUS,
    backfill_all,
    backfill_legacy_identity,
    map_legacy_status,
)
from tests.conftest import auth_headers, get_auth_token, make_admin
from tests.canon_test_utils import setup_canon


def _login(client, email="p2@test.com", username="p2user") -> str:
    token = get_auth_token(client, email=email, username=username)
    # S24D FIX 2: Adult Studio is admin-only; promote the test actor to admin.
    make_admin(email)
    return token


def _create_character(client, token, name="Summer") -> int:
    resp = client.post(
        "/characters/",
        json={"name": name, "visibility": "public"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _summer_marks() -> list[dict]:
    return [
        {
            "label": "Butterfly floral sleeve",
            "type": "tattoo",
            "body_region": "right_upper_arm",
            "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
        },
        {
            "label": "Black-and-white ballerina tattoo",
            "type": "tattoo",
            "body_region": "left_forearm",
            "side": "left",
            "description": "Left forearm black-and-white ballerina tattoo",
            "reference_image_url": "static/generated/mark_left.png",
        },
    ]


# ── Prepare drives the new system ──────────────────────────────────────────


def test_prepare_creates_adult_identity_model(client, db_session):
    """prepare route persists an AdultIdentityModel via prepare_adult_identity()."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    resp = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text

    model = (
        db_session.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == cid)
        .first()
    )
    assert model is not None
    assert model.status == "prepared"
    assert model.canon_fingerprint
    assert model.prepared_manifest_json  # manifest persisted for training-pack/refs


def test_prepare_leaves_legacy_table_untouched(client, db_session):
    """No row is written to the legacy adult_studio_identities table."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    legacy = (
        db_session.query(AdultStudioIdentity)
        .filter(AdultStudioIdentity.character_id == cid)
        .first()
    )
    assert legacy is None  # bridge writes only the new table


def test_prepare_idempotent_and_stale_on_canon_change(client, db_session):
    """Re-prepare with unchanged canon stays 'prepared'; a canon change → 'stale'."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    r1 = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    fp1 = r1.json()["canon_fingerprint"]
    r2 = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert r2.json()["status"] == "prepared"
    assert r2.json()["canon_fingerprint"] == fp1  # unchanged canon → same fingerprint

    # Mutate canon (add a mark) → next prepare flips to stale.
    from app.services import canon_service as cs
    from app.schemas.canon import AddPermanentMarkRequest

    canon = cs.get_or_create_canon(cid, db_session)
    cs.add_permanent_mark(
        canon,
        AddPermanentMarkRequest(
            label="New star", type="tattoo", body_region="left_shoulder", side="left",
            description="small star", reference_image_url="static/generated/star.png",
        ),
    )
    db_session.commit()

    r3 = client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))
    assert r3.json()["status"] == "stale"
    assert r3.json()["stale"] is True
    assert r3.json()["canon_fingerprint"] != fp1


# ── Train / generate gated OFF (409, no provider) ──────────────────────────


def test_train_disabled_returns_409(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    assert settings.ADULT_STUDIO_TRAINING_ENABLED is False
    resp = client.post(f"/adult-studio/characters/{cid}/train", headers=auth_headers(token))
    assert resp.status_code == 409, resp.text
    assert "disabled" in resp.json()["detail"].lower()


def test_generate_disabled_constructs_no_provider(client, db_session):
    """Generate is 409 while disabled and never touches the provider factory."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    assert settings.ADULT_STUDIO_GENERATION_ENABLED is False
    with patch("app.api.routes.adult_studio._get_adult_provider") as prov, \
         patch("app.services.image_provider.get_identity_provider_by_name") as factory:
        resp = client.post(
            f"/adult-studio/characters/{cid}/generate",
            json={"prompt": "Summer on a beach in a yellow bikini, adult woman"},
            headers=auth_headers(token),
        )
    assert resp.status_code == 409, resp.text
    prov.assert_not_called()
    factory.assert_not_called()


# ── Status response shape ──────────────────────────────────────────────────


def test_status_exposes_phase2_fields(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    client.post(f"/adult-studio/characters/{cid}/prepare", headers=auth_headers(token))

    resp = client.get(f"/adult-studio/characters/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for field in (
        "status", "canon_fingerprint", "stale", "marks",
        "training_enabled", "generation_enabled",
    ):
        assert field in data, f"missing {field}"
    assert data["training_enabled"] is False
    assert data["generation_enabled"] is False
    assert data["stale"] is False
    # Mark routes carry id/region/side/route.
    assert len(data["marks"]) == 2
    for m in data["marks"]:
        assert m["canon_mark_id"]
        assert m["route"]


def test_status_not_prepared_echoes_flags(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)  # locked but not prepared

    resp = client.get(f"/adult-studio/characters/{cid}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "not_trained"
    assert data["training_enabled"] is False
    assert data["generation_enabled"] is False
    assert data["marks"] == []


# ── Legacy → new backfill mapping ──────────────────────────────────────────


def test_status_map_legacy_ready_to_prepared():
    """The crux: legacy 'ready' (manifest-only) maps to new 'prepared', not 'ready'."""
    assert map_legacy_status("ready") == "prepared"
    assert map_legacy_status("not_trained") == "not_trained"
    assert map_legacy_status("preparing") == "not_trained"
    assert map_legacy_status("failed") == "failed"
    assert map_legacy_status(None) == "not_trained"
    assert LEGACY_TO_NEW_STATUS["ready"] == "prepared"


def test_backfill_legacy_ready_becomes_prepared(client, db_session):
    """A legacy 'ready' row backfills into a new model with status 'prepared'."""
    token = _login(client)
    cid = _create_character(client, token, name="Summer Fielding")

    legacy = AdultStudioIdentity(
        character_id=cid, status="ready", provider="openai",
        model_ref="gpt-image-1.5",
        training_notes_json={"refs": [{"role": "face_front", "url": "x.png"}], "marks": []},
    )
    db_session.add(legacy)
    db_session.commit()

    model = backfill_legacy_identity(legacy, db_session)
    db_session.commit()

    assert model.status == "prepared"  # NOT 'ready'
    assert model.character_id == cid
    assert model.trigger_token == "ficsummerfielding"
    # Legacy manifest carried over so training-pack keeps working post-cutover.
    assert model.prepared_manifest_json == legacy.training_notes_json
    # Legacy row is untouched.
    assert legacy.status == "ready"


def test_backfilled_row_then_prepare_stays_prepared_not_stale(client, db_session):
    """Mirrors the live Summer flow: as03 backfill creates a 'prepared' model with a
    NULL fingerprint and no mark renders; the subsequent prepare must keep it
    'prepared' (NOT flip it to 'stale') while filling in fingerprint + mark routes.
    """
    token = _login(client)
    cid = _create_character(client, token, name="Summer Fielding")
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)

    # Simulate the as03 bulk-insert: a 'prepared' model with NULL fingerprint, no marks.
    model = AdultIdentityModel(
        character_id=cid, status="prepared", canon_fingerprint=None,
        prepared_manifest_json={"refs": [{"role": "face_front", "url": "x.png"}]},
    )
    db_session.add(model)
    db_session.commit()

    res = prepare_adult_identity(cid, db_session)

    db_session.refresh(model)
    assert model.status == "prepared"          # NOT 'stale' on first fingerprinting
    assert res.model_status == "prepared"
    assert model.canon_fingerprint            # fingerprint now present

    renders = (
        db_session.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model.id)
        .all()
    )
    routes = {(r.body_region, r.route) for r in renders}
    assert len(renders) == 2
    assert ("right_upper_arm", "ip_adapter") in routes      # butterfly floral sleeve
    assert ("left_forearm", "controlnet_canny") in routes   # ballerina
    assert model.active_version_id is None                  # nothing trained


def test_backfilled_not_trained_promoted_to_prepared(client, db_session):
    """A backfilled 'not_trained' row (NULL fingerprint) becomes 'prepared' on prepare."""
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, lock=True, with_images=True)
    model = AdultIdentityModel(character_id=cid, status="not_trained", canon_fingerprint=None)
    db_session.add(model)
    db_session.commit()

    prepare_adult_identity(cid, db_session)
    db_session.refresh(model)
    assert model.status == "prepared"
    assert model.canon_fingerprint


def test_backfill_all_is_idempotent(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    legacy = AdultStudioIdentity(character_id=cid, status="ready")
    db_session.add(legacy)
    db_session.commit()

    created_first = backfill_all(db_session)
    created_second = backfill_all(db_session)
    assert created_first == 1
    assert created_second == 0  # nothing new on rerun

    models = (
        db_session.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == cid)
        .all()
    )
    assert len(models) == 1

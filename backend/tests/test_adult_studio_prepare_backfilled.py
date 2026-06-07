"""Tests for the Adult Studio backfill-preparation management command.

Covers the Phase 2 Sprint 3 acceptance: dry-run writes nothing; a Summer-style
backfilled row becomes 'prepared' with a fingerprint + mark renders; reruns do not
duplicate rows; the --character-id filter is honoured; and a canon-not-ready row is
reported as failed without crashing the batch.

No provider, training, generation, or external call — prepare reads canon read-only.
"""
from scripts.adult_studio_prepare_backfilled import prepare_backfilled

from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from tests.conftest import auth_headers, get_auth_token
from tests.canon_test_utils import setup_canon


def _login(client, email="bf@test.com", username="bfuser") -> str:
    return get_auth_token(client, email=email, username=username)


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
            "label": "Butterfly floral sleeve", "type": "tattoo",
            "body_region": "right_upper_arm", "side": "right",
            "description": "Right upper arm butterfly and floral sleeve tattoo",
            "reference_image_url": "static/generated/mark_right.png",
        },
        {
            "label": "Black-and-white ballerina tattoo", "type": "tattoo",
            "body_region": "left_forearm", "side": "left",
            "description": "Left forearm black-and-white ballerina tattoo",
            "reference_image_url": "static/generated/mark_left.png",
        },
    ]


def _backfilled_model(db, character_id: int) -> AdultIdentityModel:
    """A model in the exact post-as03 state: prepared, NULL fingerprint, no renders."""
    model = AdultIdentityModel(
        character_id=character_id, status="prepared", canon_fingerprint=None,
        prepared_manifest_json={"refs": [{"role": "face_front", "url": "x.png"}]},
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def _renders(db, model_id: int):
    return (
        db.query(AdultIdentityMarkRender)
        .filter(AdultIdentityMarkRender.identity_id == model_id)
        .all()
    )


# ── Dry run ────────────────────────────────────────────────────────────────


def test_dry_run_changes_nothing(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    model = _backfilled_model(db_session, cid)

    summary = prepare_backfilled(db_session, dry_run=True)

    assert summary.dry_run is True
    assert cid in summary.would_process
    assert summary.processed == []          # nothing actually processed
    db_session.refresh(model)
    assert model.canon_fingerprint is None  # unchanged
    assert _renders(db_session, model.id) == []


# ── Summer-style preparation ────────────────────────────────────────────────


def test_backfilled_row_becomes_prepared_with_fingerprint_and_renders(client, db_session):
    token = _login(client)
    cid = _create_character(client, token, name="Summer Fielding")
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    model = _backfilled_model(db_session, cid)

    summary = prepare_backfilled(db_session)

    assert cid in summary.processed
    assert summary.failed == []
    db_session.refresh(model)
    assert model.status == "prepared"        # not 'stale'
    assert model.canon_fingerprint           # populated
    assert model.active_version_id is None    # nothing trained

    renders = _renders(db_session, model.id)
    routes = {(r.body_region, r.route) for r in renders}
    assert len(renders) == 2
    assert ("right_upper_arm", "ip_adapter") in routes
    assert ("left_forearm", "controlnet_canny") in routes


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_rerun_does_not_duplicate_rows(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    setup_canon(db_session, cid, marks=_summer_marks(), lock=True, with_images=True)
    model = _backfilled_model(db_session, cid)

    first = prepare_backfilled(db_session)
    assert cid in first.processed

    second = prepare_backfilled(db_session)
    # Second run finds nothing to do — already prepared.
    assert cid not in second.processed
    assert second.processed == []

    models = (
        db_session.query(AdultIdentityModel)
        .filter(AdultIdentityModel.character_id == cid)
        .all()
    )
    assert len(models) == 1
    assert len(_renders(db_session, model.id)) == 2  # no duplicate renders


# ── --character-id filter ────────────────────────────────────────────────────


def test_character_id_filter_only_touches_target(client, db_session):
    # One character per account → two accounts for two characters.
    token_a = _login(client, email="alpha@test.com", username="alphauser")
    token_b = _login(client, email="beta@test.com", username="betauser")
    cid_a = _create_character(client, token_a, name="Alpha")
    cid_b = _create_character(client, token_b, name="Beta")
    setup_canon(db_session, cid_a, marks=_summer_marks(), lock=True, with_images=True)
    setup_canon(db_session, cid_b, marks=_summer_marks(), lock=True, with_images=True)
    model_a = _backfilled_model(db_session, cid_a)
    model_b = _backfilled_model(db_session, cid_b)

    summary = prepare_backfilled(db_session, character_id=cid_a)

    assert summary.processed == [cid_a]
    db_session.refresh(model_a)
    db_session.refresh(model_b)
    assert model_a.canon_fingerprint is not None   # A prepared
    assert model_b.canon_fingerprint is None       # B untouched
    assert _renders(db_session, model_b.id) == []


def test_character_id_missing_model_is_reported_not_crash(client, db_session):
    summary = prepare_backfilled(db_session, character_id=999999)
    assert summary.processed == []
    assert any(cid == 999999 for cid, _ in summary.failed)


# ── Canon not ready ──────────────────────────────────────────────────────────


def test_canon_not_ready_reported_as_failed_without_crash(client, db_session):
    token = _login(client)
    cid = _create_character(client, token)
    # Canon present but NOT locked → prepare raises CanonNotReadyError.
    setup_canon(db_session, cid, marks=_summer_marks(), lock=False, with_images=True)
    model = _backfilled_model(db_session, cid)

    summary = prepare_backfilled(db_session)  # must not raise

    assert cid not in summary.processed
    assert any(c == cid for c, _ in summary.failed)
    db_session.refresh(model)
    assert model.canon_fingerprint is None  # left unprepared, no partial write

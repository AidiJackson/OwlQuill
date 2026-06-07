"""Sprint 3 tests — Adult Studio preparation persistence.

No image generation, no training, no providers, no RunPod. Uses Summer's corrected
canon (right upper arm butterfly/floral sleeve; left forearm black-and-white ballerina)
built via the shared setup_canon helper.
"""
from app.models.adult_identity import AdultIdentityMarkRender, AdultIdentityModel
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services import canon_service as cs
from app.services.adult_identity_preparation import prepare_adult_identity
from tests.canon_test_utils import setup_canon

CID = 60
R2 = "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated"

SUMMER_MARKS = [
    {
        "label": "Butterfly floral sleeve", "type": "tattoo",
        "body_region": "Right upper arm", "side": "right",
        "description": "Right upper arm butterfly and floral sleeve tattoo",
        "reference_image_url": f"{R2}/49a155d1a8834e71885105519cfaab3e.png",
    },
    {
        "label": "Black-and-white ballerina tattoo", "type": "tattoo",
        "body_region": "Left forearm", "side": "left",
        "description": "Left forearm black-and-white ballerina tattoo",
        "reference_image_url": f"{R2}/efd8bd5522af4be2a8f155647b43b64c.png",
    },
]


def _prep_summer(db):
    setup_canon(db, CID, marks=SUMMER_MARKS, lock=True, with_images=True)
    return prepare_adult_identity(CID, db)


def _renders(db, model_id):
    return db.query(AdultIdentityMarkRender).filter_by(identity_id=model_id).all()


def _route_by_region(db, model_id):
    return {r.body_region: r.route for r in _renders(db, model_id)}


def test_creates_model_if_missing(db_session):
    db = db_session
    assert db.query(AdultIdentityModel).filter_by(character_id=CID).first() is None
    res = _prep_summer(db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    assert model is not None
    assert res.model_status == "prepared" and model.status == "prepared"
    assert res.mark_count == 2


def test_stores_fingerprint(db_session):
    db = db_session
    res = _prep_summer(db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    assert res.fingerprint == model.canon_fingerprint
    assert len(res.fingerprint) == 64 and all(c in "0123456789abcdef" for c in res.fingerprint)


def test_stores_two_mark_renders(db_session):
    db = db_session
    _prep_summer(db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    rows = _renders(db, model.id)
    assert len(rows) == 2
    # reason persisted in params_json (no dedicated column)
    for r in rows:
        assert r.params_json and "reason" in r.params_json
        assert r.mark_fingerprint and r.reference_uri


def test_butterfly_routes_ip_adapter(db_session):
    db = db_session
    _prep_summer(db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    assert _route_by_region(db, model.id)["Right upper arm"] == "ip_adapter"


def test_ballerina_routes_controlnet_canny(db_session):
    db = db_session
    _prep_summer(db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    assert _route_by_region(db, model.id)["Left forearm"] == "controlnet_canny"


def test_rerun_is_idempotent_no_duplicate_rows(db_session):
    db = db_session
    _prep_summer(db)
    res2 = prepare_adult_identity(CID, db)  # rerun, unchanged canon
    models = db.query(AdultIdentityModel).filter_by(character_id=CID).all()
    assert len(models) == 1
    assert len(_renders(db, models[0].id)) == 2
    assert res2.model_status == "prepared"  # unchanged canon → not stale


def test_metadata_change_causes_stale_state(db_session):
    db = db_session
    res1 = _prep_summer(db)
    assert res1.model_status == "prepared"

    # Edit a mark description in canon (mirrors the truth-metadata scenario).
    canon = db.query(CharacterIdentityCanon).filter_by(character_id=CID).first()
    body = cs.load_body_canon(canon)
    body.permanent_body_marks[1].description = "Left forearm colour ballerina tattoo"
    cs._save_body(canon, body)
    db.commit()

    res2 = prepare_adult_identity(CID, db)
    model = db.query(AdultIdentityModel).filter_by(character_id=CID).first()
    assert res2.fingerprint != res1.fingerprint
    assert res2.model_status == "stale" and model.status == "stale"
    # still exactly two renders (no duplication on the rerun)
    assert len(_renders(db, model.id)) == 2

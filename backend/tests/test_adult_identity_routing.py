"""Sprint 2 tests — canon fingerprinting + deterministic mark routing.

Pure logic: no DB, no GPU, no providers, no canon writes. Uses Summer Fielding's
corrected canon metadata (right upper arm butterfly/floral sleeve; left forearm
black-and-white ballerina).
"""
from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.adult_identity_fingerprint import canon_fingerprint, mark_fingerprint
from app.services.adult_identity_routing import resolve_mark_route, resolve_marks

R2 = "https://pub-2cb664acb0474ef1b96cb149469a11bc.r2.dev/generated"


def _summer_butterfly():
    return PermanentBodyMark(
        id="pbm_8cff990d", label="Butterfly floral sleeve", type="tattoo",
        body_region="Right upper arm", side="right",
        description="Right upper arm butterfly and floral sleeve tattoo",
        reference_image_url=f"{R2}/49a155d1a8834e71885105519cfaab3e.png",
    )


def _summer_ballerina():
    return PermanentBodyMark(
        id="pbm_de30011b", label="Black-and-white ballerina tattoo", type="tattoo",
        body_region="Left forearm", side="left",
        description="Left forearm black-and-white ballerina tattoo",
        reference_image_url=f"{R2}/efd8bd5522af4be2a8f155647b43b64c.png",
    )


# ── Routing ──────────────────────────────────────────────────────────────────

def test_butterfly_floral_sleeve_routes_ip_adapter():
    plan = resolve_mark_route(_summer_butterfly())
    assert plan.route == "ip_adapter"
    assert plan.canon_mark_id == "pbm_8cff990d"
    assert plan.region == "Right upper arm"
    assert plan.side == "right"
    assert "sleeve" in plan.reason
    assert plan.reference_url.endswith("49a155d1a8834e71885105519cfaab3e.png")


def test_ballerina_routes_controlnet_canny():
    plan = resolve_mark_route(_summer_ballerina())
    assert plan.route == "controlnet_canny"
    assert plan.region == "Left forearm"
    assert plan.side == "left"
    assert "ballerina" in plan.reason


def test_scar_and_birthmark_route_inpaint_direct():
    scar = PermanentBodyMark(label="Forearm scar", type="scar", body_region="Left forearm",
                             side="left", description="thin white scar")
    birth = PermanentBodyMark(label="Cheek birthmark", type="birthmark", body_region="Right cheek",
                              side="right", description="small brown birthmark")
    assert resolve_mark_route(scar).route == "inpaint_direct"
    assert resolve_mark_route(birth).route == "inpaint_direct"
    assert "inpaint_direct" in resolve_mark_route(scar).reason


def test_unknown_design_falls_back_to_ip_adapter():
    mark = PermanentBodyMark(label="Mystery mark", type="tattoo", body_region="Chest",
                             side="centre", description="an undescribed mark")
    plan = resolve_mark_route(mark)
    assert plan.route == "ip_adapter"
    assert "fallback" in plan.reason


def test_figural_symbol_routes_controlnet_canny():
    mark = PermanentBodyMark(label="Anchor", type="tattoo", body_region="Right forearm",
                             side="right", description="small anchor symbol")
    assert resolve_mark_route(mark).route == "controlnet_canny"


def test_reference_url_prefers_detail_crop():
    mark = PermanentBodyMark(label="x", type="tattoo", body_region="Chest", side="centre",
                             description="floral pattern",
                             reference_image_url="https://x/ref.png",
                             detail_crop_url="https://x/crop.png")
    assert resolve_mark_route(mark).reference_url == "https://x/crop.png"


def test_resolve_marks_preserves_order_and_routes():
    plans = resolve_marks([_summer_butterfly(), _summer_ballerina()])
    assert [p.route for p in plans] == ["ip_adapter", "controlnet_canny"]


# ── Fingerprint ──────────────────────────────────────────────────────────────

def test_mark_fingerprint_changes_when_description_changes():
    base = _summer_ballerina()
    changed = _summer_ballerina()
    changed.description = "Left forearm RED ballerina tattoo"
    assert mark_fingerprint(base) != mark_fingerprint(changed)


def test_mark_fingerprint_stable_under_key_order():
    a = {"id": "pbm_1", "type": "tattoo", "body_region": "Left forearm", "side": "left",
         "label": "Ballerina", "description": "ballerina", "reference_image_url": "u",
         "detail_crop_url": None}
    b = {"detail_crop_url": None, "description": "ballerina", "label": "Ballerina",
         "side": "left", "body_region": "Left forearm", "type": "tattoo",
         "reference_image_url": "u", "id": "pbm_1"}
    assert mark_fingerprint(a) == mark_fingerprint(b)


def test_canon_fingerprint_changes_when_a_mark_description_changes():
    face = FaceCanonData(face_description="athletic blonde, blue eyes")
    body1 = BodyCanonData(build="athletic",
                          permanent_body_marks=[_summer_butterfly(), _summer_ballerina()])
    edited = _summer_ballerina()
    edited.description = "Left forearm colour ballerina tattoo"
    body2 = BodyCanonData(build="athletic",
                          permanent_body_marks=[_summer_butterfly(), edited])
    assert canon_fingerprint(face, body1) != canon_fingerprint(face, body2)


def test_canon_fingerprint_stable_under_mark_order_and_key_order():
    face = FaceCanonData(face_description="athletic blonde, blue eyes")
    body_ab = BodyCanonData(build="athletic",
                            permanent_body_marks=[_summer_butterfly(), _summer_ballerina()])
    body_ba = BodyCanonData(build="athletic",
                            permanent_body_marks=[_summer_ballerina(), _summer_butterfly()])
    # mark ordering must not change the fingerprint (marks are sorted internally)
    assert canon_fingerprint(face, body_ab) == canon_fingerprint(face, body_ba)
    # 64-hex sha256
    fp = canon_fingerprint(face, body_ab)
    assert len(fp) == 64 and all(c in "0123456789abcdef" for c in fp)

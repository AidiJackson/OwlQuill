"""Mark detail cards — high-fidelity close-up references for permanent marks.

Tattoos previously lived only inside holistic body cards (body_front/body_map/
final_card), where the geometry is small and semantically weak. Each permanent
mark can now carry a dedicated close-up `detail_crop_url` (preferred over the
general `reference_image_url`). When the mark's region is EXPOSED, the router
splices that detail crop in as a fidelity aid — P15b order, unchanged:

    face > body_front > body_map > mark_detail_crop(s) > final_card

Clothing truth stays dominant: a covered mark routes NO detail crop, and the
compiled prompt still asserts clothing truth. These are fidelity aids, never
visibility overrides.
"""
import json

from unittest.mock import MagicMock

from app.services.scene_router import route_canon_refs
from app.services.canon_compiler import compile_canon_prompt

# Canon slot URLs (full fixture).
FACE_FRONT = "https://cdn/face_front.png"
FACE_L3Q = "https://cdn/face_l3q.png"
FACE_R3Q = "https://cdn/face_r3q.png"
BODY_FRONT = "https://cdn/body_front.png"
BODY_MAP = "https://cdn/body_map.png"
FINAL_CARD = "https://cdn/final_card.png"

# Per-mark detail crops (the new high-fidelity cards).
SLEEVE_DETAIL = "https://cdn/detail/left_sleeve_lettering.png"
WOLF_DETAIL = "https://cdn/detail/right_wolf_geometry.png"


def _canon_with_marks(marks):
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import FaceCanonData, BodyCanonData

    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 1001
    face = FaceCanonData(
        face_front_image_url=FACE_FRONT,
        face_left_3q_image_url=FACE_L3Q,
        face_right_3q_image_url=FACE_R3Q,
    )
    body = BodyCanonData(
        body_front_image_url=BODY_FRONT,
        body_map_image_url=BODY_MAP,
        final_character_card_image_url=FINAL_CARD,
        permanent_body_marks=marks,
    )
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = None
    return canon


def _leo_marks():
    """Asymmetric pair, each with a dedicated detail crop."""
    from app.schemas.canon import PermanentBodyMark
    return [
        PermanentBodyMark(
            label="Left gothic script sleeve", type="tattoo",
            body_region="left_full_arm", side="left",
            description="gothic blackletter script sleeve",
            detail_crop_url=SLEEVE_DETAIL,
        ),
        PermanentBodyMark(
            label="Right arm tribal wolf", type="tattoo",
            body_region="right_upper_arm", side="right",
            description="howling wolf head, fine linework",
            detail_crop_url=WOLF_DETAIL,
        ),
    ]


# ── The four required regression cases ────────────────────────────────


class TestMarkDetailRouting:

    def test_rolled_sleeve_routes_forearm_detail_only_wolf_hidden(self):
        """Rolled sleeve: the forearm sleeve detail crop routes; the covered
        upper-arm wolf detail does NOT."""
        urls, meta = route_canon_refs(
            "kitchen, button-up shirt with sleeves rolled to the forearms",
            _canon_with_marks(_leo_marks()),
        )
        assert SLEEVE_DETAIL in urls
        assert WOLF_DETAIL not in urls
        assert meta.mark_crops == 1
        # P15b order preserved: body anchors precede the detail crop.
        slots = meta.route_slots
        assert slots.index("body_front") < slots.index("mark_crop")
        assert slots.index("body_map") < slots.index("mark_crop")

    def test_short_sleeve_routes_exposed_forearm_not_covered_upper_arm(self):
        """Short sleeve exposes the forearm (sleeve detail routed) but covers the
        upper-arm wolf — its detail is gated out ('routed only if exposed')."""
        urls, meta = route_canon_refs(
            "wearing a short-sleeve shirt", _canon_with_marks(_leo_marks()),
        )
        assert SLEEVE_DETAIL in urls
        assert WOLF_DETAIL not in urls

    def test_formal_shirt_routes_no_detail_cards(self):
        """Formal suit covers both arms → no mark detail cards routed at all."""
        urls, meta = route_canon_refs(
            "wearing a formal suit and tie at a gala dinner",
            _canon_with_marks(_leo_marks()),
        )
        assert SLEEVE_DETAIL not in urls
        assert WOLF_DETAIL not in urls
        assert meta.mark_crops == 0

    def test_sleeveless_routes_both_detail_cards(self):
        """Sleeveless exposes both arms → both detail crops route."""
        urls, meta = route_canon_refs(
            "facing camera in a sleeveless tank top, arms visible",
            _canon_with_marks(_leo_marks()),
        )
        assert SLEEVE_DETAIL in urls
        assert WOLF_DETAIL in urls
        assert meta.mark_crops == 2
        # Detail crops sit ahead of the holistic final card (P15b).
        slots = meta.route_slots
        assert slots.index("mark_crop") < slots.index("final_character_card")


# ── Detail preferred over general reference; graceful fallback ────────


class TestDetailPreferenceAndFallback:

    def test_detail_crop_preferred_over_reference_image(self):
        from app.schemas.canon import PermanentBodyMark
        mark = PermanentBodyMark(
            label="Right arm wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf",
            reference_image_url="https://cdn/general_ref.png",
            detail_crop_url=WOLF_DETAIL,
        )
        urls, _ = route_canon_refs(
            "sleeveless tank top, arms visible", _canon_with_marks([mark]),
        )
        assert WOLF_DETAIL in urls
        assert "https://cdn/general_ref.png" not in urls

    def test_falls_back_to_reference_when_no_detail(self):
        from app.schemas.canon import PermanentBodyMark
        mark = PermanentBodyMark(
            label="Right arm wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf",
            reference_image_url="https://cdn/general_ref.png",
        )
        urls, meta = route_canon_refs(
            "sleeveless tank top, arms visible", _canon_with_marks([mark]),
        )
        assert "https://cdn/general_ref.png" in urls
        assert meta.mark_crops == 1

    def test_mark_without_any_image_degrades_gracefully(self):
        from app.schemas.canon import PermanentBodyMark
        mark = PermanentBodyMark(
            label="Right arm wolf", type="tattoo", body_region="right_upper_arm",
            side="right", description="wolf",
        )
        urls, meta = route_canon_refs(
            "sleeveless tank top, arms visible", _canon_with_marks([mark]),
        )
        assert meta.mark_crops == 0
        assert BODY_FRONT in urls  # body truth still routes


# ── Clothing truth remains dominant (covered scenes) ──────────────────


class TestClothingTruthUnaffected:

    def test_covered_scene_keeps_clothing_truth_and_routes_no_detail(self):
        canon = _canon_with_marks(_leo_marks())
        prompt = compile_canon_prompt(canon, "wearing a long-sleeve sweater indoors").lower()
        assert "permanent markings obey scene clothing" in prompt
        assert "hidden markings remain hidden" in prompt
        urls, meta = route_canon_refs("wearing a long-sleeve sweater indoors", canon)
        assert meta.mark_crops == 0
        assert SLEEVE_DETAIL not in urls and WOLF_DETAIL not in urls

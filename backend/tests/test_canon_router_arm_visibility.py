"""Canon Router arm-visibility inference — prompt/clothing → exposed arm marks.

Regression target: a generated image showed one arm's tattoo but not the other,
even though the opposite arm was visibly exposed. Cause: the router under-inferred
arm exposure from natural clothing language, and `_mark_region_exposed` ignored
the is_sleeve signal (a mark labelled "... sleeve" on the upper arm was wrongly
suppressed when only the forearm was exposed).

These tests assert the router sends BOTH arm marking refs when both arms are
likely visible (sleeveless / shirtless / rolled sleeves / forearms visible),
and NO arm marks when the arms are covered (suit jacket / long sleeves).

Pure route_canon_refs tests — no provider calls, no DB.
"""
import json
from unittest.mock import MagicMock

from app.services.scene_router import route_canon_refs, _mark_region_exposed

FACE_FRONT = "https://cdn/face_front.png"
BODY_FRONT = "https://cdn/body_front.png"
BODY_MAP = "https://cdn/body_map.png"
FINAL_CARD = "https://cdn/final_card.png"

WOLF = "https://cdn/detail/right_wolf_sleeve.png"
SCRIPT = "https://cdn/detail/left_scripture_sleeve.png"


def _canon_with_marks(marks):
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import FaceCanonData, BodyCanonData

    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.character_id = 7777
    face = FaceCanonData(face_front_image_url=FACE_FRONT)
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


def _sleeve_pair():
    """The two full-arm sleeves: scripture (left) + wolf (right)."""
    from app.schemas.canon import PermanentBodyMark
    return [
        PermanentBodyMark(
            label="Left Arm Scripture Sleeve", type="tattoo",
            body_region="left_full_arm", side="left",
            description="scripture sleeve, black lettering",
            detail_crop_url=SCRIPT,
        ),
        PermanentBodyMark(
            label="Right Arm Wolf Sleeve", type="tattoo",
            body_region="right_full_arm", side="right",
            description="howling wolf sleeve, grey ink",
            detail_crop_url=WOLF,
        ),
    ]


# ── Acceptance scenarios (requirement #5) ─────────────────────────────


class TestBothArmsVisibleSendsBothMarks:

    def test_rolled_up_sleeves_routes_both_arm_marks(self):
        """'blue shirt with sleeves rolled up' → both forearm-exposed sleeves route."""
        urls, meta = route_canon_refs(
            "blue shirt with sleeves rolled up, standing in a kitchen",
            _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF in urls
        assert SCRIPT in urls
        assert meta.mark_crops == 2

    def test_shirtless_routes_both_arm_marks(self):
        urls, meta = route_canon_refs("shirtless on the beach", _canon_with_marks(_sleeve_pair()))
        assert WOLF in urls
        assert SCRIPT in urls
        assert meta.mark_crops == 2

    def test_sleeveless_athletic_top_routes_both_arm_marks(self):
        urls, meta = route_canon_refs(
            "wearing a sleeveless black athletic top", _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF in urls
        assert SCRIPT in urls
        assert meta.mark_crops == 2

    def test_forearms_visible_routes_both_sleeves(self):
        """Natural phrasing without explicit garment — forearm visibility cue."""
        urls, meta = route_canon_refs(
            "standing pose, forearms visible", _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF in urls
        assert SCRIPT in urls
        assert meta.mark_crops == 2

    def test_arms_exposed_routes_both_sleeves(self):
        urls, meta = route_canon_refs(
            "casual stance, arms exposed", _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF in urls
        assert SCRIPT in urls

    def test_relevant_body_card_accompanies_marks(self):
        """The body truth card travels with the exposed mark crops."""
        urls, _ = route_canon_refs("shirtless", _canon_with_marks(_sleeve_pair()))
        assert BODY_FRONT in urls


class TestCoveredArmsSuppressMarks:

    def test_tailored_suit_jacket_routes_no_arm_marks(self):
        urls, meta = route_canon_refs(
            "dark tailored suit jacket at a gala", _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF not in urls
        assert SCRIPT not in urls
        assert meta.mark_crops == 0

    def test_long_sleeve_routes_no_arm_marks(self):
        urls, meta = route_canon_refs(
            "front view, wearing a long-sleeve wool sweater", _canon_with_marks(_sleeve_pair()),
        )
        assert WOLF not in urls
        assert SCRIPT not in urls
        assert meta.mark_crops == 0


# ── Arm extent comes from the REGION, never from label text ───────────
#
# These previously asserted that a mark LABELLED "... sleeve" on the upper arm
# gained forearm exposure. That behaviour is deleted, not narrowed: it was
# proven to cause a real failure. Summer's butterfly piece is upper-arm-only
# per her body-map legend but labelled "Butterfly floral sleeve"; the substring
# widened its anatomy, a rolled-sleeve scene judged it exposed, and the model
# rendered it on her bare forearm. A genuine full sleeve is expressed as a
# full-arm REGION, which is what these now assert.


class TestArmExtentFromStructuredRegion:

    def test_upper_arm_mark_stays_covered_by_rolled_sleeves(self):
        """Rolled/short sleeves bare only the forearm — an upper-arm mark is covered."""
        assert _mark_region_exposed("right_upper_arm", "sleeves rolled up") is False

    def test_full_arm_region_is_exposed_by_rolled_sleeves(self):
        """A true full sleeve reaches the wrist, so its lower portion shows."""
        assert _mark_region_exposed("right_full_arm", "sleeves rolled up") is True

    def test_upper_arm_mark_exposed_when_arm_is_bare(self):
        assert _mark_region_exposed("right_upper_arm", "sleeveless tank top") is True

    def test_full_arm_mark_exposed_when_arm_is_bare(self):
        assert _mark_region_exposed("right_full_arm", "sleeveless tank top") is True

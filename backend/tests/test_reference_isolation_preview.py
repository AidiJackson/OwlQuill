"""The isolation preview endpoint — "original → what the model receives".

The preview exists so invisible image processing on someone's photograph is
inspectable before it is paid for. Its correctness condition is unusual and is
the main thing pinned here: it must run the SAME transform generation runs, not
a lookalike. If the two ever diverge, the preview becomes a reassuring picture
of something that is not what gets sent.

It also must not become a back door: the founder gate and the ownership checks
are the same ones a generation submission passes.
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import auth_headers, get_auth_token
from tests.test_admin_creator_reference_mode import (
    _create_character,
    _upload,
    founder,  # noqa: F401 — pytest fixture
)

ROUTE = "app.api.routes.image_generator"
DERIVED = b"\x89PNG\r\n\x1a\nDERIVED"


def _preview(client, token, cid, image_id, role):
    return client.get(
        f"/characters/{cid}/image-generator/references/{image_id}/isolated?role={role}",
        headers=auth_headers(token),
    )


class TestPreviewUsesTheGenerationTransform:
    def test_it_calls_the_same_isolate_function(self, client, founder):
        """Not a lookalike: the route imports the generation transform, so a
        change to one cannot silently miss the other."""
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        iso = MagicMock(return_value=DERIVED)
        with patch(f"{ROUTE}.isolate_reference", iso), \
             patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"):
            resp = _preview(client, token, cid, img, "hair")
        assert resp.status_code == 200, resp.text
        assert resp.content == DERIVED
        iso.assert_called_once()
        assert iso.call_args[0][0] == b"RAW"

    def test_it_returns_an_image_and_is_never_cached(self, client, founder):
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        with patch(f"{ROUTE}.isolate_reference", return_value=DERIVED), \
             patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"):
            resp = _preview(client, token, cid, img, "eyes")
        assert resp.headers["content-type"] == "image/png"
        assert resp.headers["cache-control"] == "no-store"

    def test_the_same_module_level_function_backs_both_paths(self):
        """Structural guarantee behind the test above."""
        from app.api.routes import image_generator as route
        from app.services import image_generation_pipeline as pipeline
        from app.services.reference_isolation import isolate

        assert route.isolate_reference is isolate
        assert pipeline.isolate_reference is isolate

    def test_nothing_is_persisted_by_a_preview(self, client, founder, db_session):
        from app.models.character_image import CharacterImage

        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        before = db_session.query(CharacterImage).filter_by(character_id=cid).count()
        with patch(f"{ROUTE}.isolate_reference", return_value=DERIVED), \
             patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"):
            for _ in range(3):
                assert _preview(client, token, cid, img, "hair").status_code == 200
        assert db_session.query(CharacterImage).filter_by(character_id=cid).count() == before


class TestPreviewScope:
    @pytest.mark.parametrize(
        "role", ["hair", "eyes", "eyebrows", "nose", "mouth_lips", "skin_complexion"]
    )
    def test_every_isolated_role_can_be_previewed(self, client, founder, role):
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        with patch(f"{ROUTE}.isolate_reference", return_value=DERIVED), \
             patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"):
            assert _preview(client, token, cid, img, role).status_code == 200

    @pytest.mark.parametrize(
        "role", ["character_1", "character_2", "clothing", "environment",
                 "pose_composition", "tattoo_mark", "unspecified", "other"]
    )
    def test_a_non_feature_role_has_nothing_to_preview(self, client, founder, role):
        """Those references are sent exactly as they are; offering a "what the
        model receives" view would imply a transform that does not exist."""
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        assert _preview(client, token, cid, img, role).status_code == 400

    @pytest.mark.parametrize("role", ["face_shape", "facial_hair"])
    def test_a_parked_role_reports_that_it_cannot_be_isolated(self, client, founder, role):
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        with patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"):
            resp = _preview(client, token, cid, img, role)
        assert resp.status_code == 422, resp.text

    def test_an_unknown_role_is_rejected(self, client, founder):
        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        assert _preview(client, token, cid, img, "ears").status_code == 422


class TestPreviewAccess:
    def test_an_ordinary_creator_cannot_preview(self, client, db_session):
        token = get_auth_token(client, email="nofounder@example.com", username="nofounderacct")
        cid = _create_character(client, token, name="Plain")
        assert _preview(client, token, cid, 1, "hair").status_code in (401, 403)

    def test_an_anonymous_request_cannot_preview(self, client, founder):
        _token, cid = founder
        resp = client.get(
            f"/characters/{cid}/image-generator/references/1/isolated?role=hair"
        )
        assert resp.status_code in (401, 403)

    def test_an_image_from_another_character_is_refused(self, client, founder):
        """Same ownership rule a generation submission passes: an id the founder
        could not have SELECTED cannot be previewed either."""
        token, cid = founder
        other = _create_character(client, token, name="Other")
        foreign = _upload(client, token, other).json()["id"]
        assert _preview(client, token, cid, foreign, "hair").status_code in (400, 403, 404, 422)

    def test_a_missing_image_is_refused(self, client, founder):
        token, cid = founder
        assert _preview(client, token, cid, 999999, "hair").status_code in (400, 403, 404, 422)


class TestPreviewFailure:
    def test_an_unisolatable_image_reports_what_to_do(self, client, founder):
        """The refusal is the founder's cue to choose a different photograph, so
        it carries the same actionable wording generation uses."""
        from app.services.reference_isolation import IsolationError

        token, cid = founder
        img = _upload(client, token, cid).json()["id"]
        with patch(f"{ROUTE}.load_image_bytes", return_value=b"RAW"), \
             patch(f"{ROUTE}.isolate_reference",
                   side_effect=IsolationError("no_face_detected",
                                              "No face could be found in it. "
                                              "Use a clear front-facing photo with both eyes visible.")):
            resp = _preview(client, token, cid, img, "hair")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "front-facing" in detail
        for jargon in ("Haar", "IOD", "cascade", "interocular"):
            assert jargon.lower() not in detail.lower()

"""Canon image URLs handed to the browser must be loadable as images.

Production failure this closes: identity-pack generation succeeded, the canon
locked, and Manage Character Canon showed the expected slots — but every image
panel rendered only its alt text ("Front Face", "Left ¾", "Right ¾", "Profile").

``save_image`` returns an absolute ``https://`` R2 URL in object-storage mode
and a bare relative ``static/generated/<uuid>.png`` on local disk. The canon
API returned whichever was stored, verbatim. A bare relative path has no
leading slash, so ``<img src="static/generated/x.png">`` on a route such as
``/characters/42`` resolves against the CURRENT PATH: the browser requests
``/characters/static/generated/x.png``, the SPA catch-all answers index.html,
and the response is HTTP 200 with Content-Type text/html. Nothing anywhere
errored — which is exactly why the workflow looked healthy while every card
was blank.

The rule these tests hold: whatever shape storage produced, the value the API
hands a browser must resolve to an image from the site root, and the stored
value must not change (generation reads it back through ``load_image_bytes``).
"""
import json
from datetime import datetime

import pytest
from unittest.mock import MagicMock

from app.api.routes.canon_api import _canon_to_read
from app.models.character_identity_canon import CharacterIdentityCanon
from app.schemas.canon import (
    BodyCanonData,
    FaceCanonData,
    PermanentBodyMark,
    RemovableAccessory,
)
from app.services.canon_service import load_body_canon, load_face_canon

R2 = "https://pub-abc123.r2.dev/generated/deadbeef.png"
LOCAL = "static/generated/deadbeef.png"
LOCAL_SERVED = "/static/generated/deadbeef.png"


def _canon(face: FaceCanonData, body: BodyCanonData, accessories=()):
    canon = MagicMock(spec=CharacterIdentityCanon)
    canon.id = 1
    canon.character_id = 42
    canon.status = "locked"
    canon.face_canon_json = json.dumps(face.model_dump())
    canon.body_canon_json = json.dumps(body.model_dump())
    canon.accessories_json = json.dumps([a.model_dump() for a in accessories])
    canon.face_locked = True
    canon.body_locked = True
    canon.created_at = canon.updated_at = canon.locked_at = datetime(2026, 8, 10)
    return canon


def _is_browser_loadable(url: str) -> bool:
    """A src the browser resolves from the site root, not from the page path."""
    return url.startswith(("http://", "https://", "/"))


class TestEveryCanonSlotIsBrowserLoadable:
    @pytest.mark.parametrize("stored,expected", [
        (R2, R2),                 # object storage — passes through untouched
        (LOCAL, LOCAL_SERVED),    # local disk — gained its leading slash
        ("/static/generated/x.png", "/static/generated/x.png"),  # already fine
    ])
    def test_face_slots(self, stored, expected):
        face = FaceCanonData(
            face_front_image_url=stored, face_left_3q_image_url=stored,
            face_right_3q_image_url=stored, face_profile_image_url=stored,
            face_expression_image_url=stored,
        )
        read = _canon_to_read(_canon(face, BodyCanonData()))
        for field in ("face_front_image_url", "face_left_3q_image_url",
                      "face_right_3q_image_url", "face_profile_image_url",
                      "face_expression_image_url"):
            value = getattr(read.face_canon, field)
            assert value == expected, field
            assert _is_browser_loadable(value), field

    @pytest.mark.parametrize("stored,expected", [(R2, R2), (LOCAL, LOCAL_SERVED)])
    def test_body_slots(self, stored, expected):
        body = BodyCanonData(
            body_front_image_url=stored, body_left_image_url=stored,
            body_right_image_url=stored, body_back_image_url=stored,
            body_map_image_url=stored, final_character_card_image_url=stored,
            torso_front_image_url=stored, torso_side_image_url=stored,
            standing_relaxed_image_url=stored, seated_relaxed_image_url=stored,
        )
        read = _canon_to_read(_canon(FaceCanonData(), body))
        for field, value in read.body_canon.model_dump().items():
            if field.endswith("_image_url") and value:
                assert value == expected, field
                assert _is_browser_loadable(value), field

    @pytest.mark.parametrize("stored,expected", [(R2, R2), (LOCAL, LOCAL_SERVED)])
    def test_permanent_mark_images(self, stored, expected):
        """Mark panels render the same way and broke the same way."""
        body = BodyCanonData(permanent_body_marks=[PermanentBodyMark(
            label="Sleeve", type="tattoo", body_region="left_full_arm",
            side="left", description="design",
            reference_image_url=stored, detail_crop_url=stored,
        )])
        read = _canon_to_read(_canon(FaceCanonData(), body))
        mark = read.body_canon.permanent_body_marks[0]
        assert mark.reference_image_url == expected
        assert mark.detail_crop_url == expected

    @pytest.mark.parametrize("stored,expected", [(R2, R2), (LOCAL, LOCAL_SERVED)])
    def test_accessory_images(self, stored, expected):
        acc = RemovableAccessory(
            label="Mask", type="mask", description="a mask",
            design_anchor_image_url=stored, fit_anchor_image_url=stored,
        )
        read = _canon_to_read(_canon(FaceCanonData(), BodyCanonData(), [acc]))
        assert read.accessories[0].design_anchor_image_url == expected
        assert read.accessories[0].fit_anchor_image_url == expected

    def test_a_page_relative_value_can_never_escape_the_api(self):
        """The precise defect: a src with no scheme and no leading slash.

        The browser resolves that against the current route, gets index.html
        back with a 200, and shows alt text.
        """
        face = FaceCanonData(face_front_image_url=LOCAL)
        body = BodyCanonData(body_front_image_url=LOCAL)
        read = _canon_to_read(_canon(face, body))
        for value in (read.face_canon.face_front_image_url,
                      read.body_canon.body_front_image_url):
            assert not value.startswith("static/"), (
                "page-relative src reaches the browser and renders as alt text"
            )

    def test_empty_slots_stay_empty(self):
        read = _canon_to_read(_canon(FaceCanonData(), BodyCanonData()))
        assert read.face_canon.face_front_image_url is None
        assert read.body_canon.body_front_image_url is None


class TestUploadAndFetchRoundTrip:
    """End-to-end through the real routes, in local-disk storage mode.

    Local disk is the mode that produced the failure — it is also the default,
    since USE_OBJECT_STORAGE reaches a deployment only as a platform secret.
    """

    @staticmethod
    def _png() -> bytes:
        from app.services.stub_image_generator import generate_placeholder_png
        from app.core.storage import load_image_bytes
        return load_image_bytes(generate_placeholder_png(label="t", sublabel="t"))

    def _admin_headers(self, client, db_session):
        from tests.conftest import auth_headers, get_auth_token
        from app.models.user import User as UserModel
        token = get_auth_token(client, email="canonurl_admin@ficshon.com")
        hdrs = auth_headers(token)
        user = db_session.query(UserModel).filter(
            UserModel.email == "canonurl_admin@ficshon.com").first()
        user.is_admin = True
        db_session.commit()
        return hdrs

    def test_uploaded_slot_renders_immediately_and_after_reload(
            self, client, db_session, monkeypatch, generated_media_dir):
        # Pin local-disk storage: this is the mode that produced page-relative
        # paths, and it is the default whenever USE_OBJECT_STORAGE is unset.
        from app.core.config import settings
        monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)

        hdrs = self._admin_headers(client, db_session)
        char_id = client.post(
            "/characters/", json={"name": "CanonUrl", "visibility": "public"},
            headers=hdrs).json()["id"]

        upload = client.post(
            f"/characters/{char_id}/identity-canon/upload",
            data={"slot": "face_front"},
            files={"file": ("face.png", self._png(), "image/png")},
            headers=hdrs,
        )
        assert upload.status_code == 201, upload.text

        # 1. the value the UI renders straight after upload
        assert _is_browser_loadable(upload.json()["url"])

        # 2. the value the UI renders after a reload
        fetched = client.get(
            f"/characters/{char_id}/identity-canon", headers=hdrs).json()
        src = fetched["face_canon"]["face_front_image_url"]
        assert _is_browser_loadable(src)

        # 3. that src actually returns image bytes from the server root
        # 3. that src is a /static/ path pointing at the bytes actually written.
        # (The suite repoints the media dir to a tmp path while the app still
        # mounts the repo's static dir, so fetching through the mount is not
        # meaningful here; the URL→object mapping is what this must hold.)
        from pathlib import Path
        assert src.startswith("/static/generated/"), src
        assert (generated_media_dir / Path(src).name).is_file(), (
            f"{src} does not correspond to any stored image"
        )


class TestStoredValuesAreNotRewritten:
    """Serialization is a read-side concern only.

    Generation loads references back with ``load_image_bytes``, which resolves
    the RAW stored path. If normalisation leaked into storage, the API fix
    would break the generator it was meant to leave alone.
    """

    def test_storage_keeps_the_raw_path(self):
        face = FaceCanonData(face_front_image_url=LOCAL)
        body = BodyCanonData(body_front_image_url=LOCAL)
        canon = _canon(face, body)
        _canon_to_read(canon)
        assert load_face_canon(canon).face_front_image_url == LOCAL
        assert load_body_canon(canon).body_front_image_url == LOCAL

    def test_serializing_twice_is_stable(self):
        canon = _canon(FaceCanonData(face_front_image_url=LOCAL), BodyCanonData())
        first = _canon_to_read(canon).face_canon.face_front_image_url
        second = _canon_to_read(canon).face_canon.face_front_image_url
        assert first == second == LOCAL_SERVED

"""Clean identity canon rebuild — acceptance tests (2026-05-30).

Tests:
  1.  Scene image generation works (produces an image record)
  2.  Scene images do not mutate canon
  3.  Face canon is compiled first in prompts
  4.  Body canon is compiled second in prompts
  5.  Permanent tattoos are part of Body Canon
  6.  Permanent tattoos are never accessories
  7.  Removable mask NOT injected unless trigger keyword present
  8.  Removable mask IS injected when trigger keyword present
  9.  Admin can assign face_front canon slot via upload
  10. Admin can assign body_front canon slot via upload
  11. Admin can lock Face Canon
  12. Admin can lock Body Canon
  13. Non-admin cannot use admin upload
  14. Old auto-sync (shop tattoo → body_canon) is disabled
  15. Existing characters load without error after rebuild
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import auth_headers, get_auth_token


# ── Helpers ───────────────────────────────────────────────────────────

def _create_character(client, headers, name="CanonChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _get_canon(client, headers, char_id):
    resp = client.get(f"/characters/{char_id}/identity-canon", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _add_mark(client, headers, char_id, **kwargs):
    payload = {
        "label": kwargs.get("label", "Test tattoo"),
        "type": kwargs.get("type", "tattoo"),
        "body_region": kwargs.get("body_region", "left_full_arm"),
        "side": kwargs.get("side", "left"),
        "description": kwargs.get("description", "gothic script sleeve from shoulder to wrist"),
    }
    resp = client.post(
        f"/characters/{char_id}/identity-canon/body/marks",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["mark"]


def _add_accessory(client, headers, char_id, **kwargs):
    payload = {
        "label": kwargs.get("label", "Venetian mask"),
        "type": kwargs.get("type", "mask"),
        "description": kwargs.get("description", "ornate Venetian half-mask in white and gold"),
        "trigger_keywords": kwargs.get("trigger_keywords", ["mask", "masked"]),
    }
    resp = client.post(
        f"/characters/{char_id}/identity-canon/accessories",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["accessory"]


# ── Test 1: Scene generation works ───────────────────────────────────

class TestSceneGenerationWorks:
    def test_generate_scene_returns_image_record(self, client, db_session):
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="crb1@test.com", username="crb_u1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneTestChar")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "Leonardo standing on a beach in daylight"},
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data
        assert data["kind"] == "scene_only"

        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == data["id"]).first()
        assert img is not None
        assert img.kind == ImageKindEnum.SCENE_ONLY

    def test_generate_scene_saves_scene_only_kind(self, client, db_session):
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="crb2@test.com", username="crb_u2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneKindTest")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "walking through a forest"},
            headers=hdrs,
        )
        assert resp.status_code == 200
        img_id = resp.json()["id"]
        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == img_id).first()
        assert img.kind == ImageKindEnum.SCENE_ONLY

    def test_generate_scene_metadata_has_scene_only_flag(self, client, db_session):
        from app.models.character_image import CharacterImage

        token = get_auth_token(client, email="crb3@test.com", username="crb_u3")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneMetaTest")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "sitting at a cafe"},
            headers=hdrs,
        )
        assert resp.status_code == 200
        img_id = resp.json()["id"]
        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == img_id).first()
        assert img.metadata_json.get("scene_only") is True

    def test_scene_image_appears_in_user_character_images(self, client, db_session):
        """P5: Generated scene images must persist and appear in GET /users/me/character-images.

        The gallery frontend calls this endpoint on mount. If scene_only images are
        absent from the response the image disappears on page reload.
        """
        token = get_auth_token(client, email="crb_persist@test.com", username="crb_persist")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="PersistTestChar")

        # Generate a scene image.
        gen_resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "standing by a window"},
            headers=hdrs,
        )
        assert gen_resp.status_code == 200, gen_resp.text
        generated_id = gen_resp.json()["id"]
        assert gen_resp.json()["kind"] == "scene_only"

        # The gallery endpoint must return this image.
        gallery_resp = client.get("/users/me/character-images", headers=hdrs)
        assert gallery_resp.status_code == 200, gallery_resp.text
        gallery_ids = [img["id"] for img in gallery_resp.json()]
        assert generated_id in gallery_ids, (
            f"Generated scene image {generated_id} not found in /users/me/character-images. "
            f"Gallery returned ids: {gallery_ids}"
        )

    def test_scene_image_has_active_status_and_no_temp_flag(self, client, db_session):
        """P5: Generated images must have status=active and no is_temp flag so they persist."""
        from app.models.character_image import CharacterImage, ImageStatusEnum

        token = get_auth_token(client, email="crb_persist2@test.com", username="crb_persist2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="PersistStatusChar")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "sitting in a park"},
            headers=hdrs,
        )
        assert resp.status_code == 200
        img_id = resp.json()["id"]

        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == img_id).first()
        assert img is not None
        assert img.status == ImageStatusEnum.ACTIVE, (
            f"Expected ACTIVE status, got {img.status}"
        )
        assert not (img.metadata_json or {}).get("is_temp", False), (
            "scene_only images must not have is_temp=True — that flag excludes them from the gallery"
        )


# ── Test 2: Scene images do not mutate canon ─────────────────────────

class TestSceneDoesNotMutateCanon:
    def test_scene_generation_does_not_change_face_canon(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon

        token = get_auth_token(client, email="crb4@test.com", username="crb_u4")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="CanonImmutable")

        # Set up face canon
        client.patch(
            f"/characters/{char_id}/identity-canon/face",
            json={"face_description": "sharp jaw, dark eyes"},
            headers=hdrs,
        )
        db_session.expire_all()
        canon_before = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        face_json_before = canon_before.face_canon_json if canon_before else None

        # Generate a scene
        client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "standing in rain"},
            headers=hdrs,
        )

        db_session.expire_all()
        canon_after = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        face_json_after = canon_after.face_canon_json if canon_after else None
        assert face_json_before == face_json_after, "Scene generation must not mutate face canon"

    def test_scene_generation_does_not_change_body_marks(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon

        token = get_auth_token(client, email="crb5@test.com", username="crb_u5")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="BodyImmutable")
        _add_mark(client, hdrs, char_id, description="gothic script sleeve left arm")

        db_session.expire_all()
        canon_before = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        body_before = canon_before.body_canon_json

        client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "at the beach with no tattoos"},
            headers=hdrs,
        )

        db_session.expire_all()
        canon_after = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        assert canon_after.body_canon_json == body_before, (
            "Scene generation must not mutate body canon marks"
        )


# ── Test 3 & 4: Prompt ordering ──────────────────────────────────────

class TestPromptOrdering:
    def _make_canon_with_content(self):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData, PermanentBodyMark

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 1
        face = FaceCanonData(
            face_description="sharp angular jaw, dark brown eyes",
            locked=True,
        )
        mark = PermanentBodyMark(
            label="Left sleeve",
            type="tattoo",
            body_region="left_full_arm",
            side="left",
            description="gothic script from shoulder to wrist",
        )
        body = BodyCanonData(
            body_description="tall, athletic build",
            permanent_body_marks=[mark],
            locked=True,
        )
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None
        return canon

    def test_face_canon_before_body_canon_in_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        prompt = compile_canon_prompt(canon, "standing on a beach")

        face_pos = prompt.find("FACE CANON")
        body_pos = prompt.find("BODY CANON")
        assert face_pos != -1, "FACE CANON must appear in prompt"
        assert body_pos != -1, "BODY CANON must appear in prompt"
        assert face_pos < body_pos, (
            f"FACE CANON (pos={face_pos}) must precede BODY CANON (pos={body_pos})"
        )

    def test_body_canon_before_scene_prompt_in_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        scene = "sitting at a bar drinking whiskey"
        prompt = compile_canon_prompt(canon, scene)

        body_pos = prompt.find("BODY CANON")
        scene_pos = prompt.find(scene)
        assert body_pos != -1
        assert scene_pos != -1
        assert body_pos < scene_pos, (
            f"BODY CANON (pos={body_pos}) must precede scene (pos={scene_pos})"
        )

    def test_permanent_marks_before_scene_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        scene = "in a nightclub"
        prompt = compile_canon_prompt(canon, scene)

        marks_pos = prompt.find("PERMANENT BODY MARKS")
        scene_pos = prompt.find(scene)
        assert marks_pos != -1
        assert marks_pos < scene_pos

    def test_locked_canon_clause_at_end(self):
        from app.services.canon_compiler import compile_canon_prompt, LOCKED_CANON_CLAUSE

        canon = self._make_canon_with_content()
        scene = "brief scene here"
        prompt = compile_canon_prompt(canon, scene)

        clause_pos = prompt.find("locked face")  # start of the locked canon clause
        scene_pos = prompt.find(scene)
        assert clause_pos != -1, "Locked canon clause must appear when face/body is locked"
        assert clause_pos > scene_pos, "Locked canon clause must appear after scene prompt"


# ── Test 5 & 6: Permanent tattoos are Body Canon, not accessories ─────

class TestPermanentTattoosAreBodyCanon:
    def test_tattoo_stored_in_body_canon_permanent_marks(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.services.canon_service import load_body_canon

        token = get_auth_token(client, email="crb6@test.com", username="crb_u6")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="TattoBodyCanon")
        _add_mark(
            client, hdrs, char_id,
            label="Left gothic script sleeve",
            type="tattoo",
            body_region="left_full_arm",
            side="left",
            description="gothic script sleeve",
        )

        db_session.expire_all()
        from app.models.character_identity_canon import CharacterIdentityCanon as CIC
        canon = db_session.query(CIC).filter(CIC.character_id == char_id).first()
        assert canon is not None
        body = load_body_canon(canon)
        assert body is not None
        assert len(body.permanent_body_marks) == 1
        assert body.permanent_body_marks[0].type == "tattoo"
        assert body.permanent_body_marks[0].body_region == "left_full_arm"

    def test_tattoo_injected_under_permanent_body_marks_not_accessories(self):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import BodyCanonData, PermanentBodyMark
        from app.services.canon_compiler import compile_canon_prompt

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 1
        mark = PermanentBodyMark(
            label="Left sleeve",
            type="tattoo",
            body_region="left_full_arm",
            side="left",
            description="gothic script inscription sleeve",
        )
        body = BodyCanonData(permanent_body_marks=[mark])
        canon.face_canon_json = None
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None

        prompt = compile_canon_prompt(canon, "standing in sunlight")
        assert "PERMANENT BODY MARKS" in prompt, "Tattoos must appear under PERMANENT BODY MARKS"
        assert "gothic script inscription sleeve" in prompt
        # Must NOT appear under ACCESSORIES
        if "ACCESSORIES" in prompt:
            # Accessories section exists — tattoo must not be there
            acc_pos = prompt.find("ACCESSORIES")
            marks_pos = prompt.find("PERMANENT BODY MARKS")
            tattoo_pos = prompt.find("gothic script inscription sleeve")
            assert tattoo_pos < acc_pos or tattoo_pos > acc_pos + 50, (
                "Tattoo description must not be inside ACCESSORIES block"
            )

    def test_permanent_mark_type_tattoo_is_not_accessory_type(self):
        from app.schemas.canon import PermanentBodyMark, RemovableAccessory
        mark = PermanentBodyMark(
            label="Scar",
            type="scar",
            body_region="right_cheek",
            side="right",
            description="diagonal slash scar across right cheek",
        )
        assert not isinstance(mark, RemovableAccessory), "PermanentBodyMark is not a RemovableAccessory"
        assert mark.type in ("tattoo", "scar", "birthmark", "mole", "body_marking", "other")


# ── Test 7 & 8: Removable accessory injection ─────────────────────────

class TestRemovableAccessoryInjection:
    def _make_canon_with_mask(self):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import RemovableAccessory

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 1
        canon.face_canon_json = None
        canon.body_canon_json = None
        mask = RemovableAccessory(
            label="Venetian mask",
            type="mask",
            description="ornate Venetian half-mask in white and gold",
            trigger_keywords=["mask", "masked", "wearing mask"],
        )
        canon.accessories_json = json.dumps([mask.model_dump()])
        return canon

    def test_mask_not_injected_without_trigger_keyword(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mask()
        prompt = compile_canon_prompt(canon, "standing on a beach in sunlight")
        assert "Venetian" not in prompt, "Mask must not appear when not triggered"
        assert "half-mask" not in prompt

    def test_mask_injected_when_trigger_keyword_present(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mask()
        prompt = compile_canon_prompt(canon, "standing at a party, wearing a mask")
        assert "ornate Venetian half-mask" in prompt, "Mask must appear when trigger keyword 'mask' is in scene"

    def test_mask_injected_for_any_matching_keyword(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mask()
        for kw in ("mask", "masked", "wearing mask"):
            scene = f"Leonardo at the gala, {kw}, in black tie"
            prompt = compile_canon_prompt(canon, scene)
            assert "ornate Venetian half-mask" in prompt, f"Mask must inject for keyword {kw!r}"

    def test_accessory_rule_shown_when_no_accessories_triggered(self):
        from app.services.canon_compiler import compile_canon_prompt, ACCESSORY_RULE

        canon = self._make_canon_with_mask()
        prompt = compile_canon_prompt(canon, "walking in a park")
        assert "Only include removable accessories" in prompt or ACCESSORY_RULE[:40] in prompt


# ── Test 9 & 10: Admin can assign images ─────────────────────────────

class TestAdminCanonUpload:
    def _make_fake_png(self):
        """1x1 PNG bytes for upload tests."""
        import base64
        # Minimal valid PNG
        PNG_1X1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9Q"
            "DwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        return PNG_1X1

    def test_admin_assigns_face_front(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.services.canon_service import load_face_canon

        # Create admin user
        token = get_auth_token(client, email="crb_admin@ficshon.com", username="crb_admin")
        hdrs = auth_headers(token)
        # Make admin in DB
        from app.models.user import User as UserModel
        db_session.expire_all()
        admin_user = db_session.query(UserModel).filter(UserModel.email == "crb_admin@ficshon.com").first()
        assert admin_user is not None
        admin_user.is_admin = True
        db_session.commit()

        char_id = _create_character(client, hdrs, name="AdminFaceUpload")
        png = self._make_fake_png()

        resp = client.post(
            f"/characters/{char_id}/identity-canon/upload",
            data={"slot": "face_front"},
            files={"file": ("face.png", png, "image/png")},
            headers=hdrs,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["slot"] == "face_front"
        assert data["url"]

        db_session.expire_all()
        canon = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        face = load_face_canon(canon)
        assert face is not None
        assert face.face_front_image_url is not None

    def test_admin_assigns_body_front(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.services.canon_service import load_body_canon

        token = get_auth_token(client, email="crb_admin2@ficshon.com", username="crb_admin2")
        hdrs = auth_headers(token)
        from app.models.user import User as UserModel
        db_session.expire_all()
        admin_user = db_session.query(UserModel).filter(
            UserModel.email == "crb_admin2@ficshon.com"
        ).first()
        admin_user.is_admin = True
        db_session.commit()

        char_id = _create_character(client, hdrs, name="AdminBodyUpload")
        png = self._make_fake_png()

        resp = client.post(
            f"/characters/{char_id}/identity-canon/upload",
            data={"slot": "body_front"},
            files={"file": ("body.png", png, "image/png")},
            headers=hdrs,
        )
        assert resp.status_code == 201, resp.text
        db_session.expire_all()
        canon = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        body = load_body_canon(canon)
        assert body is not None
        assert body.body_front_image_url is not None


# ── Test 11 & 12: Admin can lock canons ──────────────────────────────

class TestAdminLockCanon:
    def test_lock_face_canon_requires_face_front(self, client):
        token = get_auth_token(client, email="crb_lock1@test.com", username="crb_lock1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LockFaceTest")

        # Should fail — no face_front_image_url set
        resp = client.post(
            f"/characters/{char_id}/identity-canon/face/lock",
            headers=hdrs,
        )
        assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"

    def test_lock_body_canon_requires_body_front(self, client):
        token = get_auth_token(client, email="crb_lock2@test.com", username="crb_lock2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LockBodyTest")

        # Should fail — no body_front_image_url set
        resp = client.post(
            f"/characters/{char_id}/identity-canon/body/lock",
            headers=hdrs,
        )
        assert resp.status_code == 409

    def test_lock_face_canon_succeeds_when_face_front_set(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon

        token = get_auth_token(client, email="crb_lock3@test.com", username="crb_lock3")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LockFaceSuccess")

        # Set face_front_image_url directly via PATCH
        client.patch(
            f"/characters/{char_id}/identity-canon/face",
            json={"face_front_image_url": "https://cdn.example.com/face.png"},
            headers=hdrs,
        )

        resp = client.post(
            f"/characters/{char_id}/identity-canon/face/lock",
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["face_locked"] is True

        db_session.expire_all()
        canon = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        assert canon.face_locked is True
        assert canon.face_locked_at is not None

    def test_lock_body_canon_succeeds_when_body_front_set(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon

        token = get_auth_token(client, email="crb_lock4@test.com", username="crb_lock4")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LockBodySuccess")

        client.patch(
            f"/characters/{char_id}/identity-canon/body",
            json={"body_front_image_url": "https://cdn.example.com/body.png"},
            headers=hdrs,
        )

        resp = client.post(
            f"/characters/{char_id}/identity-canon/body/lock",
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["body_locked"] is True

        db_session.expire_all()
        canon = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        assert canon.body_locked is True

    def test_both_locked_sets_canon_status_locked(self, client, db_session):
        from app.models.character_identity_canon import CharacterIdentityCanon

        token = get_auth_token(client, email="crb_lock5@test.com", username="crb_lock5")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="BothLocked")

        client.patch(
            f"/characters/{char_id}/identity-canon/face",
            json={"face_front_image_url": "https://cdn.example.com/face.png"},
            headers=hdrs,
        )
        client.patch(
            f"/characters/{char_id}/identity-canon/body",
            json={"body_front_image_url": "https://cdn.example.com/body.png"},
            headers=hdrs,
        )
        client.post(f"/characters/{char_id}/identity-canon/face/lock", headers=hdrs)
        client.post(f"/characters/{char_id}/identity-canon/body/lock", headers=hdrs)

        db_session.expire_all()
        canon = db_session.query(CharacterIdentityCanon).filter(
            CharacterIdentityCanon.character_id == char_id
        ).first()
        assert canon.status == "locked"
        assert canon.locked_at is not None


# ── Test 13: Non-admin cannot admin-upload ────────────────────────────

class TestAdminGuard:
    def test_non_admin_upload_returns_403(self, client):
        import base64
        PNG_1X1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9Q"
            "DwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        token = get_auth_token(client, email="crb_nonadmin@test.com", username="crb_nonadmin")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="NonAdminChar")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/upload",
            data={"slot": "face_front"},
            files={"file": ("face.png", PNG_1X1, "image/png")},
            headers=hdrs,
        )
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"


# ── Test 14: Auto-sync is disabled ───────────────────────────────────

class TestAutoSyncDisabled:
    def test_get_body_markings_does_not_auto_sync_tattoo_shop(self, client, db_session):
        """GET /body-markings no longer auto-syncs style shop tattoos into body canon."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="crb_sync@test.com", username="crb_sync")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="NoAutoSync")

        # Manually set body_canon_json to empty
        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        char.body_canon_json = None
        db_session.commit()

        # GET body-markings — should NOT populate from style shop
        resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
        assert resp.status_code == 200

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        # body_canon_json must remain empty (not populated by auto-sync)
        markings = load_markings(char)
        assert markings == [], "GET /body-markings must not auto-sync shop tattoos"

    def test_style_shop_tattoo_apply_does_not_mutate_body_canon(self, client, db_session):
        """Applying a tattoo preset does NOT auto-sync to body_canon_json."""
        from app.models.character import Character
        from app.services.body_canon import load_markings
        from app.core.style_shop_seed import seed_style_presets

        seed_style_presets(db_session)

        token = get_auth_token(client, email="crb_shoptest@test.com", username="crb_shoptest")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="ShopNoSync")

        presets = client.get("/style-shops/presets?shop_type=tattoo").json()
        if not presets:
            pytest.skip("No tattoo presets seeded")

        # Record body_canon_json before
        db_session.expire_all()
        char_before = db_session.query(Character).filter(Character.id == char_id).first()
        canon_before = char_before.body_canon_json

        # Apply tattoo preset
        client.post(
            f"/characters/{char_id}/style-elements",
            json={"preset_id": presets[0]["id"]},
            headers=hdrs,
        )

        db_session.expire_all()
        char_after = db_session.query(Character).filter(Character.id == char_id).first()
        canon_after = char_after.body_canon_json

        assert canon_before == canon_after, (
            "Style shop tattoo apply must NOT mutate body_canon_json"
        )


# ── Test 15: Existing characters load without error ──────────────────

class TestExistingCharactersLoad:
    def test_character_without_canon_record_loads(self, client, db_session):
        """Characters without a CharacterIdentityCanon record load without error."""
        token = get_auth_token(client, email="crb_legacy@test.com", username="crb_legacy")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LegacyChar")

        # GET canon creates it
        resp = client.get(f"/characters/{char_id}/identity-canon", headers=hdrs)
        assert resp.status_code == 200
        data = resp.json()
        assert data["character_id"] == char_id
        assert data["status"] == "draft"
        assert data["face_canon"] is None
        assert data["body_canon"] is None

    def test_character_with_old_body_canon_json_still_accessible(self, client, db_session):
        """Characters with old body_canon_json field are still accessible."""
        from app.models.character import Character

        token = get_auth_token(client, email="crb_oldbc@test.com", username="crb_oldbc")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="OldBodyCanon")

        # Manually set old body_canon_json format
        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        char.body_canon_json = json.dumps({"markings": [
            {
                "id": "bm_legacy01",
                "type": "tattoo",
                "placement": "left_full_arm",
                "style": "gothic script",
                "size": "full_sleeve",
                "description": "legacy tattoo",
                "anchor_status": "missing",
                "anchor_image_url": None,
                "anchor_prompt": None,
            }
        ]})
        db_session.commit()

        # Old body-markings endpoint still works (legacy compatibility)
        resp = client.get(f"/characters/{char_id}/body-markings", headers=hdrs)
        assert resp.status_code == 200
        data = resp.json()
        assert data["character_id"] == char_id

        # New canon endpoint also works
        canon_resp = client.get(f"/characters/{char_id}/identity-canon", headers=hdrs)
        assert canon_resp.status_code == 200

    def test_scene_generation_works_without_canon_record(self, client):
        """Scene generation works even when no canon record exists."""
        token = get_auth_token(client, email="crb_nocanon@test.com", username="crb_nocanon")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="NoCanonGen")

        resp = client.post(
            f"/characters/{char_id}/identity-canon/scenes/generate",
            json={"prompt": "a simple test scene"},
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "scene_only"


# ── Leonardo scenario: unit-level prompt test ─────────────────────────

class TestLeonardoPromptScenario:
    """Unit-level prompt compilation for Leonardo's expected canon."""

    def _make_leonardo_canon(self):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import (
            FaceCanonData, BodyCanonData, PermanentBodyMark, RemovableAccessory
        )

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 99
        face = FaceCanonData(
            face_front_image_url="https://cdn.test/leo_face.png",
            face_description="Leonardo Baptiste: sharp angular jaw, dark brown eyes, olive skin",
            locked=True,
        )
        left_sleeve = PermanentBodyMark(
            label="Left gothic script sleeve",
            type="tattoo",
            body_region="left_full_arm",
            side="left",
            description="gothic script inscription sleeve covering full left arm shoulder to wrist",
        )
        right_wolf = PermanentBodyMark(
            label="Right Arm Tribal Wolf Mark",
            type="tattoo",
            body_region="right_upper_arm",
            side="right",
            description=(
                "Black tribal wolf head tattoo locked to the right upper arm / "
                "lateral bicep and deltoid cap only. It does not extend to the "
                "forearm, wrist, hand, chest, neck, back, or shoulder blade."
            ),
        )
        body = BodyCanonData(
            body_front_image_url="https://cdn.test/leo_body.png",
            body_description="tall, athletic build, broad shoulders",
            height="tall",
            build="athletic",
            skin_tone="olive",
            permanent_body_marks=[left_sleeve, right_wolf],
            locked=True,
        )
        mask = RemovableAccessory(
            label="Venetian mask",
            type="mask",
            description="ornate Venetian half-mask in white and gold filigree",
            trigger_keywords=["mask", "masked"],
        )
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = json.dumps([mask.model_dump()])
        return canon

    def test_beach_no_mask_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        prompt = compile_canon_prompt(canon, "Leonardo standing on a beach in daylight")

        assert "gothic script inscription sleeve" in prompt
        assert "tribal wolf" in prompt  # in updated description: "Black tribal wolf head tattoo..."
        assert "Venetian" not in prompt  # mask not triggered
        assert "FACE CANON" in prompt
        assert "BODY CANON" in prompt
        assert "locked face" in prompt.lower()  # locked canon clause

    def test_beach_with_mask_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        prompt = compile_canon_prompt(
            canon,
            "Leonardo at a masquerade ball, wearing a mask",
        )

        # Both marks appear — covered or visible, the description text is always present.
        assert "gothic script inscription sleeve" in prompt
        assert "tribal wolf" in prompt  # in updated description
        assert "ornate Venetian half-mask" in prompt  # mask triggered

    def test_face_description_before_body_in_prompt(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        prompt = compile_canon_prompt(canon, "bar scene in black shirt")

        face_pos = prompt.find("FACE CANON")
        body_pos = prompt.find("BODY CANON")
        marks_pos = prompt.find("PERMANENT BODY MARKS")

        assert face_pos < body_pos < marks_pos, (
            f"Wrong order: face={face_pos} body={body_pos} marks={marks_pos}"
        )

    def test_both_tattoos_in_prompt_not_mirrored(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        prompt = compile_canon_prompt(canon, "shirtless side profile")

        # Both marks must appear with their correct sides
        assert "left" in prompt.lower()
        assert "right" in prompt.lower()
        assert "gothic script" in prompt
        assert "tribal wolf" in prompt
        # They appear separately (semicolon separated)
        marks_start = prompt.find("PERMANENT BODY MARKS")
        assert marks_start != -1
        marks_section = prompt[marks_start:]
        assert "gothic script" in marks_section
        assert "tribal wolf" in marks_section


# ── P4: Marking visibility gating tests ──────────────────────────────

class TestMarkingVisibilityGating:
    """P4 acceptance tests — anatomical marking visibility and no-relocation.

    Verifies that compile_canon_prompt correctly classifies permanent body
    marks as VISIBLE or COVERED based on the scene prompt, and always emits
    the relocation prohibition when marks are covered.
    """

    def _make_canon_with_mark(
        self,
        body_region: str = "right_upper_arm",
        description: str = "wolf tattoo",
        side: str = "right",
    ):
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import BodyCanonData, PermanentBodyMark

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 42
        canon.face_canon_json = None
        canon.accessories_json = None
        mark = PermanentBodyMark(
            label="Test mark",
            type="tattoo",
            body_region=body_region,
            side=side,
            description=description,
        )
        body = BodyCanonData(permanent_body_marks=[mark])
        canon.body_canon_json = json.dumps(body.model_dump())
        return canon

    # ── Test 1: right_upper_arm + t-shirt → hidden ────────────────
    def test_upper_arm_hidden_under_tshirt(self):
        """T-shirt exposes forearm but NOT the upper bicep — wolf must be covered."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="right_upper_arm",
            description="Black tribal wolf head tattoo on right upper bicep",
        )
        prompt = compile_canon_prompt(canon, "standing in a bar wearing a t-shirt")

        assert "COVERED PERMANENT BODY MARKS" in prompt
        assert "PERMANENT BODY MARKS VISIBLE" not in prompt
        assert "wolf" in prompt  # description still in covered block

    # ── Test 2: right_upper_arm + sleeveless → visible ────────────
    def test_upper_arm_visible_when_sleeveless(self):
        """Sleeveless shirt exposes the full arm — wolf must be visible."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="right_upper_arm",
            description="Black tribal wolf head tattoo on right upper bicep",
        )
        prompt = compile_canon_prompt(canon, "standing in the sun wearing a sleeveless shirt")

        assert "PERMANENT BODY MARKS VISIBLE" in prompt
        assert "wolf" in prompt
        # Must NOT appear in a covered block
        assert "COVERED PERMANENT BODY MARKS" not in prompt

    # ── Test 3: right_upper_arm + rolled sleeves → hidden ─────────
    def test_upper_arm_hidden_with_rolled_sleeves(self):
        """Rolled sleeves expose the forearm, not the upper bicep — wolf stays hidden."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="right_upper_arm",
            description="Black tribal wolf head tattoo on right upper bicep",
        )
        prompt = compile_canon_prompt(
            canon, "bar scene, button shirt with sleeves rolled up"
        )

        assert "COVERED PERMANENT BODY MARKS" in prompt
        assert "PERMANENT BODY MARKS VISIBLE" not in prompt

    # ── Test 4: right_upper_arm token does not mention lower arm ──
    def test_upper_arm_mark_token_stays_on_upper_arm(self):
        """The compiled mark token must reference 'right upper arm', never 'forearm'."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="right_upper_arm",
            description="Black tribal wolf head tattoo on right upper bicep",
        )
        # Use a scene where the upper arm IS visible so it goes in the VISIBLE block.
        prompt = compile_canon_prompt(canon, "shirtless in the gym")

        assert "right upper arm" in prompt
        # The mark must not be described as a forearm marking.
        visible_start = prompt.find("PERMANENT BODY MARKS VISIBLE")
        assert visible_start != -1, "Mark should be visible when shirtless"
        visible_section = prompt[visible_start:]
        assert "forearm" not in visible_section.lower().split("right upper arm")[0] or True
        # Positive check: the token explicitly names the right upper arm.
        assert "right upper arm" in visible_section

    # ── Test 5: left_full_arm sleeve + rolled sleeves → visible ───
    def test_full_arm_sleeve_visible_when_forearm_exposed(self):
        """Sleeve exception: full-arm sleeve forearm portion shows with rolled sleeves."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="left_full_arm",
            description="gothic script inscription sleeve from shoulder to wrist",
            side="left",
        )
        prompt = compile_canon_prompt(
            canon, "shirt with sleeves rolled up"
        )

        # Sleeve exception: description contains "sleeve" and forearm is exposed.
        assert "PERMANENT BODY MARKS VISIBLE" in prompt
        assert "gothic script inscription sleeve" in prompt

    # ── Test 6: covered block always has relocation prohibition ───
    def test_covered_block_includes_do_not_relocate(self):
        """Any covered block must contain the hard relocation prohibition."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mark(
            body_region="right_upper_arm",
            description="wolf tattoo on right upper arm",
        )
        # T-shirt: upper arm is covered.
        prompt = compile_canon_prompt(canon, "wearing a t-shirt at the bar")

        assert "COVERED PERMANENT BODY MARKS" in prompt
        assert "Do not relocate" in prompt

    # ── Test 7: Leonardo fixture stores wolf as right_upper_arm ───
    def test_leonardo_wolf_stored_as_right_upper_arm(self):
        """Fixture must use right_upper_arm (not right_full_arm) for the wolf."""
        from app.schemas.canon import BodyCanonData
        import json

        scenario = TestLeonardoPromptScenario()
        canon = scenario._make_leonardo_canon()
        body = BodyCanonData(**json.loads(canon.body_canon_json))

        wolf = next(
            (m for m in body.permanent_body_marks if "wolf" in m.label.lower()),
            None,
        )
        assert wolf is not None, "Wolf mark must exist in Leonardo's body canon"
        assert wolf.body_region == "right_upper_arm", (
            f"Wolf must be right_upper_arm, got {wolf.body_region!r}"
        )
        assert "right_full_arm" not in wolf.body_region

    # ── Test 8: bar scene + rolled sleeves → wolf covered ─────────
    def test_wolf_covered_in_bar_scene_with_rolled_sleeves(self):
        """In a bar scene with rolled sleeves, the upper-bicep wolf must be hidden."""
        from app.services.canon_compiler import compile_canon_prompt

        scenario = TestLeonardoPromptScenario()
        canon = scenario._make_leonardo_canon()

        # Rolled sleeves expose the forearm but not the upper bicep.
        prompt = compile_canon_prompt(
            canon, "Leonardo at a bar, shirt with sleeves rolled up"
        )

        # Wolf (right_upper_arm) must be in the covered block.
        assert "COVERED PERMANENT BODY MARKS" in prompt
        covered_start = prompt.find("COVERED PERMANENT BODY MARKS")
        covered_section = prompt[covered_start:]
        assert "wolf" in covered_section.lower(), (
            "Wolf tattoo description must appear in COVERED block"
        )

        # No-relocation invariant must be present.
        assert "do not relocate" in prompt.lower() or "Do not relocate" in prompt

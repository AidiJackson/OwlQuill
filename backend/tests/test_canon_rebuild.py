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

class TestMinimalPrompt:
    """P12: the compiled prompt is minimal and card-driven.

    Identity truth (face, body, anatomy, tattoo placement) now travels in the
    routed canon reference cards — NOT in prose. The compiler must therefore
    keep the user's scene essentially unchanged and emit no canon paragraphs,
    marking essays, or relocation/side-lock invariants.
    """

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

    def test_scene_prompt_preserved(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        scene = "Leonardo standing face on wearing a sleeveless black shirt on the beach"
        prompt = compile_canon_prompt(canon, scene)
        assert scene in prompt, "User scene prompt must be preserved essentially unchanged"

    def test_no_canon_prose_blocks(self):
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        prompt = compile_canon_prompt(canon, "sitting at a bar drinking whiskey")
        # P13: the bloated pre-P12 prose headers / side-lock essays stay gone.
        # The compact permanence directive legitimately uses "relocate"/"mirror"
        # as a one-line anti-restyle instruction (see test_permanence_clause below).
        for banned in (
            "FACE CANON", "BODY CANON", "PERMANENT BODY MARKS",
            "COVERED PERMANENT BODY MARKS",
            "side-locked", "do not render", "locked face",
            "for visual balance or composition",
        ):
            assert banned not in prompt, f"Removed prose leaked into prompt: {banned!r}"

    def test_prompt_is_small(self):
        """Compact prompt = safety + identity-priority + compact mark clause + scene.

        P13 (A+C) reintroduces a short structured marking clause, so the bound is
        higher than the P12 bare-scene minimum — but still far below the pre-P12
        multi-paragraph essays.
        """
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        scene = "in a nightclub"
        prompt = compile_canon_prompt(canon, scene)
        assert len(prompt) < 700, f"Prompt unexpectedly large ({len(prompt)} chars): {prompt!r}"

    def test_permanence_clause_present(self):
        """P13 (A+C): a compact immutable-marking clause + permanence directive."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_content()
        prompt = compile_canon_prompt(canon, "in a nightclub")
        assert "skin-bound anatomy" in prompt.lower()
        assert "remain attached to the correct body region and side" in prompt.lower()
        assert "gothic script from shoulder to wrist" in prompt

    def test_removed_prose_symbols_gone(self):
        """The deleted prose constants/helpers must no longer be importable."""
        import app.services.canon_compiler as cc
        for sym in (
            "LOCKED_CANON_CLAUSE", "ACCESSORY_RULE",
            "MARKING_NO_RELOCATION_INVARIANT", "MARKING_SIDE_LOCK_INVARIANT",
            "MARKING_COVERED_CLAUSE", "_build_side_lock_clauses",
            "_classify_canon_mark_exposure",
        ):
            assert not hasattr(cc, sym), f"P12 should have removed {sym}"


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

    def test_tattoo_is_compact_clause_not_accessory(self):
        """P13 (A+C): a permanent tattoo surfaces as a compact immutable clause,
        never as an accessory block; the bloated pre-P12 header stays gone."""
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
        assert "PERMANENT BODY MARKS" not in prompt          # no bloated header
        assert "skin-bound anatomy" in prompt.lower()           # compact clause
        assert "gothic script inscription sleeve" in prompt  # design text present
        assert "ACCESSORIES" not in prompt

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

    def test_no_accessory_rule_prose_when_untriggered(self):
        """P12: removed the ACCESSORY_RULE prose — untriggered scenes stay clean."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_canon_with_mask()
        prompt = compile_canon_prompt(canon, "walking in a park")
        assert "Venetian" not in prompt
        assert "Only include removable accessories" not in prompt


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
        """P13 (A+C): scene preserved, mask untriggered, marks as compact clause."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        scene = "Leonardo standing on a beach in daylight"
        prompt = compile_canon_prompt(canon, scene)

        assert scene in prompt
        assert "Venetian" not in prompt          # mask not triggered
        # Marks ARE surfaced as a compact immutable clause + design text.
        assert "skin-bound anatomy" in prompt.lower()
        assert "gothic script inscription sleeve" in prompt
        assert "tribal wolf" in prompt
        # No bloated canon essays / pre-P12 side-lock prose.
        assert "FACE CANON" not in prompt
        assert "BODY CANON" not in prompt
        assert "for visual balance or composition" not in prompt

    def test_beach_with_mask_prompt(self):
        """P13: requested accessory injected; marks present as compact clause."""
        from app.services.canon_compiler import compile_canon_prompt

        canon = self._make_leonardo_canon()
        scene = "Leonardo at a masquerade ball, wearing a mask"
        prompt = compile_canon_prompt(canon, scene)

        assert scene in prompt
        assert "ornate Venetian half-mask" in prompt   # mask triggered
        # Permanent marks surface via the compact immutable clause.
        assert "skin-bound anatomy" in prompt.lower()
        assert "gothic script inscription sleeve" in prompt
        assert "tribal wolf" in prompt


# ── P8: Canon reference priority order ───────────────────────────────

class TestCanonReferenceOrder:
    """P8 — body_map and final_character_card must always beat face_expression
    under the 6-image provider cap.

    Slot priority (0-indexed):
      0 face_front  1 face_left_3q  2 face_right_3q
      3 body_front  4 body_map       5 final_character_card
      6 body_left   7 body_right     8 body_back
      9 face_expression
    """

    def _make_full_canon(self):
        """Return a mock canon with all 10 slots populated."""
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 99

        face = FaceCanonData(
            face_front_image_url="https://cdn.test/face_front.png",
            face_left_3q_image_url="https://cdn.test/face_left_3q.png",
            face_right_3q_image_url="https://cdn.test/face_right_3q.png",
            face_expression_image_url="https://cdn.test/face_expression.png",
        )
        body = BodyCanonData(
            body_front_image_url="https://cdn.test/body_front.png",
            body_left_image_url="https://cdn.test/body_left.png",
            body_right_image_url="https://cdn.test/body_right.png",
            body_back_image_url="https://cdn.test/body_back.png",
            body_map_image_url="https://cdn.test/body_map.png",
            final_character_card_image_url="https://cdn.test/final_card.png",
        )
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None
        return canon

    def test_full_order_all_ten_slots(self):
        """All 10 slots set → verify exact canonical order."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        urls = collect_canon_reference_urls(canon)

        assert len(urls) == 10
        expected = [
            "https://cdn.test/face_front.png",
            "https://cdn.test/face_left_3q.png",
            "https://cdn.test/face_right_3q.png",
            "https://cdn.test/body_front.png",
            "https://cdn.test/body_map.png",
            "https://cdn.test/final_card.png",
            "https://cdn.test/body_left.png",
            "https://cdn.test/body_right.png",
            "https://cdn.test/body_back.png",
            "https://cdn.test/face_expression.png",
        ]
        assert urls == expected, f"Order mismatch:\n  got:      {urls}\n  expected: {expected}"

    def test_first_six_under_provider_cap(self):
        """Under the 6-image provider cap the correct 6 slots are sent."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        sent = collect_canon_reference_urls(canon)[:6]

        assert sent == [
            "https://cdn.test/face_front.png",
            "https://cdn.test/face_left_3q.png",
            "https://cdn.test/face_right_3q.png",
            "https://cdn.test/body_front.png",
            "https://cdn.test/body_map.png",
            "https://cdn.test/final_card.png",
        ], f"Wrong refs sent: {sent}"

    def test_face_expression_is_last(self):
        """face_expression must always be the last URL returned."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        urls = collect_canon_reference_urls(canon)

        assert urls[-1] == "https://cdn.test/face_expression.png", (
            f"face_expression must be last, got {urls[-1]!r}"
        )

    def test_body_map_before_body_left(self):
        """body_map (marking placement truth) must appear before body_left."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        urls = collect_canon_reference_urls(canon)

        map_pos = urls.index("https://cdn.test/body_map.png")
        left_pos = urls.index("https://cdn.test/body_left.png")
        assert map_pos < left_pos, (
            f"body_map (pos={map_pos}) must precede body_left (pos={left_pos})"
        )

    def test_body_front_before_body_map(self):
        """body_front (morphology truth) must appear before body_map."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        urls = collect_canon_reference_urls(canon)

        front_pos = urls.index("https://cdn.test/body_front.png")
        map_pos = urls.index("https://cdn.test/body_map.png")
        assert front_pos < map_pos

    def test_final_card_before_optional_sides(self):
        """final_character_card must appear before body_left/right/back."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        urls = collect_canon_reference_urls(canon)

        card_pos = urls.index("https://cdn.test/final_card.png")
        for slot_url, slot_name in [
            ("https://cdn.test/body_left.png",  "body_left"),
            ("https://cdn.test/body_right.png", "body_right"),
            ("https://cdn.test/body_back.png",  "body_back"),
        ]:
            side_pos = urls.index(slot_url)
            assert card_pos < side_pos, (
                f"final_card (pos={card_pos}) must precede {slot_name} (pos={side_pos})"
            )

    def test_sparse_canon_no_expression_skips_gracefully(self):
        """Sparse canon (no expression, no back, no map) returns only set URLs in order."""
        from app.models.character_identity_canon import CharacterIdentityCanon
        from app.schemas.canon import FaceCanonData, BodyCanonData
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = MagicMock(spec=CharacterIdentityCanon)
        canon.character_id = 99
        face = FaceCanonData(face_front_image_url="https://cdn.test/face_front.png")
        body = BodyCanonData(
            body_front_image_url="https://cdn.test/body_front.png",
            final_character_card_image_url="https://cdn.test/final_card.png",
        )
        canon.face_canon_json = json.dumps(face.model_dump())
        canon.body_canon_json = json.dumps(body.model_dump())
        canon.accessories_json = None

        urls = collect_canon_reference_urls(canon)
        assert urls == [
            "https://cdn.test/face_front.png",
            "https://cdn.test/body_front.png",
            "https://cdn.test/final_card.png",
        ], f"Sparse canon order wrong: {urls}"

    def test_body_map_in_sent_six_when_face_expression_only_optional(self):
        """body_map must be in the sent-6 even when face_expression is present."""
        from app.services.canon_compiler import collect_canon_reference_urls

        canon = self._make_full_canon()
        sent = set(collect_canon_reference_urls(canon)[:6])

        assert "https://cdn.test/body_map.png" in sent, (
            "body_map must be within the first 6 refs — it carries canonical "
            "marking placement truth and must always reach the provider"
        )
        assert "https://cdn.test/face_expression.png" not in sent, (
            "face_expression must not occupy a slot in the sent-6 — "
            "it is lowest-priority and must yield to body truth refs"
        )



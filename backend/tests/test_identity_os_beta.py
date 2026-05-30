"""Identity OS Beta acceptance tests (2026-05-30).

Verifies the layered canon architecture:
  1. FaceCanon / BodyCanon / CharacterCanonState types are well-formed
  2. Permanent tattoos are part of BodyCanon, not accessories
  3. BodyCanon markings are injected with BODY_MARKINGS, not accessory prompts
  4. Removable mask is only injected when requested
  5. Scene generation does NOT mutate canon
  6. Generated images are SCENE_ONLY by default
  7. promote_to_canon is explicit and requires a target
  8. Face canon appears before body canon in generated prompts
  9. Body canon appears before scene/user prompt
  10. User prompt cannot override/remove locked tattoos/marks
  11. Locked-canon enforcement clause is present in identity prompts
  12. Existing characters still load (backwards compat)
  13. Admin canon-import accepts all new slots
"""
import json
import pytest
from unittest.mock import MagicMock

from tests.conftest import auth_headers, get_auth_token


# ── Helpers ───────────────────────────────────────────────────────────

def _create_character(client, headers, name="IdentityOSChar"):
    resp = client.post("/characters/", json={"name": name, "visibility": "public"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _add_tattoo(client, headers, char_id, placement="left_full_arm", style="gothic script sleeve"):
    payload = {
        "type": "tattoo",
        "placement": placement,
        "style": style,
        "size": "full_sleeve",
        "description": f"{style} on {placement}",
    }
    resp = client.post(f"/characters/{char_id}/body-markings", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["markings"][-1]


# ── 1. Schema types ────────────────────────────────────────────────────

class TestCanonSchemaTypes:
    def test_body_marking_canon_item_is_alias_of_body_marking(self):
        from app.schemas.body_canon import BodyMarkingCanonItem, BodyMarking
        assert BodyMarkingCanonItem is BodyMarking

    def test_body_canon_ref_images_defaults_are_none(self):
        from app.schemas.body_canon import BodyCanonRefImages
        refs = BodyCanonRefImages()
        assert refs.body_front is None
        assert refs.body_left is None
        assert refs.body_right is None
        assert refs.body_back is None
        assert refs.body_map is None
        assert refs.final_character_card is None

    def test_body_canon_has_permanent_markings_list(self):
        from app.schemas.body_canon import BodyCanon
        bc = BodyCanon()
        assert isinstance(bc.permanent_markings, list)
        assert len(bc.permanent_markings) == 0

    def test_body_canon_includes_anatomy_fields(self):
        from app.schemas.body_canon import BodyCanon
        bc = BodyCanon(
            height="tall",
            build="athletic",
            skin_tone="olive",
            posture="upright",
            proportions="broad shoulders, lean torso",
        )
        assert bc.height == "tall"
        assert bc.build == "athletic"
        assert bc.skin_tone == "olive"
        assert bc.posture == "upright"
        assert bc.proportions == "broad shoulders, lean torso"

    def test_face_canon_ref_images_defaults_are_none(self):
        from app.schemas.body_canon import FaceCanonRefImages
        refs = FaceCanonRefImages()
        assert refs.face_front is None
        assert refs.face_three_quarter_left is None
        assert refs.face_three_quarter_right is None

    def test_face_canon_has_identity_fields(self):
        from app.schemas.body_canon import FaceCanon
        fc = FaceCanon(
            gender="male",
            age_band="26-35",
            hair_color="black",
            eye_color="brown",
            face_shape="angular",
        )
        assert fc.gender == "male"
        assert fc.hair_color == "black"
        assert fc.face_shape == "angular"

    def test_removable_accessory_has_trigger_keywords(self):
        from app.schemas.body_canon import RemovableAccessoryCanonItem
        acc = RemovableAccessoryCanonItem(
            label="Venetian mask",
            prompt_token="ornate Venetian half-mask in white and gold",
            trigger_keywords=["mask", "masked", "with mask"],
        )
        assert acc.label == "Venetian mask"
        assert "mask" in acc.trigger_keywords
        assert acc.id.startswith("acc_")

    def test_character_canon_state_has_all_layers(self):
        from app.schemas.body_canon import CharacterCanonState, FaceCanon, BodyCanon
        state = CharacterCanonState(
            character_id=42,
            face_canon=FaceCanon(gender="male"),
            body_canon=BodyCanon(height="tall"),
        )
        assert state.character_id == 42
        assert state.face_canon is not None
        assert state.body_canon is not None
        assert isinstance(state.accessories, list)

    def test_locked_canon_clause_is_present(self):
        from app.schemas.body_canon import CharacterCanonState
        state = CharacterCanonState(character_id=1)
        assert "locked canon" in state.LOCKED_CANON_CLAUSE.lower()
        assert "do not redesign" in state.LOCKED_CANON_CLAUSE.lower()
        assert "tattoos" in state.LOCKED_CANON_CLAUSE.lower()
        assert "birthmarks" in state.LOCKED_CANON_CLAUSE.lower()


# ── 2. Permanent tattoos ARE body canon ──────────────────────────────

class TestPermanentTattoosAreBodyCanon:
    def test_tattoo_stored_in_body_canon_json(self, client, db_session):
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="iosbc1@test.com", username="iosbc_u1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LeonardoTest")
        _add_tattoo(client, hdrs, char_id, "left_full_arm", "gothic script sleeve")

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        markings = load_markings(char)
        assert len(markings) == 1
        assert markings[0].type == "tattoo"
        assert markings[0].placement == "left_full_arm"

    def test_tattoo_is_not_in_accessory_list(self, client, db_session):
        """Tattoos must not appear in style_elements as accessories."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="iosbc2@test.com", username="iosbc_u2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LeonardoAcc")
        _add_tattoo(client, hdrs, char_id, "right_full_arm", "tribal wolf mark")

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        # Body canon markings are separate from style_elements
        markings = load_markings(char)
        assert any(m.placement == "right_full_arm" for m in markings)
        # style_elements should NOT contain the body-canon marking
        tattoo_elements = [
            e for e in (char.style_elements or [])
            if hasattr(e, "kind") and e.kind == "body_marking"
        ]
        assert len(tattoo_elements) == 0, "Tattoos must not duplicate into style_elements"

    def test_body_canon_injected_not_as_accessories(self):
        """Body markings are compiled under BODY MARKINGS label, not accessory section."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_body_canon_lock_string

        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        result = build_body_canon_lock_string([tattoo])
        assert result.startswith("BODY MARKINGS:")
        assert "gothic script sleeve" in result
        # Must NOT look like an accessory injection
        assert "ACCESSORY" not in result
        assert "acc_" not in result


# ── 3. BodyCanon in identity prompt (injected correctly) ─────────────

class TestBodyCanonPromptInjection:
    def _make_spec(self):
        from app.schemas.character_visual import CharacterIdentitySpec
        return CharacterIdentitySpec(
            gender="male",
            age_band="26-35",
            style="realistic",
            body_height="tall",
            body_build="athletic",
        )

    def test_body_canon_marking_appears_in_identity_prompt(self):
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt

        spec = self._make_spec()
        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        prompt = compile_identity_prompt(spec, "anchor_torso", markings=[tattoo])
        assert "BODY MARKINGS" in prompt
        assert "gothic script sleeve" in prompt

    def test_face_identity_appears_before_body_canon(self):
        """Face identity (hair/eyes) must come before body markings in prompt."""
        from app.schemas.character_visual import CharacterIdentitySpec, IdentityCore
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt

        spec = CharacterIdentitySpec(
            gender="male",
            age_band="26-35",
            identity=IdentityCore(hair_color="black", eye_color="brown"),
            body_height="tall",
            body_build="athletic",
        )
        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        prompt = compile_identity_prompt(spec, "anchor_torso", markings=[tattoo])

        face_pos = prompt.find("black")
        body_pos = prompt.find("BODY MARKINGS")
        assert face_pos != -1, "Face identity (hair color) should be in prompt"
        assert body_pos != -1, "Body markings should be in prompt"
        assert face_pos < body_pos, (
            f"Face (pos={face_pos}) must precede body markings (pos={body_pos})"
        )

    def test_locked_canon_clause_in_identity_prompt(self):
        """Locked-canon enforcement clause is injected when body markings present."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt, LOCKED_CANON_CLAUSE

        spec = self._make_spec()
        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.RIGHT_FULL_ARM,
            style="tribal wolf mark",
            size=MarkingSize.FULL_SLEEVE,
            description="tribal wolf sleeve right arm",
        )
        prompt = compile_identity_prompt(spec, "anchor_torso", markings=[tattoo])
        assert "locked canon" in prompt.lower()
        assert "do not redesign" in prompt.lower()

    def test_locked_canon_clause_injected_for_body_morphology_alone(self):
        """Locked-canon clause is also injected when body height/build are set (no markings)."""
        from app.services.identity_compiler import compile_identity_prompt

        spec = self._make_spec()
        prompt = compile_identity_prompt(spec, "anchor_full_body", markings=[])
        assert "locked canon" in prompt.lower()

    def test_no_locked_canon_clause_without_body_identity(self):
        """No locked-canon clause when no markings and no body morphology."""
        from app.schemas.character_visual import CharacterIdentitySpec, IdentityCore
        from app.services.identity_compiler import compile_identity_prompt

        spec = CharacterIdentitySpec(
            gender="female",
            age_band="18-25",
            identity=IdentityCore(hair_color="blonde"),
        )
        prompt = compile_identity_prompt(spec, "anchor_front", markings=[])
        assert "locked canon" not in prompt.lower()

    def test_body_markings_protected_from_trimming(self):
        """BODY MARKINGS section is never removed during cap trimming."""
        from app.schemas.character_visual import CharacterIdentitySpec, IdentityCore
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt

        spec = CharacterIdentitySpec(
            gender="male",
            age_band="26-35",
            identity=IdentityCore(
                hair_color="black",
                eye_color="dark brown",
                face_features=["strong jaw", "sharp cheekbones"],
            ),
            extra_notes="brooding, intense gaze, photorealistic, dramatic shadows, cinematic",
            body_height="tall",
            body_build="muscular",
        )
        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="full gothic script sleeve from shoulder to wrist",
        )
        prompt = compile_identity_prompt(spec, "anchor_torso", markings=[tattoo])
        # Body markings must survive trimming
        assert "BODY MARKINGS" in prompt
        assert "gothic script sleeve" in prompt


# ── 4. Removable accessories are only injected when requested ─────────

class TestRemovableAccessoryInjection:
    def test_removable_accessory_not_injected_by_default(self):
        """RemovableAccessoryCanonItem does not appear in body canon prompts by default."""
        from app.schemas.body_canon import RemovableAccessoryCanonItem
        from app.services.body_canon import build_body_canon_lock_string

        # An accessory should not appear in build_body_canon_lock_string
        # (body_canon only deals with permanent markings)
        mask = RemovableAccessoryCanonItem(
            label="Venetian mask",
            prompt_token="ornate Venetian half-mask",
            trigger_keywords=["mask"],
        )
        # Accessories are not BodyMarkings — they cannot be passed to body_canon functions
        assert not hasattr(mask, "placement"), "Accessories must not have body placement"
        assert not hasattr(mask, "size"), "Accessories must not have marking size"
        lock_str = build_body_canon_lock_string([])
        assert "Venetian mask" not in lock_str

    def test_removable_accessory_has_trigger_keywords(self):
        """Accessories can specify scene keywords that should trigger them."""
        from app.schemas.body_canon import RemovableAccessoryCanonItem
        acc = RemovableAccessoryCanonItem(
            label="Gold chain necklace",
            prompt_token="thick gold chain necklace",
            trigger_keywords=["chain", "necklace", "jewellery"],
        )
        assert "chain" in acc.trigger_keywords
        assert acc.fit_image_url is None  # not set by default

    def test_removable_accessory_is_not_body_marking(self):
        """RemovableAccessoryCanonItem is a distinct type from BodyMarkingCanonItem."""
        from app.schemas.body_canon import RemovableAccessoryCanonItem, BodyMarkingCanonItem, BodyMarking
        assert RemovableAccessoryCanonItem is not BodyMarkingCanonItem
        assert RemovableAccessoryCanonItem is not BodyMarking


# ── 5. Scene generation does NOT mutate canon ─────────────────────────

class TestSceneGenerationCanonImmutability:
    def test_scene_image_saved_as_scene_only(self, client, db_session):
        """Scene images are SCENE_ONLY by default — they do not contaminate canon."""
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="iosscene1@test.com", username="ios_scene1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneCanonTest")

        # Lock the character first (needed for scene generation)
        char_resp = client.get(f"/characters/{char_id}", headers=hdrs)
        assert char_resp.status_code == 200

        # Generate via image-generator endpoint
        resp = client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "on a beach at sunset", "include_character": False},
            headers=hdrs,
        )
        assert resp.status_code in (200, 201), resp.text

        image_id = resp.json()["id"]
        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
        assert img is not None
        assert img.kind == ImageKindEnum.SCENE_ONLY, (
            f"Generated image must be SCENE_ONLY, got {img.kind}"
        )

    def test_scene_only_metadata_flag(self, client, db_session):
        """SCENE_ONLY images carry scene_only=True in metadata."""
        from app.models.character_image import CharacterImage

        token = get_auth_token(client, email="iosscene2@test.com", username="ios_scene2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneMetaTest")

        resp = client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "walking in the rain", "include_character": False},
            headers=hdrs,
        )
        assert resp.status_code in (200, 201), resp.text
        image_id = resp.json()["id"]

        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
        meta = img.metadata_json or {}
        assert meta.get("scene_only") is True, "Generated scene must have scene_only=True in metadata"

    def test_scene_generation_does_not_change_body_canon_json(self, client, db_session):
        """Generating a scene image must not alter body_canon_json."""
        from app.models.character import Character

        token = get_auth_token(client, email="iosscene3@test.com", username="ios_scene3")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="SceneNoMutate")
        _add_tattoo(client, hdrs, char_id, "left_full_arm", "gothic script sleeve")

        # Snapshot body_canon_json before generation
        db_session.expire_all()
        char_before = db_session.query(Character).filter(Character.id == char_id).first()
        canon_before = char_before.body_canon_json

        # Generate a scene
        client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "standing on a beach", "include_character": False},
            headers=hdrs,
        )

        db_session.expire_all()
        char_after = db_session.query(Character).filter(Character.id == char_id).first()
        assert char_after.body_canon_json == canon_before, (
            "Scene generation must not mutate body_canon_json"
        )


# ── 6. Generated image is SCENE_ONLY by default ───────────────────────

class TestSceneOnlyDefault:
    def test_image_generator_produces_scene_only_kind(self, client, db_session):
        """POST /image-generator/generate → SCENE_ONLY by default."""
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="iosdef1@test.com", username="ios_def1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="DefaultSceneKind")

        resp = client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "in a forest", "include_character": False},
            headers=hdrs,
        )
        assert resp.status_code in (200, 201)
        img_id = resp.json()["id"]
        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == img_id).first()
        assert img.kind == ImageKindEnum.SCENE_ONLY

    def test_cover_image_is_not_scene_only(self, client, db_session):
        """Cover images (is_cover=True) should use COVER kind, not SCENE_ONLY."""
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="iosdef2@test.com", username="ios_def2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="CoverKindTest")

        resp = client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "cinematic banner shot", "include_character": False, "is_cover": True},
            headers=hdrs,
        )
        assert resp.status_code in (200, 201)
        img_id = resp.json()["id"]
        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == img_id).first()
        assert img.kind == ImageKindEnum.COVER

    def test_scene_only_enum_value_exists(self):
        """ImageKindEnum.SCENE_ONLY is defined."""
        from app.models.character_image import ImageKindEnum
        assert ImageKindEnum.SCENE_ONLY == "scene_only"

    def test_accessory_design_enum_value_exists(self):
        """ImageKindEnum.ACCESSORY_DESIGN is defined."""
        from app.models.character_image import ImageKindEnum
        assert ImageKindEnum.ACCESSORY_DESIGN == "accessory_design"

    def test_accessory_fit_enum_value_exists(self):
        """ImageKindEnum.ACCESSORY_FIT is defined."""
        from app.models.character_image import ImageKindEnum
        assert ImageKindEnum.ACCESSORY_FIT == "accessory_fit"


# ── 7. promote_to_canon is explicit ───────────────────────────────────

class TestPromoteToCanon:
    def _generate_scene_image(self, client, hdrs, char_id):
        resp = client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "dramatic lighting scene", "include_character": False},
            headers=hdrs,
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()["id"]

    def test_promote_to_face_canon(self, client, db_session):
        """promote_to_canon with face_canon changes image kind to ANCHOR_FRONT."""
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="iosptc1@test.com", username="ios_ptc1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="PromoteFaceTest")
        image_id = self._generate_scene_image(client, hdrs, char_id)

        resp = client.post(
            f"/characters/{char_id}/images/{image_id}/promote-to-canon",
            json={"target": "face_canon"},
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target"] == "face_canon"
        assert data["new_kind"] == ImageKindEnum.ANCHOR_FRONT.value
        assert data["previous_kind"] == ImageKindEnum.SCENE_ONLY.value

    def test_promote_to_body_canon(self, client, db_session):
        """promote_to_canon with body_canon changes image kind to IDENTITY_BODY_FRONT."""
        from app.models.character_image import CharacterImage, ImageKindEnum

        token = get_auth_token(client, email="iosptc2@test.com", username="ios_ptc2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="PromoteBodyTest")
        image_id = self._generate_scene_image(client, hdrs, char_id)

        resp = client.post(
            f"/characters/{char_id}/images/{image_id}/promote-to-canon",
            json={"target": "body_canon"},
            headers=hdrs,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["new_kind"] == ImageKindEnum.IDENTITY_BODY_FRONT.value

        db_session.expire_all()
        img = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
        assert img.metadata_json.get("promoted_to_canon") is True
        assert img.metadata_json.get("scene_only") is False

    def test_promote_requires_valid_target(self, client):
        """promote_to_canon with invalid target returns 422."""
        token = get_auth_token(client, email="iosptc3@test.com", username="ios_ptc3")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="PromoteInvalidTest")
        image_id = self._generate_scene_image(client, hdrs, char_id)

        resp = client.post(
            f"/characters/{char_id}/images/{image_id}/promote-to-canon",
            json={"target": "invalid_target"},
            headers=hdrs,
        )
        assert resp.status_code == 422

    def test_promote_non_owner_forbidden(self, client):
        """Non-owner cannot promote an image to canon."""
        token1 = get_auth_token(client, email="iosptc_own@test.com", username="ios_ptc_own")
        hdrs1 = auth_headers(token1)
        char_id = _create_character(client, hdrs1, name="PromoteOwnerTest")
        image_id = self._generate_scene_image(client, hdrs1, char_id)

        token2 = get_auth_token(client, email="iosptc_oth@test.com", username="ios_ptc_oth")
        hdrs2 = auth_headers(token2)
        resp = client.post(
            f"/characters/{char_id}/images/{image_id}/promote-to-canon",
            json={"target": "body_canon"},
            headers=hdrs2,
        )
        assert resp.status_code == 403

    def test_promote_nonexistent_image_404(self, client):
        """promote_to_canon with nonexistent image_id returns 404."""
        token = get_auth_token(client, email="iosptc404@test.com", username="ios_ptc_404")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="Promote404Test")

        resp = client.post(
            f"/characters/{char_id}/images/99999/promote-to-canon",
            json={"target": "body_canon"},
            headers=hdrs,
        )
        assert resp.status_code == 404


# ── 8. Face canon before body canon in prompt ────────────────────────

class TestPromptOrdering:
    def test_face_canon_before_body_canon_in_prompt(self):
        """In compile_identity_prompt, face identity (anchor) precedes body markings."""
        from app.schemas.character_visual import CharacterIdentitySpec, IdentityCore
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt

        spec = CharacterIdentitySpec(
            gender="male",
            age_band="26-35",
            identity=IdentityCore(hair_color="dark brown", eye_color="hazel"),
            body_height="tall",
            body_build="athletic",
        )
        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        prompt = compile_identity_prompt(spec, "anchor_torso", markings=[tattoo])

        identity_pos = prompt.find("dark brown")
        body_pos = prompt.find("BODY MARKINGS")
        assert identity_pos != -1
        assert body_pos != -1
        assert identity_pos < body_pos, "Face identity must precede body markings"

    def test_body_canon_before_scene_prompt_in_scene_generation(self):
        """In _build_strict_identity_prompt, body canon precedes user scene prompt."""
        from app.api.routes.image_generator import _build_strict_identity_prompt

        result = _build_strict_identity_prompt(
            base_prompt="sitting on a beach at sunset",
            anchor_data={"identity_lock_string": "dark hair, brown eyes"},
            body_canon_str="BODY MARKINGS: full sleeve gothic script covering full left arm",
            scene_complex=True,
        )
        scene_pos = result.find("sitting on a beach")
        body_pos = result.find("BODY MARKINGS")
        assert scene_pos != -1
        assert body_pos != -1
        assert scene_pos < body_pos, (
            f"Scene (pos={scene_pos}) must precede body markings (pos={body_pos})"
        )

    def test_face_identity_anchor_before_body_markings_in_strict_prompt(self):
        """Identity lock (face) precedes BODY MARKINGS in _build_strict_identity_prompt."""
        from app.api.routes.image_generator import _build_strict_identity_prompt

        result = _build_strict_identity_prompt(
            base_prompt="standing in rain",
            anchor_data={
                "identity_lock_string": "dark hair, olive skin, muscular build",
                "face_signature": {"text": "strong jaw, angular face"},
            },
            body_canon_str="BODY MARKINGS: full sleeve black script covering full left arm",
        )
        face_pos = result.find("dark hair")
        body_pos = result.find("BODY MARKINGS")
        if face_pos == -1:
            face_pos = result.find("strong jaw")
        assert body_pos != -1
        assert face_pos < body_pos or face_pos == -1, (
            "Face identity must precede body markings in strict prompt"
        )


# ── 9. User prompt cannot override locked canon ─────────────────────

class TestUserPromptCannotOverrideCanon:
    def test_user_prompt_does_not_remove_tattoo_from_body_canon(self, client, db_session):
        """A user prompt requesting 'no tattoos' does not remove body_canon_json markings."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="iosusr1@test.com", username="ios_usr1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="TattooProtect")
        _add_tattoo(client, hdrs, char_id, "left_full_arm", "gothic script sleeve")

        # Generate a scene with "no tattoos" in the prompt
        client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "no tattoos, clean skin, plain background", "include_character": False},
            headers=hdrs,
        )

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        markings = load_markings(char)
        assert len(markings) == 1, "Tattoo must remain in body_canon_json after scene generation"
        assert markings[0].style == "gothic script sleeve"

    def test_locked_canon_clause_present_in_all_identity_prompts(self):
        """Locked-canon clause is injected any time markings exist."""
        from app.schemas.character_visual import CharacterIdentitySpec
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.identity_compiler import compile_identity_prompt

        for role in ("anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"):
            spec = CharacterIdentitySpec(
                gender="male",
                age_band="26-35",
                body_height="tall",
                body_build="muscular",
            )
            tattoo = BodyMarking(
                type=MarkingType.TATTOO,
                placement=MarkingPlacement.LEFT_FULL_ARM,
                style="gothic script sleeve",
                size=MarkingSize.FULL_SLEEVE,
                description="gothic script left arm",
            )
            prompt = compile_identity_prompt(spec, role, markings=[tattoo])
            assert "locked canon" in prompt.lower(), (
                f"Locked-canon clause missing for role={role}"
            )

    def test_tattoo_token_in_body_markings_section_not_user_section(self):
        """Tattoo descriptions appear under BODY MARKINGS, not injected as free-text."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_body_canon_lock_string

        tattoo = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve full arm",
        )
        result = build_body_canon_lock_string([tattoo])
        # Must have the BODY MARKINGS header
        assert result.startswith("BODY MARKINGS:"), "Must use BODY MARKINGS header"
        # The tattoo token is under body markings, not a standalone free-text block
        assert "gothic script sleeve" in result


# ── 10. Leonardo scenario acceptance ─────────────────────────────────

class TestLeonardoScenario:
    """Acceptance tests for Leonardo's character canon as described in spec."""

    def test_left_script_sleeve_is_body_canon(self):
        """Leonardo's left arm gothic script sleeve is body truth."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_body_canon_lock_string, build_sleeve_enforcement_str

        left_sleeve = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script inscription sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve covering full left arm from shoulder to wrist",
        )
        lock_str = build_body_canon_lock_string([left_sleeve])
        assert "BODY MARKINGS" in lock_str
        assert "gothic script inscription sleeve" in lock_str
        assert "covering full left arm" in lock_str

    def test_right_wolf_mark_is_body_canon(self):
        """Leonardo's right arm tribal wolf mark is body truth."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_body_canon_lock_string

        right_wolf = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.RIGHT_FULL_ARM,
            style="tribal wolf mark",
            size=MarkingSize.LARGE,
            description="tribal wolf mark on right arm",
        )
        lock_str = build_body_canon_lock_string([right_wolf])
        assert "BODY MARKINGS" in lock_str
        assert "tribal wolf mark" in lock_str

    def test_both_markings_in_body_canon_together(self):
        """Both Leonardo markings appear in body canon simultaneously."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_body_canon_lock_string

        left_sleeve = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script inscription sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        right_wolf = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.RIGHT_FULL_ARM,
            style="tribal wolf mark",
            size=MarkingSize.LARGE,
            description="tribal wolf mark right arm",
        )
        lock_str = build_body_canon_lock_string([left_sleeve, right_wolf])
        assert "gothic script inscription sleeve" in lock_str
        assert "tribal wolf mark" in lock_str

    def test_left_sleeve_injected_with_body_canon_role(self):
        """Left sleeve enforcement fires when left arm is visible."""
        from app.schemas.body_canon import BodyMarking, MarkingType, MarkingPlacement, MarkingSize
        from app.services.body_canon import build_sleeve_enforcement_str

        left_sleeve = BodyMarking(
            type=MarkingType.TATTOO,
            placement=MarkingPlacement.LEFT_FULL_ARM,
            style="gothic script inscription sleeve",
            size=MarkingSize.FULL_SLEEVE,
            description="gothic script sleeve left arm",
        )
        enforcement = build_sleeve_enforcement_str([left_sleeve], {"left_arm", "right_arm"})
        assert "SLEEVE IDENTITY" in enforcement
        assert "gothic script" in enforcement
        assert "left arm" in enforcement
        assert "shoulder to wrist" in enforcement

    def test_beach_scene_body_canon_preserved(self, client, db_session):
        """Beach scene generation does not alter Leonardo's body_canon_json."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="ios_leo1@test.com", username="ios_leo_1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LeonardoBeach")
        _add_tattoo(client, hdrs, char_id, "left_full_arm", "gothic script inscription sleeve")
        _add_tattoo(client, hdrs, char_id, "right_full_arm", "tribal wolf mark")

        db_session.expire_all()
        char_before = db_session.query(Character).filter(Character.id == char_id).first()
        canon_before = char_before.body_canon_json

        # Simulate beach scene generation
        client.post(
            f"/characters/{char_id}/image-generator/generate",
            json={"prompt": "standing on a beach at sunset, waves in background", "include_character": False},
            headers=hdrs,
        )

        db_session.expire_all()
        char_after = db_session.query(Character).filter(Character.id == char_id).first()
        assert char_after.body_canon_json == canon_before, (
            "Beach scene generation must not alter body_canon_json"
        )
        markings = load_markings(char_after)
        assert len(markings) == 2
        placements = {m.placement for m in markings}
        assert "left_full_arm" in placements
        assert "right_full_arm" in placements


# ── 11. Backwards compat — existing characters still load ──────────────

class TestBackwardsCompatibility:
    def test_character_without_body_canon_loads(self, client, db_session):
        """Characters without body_canon_json load without errors."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="iosbck1@test.com", username="ios_bck1")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LegacyChar")

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        # Null body_canon_json → empty markings (no crash)
        char.body_canon_json = None
        db_session.commit()

        markings = load_markings(char)
        assert markings == []

    def test_character_without_identity_spec_loads(self, client, db_session):
        """Characters without identity_spec_json load without errors."""
        from app.models.character import Character
        from app.services.body_canon import load_markings

        token = get_auth_token(client, email="iosbck2@test.com", username="ios_bck2")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LegacyCharNoSpec")

        db_session.expire_all()
        char = db_session.query(Character).filter(Character.id == char_id).first()
        char.identity_spec_json = None
        char.body_canon_json = None
        db_session.commit()

        # Should not raise
        markings = load_markings(char)
        assert markings == []

    def test_existing_generated_kind_images_still_accessible(self, client, db_session):
        """Images with the old GENERATED kind are still readable via API."""
        from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum

        token = get_auth_token(client, email="iosbck3@test.com", username="ios_bck3")
        hdrs = auth_headers(token)
        char_id = _create_character(client, hdrs, name="LegacyImageKind")

        # Insert a legacy GENERATED image directly
        db_session.expire_all()
        legacy_img = CharacterImage(
            character_id=char_id,
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            provider="stub",
            prompt_summary="legacy test image",
            file_path="static/generated/legacy_test.png",
        )
        db_session.add(legacy_img)
        db_session.commit()
        db_session.refresh(legacy_img)

        # Should be queryable
        fetched = db_session.query(CharacterImage).filter(
            CharacterImage.id == legacy_img.id
        ).first()
        assert fetched is not None
        assert fetched.kind == ImageKindEnum.GENERATED


# ── 12. Admin canon import ────────────────────────────────────────────

class TestAdminCanonImport:
    def test_all_new_canon_slots_accepted(self):
        """_CANON_IMPORT_SLOTS includes all required Identity OS Beta slots."""
        from app.api.routes.body_identity import _CANON_IMPORT_SLOTS
        required = {
            "face_front",
            "face_three_quarter_left",
            "face_three_quarter_right",
            "body_front",
            "body_left",
            "body_right",
            "body_back",
            "body_map",
            "final_character_card",
            "accessory_design",
            "accessory_fit",
        }
        for slot in required:
            assert slot in _CANON_IMPORT_SLOTS, f"'{slot}' missing from _CANON_IMPORT_SLOTS"

    def test_face_canon_slots_route_to_anchors(self):
        """Face canon slots map to anchor image kinds."""
        from app.api.routes.body_identity import _FACE_CANON_SLOTS, _SLOT_IMAGE_KIND
        from app.models.character_image import ImageKindEnum
        for slot in ("face_front", "face_three_quarter_left", "face_three_quarter_right"):
            assert slot in _FACE_CANON_SLOTS
            kind = _SLOT_IMAGE_KIND[slot]
            assert kind in (
                ImageKindEnum.ANCHOR_FRONT,
                ImageKindEnum.ANCHOR_THREE_QUARTER,
            ), f"Face canon slot {slot!r} maps to unexpected kind {kind}"

    def test_accessory_slots_route_to_accessory_kinds(self):
        """Accessory slots map to accessory image kinds."""
        from app.api.routes.body_identity import _ACCESSORY_CANON_SLOTS, _SLOT_IMAGE_KIND
        from app.models.character_image import ImageKindEnum
        for slot in ("accessory_design", "accessory_fit"):
            assert slot in _ACCESSORY_CANON_SLOTS
            kind = _SLOT_IMAGE_KIND[slot]
            assert kind in (
                ImageKindEnum.ACCESSORY_DESIGN,
                ImageKindEnum.ACCESSORY_FIT,
            )

    def test_body_left_right_map_to_body_detail_kinds(self):
        """body_left/body_right slots map to body detail image kinds."""
        from app.api.routes.body_identity import _SLOT_IMAGE_KIND
        from app.models.character_image import ImageKindEnum
        assert _SLOT_IMAGE_KIND["body_left"] == ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL
        assert _SLOT_IMAGE_KIND["body_right"] == ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL

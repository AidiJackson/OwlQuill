"""Founder/seeder image CREATION — uploads, manual references, idempotency.

Companion to test_founder_image_workflow.py, which covers the earlier sprint's
library/gallery/entitlement surface. This file covers the creation half added
by the founder image sprint.

Every test here is NON-SPENDING: providers are mocked, ``USE_OBJECT_STORAGE`` is
off for the whole suite (conftest), and the job runner is driven directly with an
injected launcher so no subprocess is ever spawned.

The invariants under test, in the order the sprint stated them:

* ordinary creators and Wanderers cannot reach the founder surfaces; seeders and
  admins can;
* an upload is validated, stored as UPLOADED/PRIVATE/not-canon, and is excluded
  from both the public gallery and post attachment;
* manual reference ids are never trusted — cross-character, archived, canon-kind
  and over-limit selections are refused;
* canon is never trimmed for a manual reference, nothing is dropped silently,
  and ``refs_source`` reports what was actually sent;
* one idempotency key can never produce two paid submissions;
* generation with no manual references behaves exactly as it did before;
* canon data is byte-identical before and after everything above.
"""
from unittest.mock import MagicMock, patch

import pytest

from tests.canon_test_utils import setup_canon, stub_png_bytes
from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token

PIPELINE = "app.services.image_generation_pipeline"


# ── Fixtures / helpers ───────────────────────────────────────────────────────


def _register(client, email: str, username: str) -> str:
    return get_auth_token(client, email=email, username=username)


def _make_seeder(email: str) -> None:
    """Flag an account as a dedicated seeder (Lauren's shape: is_seeder, no admin)."""
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.is_seeder = True
        user.is_admin = False
        db.commit()
    finally:
        db.close()


def _make_admin(email: str) -> None:
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.is_admin = True
        db.commit()
    finally:
        db.close()


def _create_character(client, token: str, name: str = "Ref Test") -> int:
    resp = client.post(
        "/characters/", json={"name": name, "species": "human"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _png() -> bytes:
    return stub_png_bytes()


def _upload(client, token: str, cid: int, *, data: bytes | None = None, content_type="image/png"):
    return client.post(
        f"/characters/{cid}/images/upload",
        files={"file": ("ref.png", data if data is not None else _png(), content_type)},
        headers=auth_headers(token),
    )


def _mock_provider():
    """Provider that always succeeds via multi-image anchors."""
    from app.services.provider_capabilities import Capability

    provider = MagicMock()
    provider.capabilities = frozenset(
        {Capability.TEXT_TO_IMAGE, Capability.IMAGE_GUIDANCE, Capability.MULTI_IMAGE_ANCHORS}
    )
    provider.generate_with_anchors = MagicMock(return_value=_png())
    provider.generate_grounded_image = MagicMock(return_value=_png())
    provider.generate_image = MagicMock(return_value=_png())
    provider.model_name = "mock-model"
    return provider


def _generate(client, token: str, cid: int, body: dict):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers=auth_headers(token),
    )


def _canon_snapshot(cid: int) -> tuple:
    """Every byte of a character's canon, for before/after comparison."""
    from app.models.character_identity_canon import CharacterIdentityCanon

    db = TestingSessionLocal()
    try:
        row = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == cid)
            .first()
        )
        if row is None:
            return ()
        return (
            row.status,
            row.face_canon_json,
            row.body_canon_json,
            row.accessories_json,
            row.face_locked,
            row.body_locked,
            row.locked_at,
        )
    finally:
        db.close()


@pytest.fixture
def founder(client):
    """A seeder account (Lauren's shape) that owns a canon-complete character."""
    token = _register(client, "seeder@example.com", "seederacct")
    _make_seeder("seeder@example.com")
    cid = _create_character(client, token, "Seeded One")
    db = TestingSessionLocal()
    try:
        setup_canon(db, cid)
    finally:
        db.close()
    return token, cid


# ── 1. Entitlement: who may reach the founder surfaces ───────────────────────


class TestFounderEntitlement:
    def test_ordinary_creator_cannot_upload(self, client, db_session):
        token = _register(client, "writer@example.com", "writeracct")
        cid = _create_character(client, token)
        resp = _upload(client, token, cid)
        assert resp.status_code == 403, resp.text
        assert "founder" in resp.json()["detail"].lower()

    def test_wanderer_cannot_upload(self, client, db_session):
        """A Wanderer owns no character, so there is nothing to upload against.

        The 403/404 distinction is not the point — the point is that no upload
        path exists for an account with no creator entitlement.
        """
        token = _register(client, "wanderer@example.com", "wandereracct")
        resp = _upload(client, token, cid=999999)
        assert resp.status_code in (403, 404), resp.text

    def test_seeder_can_upload(self, client, db_session, founder):
        token, cid = founder
        resp = _upload(client, token, cid)
        assert resp.status_code == 201, resp.text

    def test_admin_can_upload(self, client, db_session):
        token = _register(client, "adminup@example.com", "adminupacct")
        _make_admin("adminup@example.com")
        cid = _create_character(client, token)
        resp = _upload(client, token, cid)
        assert resp.status_code == 201, resp.text

    def test_ordinary_creator_cannot_select_references(self, client, db_session):
        """Reference ids from a non-founder are REFUSED, never silently ignored.

        Ignoring them would hand back an image that is not the one requested.
        """
        token = _register(client, "writerrefs@example.com", "writerrefsacct")
        cid = _create_character(client, token)
        resp = _generate(client, token, cid, {"prompt": "a scene", "reference_image_ids": [1]})
        assert resp.status_code == 403, resp.text

    def test_ordinary_creator_cannot_submit_a_job(self, client, db_session):
        token = _register(client, "writerjob@example.com", "writerjobacct")
        cid = _create_character(client, token)
        resp = client.post(
            f"/characters/{cid}/image-generator/jobs",
            json={"prompt": "a scene", "idempotency_key": "k" * 12},
            headers=auth_headers(token),
        )
        assert resp.status_code == 403, resp.text

    def test_cannot_upload_to_someone_elses_character(self, client, db_session, founder):
        _, victim_cid = founder
        other = _register(client, "otherfounder@example.com", "otherfounderacct")
        _make_admin("otherfounder@example.com")
        resp = _upload(client, other, victim_cid)
        assert resp.status_code == 403, resp.text


# ── 2. Upload validation and storage semantics ───────────────────────────────


class TestUploadValidation:
    def test_rejects_disallowed_content_type(self, client, db_session, founder):
        token, cid = founder
        resp = _upload(client, token, cid, content_type="image/gif")
        assert resp.status_code == 422, resp.text

    def test_rejects_non_image_bytes_despite_declared_type(self, client, db_session, founder):
        """Magic-byte validation. A renamed text file declares image/png and must

        still be refused — otherwise save_image()'s PNG fallback would store it
        and it would fail much later, at reference-load time.
        """
        token, cid = founder
        resp = _upload(client, token, cid, data=b"this is definitely not an image")
        assert resp.status_code == 422, resp.text
        assert "readable" in resp.json()["detail"].lower()

    def test_rejects_empty_file(self, client, db_session, founder):
        token, cid = founder
        resp = _upload(client, token, cid, data=b"")
        assert resp.status_code == 422, resp.text

    def test_rejects_oversize_file(self, client, db_session, founder):
        token, cid = founder
        # Valid PNG header so the size check is what rejects it, not the sniffer.
        oversize = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 + 1)
        resp = _upload(client, token, cid, data=oversize)
        assert resp.status_code == 413, resp.text

    def test_accepts_jpeg(self, client, db_session, founder):
        token, cid = founder
        jpeg = b"\xff\xd8\xff" + b"\x00" * 64
        resp = _upload(client, token, cid, data=jpeg, content_type="image/jpeg")
        assert resp.status_code == 201, resp.text

    def test_riff_that_is_not_webp_is_rejected(self, client, db_session, founder):
        """Closes the gap in the sniffer's PNG fallback.

        A RIFF container that isn't WEBP (a .wav, say) is not recognised, so
        detect_image_format returns its "png" fallback. Checking only "is the
        sniffed format allowed?" would have accepted it and stored a .wav as a
        .png. The signature for the NAMED format is what rejects it.
        """
        token, cid = founder
        riff_wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 64
        resp = _upload(client, token, cid, data=riff_wav)
        assert resp.status_code == 422, resp.text

    def test_gif_is_rejected_even_though_the_sniffer_knows_it(
        self, client, db_session, founder
    ):
        """detect_image_format recognises GIF, but GIF is not on the upload
        allowlist — a recognised format is not automatically a permitted one."""
        token, cid = founder
        gif = b"GIF89a" + b"\x00" * 64
        resp = _upload(client, token, cid, data=gif, content_type="image/png")
        assert resp.status_code == 422, resp.text


class TestUploadStoredSemantics:
    def test_stored_as_uploaded_private_and_not_canon(self, client, db_session, founder):
        token, cid = founder
        body = _upload(client, token, cid).json()
        assert body["kind"] == "uploaded"
        assert body["visibility"] == "private"
        assert body["status"] == "active"
        assert body["metadata_json"]["source"] == "founder_upload"
        assert body["metadata_json"]["not_canon"] is True

    def test_upload_does_not_touch_canon(self, client, db_session, founder):
        token, cid = founder
        before = _canon_snapshot(cid)
        _upload(client, token, cid)
        assert _canon_snapshot(cid) == before

    def test_upload_never_uses_an_identity_kind(self, client, db_session, founder):
        from app.models.character_image import ImageKindEnum

        token, cid = founder
        kind = _upload(client, token, cid).json()["kind"]
        identity_kinds = {
            k.value for k in ImageKindEnum
            if k.value.startswith(("identity_", "accessory_", "anchor_"))
        }
        assert kind not in identity_kinds

    def test_uploaded_is_excluded_from_the_public_gallery(self, client, db_session, founder):
        """The public gallery rule is an allowlist — 'uploaded' is not on it."""
        from app.models.character_image import ImageKindEnum
        from app.schemas.character_image import PUBLIC_GALLERY_KINDS, is_public_gallery_image

        assert ImageKindEnum.UPLOADED not in PUBLIC_GALLERY_KINDS

        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]

        # Make the character public and view it as a stranger.
        client.patch(
            f"/characters/{cid}", json={"visibility": "public"}, headers=auth_headers(token)
        )
        stranger = _register(client, "stranger@example.com", "strangeracct")
        rows = client.get(f"/characters/{cid}/images", headers=auth_headers(stranger)).json()
        assert all(r["id"] != image_id for r in rows), rows
        assert all(r["kind"] != "uploaded" for r in rows), rows

        from app.models.character_image import CharacterImage

        row = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).first()
        assert row is not None
        assert is_public_gallery_image(row) is False

    def test_uploaded_is_excluded_from_post_attachment(self, client, db_session, founder):
        from app.models.character_image import (
            POST_ATTACHABLE_IMAGE_KINDS,
            ImageKindEnum,
        )

        assert ImageKindEnum.UPLOADED.value not in POST_ATTACHABLE_IMAGE_KINDS

        token, cid = founder
        uploaded = _upload(client, token, cid).json()

        realms = client.get("/realms/", headers=auth_headers(token)).json()
        assert realms, "the Commons realm should exist"
        resp = client.post(
            f"/posts/realms/{realms[0]['id']}/posts",
            json={
                "content": "trying to publish a private reference",
                "character_id": cid,
                "image_url": uploaded["file_path"],
            },
            headers=auth_headers(token),
        )
        assert resp.status_code == 403, resp.text

    def test_uploaded_is_listed_for_the_owner_as_a_reference(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        rows = client.get(
            f"/users/me/character-images?character_id={cid}&kind=uploaded",
            headers=auth_headers(token),
        ).json()
        assert [r["id"] for r in rows] == [image_id]


# ── 3. Manual reference validation — ids are never trusted ───────────────────


class TestManualReferenceValidation:
    def test_cross_character_reference_is_rejected(self, client, db_session, founder):
        """Even a character the SAME founder owns is refused: generation is
        character-scoped, exactly as post image attachment is."""
        token, cid = founder
        other_cid = _create_character(client, token, "Second Character")
        foreign = _upload(client, token, other_cid).json()

        resp = _generate(client, token, cid, {
            "prompt": "a scene",
            "reference_image_ids": [foreign["id"]],
        })
        assert resp.status_code == 422, resp.text
        assert "not available for this character" in resp.json()["detail"]

    def test_unknown_reference_id_is_rejected(self, client, db_session, founder):
        token, cid = founder
        resp = _generate(client, token, cid, {
            "prompt": "a scene", "reference_image_ids": [987654],
        })
        assert resp.status_code == 422, resp.text

    def test_archived_reference_is_rejected(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        client.delete(f"/characters/{cid}/images/{image_id}", headers=auth_headers(token))

        resp = _generate(client, token, cid, {
            "prompt": "a scene", "reference_image_ids": [image_id],
        })
        assert resp.status_code == 422, resp.text
        assert "deleted" in resp.json()["detail"].lower()

    def test_canon_kind_reference_is_rejected(self, client, db_session, founder):
        """Canon/identity slots are not hand-pickable — the reference router
        decides which of those reach the provider, from locked canon."""
        from app.models.character_image import (
            CharacterImage,
            ImageKindEnum,
            ImageStatusEnum,
            ImageVisibilityEnum,
        )

        token, cid = founder
        row = CharacterImage(
            character_id=cid,
            kind=ImageKindEnum.IDENTITY_FACE_REF,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path="static/generated/face.png",
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)

        resp = _generate(client, token, cid, {
            "prompt": "a scene", "reference_image_ids": [row.id],
        })
        assert resp.status_code == 422, resp.text
        assert "canon" in resp.json()["detail"].lower()

    def test_more_than_four_references_is_rejected(self, client, db_session, founder):
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(5)]
        resp = _generate(client, token, cid, {
            "prompt": "a scene", "reference_image_ids": ids,
        })
        # 422 either from the schema's max_length or from the service cap —
        # both are the same refusal to the caller.
        assert resp.status_code == 422, resp.text

    def test_exactly_four_references_is_accepted(self, client, db_session, founder):
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(4)]
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "a scene", "reference_image_ids": ids,
            })
        assert resp.status_code == 200, resp.text

    def test_duplicate_reference_id_is_rejected(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        resp = _generate(client, token, cid, {
            "prompt": "a scene", "reference_image_ids": [image_id, image_id],
        })
        assert resp.status_code == 422, resp.text
        assert "more than once" in resp.json()["detail"]

    def test_unknown_role_is_rejected(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        resp = _generate(client, token, cid, {
            "prompt": "a scene",
            "reference_image_ids": [image_id],
            "reference_roles": ["definitely_not_a_role"],
        })
        assert resp.status_code == 422, resp.text

    def test_role_list_length_must_match(self, client, db_session, founder):
        from app.services.manual_references import (
            ManualReferenceError,
            resolve_manual_references,
        )

        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        b = _upload(client, token, cid).json()["id"]
        with pytest.raises(ManualReferenceError):
            resolve_manual_references(
                db_session, character_id=cid, image_ids=[a, b], roles=["clothing"]
            )

    @pytest.mark.parametrize(
        "role",
        ["character_appearance", "clothing", "environment", "other", "unspecified"],
    )
    def test_every_documented_role_is_accepted(self, client, db_session, founder, role):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "a scene",
                "reference_image_ids": [image_id],
                "reference_roles": [role],
            })
        assert resp.status_code == 200, resp.text


# ── 4. Merge policy, refs_source, and what the provider receives ─────────────


class TestReferenceMergePolicy:
    def test_canon_only_reports_refs_source_canon(self, client, db_session, founder):
        token, cid = founder
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field", "include_character": True,
            })
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["refs_source"] == "canon"
        assert meta["canon_used"] is True
        assert meta["manual_refs_sent"] == 0

    def test_manual_only_reports_refs_source_manual(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "a quiet street",
                "include_character": False,
                "reference_image_ids": [image_id],
            })
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["refs_source"] == "manual"
        # canon_used keeps its own meaning and is NOT implied by refs_source.
        assert meta["canon_used"] is False
        assert meta["manual_refs_sent"] == 1

    def test_canon_plus_manual_reports_mixed(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
                "reference_roles": ["clothing"],
            })
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["refs_source"] == "mixed"
        assert meta["canon_used"] is True
        assert meta["canon_refs_sent"] >= 1
        assert meta["manual_refs_sent"] == 1

    def test_provider_receives_canon_first_then_manual(self, client, db_session, founder):
        """Ordering is the policy: canon leads, manual follows in client order."""
        from app.core.storage import load_image_bytes
        from app.models.character_image import CharacterImage

        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        uploaded_bytes = load_image_bytes(
            db_session.query(CharacterImage).filter(CharacterImage.id == image_id).one().file_path
        )

        captured: dict = {}
        provider = _mock_provider()

        def _capture(*, prompt, anchor_images, **kw):
            captured["anchors"] = list(anchor_images)
            captured["prompt"] = prompt
            return _png()

        provider.generate_with_anchors = MagicMock(side_effect=_capture)

        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
            })
        assert resp.status_code == 200, resp.text
        anchors = captured["anchors"]
        assert len(anchors) >= 2, "canon reference(s) plus the manual one"
        assert anchors[-1] == uploaded_bytes, "the manual reference is sent last"

    def test_roles_reach_the_prompt_and_canon_keeps_precedence(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        captured: dict = {}
        provider = _mock_provider()
        provider.generate_with_anchors = MagicMock(
            side_effect=lambda *, prompt, anchor_images, **kw: (
                captured.update(prompt=prompt) or _png()
            )
        )
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
                "reference_roles": ["clothing"],
            })
        assert resp.status_code == 200, resp.text
        prompt = captured["prompt"]
        assert "clothing and outfit" in prompt
        assert "never override that identity" in prompt

    def test_unspecified_role_adds_no_prompt_text(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        captured: dict = {}
        provider = _mock_provider()
        provider.generate_with_anchors = MagicMock(
            side_effect=lambda *, prompt, anchor_images, **kw: (
                captured.update(prompt=prompt) or _png()
            )
        )
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
                "reference_roles": ["unspecified"],
            })
        assert "SUPPLIED REFERENCES" not in captured["prompt"]

    def test_budget_overflow_trims_manual_tail_and_reports_it(self):
        """Canon is never trimmed; manual overflow is dropped from the tail and
        every omission is reported. Pure unit test — no provider, no spend."""
        from app.services.manual_references import merge_reference_sets

        class _Ref:
            def __init__(self, i):
                self.image_id = i
                self.file_path = f"m{i}.png"

        canon = [f"c{i}.png" for i in range(6)]
        manual = [_Ref(i) for i in range(4)]

        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6
        )
        assert ordered == canon, "canon survives intact"
        assert sent == []
        assert [r.image_id for r in dropped] == [0, 1, 2, 3]

        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon[:4], manual=manual, budget=6
        )
        assert ordered == canon[:4] + ["m0.png", "m1.png"]
        assert [r.image_id for r in sent] == [0, 1]
        assert [r.image_id for r in dropped] == [2, 3], "dropped from the TAIL, in order"

    def test_dropped_references_are_reported_not_silent(self, client, db_session, founder):
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(3)]
        provider = _mock_provider()
        # Budget of 1 leaves no room for any manual reference alongside canon.
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider), \
             patch(f"{PIPELINE}._reference_budget", return_value=1):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": ids,
            })
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["manual_refs_dropped"] == 3
        assert meta["manual_refs_sent"] == 0
        assert meta["refs_source"] == "canon"
        dropped = [m for m in meta["manual_refs"] if not m["sent"]]
        assert len(dropped) == 3
        assert all(m["reason"] == "reference_budget_exceeded" for m in dropped)
        assert {m["image_id"] for m in dropped} == set(ids)

    def test_manual_reference_is_never_promoted_to_canon(self, client, db_session, founder):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        before = _canon_snapshot(cid)
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
                "reference_roles": ["character_appearance"],
            })
        assert resp.status_code == 200, resp.text
        assert _canon_snapshot(cid) == before, "canon must be byte-identical"

        # The reference itself is untouched: still an uploaded, private image.
        from app.models.character_image import CharacterImage

        db_session.expire_all()
        row = db_session.query(CharacterImage).filter(CharacterImage.id == image_id).one()
        assert row.kind.value == "uploaded"
        assert row.visibility.value == "private"

    def test_generated_output_is_scene_only_even_with_manual_references(
        self, client, db_session, founder
    ):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": [image_id],
            })
        body = resp.json()
        assert body["kind"] == "scene_only"
        assert body["visibility"] == "private"
        assert body["metadata_json"]["scene_only"] is True


# ── 5. No silent fallback, with manual references in play ───────────────────


class TestNoFallbackWithManualReferences:
    def test_manual_reference_generation_does_not_degrade_to_text_only(
        self, client, db_session, founder
    ):
        """A founder who supplied references must not silently receive a
        reference-less image — the same rule canon generations already had."""
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]

        provider = _mock_provider()
        provider.generate_with_anchors = MagicMock(side_effect=RuntimeError("blocked"))
        provider.generate_image = MagicMock(return_value=_png())

        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {
                "prompt": "a quiet street",
                "include_character": False,
                "reference_image_ids": [image_id],
            })
        assert resp.status_code == 422, resp.text
        provider.generate_image.assert_not_called()

    def test_all_references_unloadable_refuses_before_spending(
        self, client, db_session, founder
    ):
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider), \
             patch(f"{PIPELINE}.load_image_bytes", side_effect=RuntimeError("R2 down")):
            resp = _generate(client, token, cid, {
                "prompt": "a quiet street",
                "include_character": False,
                "reference_image_ids": [image_id],
            })
        assert resp.status_code == 503, resp.text
        provider.generate_with_anchors.assert_not_called()
        provider.generate_image.assert_not_called()


# ── 6. Existing behaviour is unchanged without manual references ────────────


class TestUnchangedWithoutManualReferences:
    def test_plain_canon_generation_still_works(self, client, db_session, founder):
        token, cid = founder
        before = _canon_snapshot(cid)
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "standing in a field", "include_character": True,
            })
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["canon_used"] is True
        assert meta["manual_refs_selected"] == 0
        assert meta["refs_source"] == "canon"
        assert _canon_snapshot(cid) == before

    def test_ordinary_creator_generation_is_untouched(self, client, db_session):
        """A Writer with no founder rights still generates exactly as before."""
        token = _register(client, "plainwriter@example.com", "plainwriteracct")
        cid = _create_character(client, token)
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "a plain scene", "include_character": False,
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["kind"] == "scene_only"


# ── 7. Idempotency: one intent, one paid submission ─────────────────────────


class TestJobIdempotency:
    def _submit(self, client, token, cid, key, **extra):
        payload = {"prompt": "standing in a field", "idempotency_key": key, **extra}
        return client.post(
            f"/characters/{cid}/image-generator/jobs",
            json=payload,
            headers=auth_headers(token),
        )

    def test_same_key_returns_the_same_job_and_launches_once(
        self, client, db_session, founder
    ):
        """The double-tap case, end to end through the route."""
        token, cid = founder
        launches: list[str] = []

        from app.services import image_generation_job_service as svc

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: launches.append(pid))

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            first = self._submit(client, token, cid, "intent-key-0001")
            second = self._submit(client, token, cid, "intent-key-0001")

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["job_id"] == second.json()["job_id"]
        assert first.json()["reused"] is False
        assert second.json()["reused"] is True
        assert len(launches) == 1, "exactly one driver launched → one paid submission"

    def test_different_keys_create_different_jobs(self, client, db_session, founder):
        token, cid = founder
        from app.services import image_generation_job_service as svc

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: None)

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            a = self._submit(client, token, cid, "intent-key-000a")
            b = self._submit(client, token, cid, "intent-key-000b")
        assert a.json()["job_id"] != b.json()["job_id"]

    def test_key_stays_claimed_after_the_job_finishes(self, client, db_session, founder):
        """A retry AFTER completion re-attaches instead of buying a second image."""
        token, cid = founder
        from app.models.image_generation_job import ImageGenerationJob
        from app.services import image_generation_job_service as svc

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: None)

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            first = self._submit(client, token, cid, "intent-key-done")
            job_id = first.json()["job_id"]

            row = (
                db_session.query(ImageGenerationJob)
                .filter(ImageGenerationJob.public_id == job_id)
                .one()
            )
            row.status = "completed"
            db_session.commit()

            again = self._submit(client, token, cid, "intent-key-done")

        assert again.json()["job_id"] == job_id
        assert again.json()["reused"] is True

    def test_submission_without_a_key_is_refused(self, client, db_session, founder):
        token, cid = founder
        resp = client.post(
            f"/characters/{cid}/image-generator/jobs",
            json={"prompt": "standing in a field"},
            headers=auth_headers(token),
        )
        assert resp.status_code == 422, resp.text

    def test_the_database_itself_rejects_a_duplicate_intent_key(self, db_session):
        """The service's fast-path lookup is the polite answer; this index is the
        guarantee. Without it, two concurrent submissions could both miss the
        lookup and both insert — two rows, two drivers, two paid generations."""
        from sqlalchemy.exc import IntegrityError

        from app.models.image_generation_job import ImageGenerationJob

        for public_id in ("dup-a", "dup-b"):
            db_session.add(
                ImageGenerationJob(
                    public_id=public_id, user_id=7, character_id=7, status="queued",
                    idempotency_key="same-intent", params_json={},
                )
            )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_resubmitting_an_intent_launches_no_second_driver(self, db_session):
        """At the service layer: the second call is handed the first call's job
        and never reaches the launcher. One driver launched is one paid
        generation; the unique index above is the backstop if two ever race."""
        from app.services.image_generation_job_service import start_image_generation_job
        from app.services.image_generation_pipeline import GenerationParams

        params = GenerationParams(prompt="a scene")
        launches: list[str] = []

        first, first_reused = start_image_generation_job(
            db_session, character_id=3, user_id=3, params=params,
            idempotency_key="raced-key",
            launcher=lambda pid, jid: launches.append(pid),
        )
        second, second_reused = start_image_generation_job(
            db_session, character_id=3, user_id=3, params=params,
            idempotency_key="raced-key",
            launcher=lambda pid, jid: launches.append(pid),
        )

        assert first_reused is False and second_reused is True
        assert second.id == first.id
        assert len(launches) == 1, "no second driver, so no second paid generation"

    def test_a_missing_idempotency_key_is_refused_at_the_service_layer(self, db_session):
        """Defence in depth: the route requires a key, and so does the service —
        so no future caller can create an unguarded, spendable job."""
        from app.services.image_generation_job_service import (
            ImageGenerationJobError,
            start_image_generation_job,
        )
        from app.services.image_generation_pipeline import GenerationParams

        with pytest.raises(ImageGenerationJobError):
            start_image_generation_job(
                db_session, character_id=3, user_id=3,
                params=GenerationParams(prompt="a scene"),
                idempotency_key="   ", launcher=lambda pid, jid: None,
            )

    def test_runner_ignores_a_job_that_is_not_queued(self, db_session):
        """The second half of the spend guarantee: a stray relaunch is a no-op."""
        from app.models.image_generation_job import ImageGenerationJob
        from app.services.image_generation_job_service import run_image_generation_job

        job = ImageGenerationJob(
            public_id="abc123", user_id=1, character_id=1, status="running",
            idempotency_key="k-running", params_json={},
        )
        db_session.add(job)
        db_session.commit()
        db_session.refresh(job)

        pipeline = MagicMock()
        run_image_generation_job(
            job.id, session_factory=lambda: TestingSessionLocal(), pipeline=pipeline
        )
        pipeline.assert_not_called()

    def test_two_accounts_may_use_the_same_key(self, client, db_session, founder):
        """Uniqueness is per-account: one founder's key cannot block another's."""
        token, cid = founder
        other = _register(client, "founder2@example.com", "founder2acct")
        _make_admin("founder2@example.com")
        other_cid = _create_character(client, other, "Other Character")

        from app.services import image_generation_job_service as svc

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: None)

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            a = self._submit(client, token, cid, "shared-key-1234")
            b = self._submit(client, other, other_cid, "shared-key-1234")
        assert a.status_code == 202 and b.status_code == 202
        assert a.json()["job_id"] != b.json()["job_id"]


# ── 8. Job execution and polling ────────────────────────────────────────────


class TestJobExecution:
    def _queued_job(self, client, token, cid, key="run-key-0001", **extra):
        from app.services import image_generation_job_service as svc

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: None)

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            resp = client.post(
                f"/characters/{cid}/image-generator/jobs",
                json={"prompt": "standing in a field", "idempotency_key": key, **extra},
                headers=auth_headers(token),
            )
        assert resp.status_code == 202, resp.text
        return resp.json()["job_id"]

    def test_runner_produces_an_image_and_completes(self, client, db_session, founder):
        from app.models.image_generation_job import ImageGenerationJob
        from app.services.image_generation_job_service import run_image_generation_job

        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]
        job_id = self._queued_job(
            client, token, cid,
            include_character=True, reference_image_ids=[image_id],
        )
        row = (
            db_session.query(ImageGenerationJob)
            .filter(ImageGenerationJob.public_id == job_id)
            .one()
        )

        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            run_image_generation_job(row.id, session_factory=lambda: TestingSessionLocal())

        poll = client.get(
            f"/characters/{cid}/image-generator/jobs/{job_id}", headers=auth_headers(token)
        ).json()
        assert poll["status"] == "completed", poll
        assert poll["image"]["kind"] == "scene_only"
        assert poll["result"]["refs_source"] == "mixed"
        assert poll["result"]["manual_refs_sent"] == 1

    def test_classified_failure_is_preserved_on_the_job(self, client, db_session, founder):
        """A provider refusal keeps its own message rather than becoming generic."""
        from app.models.image_generation_job import ImageGenerationJob
        from app.services.image_generation_job_service import run_image_generation_job

        token, cid = founder
        job_id = self._queued_job(client, token, cid, key="fail-key-0001", include_character=True)
        row = (
            db_session.query(ImageGenerationJob)
            .filter(ImageGenerationJob.public_id == job_id)
            .one()
        )

        provider = _mock_provider()
        provider.generate_with_anchors = MagicMock(
            side_effect=RuntimeError("google_prompt_blocked:SAFETY:HARM_CATEGORY_SEXUAL")
        )
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            run_image_generation_job(row.id, session_factory=lambda: TestingSessionLocal())

        poll = client.get(
            f"/characters/{cid}/image-generator/jobs/{job_id}", headers=auth_headers(token)
        ).json()
        assert poll["status"] == "failed"
        assert poll["error_code"] == "http_422"
        assert "Adult Studio" in poll["error_message"]

    def test_diag_json_is_never_serialised(self, client, db_session, founder):
        from app.models.image_generation_job import ImageGenerationJob
        from app.services.image_generation_job_service import run_image_generation_job

        token, cid = founder
        job_id = self._queued_job(client, token, cid, key="diag-key-0001")
        row = (
            db_session.query(ImageGenerationJob)
            .filter(ImageGenerationJob.public_id == job_id)
            .one()
        )
        with patch(
            f"{PIPELINE}.get_provider_for_option", side_effect=Exception("boom secret detail")
        ):
            run_image_generation_job(row.id, session_factory=lambda: TestingSessionLocal())

        poll = client.get(
            f"/characters/{cid}/image-generator/jobs/{job_id}", headers=auth_headers(token)
        )
        assert "boom secret detail" not in poll.text
        assert "diag" not in poll.json()

    def test_latest_endpoint_supports_reconnect_recovery(self, client, db_session, founder):
        token, cid = founder
        job_id = self._queued_job(client, token, cid, key="resume-key-001")
        latest = client.get(
            f"/characters/{cid}/image-generator/jobs/latest", headers=auth_headers(token)
        ).json()
        assert latest["job"]["job_id"] == job_id

    def test_another_account_cannot_poll_the_job(self, client, db_session, founder):
        token, cid = founder
        job_id = self._queued_job(client, token, cid, key="private-key-01")
        other = _register(client, "nosy@example.com", "nosyacct")
        _make_admin("nosy@example.com")
        resp = client.get(
            f"/characters/{cid}/image-generator/jobs/{job_id}", headers=auth_headers(other)
        )
        # Refused as a non-owner of the character before the job is even reached.
        assert resp.status_code in (403, 404), resp.text


# ── 9. Entitlement normalisation (quota + provider gating) ──────────────────


class TestEntitlementNormalisation:
    def test_seeder_is_exempt_from_the_weekly_image_quota(self, client, db_session, founder):
        """Lauren's account is the reason this exists: the quota exemption used
        to read ADMIN_EMAILS only, so a dedicated seeder was capped at 10/week."""
        from app.models.user import User
        from app.services.image_quota import get_quota_status

        token, _cid = founder
        user = db_session.query(User).filter(User.email == "seeder@example.com").one()
        assert user.is_seeder is True and user.is_admin is False
        assert get_quota_status(user, db_session)["unlimited"] is True

    def test_db_flagged_admin_is_exempt_even_without_admin_emails(self, client, db_session):
        from app.models.user import User
        from app.services.image_quota import get_quota_status

        _register(client, "dbadmin@example.com", "dbadminacct")
        _make_admin("dbadmin@example.com")
        user = db_session.query(User).filter(User.email == "dbadmin@example.com").one()
        assert get_quota_status(user, db_session)["unlimited"] is True

    def test_ordinary_creator_keeps_the_weekly_quota(self, client, db_session):
        from app.models.user import User
        from app.services.image_quota import get_quota_status

        _register(client, "quotaed@example.com", "quotaedacct")
        user = db_session.query(User).filter(User.email == "quotaed@example.com").one()
        status = get_quota_status(user, db_session)
        assert status["unlimited"] is False
        assert status["limit"] is not None

    def test_founder_may_select_openai_but_ordinary_creator_may_not(self):
        from app.services.image_provider import resolve_canon_provider_option

        founder_option, founder_meta = resolve_canon_provider_option(
            "option1", is_admin=False, is_founder=True
        )
        assert founder_option == "option1" and founder_meta == {}

        writer_option, writer_meta = resolve_canon_provider_option(
            "option1", is_admin=False, is_founder=False
        )
        assert writer_option == "option2"
        assert writer_meta["provider_fallback_reason"] == "openai_admin_only_beta"

    def test_experimental_providers_stay_admin_only_for_founders(self):
        from app.services.image_provider import resolve_canon_provider_option

        for option in ("option3", "option4", "option5", "option6"):
            effective, meta = resolve_canon_provider_option(
                option, is_admin=False, is_founder=True
            )
            assert effective == "option2", option
            assert meta, option

    def test_existing_callers_are_unaffected_by_the_new_parameter(self):
        """is_founder defaults to False, so every pre-existing call is identical."""
        from app.services.image_provider import resolve_canon_provider_option

        assert resolve_canon_provider_option("option1", is_admin=True)[0] == "option1"
        assert resolve_canon_provider_option("option1", is_admin=False)[0] == "option2"
        assert resolve_canon_provider_option("option2", is_admin=False)[0] == "option2"


# ── 10. Character Authority is untouched by the whole workflow ──────────────


def test_full_workflow_leaves_canon_byte_identical(client, db_session, founder):
    """Upload → select as reference → generate → poll. Canon must not move."""
    from app.models.image_generation_job import ImageGenerationJob
    from app.services import image_generation_job_service as svc
    from app.services.image_generation_job_service import run_image_generation_job

    token, cid = founder
    before = _canon_snapshot(cid)
    assert before, "the fixture character must have canon to compare"

    image_id = _upload(client, token, cid).json()["id"]

    real_start = svc.start_image_generation_job

    def _no_subprocess(db, **kw):
        return real_start(db, **kw, launcher=lambda pid, jid: None)

    with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
        submitted = client.post(
            f"/characters/{cid}/image-generator/jobs",
            json={
                "prompt": "standing in a field at dusk",
                "include_character": True,
                "reference_image_ids": [image_id],
                "reference_roles": ["environment"],
                "idempotency_key": "full-workflow-key",
            },
            headers=auth_headers(token),
        )
    assert submitted.status_code == 202, submitted.text

    row = (
        db_session.query(ImageGenerationJob)
        .filter(ImageGenerationJob.public_id == submitted.json()["job_id"])
        .one()
    )
    with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
        run_image_generation_job(row.id, session_factory=lambda: TestingSessionLocal())

    poll = client.get(
        f"/characters/{cid}/image-generator/jobs/{submitted.json()['job_id']}",
        headers=auth_headers(token),
    ).json()
    assert poll["status"] == "completed", poll

    assert _canon_snapshot(cid) == before, "Character Authority must be untouched"

"""Admin Creator's OWN OpenAI provider — isolation, request shape, diagnostics.

WHAT THIS PROTECTS. Admin Creator (reference_mode="deliberate", option1) is the
production tool for the Creator visual-reference assets, so it was given its
own OpenAI configuration: ``ADMIN_CREATOR_OPENAI_MODEL`` / ``_QUALITY`` /
``_OUTPUT_FORMAT``, reached through the registry entry
``"openai_admin_creator"``. The registry entry ``"openai"`` — the identity
pack, scene images, accessories and the public /images generator — must keep
sending exactly the request it always sent. These tests pin both halves:

  1. the legacy ``"openai"`` request is byte-for-byte unchanged (model from
     IMAGE_MODEL, no quality, no output_format, default client retries);
  2. the Admin Creator entry sends its own model/quality/format and only under
     deliberate + option1 — augment + option1 and deliberate + option2 resolve
     exactly as before;
  3. an exhausted OpenAI credit balance is classified as a quota failure with
     an actionable founder-facing message, and a safe truncated copy of the
     provider's error is persisted on the job row (it used to be dropped);
  4. Google's failure classification is untouched.

Everything is offline: the OpenAI client is a MagicMock, so no request can
leave the process (tests/test_external_network_safety.py enforces that
independently).
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.canon_test_utils import setup_canon, stub_png_bytes
from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token

PIPELINE = "app.services.image_generation_pipeline"
PROVIDER = "app.services.image_provider"

#: The real error body an exhausted balance produces (captured 2026-09-14),
#: as the pipeline sees it after the provider wraps it in a RuntimeError.
_QUOTA_ERROR = (
    "OpenAI multi-anchor image generation failed: Error code: 429 - {'error': "
    "{'message': 'You have no credits remaining. Add credits to continue using "
    "the API at https://platform.openai.com/settings/organization/billing/.', "
    "'type': 'insufficient_quota', 'param': None, 'code': 'credit_balance_exhausted'}}"
)
_MODERATION_ERROR = (
    "OpenAI multi-anchor image generation failed: Error code: 400 - {'error': "
    "{'message': 'Your request was rejected as a result of our safety system.', "
    "'type': 'image_generation_user_error', 'code': 'moderation_blocked'}}"
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _png() -> bytes:
    return stub_png_bytes()


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _webp() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (30, 200, 30)).save(buf, format="WEBP")
    return buf.getvalue()


def _fake_openai_client(*, png_out: bytes | None = None) -> MagicMock:
    """A stand-in for ``openai.OpenAI`` whose images.* return one b64 image."""
    import base64

    client = MagicMock(name="OpenAI-client")
    payload = MagicMock()
    payload.data = [MagicMock(b64_json=base64.b64encode(png_out or _png()).decode())]
    client.images.edit.return_value = payload
    client.images.generate.return_value = payload
    return client


@pytest.fixture
def openai_ctor(monkeypatch):
    """Patch the OpenAI constructor; yields (ctor_mock, client_mock)."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-fake-key")
    client = _fake_openai_client()
    ctor = MagicMock(return_value=client)
    with patch(f"{PROVIDER}.OpenAI", ctor):
        yield ctor, client


def _make_seeder(email: str) -> None:
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


def _create_character(client, token: str, name: str = "AC OpenAI Test") -> int:
    resp = client.post(
        "/characters/", json={"name": name, "species": "human"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client, token: str, cid: int, *, data: bytes | None = None, name="ref.png"):
    return client.post(
        f"/characters/{cid}/images/upload",
        files={"file": (name, data if data is not None else _png(), "image/png")},
        headers=auth_headers(token),
    )


def _mock_provider(captured: dict | None = None, *, fail_with: str | None = None):
    from app.services.provider_capabilities import Capability

    provider = MagicMock()
    provider.capabilities = frozenset(
        {Capability.TEXT_TO_IMAGE, Capability.IMAGE_GUIDANCE, Capability.MULTI_IMAGE_ANCHORS}
    )
    provider.model_name = "mock-model"
    provider.quality = "medium"
    provider.output_format = "png"

    def _anchors(*, prompt, anchor_images, **kw):
        if captured is not None:
            captured.update(prompt=prompt, anchors=list(anchor_images))
        if fail_with is not None:
            raise RuntimeError(fail_with)
        return _png()

    provider.generate_with_anchors = MagicMock(side_effect=_anchors)
    provider.generate_grounded_image = MagicMock(return_value=_png())
    provider.generate_image = MagicMock(return_value=_png())
    return provider


@pytest.fixture
def founder(client):
    token = get_auth_token(client, email="ac-openai@example.com", username="acopenai")
    _make_seeder("ac-openai@example.com")
    cid = _create_character(client, token)
    db = TestingSessionLocal()
    try:
        setup_canon(db, cid)
    finally:
        db.close()
    return token, cid


def _generate(client, token: str, cid: int, body: dict):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers=auth_headers(token),
    )


# ── 1. Legacy "openai" request is unchanged ──────────────────────────────────


class TestLegacyOpenAIRequestUnchanged:
    """The regression guard for every non-Admin-Creator OpenAI caller."""

    def test_multi_anchor_edit_sends_exactly_the_legacy_kwargs(self, openai_ctor, monkeypatch):
        from app.services.image_provider import create_provider

        ctor, client = openai_ctor
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-1.5")
        provider = create_provider("openai")
        provider.generate_with_anchors(prompt="a scene", anchor_images=[_png(), _jpeg()])

        # The client is built the way it always was: key only, SDK-default retries.
        assert ctor.call_args.kwargs == {"api_key": "test-fake-key"}
        kwargs = client.images.edit.call_args.kwargs
        assert set(kwargs) == {"model", "image", "prompt", "n", "size"}, kwargs
        assert kwargs["model"] == "gpt-image-1.5"
        assert kwargs["prompt"] == "a scene"
        assert kwargs["n"] == 1 and kwargs["size"] == "1024x1024"
        assert isinstance(kwargs["image"], list) and len(kwargs["image"]) == 2

    def test_single_anchor_edit_sends_one_handle_not_a_list(self, openai_ctor):
        from app.services.image_provider import create_provider

        _, client = openai_ctor
        create_provider("openai").generate_with_anchors(prompt="p", anchor_images=[_png()])
        assert not isinstance(client.images.edit.call_args.kwargs["image"], list)

    def test_text_to_image_sends_exactly_the_legacy_kwargs(self, openai_ctor, monkeypatch):
        from app.services.image_provider import create_provider

        _, client = openai_ctor
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-1.5")
        create_provider("openai").generate_image(prompt="a field")
        kwargs = client.images.generate.call_args.kwargs
        assert set(kwargs) == {"model", "prompt", "n", "size"}, kwargs
        assert kwargs["model"] == "gpt-image-1.5"

    def test_grounded_edit_sends_exactly_the_legacy_kwargs(self, openai_ctor):
        from app.services.image_provider import create_provider

        _, client = openai_ctor
        create_provider("openai").generate_grounded_image(
            prompt="angle", reference_image_bytes=_png()
        )
        assert set(client.images.edit.call_args.kwargs) == {"model", "image", "prompt", "n", "size"}

    def test_legacy_model_follows_image_model_live(self, openai_ctor, monkeypatch):
        """IMAGE_MODEL is read at call time, as before — not frozen at construction."""
        from app.services.image_provider import create_provider

        _, client = openai_ctor
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-1")
        provider = create_provider("openai")
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-2")
        provider.generate_image(prompt="p")
        assert client.images.generate.call_args.kwargs["model"] == "gpt-image-2"
        assert provider.model_name == "gpt-image-2"

    def test_admin_creator_settings_never_reach_the_legacy_entry(self, openai_ctor, monkeypatch):
        from app.services.image_provider import create_provider

        _, client = openai_ctor
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-1.5")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_MODEL", "gpt-image-2")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_QUALITY", "high")
        create_provider("openai").generate_with_anchors(prompt="p", anchor_images=[_png()])
        kwargs = client.images.edit.call_args.kwargs
        assert kwargs["model"] == "gpt-image-1.5"
        assert "quality" not in kwargs and "output_format" not in kwargs


# ── 2. Admin Creator entry: its own configuration ────────────────────────────


class TestAdminCreatorOpenAIProvider:
    def test_sends_its_own_model_quality_and_format(self, openai_ctor, monkeypatch):
        from app.services.image_provider import get_admin_creator_provider

        ctor, client = openai_ctor
        monkeypatch.setattr(settings, "IMAGE_MODEL", "gpt-image-1.5")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_MODEL", "gpt-image-2")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_QUALITY", "medium")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_OUTPUT_FORMAT", "png")

        provider = get_admin_creator_provider()
        provider.generate_with_anchors(prompt="jaw example", anchor_images=[_png(), _jpeg()])

        # Account-level failures are not transient: one retry, not the SDK's two.
        assert ctor.call_args.kwargs == {"api_key": "test-fake-key", "max_retries": 1}
        kwargs = client.images.edit.call_args.kwargs
        assert set(kwargs) == {"model", "quality", "output_format", "image", "prompt", "n", "size"}
        assert kwargs["model"] == "gpt-image-2"
        assert kwargs["quality"] == "medium"
        assert kwargs["output_format"] == "png"
        assert provider.model_name == "gpt-image-2"
        assert provider.quality == "medium" and provider.output_format == "png"

    def test_defaults_are_gpt_image_2_medium_png(self):
        from app.core.config import Settings

        fresh = Settings(_env_file=None)
        assert fresh.ADMIN_CREATOR_OPENAI_MODEL == "gpt-image-2"
        assert fresh.ADMIN_CREATOR_OPENAI_QUALITY == "medium"
        assert fresh.ADMIN_CREATOR_OPENAI_OUTPUT_FORMAT == "png"

    def test_image_order_is_the_anchor_order(self, openai_ctor):
        """Card order is the payload order — the prompt numbers references by it."""
        from app.services.image_provider import get_admin_creator_provider

        _, client = openai_ctor
        first, second, third = _png(), _jpeg(), _webp()
        sent: list[bytes] = []
        payload = client.images.edit.return_value

        def _capture(**kwargs):
            # Handles are open only for the duration of the call — read them now.
            sent.extend(fh.read() for fh in kwargs["image"])
            return payload

        client.images.edit.side_effect = _capture
        get_admin_creator_provider().generate_with_anchors(
            prompt="p", anchor_images=[first, second, third]
        )
        assert sent == [first, second, third]

    def test_temp_files_carry_their_detected_format(self, openai_ctor):
        """A JPEG reaches the SDK as .jpg (→ image/jpeg), not mislabelled .png."""
        from app.services.image_provider import get_admin_creator_provider

        _, client = openai_ctor
        get_admin_creator_provider().generate_with_anchors(
            prompt="p", anchor_images=[_png(), _jpeg(), _webp()]
        )
        names = [fh.name for fh in client.images.edit.call_args.kwargs["image"]]
        assert [n.rsplit(".", 1)[1] for n in names] == ["png", "jpg", "webp"], names

    def test_unsupported_quality_for_model_falls_back_to_provider_default(self, monkeypatch, caplog):
        from app.services.image_provider import admin_creator_openai_config

        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_MODEL", "gpt-image-1.5")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_QUALITY", "xhigh")
        cfg = admin_creator_openai_config()
        assert cfg["model"] == "gpt-image-1.5"
        assert cfg["quality"] is None and cfg["quality_supported"] is False

    def test_supported_quality_passes_validation(self, monkeypatch):
        from app.services.image_provider import admin_creator_openai_config

        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_MODEL", "gpt-image-2")
        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_QUALITY", "xhigh")
        cfg = admin_creator_openai_config()
        assert cfg["quality"] == "xhigh" and cfg["quality_supported"] is True

    def test_unknown_output_format_is_not_sent(self, monkeypatch):
        from app.services.image_provider import admin_creator_openai_config

        monkeypatch.setattr(settings, "ADMIN_CREATOR_OPENAI_OUTPUT_FORMAT", "gif")
        cfg = admin_creator_openai_config()
        assert cfg["output_format"] is None and cfg["output_format_supported"] is False

    def test_the_entry_is_not_a_configurable_image_provider(self):
        """Reachable only via get_admin_creator_provider — never via IMAGE_PROVIDER."""
        from app.services.image_provider import (
            ADMIN_CREATOR_OPENAI_PROVIDER,
            _CONFIGURABLE_PROVIDERS,
            _PROVIDER_OPTION_NAMES,
        )

        assert ADMIN_CREATOR_OPENAI_PROVIDER not in _CONFIGURABLE_PROVIDERS
        assert ADMIN_CREATOR_OPENAI_PROVIDER not in _PROVIDER_OPTION_NAMES.values()

    def test_missing_key_is_a_runtime_error(self, monkeypatch):
        from app.services.image_provider import get_admin_creator_provider

        monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
        with pytest.raises(RuntimeError):
            get_admin_creator_provider()


# ── 3. Model profiles ────────────────────────────────────────────────────────


class TestModelProfiles:
    def test_quality_facts(self):
        from app.services.model_profiles import supports_quality

        assert supports_quality("gpt-image-1.5", "medium")
        assert not supports_quality("gpt-image-1.5", "xhigh")
        assert supports_quality("gpt-image-2", "xhigh") and supports_quality("gpt-image-2", "max")
        assert supports_quality("gpt-image-2-2026-04-21", "medium")
        assert supports_quality("gpt-image-2.5-flare", "max")
        assert supports_quality("gpt-image-2", None)
        assert not supports_quality("some-future-model", "medium")

    def test_gpt_image_2_5_resolves_to_its_own_profile(self):
        from app.services.model_profiles import model_profile, supports_input_fidelity

        p = model_profile("openai", "gpt-image-2.5-sunburst-2026-09-08")
        assert p.max_reference_images == 16
        assert not supports_input_fidelity("gpt-image-2.5-sunburst")
        assert not supports_input_fidelity("gpt-image-2")
        assert supports_input_fidelity("gpt-image-1.5")


# ── 4. Failure classification ────────────────────────────────────────────────


class TestAccountFailureClassification:
    def test_provider_level(self):
        from app.services.image_provider import classify_account_failure, is_moderation_block

        assert classify_account_failure(_QUOTA_ERROR) == "quota"
        assert classify_account_failure(
            "Error code: 401 - {'error': {'code': 'invalid_api_key'}}"
        ) == "auth"
        assert classify_account_failure(
            "Error code: 429 - {'error': {'code': 'rate_limit_exceeded'}}"
        ) == "rate_limit"
        # Content verdicts stay with is_moderation_block.
        assert classify_account_failure(_MODERATION_ERROR) is None
        assert is_moderation_block(_MODERATION_ERROR)
        assert classify_account_failure("connection timed out") is None

    def test_pipeline_kinds_for_openai(self):
        from app.services.image_generation_pipeline import _classify_ref_failure

        assert _classify_ref_failure(_QUOTA_ERROR, "openai")[0] == "provider_quota"
        assert _classify_ref_failure(
            "Error code: 401 - invalid_api_key", "openai"
        )[0] == "provider_auth"
        assert _classify_ref_failure(
            "Error code: 429 - rate_limit_exceeded", "openai"
        )[0] == "provider_rate_limited"
        assert _classify_ref_failure(_MODERATION_ERROR, "openai")[0] == "sexual_refusal"
        assert _classify_ref_failure("connection timed out", "openai")[0] == "unknown"

    def test_google_classification_is_untouched(self):
        """The same texts under Google classify exactly as before this change."""
        from app.services.image_generation_pipeline import _classify_ref_failure

        assert _classify_ref_failure(_QUOTA_ERROR, "google")[0] == "unknown"
        assert _classify_ref_failure(_QUOTA_ERROR)[0] == "unknown"
        assert _classify_ref_failure("google_refused_image", "google")[0] == "image_recitation"

    def test_diag_reason_is_truncated_and_masked(self):
        from app.services.image_generation_pipeline import _DIAG_REASON_CHARS, _safe_diag_reason

        assert _safe_diag_reason(None) is None
        assert len(_safe_diag_reason("x" * 5000)) == _DIAG_REASON_CHARS
        masked = _safe_diag_reason("bad key sk-abcdefghijklmnop1234 rejected")
        assert "sk-abcdefghijklmnop1234" not in masked and "<redacted>" in masked


# ── 5. Pipeline selection: deliberate + option1 → Admin Creator entry ────────


class TestPipelineProviderSelection:
    def _run(self, client, token, cid, body, *, ac_provider, legacy_provider):
        with patch(f"{PIPELINE}.get_admin_creator_provider", return_value=ac_provider) as ac, \
             patch(f"{PIPELINE}.get_provider_for_option", return_value=legacy_provider) as legacy:
            resp = _generate(client, token, cid, body)
        return resp, ac, legacy

    def test_deliberate_option1_uses_the_admin_creator_entry(self, client, founder):
        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        captured: dict = {}
        ac, legacy = _mock_provider(captured), _mock_provider()
        resp, ac_spy, legacy_spy = self._run(
            client, token, cid,
            {
                "prompt": "jaw shape example",
                "provider_option": "option1",
                "reference_mode": "deliberate",
                "reference_image_ids": [a],
                "reference_roles": ["character_1"],
            },
            ac_provider=ac, legacy_provider=legacy,
        )
        assert resp.status_code == 200, resp.text
        ac_spy.assert_called_once()
        legacy_spy.assert_not_called()
        ac.generate_with_anchors.assert_called_once()
        legacy.generate_with_anchors.assert_not_called()
        # The deliberate prompt semantics ride along unchanged.
        assert "Person A" in captured["prompt"]

        meta = resp.json()["metadata_json"]
        assert meta["provider"] == "openai"
        assert meta["provider_option"] == "option1"
        assert meta["provider_profile"] == "openai_admin_creator"
        assert meta["model"] == "mock-model"
        assert meta["quality"] == "medium" and meta["output_format"] == "png"

    def test_deliberate_option1_preserves_card_order_and_roles(self, client, founder):
        """Character 1 / Character 2 / Clothing / Environment reach the provider
        in card order, and the prompt names them by that order."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(4)]
        captured: dict = {}
        ac = _mock_provider(captured)

        def _bytes_for(url: str) -> bytes:
            return f"BYTES::{url}".encode()

        with patch(f"{PIPELINE}.get_admin_creator_provider", return_value=ac), \
             patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()), \
             patch(f"{PIPELINE}.load_image_bytes", side_effect=_bytes_for):
            resp = _generate(client, token, cid, {
                "prompt": "two people in a doorway",
                "provider_option": "option1",
                "reference_mode": "deliberate",
                "reference_image_ids": ids,
                "reference_roles": ["character_1", "character_2", "clothing", "environment"],
            })
        assert resp.status_code == 200, resp.text

        from app.models.character_image import CharacterImage

        db = TestingSessionLocal()
        try:
            paths = [
                db.get(CharacterImage, i).file_path for i in ids
            ]
        finally:
            db.close()
        assert captured["anchors"] == [_bytes_for(p) for p in paths]
        prompt = captured["prompt"]
        assert "Reference image 1 is Person A" in prompt
        assert "Reference image 2 is Person B" in prompt
        assert "Reference image 3 is the clothing" in prompt
        assert "Reference image 4 is the environment" in prompt
        assert "two DIFFERENT people" in prompt

        sent = resp.json()["metadata_json"]["manual_refs"]
        assert [r["role"] for r in sent] == ["character_1", "character_2", "clothing", "environment"]

    def test_augment_option1_still_uses_the_legacy_entry(self, client, founder):
        """The public /images generator on OpenAI is not touched by the split."""
        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        ac, legacy = _mock_provider(), _mock_provider()
        resp, ac_spy, legacy_spy = self._run(
            client, token, cid,
            {
                "prompt": "in a field",
                "provider_option": "option1",
                "include_character": True,
                "reference_image_ids": [a],
                "reference_roles": ["clothing"],
            },
            ac_provider=ac, legacy_provider=legacy,
        )
        assert resp.status_code == 200, resp.text
        ac_spy.assert_not_called()
        legacy_spy.assert_called_once_with("option1")
        meta = resp.json()["metadata_json"]
        assert "provider_profile" not in meta and "quality" not in meta

    def test_deliberate_option2_still_uses_google_via_the_legacy_entry(self, client, founder):
        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        ac, legacy = _mock_provider(), _mock_provider()
        resp, ac_spy, legacy_spy = self._run(
            client, token, cid,
            {
                "prompt": "a scene",
                "provider_option": "option2",
                "reference_mode": "deliberate",
                "reference_image_ids": [a],
                "reference_roles": ["character_1"],
            },
            ac_provider=ac, legacy_provider=legacy,
        )
        assert resp.status_code == 200, resp.text
        ac_spy.assert_not_called()
        legacy_spy.assert_called_once_with("option2")
        assert resp.json()["metadata_json"]["provider"] == "google"
        assert "provider_profile" not in resp.json()["metadata_json"]


# ── 6. Failure surface: actionable message + persisted diagnostics ──────────


class TestFailureSurface:
    def test_quota_failure_is_actionable_on_the_sync_route(self, client, founder):
        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        ac = _mock_provider(fail_with=_QUOTA_ERROR)
        with patch(f"{PIPELINE}.get_admin_creator_provider", return_value=ac), \
             patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "jaw example",
                "provider_option": "option1",
                "reference_mode": "deliberate",
                "reference_image_ids": [a],
                "reference_roles": ["character_1"],
            })
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "OpenAI has no remaining credits" in detail
        assert "Canon · Google" in detail
        assert "try again" not in detail.split(".")[0].lower()
        # The provider's raw error never reaches the client.
        assert "credit_balance_exhausted" not in resp.text

    def test_moderation_failure_still_reads_as_a_content_refusal(self, client, founder):
        token, cid = founder
        a = _upload(client, token, cid).json()["id"]
        ac = _mock_provider(fail_with=_MODERATION_ERROR)
        with patch(f"{PIPELINE}.get_admin_creator_provider", return_value=ac), \
             patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            resp = _generate(client, token, cid, {
                "prompt": "p", "provider_option": "option1", "reference_mode": "deliberate",
                "reference_image_ids": [a], "reference_roles": ["character_1"],
            })
        assert resp.status_code == 422
        assert "declined this scene" in resp.json()["detail"]

    def test_job_row_persists_the_classified_diagnostic(self, client, db_session, founder):
        """What was dropped for three weeks: the kind and the provider's own text."""
        from app.models.image_generation_job import ImageGenerationJob
        from app.services import image_generation_job_service as svc
        from app.services.image_generation_job_service import run_image_generation_job

        token, cid = founder
        a = _upload(client, token, cid).json()["id"]

        real_start = svc.start_image_generation_job

        def _no_subprocess(db, **kw):
            return real_start(db, **kw, launcher=lambda pid, jid: None)

        with patch.object(svc, "start_image_generation_job", side_effect=_no_subprocess):
            resp = client.post(
                f"/characters/{cid}/image-generator/jobs",
                json={
                    "prompt": "jaw example",
                    "idempotency_key": "ac-openai-quota-0001",
                    "provider_option": "option1",
                    "reference_mode": "deliberate",
                    "reference_image_ids": [a],
                    "reference_roles": ["character_1"],
                },
                headers=auth_headers(token),
            )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        row = db_session.query(ImageGenerationJob).filter_by(public_id=job_id).one()

        ac = _mock_provider(fail_with=_QUOTA_ERROR)
        with patch(f"{PIPELINE}.get_admin_creator_provider", return_value=ac), \
             patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()):
            run_image_generation_job(row.id, session_factory=lambda: TestingSessionLocal())

        db_session.expire_all()
        row = db_session.query(ImageGenerationJob).filter_by(public_id=job_id).one()
        assert row.status == "failed"
        assert row.error_code == "http_422"
        assert "OpenAI has no remaining credits" in row.error_message
        diag = row.diag_json
        assert diag["http_status"] == 422
        assert diag["failure_kind"] == "provider_quota"
        assert diag["provider"] == "openai"
        assert diag["provider_profile"] == "openai_admin_creator"
        assert diag["model"] == "mock-model"
        assert "credit_balance_exhausted" in diag["provider_reason"]
        assert len(diag["provider_reason"]) <= 300

        # The owner-visible job view carries the message, never the diag.
        poll = client.get(
            f"/characters/{cid}/image-generator/jobs/{job_id}", headers=auth_headers(token)
        )
        assert poll.status_code == 200
        assert "credit_balance_exhausted" not in poll.text
        assert "no remaining credits" in poll.json()["error_message"]


# ── 7. Admin diagnostics ─────────────────────────────────────────────────────


def test_admin_diagnostics_reports_admin_creator_openai_config(client: TestClient, monkeypatch):
    from app.core import config as cfg_module

    admin_email = "ac-diag-admin@ficshon.com"
    monkeypatch.setenv("ADMIN_EMAIL", admin_email)
    monkeypatch.setattr(cfg_module.settings, "ADMIN_EMAILS", "")
    monkeypatch.setattr(cfg_module.settings, "ADMIN_CREATOR_OPENAI_MODEL", "gpt-image-2")
    monkeypatch.setattr(cfg_module.settings, "ADMIN_CREATOR_OPENAI_QUALITY", "medium")
    monkeypatch.setattr(cfg_module.settings, "ADMIN_CREATOR_OPENAI_OUTPUT_FORMAT", "png")

    client.post("/auth/register", json={
        "email": admin_email, "password": "adminpass123", "username": "acdiagadmin",
    })
    login = client.post("/auth/login", json={"email": admin_email, "password": "adminpass123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    resp = client.get("/api/admin/diagnostics", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    ac = resp.json()["images"]["admin_creator_openai"]
    assert ac == {
        "model": "gpt-image-2",
        "quality": "medium",
        "output_format": "png",
        "quality_supported": True,
        "output_format_supported": True,
    }

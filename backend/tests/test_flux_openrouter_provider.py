"""Tests for FLUX via OpenRouter provider (option3 / option4).

All HTTP is mocked — no real network calls.

Covers:
  * FluxOpenRouterProvider unit tests (text-to-image, response parsing)
  * Explicit ref-unsupported behaviour (no silent fallback)
  * Provider gating (option3/option4 admin-only, non-admin → Google fallback)
  * Adapter flags (supports_image_guidance=False, supports_multi_image_input=False)
  * Endpoint metadata: model, refs_count, multi_image_used=False, used_ref=False,
    refs_not_used_reason, refs_support_level
  * Existing Google/OpenAI paths unaffected
"""
from __future__ import annotations

import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────


def _make_png(width: int = 512, height: int = 768) -> bytes:
    from PIL import Image
    import io
    img = Image.new("RGB", (width, height), color=(60, 40, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _flux_b64_response(image_bytes: bytes) -> bytes:
    """Build a fake OpenRouter /v1/images/generations JSON response body."""
    body = {
        "created": 1234567890,
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}],
    }
    return json.dumps(body).encode()


def _flux_url_response(url: str) -> bytes:
    """Fake response that returns a URL instead of b64_json."""
    body = {"created": 1234567890, "data": [{"url": url}]}
    return json.dumps(body).encode()


class _FakeHTTPResp:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


# ── Unit: FluxOpenRouterProvider ────────────────────────────────────


class TestFluxOpenRouterProviderUnit:
    """Tests exercised directly against FluxOpenRouterProvider (no FastAPI)."""

    def _make_provider(self, model: str = "black-forest-labs/flux-pro-v1.1") -> "FluxOpenRouterProvider":  # type: ignore[name-defined]
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-flux-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            return FluxOpenRouterProvider(model=model, provider_label="flux_pro")

    def test_generate_text_to_image_returns_decoded_png(self):
        """generate_text_to_image decodes b64_json from Images API response."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        expected = _make_png()
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-flux-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ), patch(
            "urllib.request.urlopen",
            return_value=_FakeHTTPResp(_flux_b64_response(expected)),
        ):
            p = FluxOpenRouterProvider(model="black-forest-labs/flux-pro-v1.1", provider_label="flux_pro")
            result = p.generate_text_to_image(prompt="summer bikini beach")
        assert result == expected

    def test_generate_sends_to_images_endpoint(self):
        """Request goes to /v1/images/generations, not /v1/chat/completions."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        captured: list = []

        def _fake_urlopen(req, timeout=None):
            captured.append(req)
            return _FakeHTTPResp(_flux_b64_response(_make_png()))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            p = FluxOpenRouterProvider(model="black-forest-labs/flux-pro-v1.1", provider_label="flux_pro")
            p.generate_text_to_image(prompt="yellow sundress meadow")

        assert len(captured) == 1
        assert "images/generations" in captured[0].full_url

    def test_generate_sends_correct_payload(self):
        """Payload includes model, prompt, n=1, size, response_format=b64_json."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        captured: list = []

        def _fake_urlopen(req, timeout=None):
            captured.append(req)
            return _FakeHTTPResp(_flux_b64_response(_make_png()))

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            p = FluxOpenRouterProvider(model="black-forest-labs/flux-pro-v1.1", provider_label="flux_pro")
            p.generate_text_to_image(prompt="cliff portrait rolled sleeve", size="1024x1024")

        payload = json.loads(captured[0].data)
        assert payload["model"] == "black-forest-labs/flux-pro-v1.1"
        assert payload["prompt"] == "cliff portrait rolled sleeve"
        assert payload["n"] == 1
        assert payload["size"] == "1024x1024"
        assert payload["response_format"] == "b64_json"

    def test_parse_b64_json_response(self):
        """_parse_image_bytes correctly handles b64_json format."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        png = _make_png()
        body = {"data": [{"b64_json": base64.b64encode(png).decode()}]}
        result = FluxOpenRouterProvider._parse_image_bytes(body)
        assert result == png

    def test_parse_url_response_downloads(self):
        """_parse_image_bytes downloads image when only a URL is present."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        png = _make_png()
        body = {"data": [{"url": "https://cdn.openrouter.ai/flux/test.png"}]}
        with patch("urllib.request.urlopen", return_value=_FakeHTTPResp(png)):
            result = FluxOpenRouterProvider._parse_image_bytes(body)
        assert result == png

    def test_parse_missing_data_raises(self):
        """_parse_image_bytes raises RuntimeError when data key is absent."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        with pytest.raises(RuntimeError, match="missing expected data structure"):
            FluxOpenRouterProvider._parse_image_bytes({"choices": []})

    def test_generate_edit_raises_not_implemented_clearly(self):
        """generate_edit raises NotImplementedError with a clear message (no silent fallback)."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            p = FluxOpenRouterProvider(model="model", provider_label="flux_pro")
            with pytest.raises(NotImplementedError, match="does not support"):
                p.generate_edit(prompt="test", reference_image_url="https://example.com/img.png")

    def test_empty_prompt_raises_value_error(self):
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            p = FluxOpenRouterProvider(model="model", provider_label="flux_pro")
            with pytest.raises(ValueError, match="empty"):
                p.generate_text_to_image(prompt="")

    def test_missing_api_key_raises_on_init(self):
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = ""
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
                FluxOpenRouterProvider(model="model", provider_label="flux_pro")

    def test_http_error_raises_runtime_without_retrying(self):
        import urllib.error
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        call_count = 0

        def _fail(req, timeout=None):
            nonlocal call_count
            call_count += 1
            raise urllib.error.HTTPError(
                url="https://openrouter.ai/api/v1/images/generations",
                code=422,
                msg="Unprocessable",
                hdrs=MagicMock(),
                fp=BytesIO(b'{"error":"bad request"}'),
            )

        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ), patch("urllib.request.urlopen", side_effect=_fail):
            p = FluxOpenRouterProvider(model="model", provider_label="flux_pro")
            with pytest.raises(RuntimeError, match="HTTP 422"):
                p.generate_text_to_image(prompt="test")
        assert call_count == 1

    def test_refs_support_level_is_none(self):
        """FluxOpenRouterProvider explicitly declares refs_support_level='none'."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
            REFS_SUPPORT_LEVEL,
        )
        assert REFS_SUPPORT_LEVEL == "none"
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            p = FluxOpenRouterProvider(model="model", provider_label="flux_pro")
            assert p.refs_support_level == "none"

    def test_model_name_property(self):
        """model_name returns the model slug passed at construction."""
        from app.services.image_providers.flux_openrouter_provider import (
            FluxOpenRouterProvider,
        )
        mock_settings = MagicMock()
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        with patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            p = FluxOpenRouterProvider(model="black-forest-labs/flux-pro-v1.1", provider_label="flux_pro")
            assert p.model_name == "black-forest-labs/flux-pro-v1.1"


# ── Unit: adapter flags ──────────────────────────────────────────────


class TestFluxOpenRouterAdapterFlags:

    def _make_adapter(self, option: str = "option3"):
        from app.services.image_provider import get_provider_for_option
        mock_settings = MagicMock()
        mock_settings.IMAGE_GENERATOR_PROVIDER_TOGGLE = True
        mock_settings.OPENROUTER_API_KEY = "sk-or-test"
        mock_settings.OPENROUTER_FLUX_PRO_MODEL = "black-forest-labs/flux-pro-v1.1"
        mock_settings.OPENROUTER_FLUX_MAX_MODEL = "black-forest-labs/flux-pro-v1.1-ultra"
        with patch("app.services.image_provider.settings", mock_settings), patch(
            "app.services.image_providers.flux_openrouter_provider.settings",
            mock_settings,
        ):
            return get_provider_for_option(option)

    def test_flux_pro_adapter_disables_image_guidance(self):
        adapter = self._make_adapter("option3")
        assert adapter.supports_image_guidance is False

    def test_flux_pro_adapter_disables_multi_image(self):
        adapter = self._make_adapter("option3")
        assert adapter.supports_multi_image_input is False

    def test_flux_pro_refs_support_level_none(self):
        adapter = self._make_adapter("option3")
        assert adapter.refs_support_level == "none"

    def test_flux_max_adapter_disables_image_guidance(self):
        adapter = self._make_adapter("option4")
        assert adapter.supports_image_guidance is False

    def test_flux_max_refs_support_level_none(self):
        adapter = self._make_adapter("option4")
        assert adapter.refs_support_level == "none"

    def test_flux_pro_model_name_matches_settings(self):
        adapter = self._make_adapter("option3")
        assert adapter.model_name == "black-forest-labs/flux-pro-v1.1"

    def test_flux_max_model_name_matches_settings(self):
        adapter = self._make_adapter("option4")
        assert adapter.model_name == "black-forest-labs/flux-pro-v1.1-ultra"


# ── Unit: provider gating matrix ────────────────────────────────────


class TestFluxProviderGating:

    def test_non_admin_option3_falls_back_to_google(self):
        from app.services.image_provider import resolve_canon_provider_option
        opt, meta = resolve_canon_provider_option("option3", is_admin=False)
        assert opt == "option2"
        assert meta["original_requested_provider"] == "flux_pro"
        assert meta["provider_fallback_reason"] == "flux_pro_admin_only"

    def test_non_admin_option4_falls_back_to_google(self):
        from app.services.image_provider import resolve_canon_provider_option
        opt, meta = resolve_canon_provider_option("option4", is_admin=False)
        assert opt == "option2"
        assert meta["original_requested_provider"] == "flux_max"
        assert meta["provider_fallback_reason"] == "flux_max_admin_only"

    def test_admin_option3_allowed(self):
        from app.services.image_provider import resolve_canon_provider_option
        opt, meta = resolve_canon_provider_option("option3", is_admin=True)
        assert opt == "option3"
        assert meta == {}

    def test_admin_option4_allowed(self):
        from app.services.image_provider import resolve_canon_provider_option
        opt, meta = resolve_canon_provider_option("option4", is_admin=True)
        assert opt == "option4"
        assert meta == {}

    def test_openai_fallback_reason_unchanged(self):
        """Existing option1 gating still uses 'openai_admin_only_beta'."""
        from app.services.image_provider import resolve_canon_provider_option
        _, meta = resolve_canon_provider_option("option1", is_admin=False)
        assert meta["provider_fallback_reason"] == "openai_admin_only_beta"

    def test_google_still_allowed_for_non_admin(self):
        from app.services.image_provider import resolve_canon_provider_option
        opt, meta = resolve_canon_provider_option("option2", is_admin=False)
        assert opt == "option2"
        assert meta == {}


# ── Helpers ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpassword123"})
    return resp.json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "Test Character", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


def _make_admin(db_session, email: str) -> None:
    from app.models.user import User as UserModel
    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == email).first()
    assert user is not None
    user.is_admin = True
    db_session.commit()


def _stub_png_bytes() -> bytes:
    from app.services.stub_image_generator import generate_placeholder_png
    from pathlib import Path
    fp = generate_placeholder_png(label="test", sublabel="stub")
    from app.core.storage import load_image_bytes
    return load_image_bytes(fp)


def _capturing_provider(captured: dict) -> MagicMock:
    mock = MagicMock()
    mock.supports_multi_image_input = False
    mock.supports_image_guidance = False
    mock.refs_support_level = "none"
    mock.model_name = "black-forest-labs/flux-pro-v1.1"
    mock.generate_image = lambda *, prompt, **_: (
        captured.__setitem__("prompt", prompt) or _stub_png_bytes()
    )
    mock.generate_grounded_image = MagicMock(side_effect=NotImplementedError())
    mock.generate_with_anchors = MagicMock(side_effect=NotImplementedError())
    return mock


def _post(client, token, cid, body):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )


# ── Endpoint: non-admin behaviour ────────────────────────────────────


def test_non_admin_option3_request_falls_back_to_google(client: TestClient):
    """Non-admin requesting FLUX Pro is silently routed to Google with audit metadata."""
    token = _register_and_login(client, "flux_gate3@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "Summer on the beach in a bikini",
        "include_character": False,
        "provider_option": "option3",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"  # forced to Google
    assert meta["original_requested_provider"] == "flux_pro"
    assert meta["provider_fallback_reason"] == "flux_pro_admin_only"


def test_non_admin_option4_request_falls_back_to_google(client: TestClient):
    token = _register_and_login(client, "flux_gate4@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "Summer in a yellow sundress",
        "include_character": False,
        "provider_option": "option4",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"
    assert meta["provider_fallback_reason"] == "flux_max_admin_only"


# ── Endpoint: admin FLUX behaviour ───────────────────────────────────


def test_admin_can_select_flux_pro(client: TestClient, db_session):
    """Admin requesting option3 gets FLUX Pro, no fallback metadata."""
    email = "flux_admin3@example.com"
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _make_admin(db_session, email)

    captured: dict = {}
    with patch(
        "app.api.routes.image_generator.get_provider_for_option",
        return_value=_capturing_provider(captured),
    ):
        resp = _post(client, token, cid, {
            "prompt": "Summer bikini beach scene",
            "include_character": False,
            "provider_option": "option3",
        })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option3"
    assert "provider_fallback_reason" not in meta
    assert meta["provider"] == "flux_pro"


def test_admin_can_select_flux_max(client: TestClient, db_session):
    """Admin requesting option4 gets FLUX Max, no fallback metadata."""
    email = "flux_admin4@example.com"
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _make_admin(db_session, email)

    captured: dict = {}
    with patch(
        "app.api.routes.image_generator.get_provider_for_option",
        return_value=_capturing_provider(captured),
    ):
        resp = _post(client, token, cid, {
            "prompt": "Formal dinner in a covered suit",
            "include_character": False,
            "provider_option": "option4",
        })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option4"
    assert meta["provider"] == "flux_max"


def test_flux_metadata_includes_model_name(client: TestClient, db_session):
    """Metadata records model_name for FLUX providers."""
    email = "flux_model_meta@example.com"
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _make_admin(db_session, email)

    captured: dict = {}
    with patch(
        "app.api.routes.image_generator.get_provider_for_option",
        return_value=_capturing_provider(captured),
    ):
        resp = _post(client, token, cid, {
            "prompt": "Pan cliff portrait",
            "include_character": False,
            "provider_option": "option3",
        })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["model"] == "black-forest-labs/flux-pro-v1.1"


def test_flux_refs_not_used_metadata_when_include_character(client: TestClient, db_session):
    """include_character=True + FLUX (no ref support) fails loudly per S24AD."""
    from tests.canon_test_utils import setup_canon
    email = "flux_refs_meta@example.com"
    token = _register_and_login(client, email)
    cid = _create_character(client, token)
    _make_admin(db_session, email)

    # Setup minimal canon so include_character=True doesn't 409
    setup_canon(db_session, cid)

    captured: dict = {}
    provider_mock = _capturing_provider(captured)

    with patch(
        "app.api.routes.image_generator.get_provider_for_option",
        return_value=provider_mock,
    ), patch(
        "app.api.routes.image_generator.load_image_bytes",
        return_value=_make_png(),
    ):
        resp = _post(client, token, cid, {
            "prompt": "Pan rolled-sleeve cliff scene",
            "include_character": True,
            "provider_option": "option3",
        })

    # S24AD: a canon generation with reference images on a provider that cannot
    # consume them must FAIL LOUDLY (422) instead of silently degrading to a
    # ref-less text-only image that drops the character's identity.
    assert resp.status_code == 422, resp.text
    assert "Canon provider declined" in resp.json()["detail"]


def test_existing_google_path_unaffected_by_flux_addition(client: TestClient):
    """Existing Google (option2) path is completely unaffected."""
    token = _register_and_login(client, "flux_google_ok@example.com")
    cid = _create_character(client, token)
    resp = _post(client, token, cid, {
        "prompt": "Pan formal covered-arm portrait",
        "include_character": False,
        "provider_option": "option2",
    })
    assert resp.status_code == 200, resp.text
    meta = resp.json()["metadata_json"]
    assert meta["provider_option"] == "option2"
    assert "provider_fallback_reason" not in meta
    assert "flux" not in meta.get("provider", "")

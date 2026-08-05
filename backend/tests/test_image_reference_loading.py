"""Reference loading must fail honestly, and boto3 must never go missing again.

Production ran with USE_OBJECT_STORAGE=true but without boto3 in
requirements.txt, so every image generation hit
``ModuleNotFoundError: No module named 'boto3'``. Two separate defects turned
that into a mystery:

  * ``requirements.txt`` never declared boto3, so the deployment installed
    without it while dev kept a copy in the excluded .pythonlibs.
  * ``_load_from_r2``'s error handler read the S3 error code with
    ``getattr(getattr(exc, "response", None), "get", lambda *_: None)(...)``,
    which produced None for any non-ClientError and then called ``.get`` on it.
    The handler raised AttributeError("'NoneType' object has no attribute
    'get'") and buried the real ModuleNotFoundError at all six references.

These tests pin the dependency, the honest error reporting, and the refusal to
generate an identity-weak image when no canon reference loads at all.
"""
import logging
import re
from pathlib import Path

import pytest

from app.core import storage

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


class TestBoto3IsADeclaredDependency:
    """boto3 is a runtime requirement whenever object storage is enabled."""

    def test_requirements_declares_boto3(self):
        assert re.search(r"^boto3==", REQUIREMENTS.read_text(), re.M), (
            "boto3 must be pinned in requirements.txt — production installs only "
            "from this file and reaches boto3 on every image generation"
        )

    def test_boto3_is_importable(self):
        """Guards the regression directly: a missing boto3 must fail loudly here."""
        import boto3  # noqa: F401

    def test_storage_module_can_build_an_r2_client(self, monkeypatch):
        """_r2_client must reach boto3, not ModuleNotFoundError."""
        for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
            monkeypatch.setenv(var, "test-value")
        assert storage._r2_client() is not None


class TestR2ErrorHandlerDoesNotMaskTheRealError:
    """The NoneType.get regression, reproduced and prevented."""

    @pytest.fixture(autouse=True)
    def _r2_env(self, monkeypatch):
        monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")
        monkeypatch.setenv("R2_PUBLIC_URL", "https://cdn.example.test")

    def test_module_not_found_is_reported_not_masked(self, monkeypatch):
        """The exact production shape: boto3 missing inside _r2_client."""
        def _boom():
            raise ModuleNotFoundError("No module named 'boto3'")

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with pytest.raises(RuntimeError) as excinfo:
            storage._load_from_r2("https://cdn.example.test/generated/x.png")

        message = str(excinfo.value)
        assert "ModuleNotFoundError" in message, message
        assert "NoneType" not in message, "the real error was masked again"

    def test_original_exception_is_chained(self, monkeypatch):
        def _boom():
            raise ModuleNotFoundError("No module named 'boto3'")

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with pytest.raises(RuntimeError) as excinfo:
            storage._load_from_r2("https://cdn.example.test/generated/x.png")
        assert isinstance(excinfo.value.__cause__, ModuleNotFoundError)

    @pytest.mark.parametrize(
        "exc",
        [
            ModuleNotFoundError("No module named 'boto3'"),
            ConnectionError("network unreachable"),
            TimeoutError("timed out"),
            ValueError("bad key"),
        ],
    )
    def test_no_attribute_error_for_any_exception_without_response(
        self, monkeypatch, exc
    ):
        """Any exception lacking a botocore-style .response must still report cleanly."""
        def _boom():
            raise exc

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with pytest.raises(RuntimeError) as excinfo:
            storage._load_from_r2("https://cdn.example.test/generated/x.png")
        assert "NoneType" not in str(excinfo.value)

    def test_client_error_code_still_extracted(self, monkeypatch, caplog):
        """A real botocore ClientError shape must still yield its error code."""
        class _ClientErrorLike(Exception):
            response = {"Error": {"Code": "NoSuchKey"}}

        def _boom():
            raise _ClientErrorLike("not found")

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with caplog.at_level(logging.ERROR, logger="app.core.storage"):
            with pytest.raises(RuntimeError):
                storage._load_from_r2("https://cdn.example.test/generated/x.png")
        assert "error_code=NoSuchKey" in " ".join(r.getMessage() for r in caplog.records)

    def test_malformed_response_does_not_crash_the_handler(self, monkeypatch):
        """A .response that is not the expected shape must not raise in the handler."""
        class _WeirdError(Exception):
            response = "not-a-dict"

        def _boom():
            raise _WeirdError("odd")

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with pytest.raises(RuntimeError) as excinfo:
            storage._load_from_r2("https://cdn.example.test/generated/x.png")
        assert "NoneType" not in str(excinfo.value)

    def test_exception_type_is_logged(self, monkeypatch, caplog):
        def _boom():
            raise ModuleNotFoundError("No module named 'boto3'")

        monkeypatch.setattr(storage, "_r2_client", _boom)
        with caplog.at_level(logging.ERROR, logger="app.core.storage"):
            with pytest.raises(RuntimeError):
                storage._load_from_r2("https://cdn.example.test/generated/x.png")
        assert "exc_type=ModuleNotFoundError" in " ".join(
            r.getMessage() for r in caplog.records
        )


class TestPublicUrlRoutingByStorageMode:
    """Which loader an https:// reference uses is decided by storage mode.

    With object storage ON, R2 public URLs are fetched via authenticated
    GetObject on purpose — R2 blocks anonymous server-side reads (see
    load_image_bytes' docstring). With it OFF, a plain HTTP GET is used.
    """

    def test_object_storage_on_uses_authenticated_r2(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", True)
        called = {}
        monkeypatch.setattr(
            storage, "_load_from_r2", lambda url: called.setdefault("r2", url) or b"x"
        )
        storage.load_image_bytes("https://cdn.example.test/generated/a.png")
        assert called["r2"] == "https://cdn.example.test/generated/a.png"

    def test_object_storage_off_uses_plain_http(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)
        called = {}
        monkeypatch.setattr(
            storage, "_load_from_http", lambda url: called.setdefault("http", url) or b"x"
        )
        storage.load_image_bytes("https://cdn.example.test/generated/a.png")
        assert called["http"] == "https://cdn.example.test/generated/a.png"

    def test_plain_http_needs_no_r2_credentials(self, monkeypatch):
        """The non-R2 path must never construct an S3 client."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)

        def _fail():
            raise AssertionError("_r2_client must not be called for plain HTTP")

        monkeypatch.setattr(storage, "_r2_client", _fail)
        monkeypatch.setattr(storage, "_load_from_http", lambda url: b"ok")
        assert storage.load_image_bytes("https://cdn.example.test/x.png") == b"ok"


# ── Route-level: what happens when canon references fail to load ──────────

from unittest.mock import MagicMock, patch  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from tests.test_image_generator import (  # noqa: E402
    _create_character,
    _mock_provider_succeeds,
    _register_and_login,
    _setup_canon,
)

ROUTE = "app.api.routes.image_generator"


def _generate(client, token, cid, **overrides):
    payload = {
        "prompt": "Standing in a quiet library",
        "include_character": True,
        "provider_option": "option1",
    }
    payload.update(overrides)
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


class TestAllReferencesFailing:
    """A canon generation with zero loaded references must refuse, not degrade.

    Producing a generic person wearing none of the character's locked identity
    is worse than an error the caller can retry — and indistinguishable from a
    good result once saved to the gallery.
    """

    def test_returns_503_when_every_reference_fails(self, client: TestClient, db_session):
        token = _register_and_login(client, "refs_all_fail@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        with patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("R2 down")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            resp = _generate(client, token, cid)

        assert resp.status_code == 503, resp.text

    def test_error_message_is_the_safe_public_string(self, client: TestClient, db_session):
        token = _register_and_login(client, "refs_msg@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        with patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("R2 down")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            resp = _generate(client, token, cid)

        assert resp.json()["detail"] == (
            "Character reference images could not be loaded. Please try again."
        )

    def test_no_provider_call_is_wasted(self, client: TestClient, db_session):
        """Refusal happens before the provider is invoked."""
        token = _register_and_login(client, "refs_no_call@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        provider = _mock_provider_succeeds()
        with patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("R2 down")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=provider):
            _generate(client, token, cid)

        provider.generate_with_anchors.assert_not_called()
        provider.generate_image.assert_not_called()

    def test_internal_error_detail_is_not_leaked(self, client: TestClient, db_session):
        token = _register_and_login(client, "refs_noleak@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        with patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("R2 secret-bucket down")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            resp = _generate(client, token, cid)

        assert "secret-bucket" not in resp.text
        assert "RuntimeError" not in resp.text

    def test_plain_generation_is_unaffected(self, client: TestClient, db_session):
        """include_character=False uses no references, so it must still succeed."""
        token = _register_and_login(client, "refs_plain@example.com")
        cid = _create_character(client, token)

        with patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("R2 down")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            resp = _generate(client, token, cid, include_character=False)

        assert resp.status_code == 200, resp.text


class TestPartialReferenceFailure:
    """Some grounding beats none — a partial load must still generate."""

    def test_one_surviving_reference_still_generates(self, client: TestClient, db_session):
        token = _register_and_login(client, "refs_partial@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        calls = {"n": 0}

        def _flaky(url):
            calls["n"] += 1
            if calls["n"] == 1:
                return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
            raise RuntimeError("R2 down")

        with patch(f"{ROUTE}.load_image_bytes", side_effect=_flaky), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            resp = _generate(client, token, cid)

        assert resp.status_code == 200, resp.text
        assert resp.json()["metadata_json"]["refs_count"] == 1

    def test_loaded_references_reach_the_provider(self, client: TestClient, db_session):
        token = _register_and_login(client, "refs_forwarded@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        provider = _mock_provider_succeeds()
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        with patch(f"{ROUTE}.load_image_bytes", return_value=png), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid)

        assert resp.status_code == 200, resp.text
        provider.generate_with_anchors.assert_called_once()
        assert provider.generate_with_anchors.call_args.kwargs["anchor_images"] == [png] * len(
            provider.generate_with_anchors.call_args.kwargs["anchor_images"]
        )


class TestReferenceCheckpoints:
    def test_start_and_summary_are_emitted(self, client: TestClient, db_session, caplog):
        token = _register_and_login(client, "refs_ckpt@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        with caplog.at_level(logging.INFO, logger=ROUTE), \
             patch(f"{ROUTE}.load_image_bytes", return_value=png), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            _generate(client, token, cid)

        messages = [r.getMessage() for r in caplog.records]
        assert any("IMAGE_GEN_REF_LOAD_START" in m for m in messages)
        assert any("IMAGE_GEN_REF_LOAD_OK" in m for m in messages)
        summary = next(m for m in messages if "IMAGE_GEN_REF_LOAD_SUMMARY" in m)
        assert "refs_requested=" in summary and "refs_loaded=" in summary

    def test_failed_reference_logs_exception_type(self, client: TestClient, db_session, caplog):
        token = _register_and_login(client, "refs_ckpt_fail@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        with caplog.at_level(logging.INFO, logger=ROUTE), \
             patch(f"{ROUTE}.load_image_bytes", side_effect=ModuleNotFoundError("No module named 'boto3'")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            _generate(client, token, cid)

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "IMAGE_GEN_REF_LOAD_FAILED" in messages
        assert "exc_type=ModuleNotFoundError" in messages

    def test_query_string_is_stripped_from_logged_urls(self, client: TestClient, db_session, caplog):
        """Signed-URL credentials live in the query string and must not be logged."""
        token = _register_and_login(client, "refs_ckpt_sig@example.com")
        cid = _create_character(client, token)
        _setup_canon(db_session, cid)

        with caplog.at_level(logging.INFO, logger=ROUTE), \
             patch(f"{ROUTE}.route_canon_refs") as routed, \
             patch(f"{ROUTE}.load_image_bytes", side_effect=RuntimeError("nope")), \
             patch(f"{ROUTE}.get_provider_for_option", return_value=_mock_provider_succeeds()):
            routed.return_value = (
                ["https://cdn.example.test/a.png?X-Amz-Signature=SECRETSIG"],
                MagicMock(camera="x", routed=True, exposure=[]),
            )
            _generate(client, token, cid)

        assert "SECRETSIG" not in " ".join(r.getMessage() for r in caplog.records)

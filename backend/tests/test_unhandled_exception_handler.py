"""Unhandled exceptions must reach clients as safe, parseable JSON.

Starlette's default answer to an unhandled exception is a plain-text
``Internal Server Error`` body. Every frontend client parses error bodies as
JSON, so that body fails to parse and a real backend fault is flattened into a
generic "Something went wrong" — which is what made the Canon image-generation
incident so hard to localise from the client side.

These tests pin both halves of the contract: the response is JSON and carries a
correlation id, and it leaks nothing about the underlying exception.
"""
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import PUBLIC_ERROR_MESSAGE, unhandled_exception_handler

SECRET_ISH = "sk-live-abcdef123456 postgres://user:pw@db.internal/prod /home/runner/secret.py"


@pytest.fixture
def failing_app():
    """A minimal app wired with the real handler, so nothing else interferes."""
    app = FastAPI()
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boom")
    def boom():
        raise RuntimeError(f"storage upload failed: {SECRET_ISH}")

    @app.get("/keyerror")
    def keyerror():
        raise KeyError("R2_ACCOUNT_ID")

    # raise_server_exceptions=False lets the handler produce a response instead
    # of the exception propagating into the test.
    return TestClient(app, raise_server_exceptions=False)


class TestResponseShape:
    def test_status_is_500(self, failing_app):
        assert failing_app.get("/boom").status_code == 500

    def test_body_is_parseable_json(self, failing_app):
        """The whole point: json() must not raise."""
        assert failing_app.get("/boom").json() is not None

    def test_content_type_is_json(self, failing_app):
        resp = failing_app.get("/boom")
        assert resp.headers["content-type"].startswith("application/json")

    def test_detail_is_the_generic_message(self, failing_app):
        assert failing_app.get("/boom").json()["detail"] == PUBLIC_ERROR_MESSAGE

    def test_request_id_present_in_body(self, failing_app):
        assert failing_app.get("/boom").json()["request_id"]

    def test_request_id_present_in_header(self, failing_app):
        resp = failing_app.get("/boom")
        assert resp.headers["X-Request-ID"] == resp.json()["request_id"]

    def test_request_id_is_unique_per_request(self, failing_app):
        first = failing_app.get("/boom").json()["request_id"]
        second = failing_app.get("/boom").json()["request_id"]
        assert first != second


class TestNoLeakage:
    """The public payload must never carry exception detail."""

    def test_exception_message_not_leaked(self, failing_app):
        raw = failing_app.get("/boom").text
        assert "storage upload failed" not in raw

    def test_credential_shaped_text_not_leaked(self, failing_app):
        raw = failing_app.get("/boom").text
        assert "sk-live-abcdef123456" not in raw
        assert "postgres://" not in raw

    def test_filesystem_paths_not_leaked(self, failing_app):
        assert "/home/runner" not in failing_app.get("/boom").text

    def test_exception_type_not_leaked(self, failing_app):
        raw = failing_app.get("/keyerror").text
        assert "KeyError" not in raw
        assert "R2_ACCOUNT_ID" not in raw

    def test_no_traceback_in_body(self, failing_app):
        raw = failing_app.get("/boom").text
        assert "Traceback" not in raw
        assert ".py" not in raw

    def test_body_has_only_expected_keys(self, failing_app):
        assert set(failing_app.get("/boom").json()) == {"detail", "request_id"}


class TestServerSideLogging:
    """Full detail must survive server-side, keyed by the same id."""

    def test_traceback_and_id_logged(self, failing_app, caplog):
        with caplog.at_level(logging.ERROR, logger="app.main"):
            resp = failing_app.get("/boom")
        request_id = resp.json()["request_id"]
        record = next(r for r in caplog.records if "UNHANDLED_EXCEPTION" in r.getMessage())
        assert request_id in record.getMessage()
        # exc_info is what carries the traceback to the log sink.
        assert record.exc_info is not None

    def test_exception_type_recorded_server_side(self, failing_app, caplog):
        with caplog.at_level(logging.ERROR, logger="app.main"):
            failing_app.get("/keyerror")
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "KeyError" in joined


class TestRealAppRegistration:
    """The production app must actually have the handler wired."""

    def test_handler_registered_on_app(self):
        from app.main import app

        assert app.exception_handlers.get(Exception) is unhandled_exception_handler

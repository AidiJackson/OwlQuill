"""Image generation emits a checkpoint at every stage boundary.

The Canon image-generation incident could not be localised from logs: the route
logged that generation started and that the provider succeeded, then went quiet
until after the DB commit. A failure anywhere in between — storage write, DB
write — looked identical from the outside.

These tests pin the checkpoints that close that gap, and pin the safety
property that matters just as much: checkpoints carry byte counts, ids and
paths, never prompt text or credentials.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

ROUTE_LOGGER = "app.api.routes.image_generator"

SECRET_PROMPT = "A lakeside at dusk with zzsecretpromptmarkerzz in the scene"


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Force local disk storage so the storage path is deterministic."""
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


def _register_and_login(client: TestClient, email: str) -> str:
    client.post(
        "/auth/register",
        json={"email": email, "username": email.split("@")[0], "password": "testpassword123"},
    )
    return client.post(
        "/auth/login", json={"email": email, "password": "testpassword123"}
    ).json()["access_token"]


def _create_character(client: TestClient, token: str) -> int:
    return client.post(
        "/characters/",
        json={"name": "Checkpoint Subject", "species": "human"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]


def _stub_png_bytes() -> bytes:
    from app.core.storage import load_image_bytes
    from app.services.stub_image_generator import generate_placeholder_png

    return load_image_bytes(generate_placeholder_png(label="test", sublabel="stub"))


@pytest.fixture
def generated(client: TestClient, caplog):
    """Run one generation through a *succeeding* provider.

    The provider is mocked so real bytes flow through the storage path — the
    no-provider placeholder branch is covered separately, since it is the one
    that skips BYTES_RECEIVED by design.
    """
    token = _register_and_login(client, "checkpoints@example.com")
    cid = _create_character(client, token)
    provider = MagicMock()
    provider.supports_multi_image_input = False
    provider.generate_image = MagicMock(return_value=_stub_png_bytes())
    with caplog.at_level(logging.INFO, logger=ROUTE_LOGGER), patch(
        "app.api.routes.image_generator.get_provider_for_option", return_value=provider
    ):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": SECRET_PROMPT,
                "include_character": False,
                "provider_option": "option1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    return resp, [r.getMessage() for r in caplog.records]


@pytest.fixture
def generated_placeholder(client: TestClient, caplog):
    """Run one generation with NO provider available (placeholder branch)."""
    token = _register_and_login(client, "checkpoints_stub@example.com")
    cid = _create_character(client, token)
    with caplog.at_level(logging.INFO, logger=ROUTE_LOGGER), patch(
        "app.api.routes.image_generator.get_provider_for_option",
        side_effect=RuntimeError("no credentials"),
    ), patch(
        "app.api.routes.image_generator.get_fallback_provider", return_value=None
    ):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={
                "prompt": SECRET_PROMPT,
                "include_character": False,
                "provider_option": "option1",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200, resp.text
    return resp, [r.getMessage() for r in caplog.records]


class TestCheckpointsEmitted:
    @pytest.mark.parametrize(
        "checkpoint",
        [
            "IMAGE_GEN_START",
            "IMAGE_GEN_BYTES_RECEIVED",
            "IMAGE_GEN_STORAGE_START",
            "IMAGE_GEN_STORAGE_OK",
            "IMAGE_GEN_DB_WRITE_START",
            "IMAGE_GEN_DB_WRITE_OK",
        ],
    )
    def test_checkpoint_present(self, generated, checkpoint):
        _, messages = generated
        assert any(checkpoint in m for m in messages), f"missing {checkpoint}"


class TestCheckpointOrdering:
    """Ordering is what makes a missing OK diagnostic — it localises the fault."""

    def _index(self, messages, marker):
        return next(i for i, m in enumerate(messages) if marker in m)

    def test_storage_brackets_are_ordered(self, generated):
        _, messages = generated
        assert self._index(messages, "IMAGE_GEN_STORAGE_START") < self._index(
            messages, "IMAGE_GEN_STORAGE_OK"
        )

    def test_db_brackets_are_ordered(self, generated):
        _, messages = generated
        assert self._index(messages, "IMAGE_GEN_DB_WRITE_START") < self._index(
            messages, "IMAGE_GEN_DB_WRITE_OK"
        )

    def test_storage_completes_before_db_write_begins(self, generated):
        _, messages = generated
        assert self._index(messages, "IMAGE_GEN_STORAGE_OK") < self._index(
            messages, "IMAGE_GEN_DB_WRITE_START"
        )

    def test_bytes_received_precedes_storage(self, generated):
        _, messages = generated
        assert self._index(messages, "IMAGE_GEN_BYTES_RECEIVED") < self._index(
            messages, "IMAGE_GEN_STORAGE_START"
        )


class TestCheckpointContent:
    def test_bytes_received_reports_a_positive_size(self, generated):
        _, messages = generated
        line = next(m for m in messages if "IMAGE_GEN_BYTES_RECEIVED" in m)
        size = int(line.split("bytes=")[1].split()[0])
        assert size > 0

    def test_storage_ok_reports_the_stored_path(self, generated):
        _, messages = generated
        line = next(m for m in messages if "IMAGE_GEN_STORAGE_OK" in m)
        assert "file_path=static/generated/" in line

    def test_db_write_ok_reports_the_image_id(self, generated):
        resp, messages = generated
        line = next(m for m in messages if "IMAGE_GEN_DB_WRITE_OK" in m)
        assert f"image_id={resp.json()['id']}" in line


class TestCheckpointsAreSafe:
    """Checkpoints must not become a leak channel."""

    def test_prompt_text_never_appears_in_stage_checkpoints(self, generated):
        _, messages = generated
        staged = [
            m for m in messages
            if any(
                k in m for k in (
                    "IMAGE_GEN_BYTES_RECEIVED",
                    "IMAGE_GEN_STORAGE_START",
                    "IMAGE_GEN_STORAGE_OK",
                    "IMAGE_GEN_DB_WRITE_START",
                    "IMAGE_GEN_DB_WRITE_OK",
                )
            )
        ]
        assert staged, "no stage checkpoints captured"
        for message in staged:
            assert "zzsecretpromptmarkerzz" not in message

    def test_no_credential_shaped_values_in_checkpoints(self, generated):
        _, messages = generated
        joined = " ".join(messages)
        for marker in ("api_key", "API_KEY", "Bearer ", "R2_SECRET", "AKIA"):
            assert marker not in joined


class TestPlaceholderBranchInstrumented:
    """No provider available still writes a file — it must not be a blind spot.

    This is the branch production takes when a provider fails to resolve in one
    environment only, so it is precisely the case worth instrumenting.
    """

    def test_storage_bracket_still_emitted(self, generated_placeholder):
        _, messages = generated_placeholder
        assert any("IMAGE_GEN_STORAGE_START" in m for m in messages)
        assert any("IMAGE_GEN_STORAGE_OK" in m for m in messages)

    def test_source_is_reported_as_placeholder(self, generated_placeholder):
        _, messages = generated_placeholder
        line = next(m for m in messages if "IMAGE_GEN_STORAGE_START" in m)
        assert "source=placeholder" in line

    def test_bytes_received_absent_when_no_provider_bytes(self, generated_placeholder):
        """BYTES_RECEIVED means 'a provider returned bytes' — it must stay truthful."""
        _, messages = generated_placeholder
        assert not any("IMAGE_GEN_BYTES_RECEIVED" in m for m in messages)

    def test_db_bracket_still_emitted(self, generated_placeholder):
        _, messages = generated_placeholder
        assert any("IMAGE_GEN_DB_WRITE_START" in m for m in messages)
        assert any("IMAGE_GEN_DB_WRITE_OK" in m for m in messages)

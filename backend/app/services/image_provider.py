"""Image generation provider abstraction.

Provides a pluggable interface for image generation backends.
Currently supports OpenAI Images API (gpt-image-1.5).
"""
from __future__ import annotations

import base64
import tempfile
import urllib.request
from pathlib import Path

from openai import OpenAI, OpenAIError

from app.core.config import settings

_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_DOWNLOAD_TIMEOUT_S = 10


class ImageProvider:
    """Base image provider with prompt validation and delegation."""

    def generate_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        reference_image_url: str | None = None,
    ) -> bytes:
        """Validate inputs and delegate to provider-specific implementation.

        Returns raw PNG bytes.

        Raises:
            ValueError: If prompt is empty or exceeds 200 characters.
        """
        if not prompt or len(prompt.strip()) == 0:
            raise ValueError("Prompt must not be empty.")
        if len(prompt) > 200:
            raise ValueError("Prompt must be 200 characters or fewer.")
        return self._generate(prompt=prompt, size=size, reference_image_url=reference_image_url)

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        raise NotImplementedError


def _download_image(url: str) -> Path:
    """Download an image URL to a temporary file.

    Enforces https/http, max size, and timeout.
    Returns the Path to the temp file (caller must clean up).
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError("reference_image_url must be an http or https URL.")

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Reference image too large ({int(content_length)} bytes, "
                f"max {_MAX_DOWNLOAD_BYTES})."
            )
        data = resp.read(_MAX_DOWNLOAD_BYTES + 1)
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Reference image exceeds {_MAX_DOWNLOAD_BYTES} byte limit."
            )

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(data)
        tmp.flush()
    finally:
        tmp.close()
    return Path(tmp.name)


class _OpenAIImageProvider(ImageProvider):
    """OpenAI Images API provider."""

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. "
                "Set it in your environment or .env file to use the OpenAI image provider."
            )
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        try:
            if reference_image_url:
                return self._edit(prompt=prompt, size=size, url=reference_image_url)
            return self._text_to_image(prompt=prompt, size=size)
        except OpenAIError as exc:
            raise RuntimeError(f"OpenAI image generation failed: {exc}") from exc

    def _text_to_image(self, *, prompt: str, size: str) -> bytes:
        response = self._client.images.generate(
            model=settings.IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size=size,
            response_format="b64_json",
        )
        return base64.b64decode(response.data[0].b64_json)

    def _edit(self, *, prompt: str, size: str, url: str) -> bytes:
        tmp_path = _download_image(url)
        try:
            with open(tmp_path, "rb") as fh:
                response = self._client.images.edit(
                    model=settings.IMAGE_MODEL,
                    image=fh,
                    prompt=prompt,
                    n=1,
                    size=size,
                    response_format="b64_json",
                )
            return base64.b64decode(response.data[0].b64_json)
        finally:
            tmp_path.unlink(missing_ok=True)


def get_image_provider() -> ImageProvider:
    """Factory: return the configured image provider instance.

    Raises:
        ValueError: If IMAGE_PROVIDER names an unsupported backend.
    """
    provider = settings.IMAGE_PROVIDER.lower()
    if provider == "openai":
        return _OpenAIImageProvider()
    raise ValueError(
        f"Unsupported IMAGE_PROVIDER: {settings.IMAGE_PROVIDER!r}. "
        f"Supported providers: 'openai'."
    )


def test_image_generation() -> bytes:
    """Quick smoke-test helper (not wired to any route).

    Returns raw PNG bytes of a generated test image.
    """
    provider = get_image_provider()
    return provider.generate_image(
        prompt="A cinematic portrait of a fictional character, dramatic lighting",
    )

"""OpenRouter image generation provider.

Uses the OpenRouter chat completions endpoint with image modality support.
Supports text-to-image and image-to-image (grounded) generation.

Docs: https://openrouter.ai/docs
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from app.core.config import settings
from app.services.image_providers.base import ImageProviderBase

logger = logging.getLogger(__name__)

_OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
_READ_TIMEOUT_S = 90        # image generation can be slow
_MAX_RETRIES = 2            # retry on transient network errors only


class OpenRouterImageProvider(ImageProviderBase):
    """OpenRouter image generation via chat completions with image modality."""

    name = "openrouter"

    def __init__(self) -> None:
        if not settings.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured. "
                "Set it in your environment or .env file to use the OpenRouter image provider."
            )
        self._api_key = settings.OPENROUTER_API_KEY
        self._model = settings.OPENROUTER_IMAGE_MODEL

    # ── Public API ────────────────────────────────────────────────────

    def generate_text_to_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        style: str = "realistic",
    ) -> bytes:
        """Generate an image from a text prompt."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        payload = self._build_payload(
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": prompt}],
            }],
            size=size,
        )
        return self._post_with_retry(payload)

    def generate_with_reference(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str = "1024x1024",
    ) -> bytes:
        """Generate an image grounded by a seed image (image-to-image).

        The seed image is embedded as a data-URL so no extra HTTP round-trip
        is needed.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not reference_image_bytes:
            raise ValueError("reference_image_bytes must not be empty.")

        encoded_seed = base64.b64encode(reference_image_bytes).decode("ascii")
        payload = self._build_payload(
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded_seed}"
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            size=size,
        )
        return self._post_with_retry(payload)

    # ── Internal helpers ──────────────────────────────────────────────

    def _build_payload(self, messages: list[dict], size: str) -> dict:
        return {
            "model": self._model,
            "messages": messages,
            "modalities": ["image", "text"],
            "image_config": {"size": size},
        }

    def _post_with_retry(self, payload: dict) -> bytes:
        """POST to the OpenRouter completions endpoint with retry on transient errors.

        HTTP errors (4xx/5xx) are not retried — they indicate auth failures or
        moderation blocks that won't change on a retry.

        Raises:
            RuntimeError: On HTTP error or after _MAX_RETRIES transient failures.
        """
        url = f"{_OPENROUTER_API_BASE}/chat/completions"
        data = json.dumps(payload).encode()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=_READ_TIMEOUT_S) as resp:
                    body = json.loads(resp.read())
                return self._parse_image_bytes(body)

            except urllib.error.HTTPError as exc:
                # Don't retry — read error body for diagnostics (no key/prompt in log)
                error_body = ""
                try:
                    error_body = exc.read().decode(errors="replace")[:300]
                except Exception:
                    pass
                logger.warning(
                    "openrouter_image_api_error status=%s snippet=%r",
                    exc.code, error_body[:100],
                )
                raise RuntimeError(
                    f"OpenRouter image generation failed (HTTP {exc.code}): "
                    f"{error_body[:200]}"
                ) from exc

            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "openrouter_image_transient_error attempt=%d/%d",
                        attempt + 1, _MAX_RETRIES + 1,
                    )
                    continue  # retry

        raise RuntimeError(
            f"OpenRouter request failed after {_MAX_RETRIES + 1} attempts: {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse_image_bytes(body: dict) -> bytes:
        """Extract and decode image bytes from an OpenRouter chat completion response.

        Expected structure:
          body["choices"][0]["message"]["images"][0]["image_url"]["url"]
        where url is a data URL: "data:<mime>;base64,<b64_data>"
        """
        try:
            image_url: str = (
                body["choices"][0]["message"]["images"][0]["image_url"]["url"]
            )
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"OpenRouter response missing expected image structure: {snippet}"
            )

        if not image_url:
            raise RuntimeError("OpenRouter response contained an empty image URL.")

        if not image_url.startswith("data:"):
            raise RuntimeError(
                f"OpenRouter returned an unexpected image URL format: {image_url[:80]}"
            )

        # Parse "data:<mime>;base64,<encoded>"
        try:
            _, encoded = image_url.split(",", 1)
            return base64.b64decode(encoded)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to decode OpenRouter image data URL: {exc}"
            ) from exc

"""FLUX image generation provider via OpenRouter Images API.

Uses the OpenRouter /v1/images/generations endpoint (OpenAI-compatible).

IMPORTANT — reference image support:
  FLUX via OpenRouter does NOT support the multi-reference image conditioning
  format used by Google (multiple inlineData parts in a single request).
  ``generate_text_to_image`` is the only supported generation mode.
  Callers must NOT assume reference images will be used — check the metadata
  field ``refs_support_level`` before interpreting generation results.

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
_READ_TIMEOUT_S = 120
_MAX_RETRIES = 2

# Explicit statement of reference-image capability for this provider class.
# Included in provider metadata so callers can report it without guessing.
REFS_SUPPORT_LEVEL = "none"


class FluxOpenRouterProvider(ImageProviderBase):
    """FLUX image generation via OpenRouter Images API (text-to-image only).

    Multi-reference image conditioning is NOT supported by FLUX via OpenRouter.
    ``generate_edit`` and reference-image methods are intentionally not
    implemented — callers receive a clear ``NotImplementedError`` rather than
    a silent text-only fallback, so the admin metadata accurately reflects
    what happened.
    """

    name = "flux_openrouter"
    refs_support_level: str = REFS_SUPPORT_LEVEL

    def __init__(self, model: str, provider_label: str = "flux_openrouter") -> None:
        if not settings.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured. "
                "Set it in your environment or .env file to use the FLUX OpenRouter provider."
            )
        self._api_key = settings.OPENROUTER_API_KEY
        self._model = model
        self._provider_label = provider_label

    @property
    def model_name(self) -> str:
        return self._model

    # ── Public API ────────────────────────────────────────────────────

    def generate_text_to_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        style: str = "realistic",
    ) -> bytes:
        """Generate an image from a text prompt via the OpenRouter Images API."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        payload = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }
        return self._post_with_retry(payload)

    def generate_edit(
        self,
        *,
        prompt: str,
        reference_image_url: str,
        size: str = "1024x1024",
    ) -> bytes:
        raise NotImplementedError(
            f"{self._provider_label} ({self._model}) via OpenRouter does not support "
            "reference-image edits. FLUX image generation is text-to-image only via "
            "this API. refs_support_level='none'. Do not fake reference support."
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _post_with_retry(self, payload: dict) -> bytes:
        """POST to the OpenRouter images/generations endpoint with retry on transient errors."""
        url = f"{_OPENROUTER_API_BASE}/images/generations"
        data = json.dumps(payload).encode()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://ficshon.com",
                    "X-Title": "Ficshon",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=_READ_TIMEOUT_S) as resp:
                    body = json.loads(resp.read())
                return self._parse_image_bytes(body)

            except urllib.error.HTTPError as exc:
                error_body = ""
                try:
                    error_body = exc.read().decode(errors="replace")[:300]
                except Exception:
                    pass
                logger.warning(
                    "flux_openrouter_api_error provider=%s model=%r status=%s snippet=%r",
                    self._provider_label, self._model, exc.code, error_body[:100],
                )
                raise RuntimeError(
                    f"FLUX OpenRouter ({self._provider_label}) image generation failed "
                    f"(HTTP {exc.code}): {error_body[:200]}"
                ) from exc

            except (urllib.error.URLError, TimeoutError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "flux_openrouter_transient_error provider=%s attempt=%d/%d",
                        self._provider_label, attempt + 1, _MAX_RETRIES + 1,
                    )
                    continue

        raise RuntimeError(
            f"FLUX OpenRouter ({self._provider_label}) request failed after "
            f"{_MAX_RETRIES + 1} attempts: {last_exc}"
        ) from last_exc

    @staticmethod
    def _parse_image_bytes(body: dict) -> bytes:
        """Extract and decode image bytes from an OpenRouter images/generations response.

        Handles both b64_json and url response formats.
        Expected structure: body["data"][0]["b64_json"]  or  body["data"][0]["url"]
        """
        try:
            item = body["data"][0]
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"FLUX OpenRouter response missing expected data structure: {snippet}"
            )

        b64 = item.get("b64_json")
        if b64:
            try:
                return base64.b64decode(b64)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to decode FLUX OpenRouter b64_json image: {exc}"
                ) from exc

        url = item.get("url")
        if url:
            # Download from URL — only expected when response_format=url was used
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read()
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to download FLUX OpenRouter image from URL: {exc}"
                ) from exc

        snippet = json.dumps(body)[:300]
        raise RuntimeError(
            f"FLUX OpenRouter response contained neither b64_json nor url: {snippet}"
        )

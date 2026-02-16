"""fal.ai image generation provider.

Uses the fal.ai synchronous REST API — no extra dependencies required.
Supports text-to-image only (no reference-image edits).
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from app.core.config import settings
from app.services.image_providers.base import ImageProviderBase

logger = logging.getLogger(__name__)

_FAL_RUN_BASE = "https://fal.run"
_TIMEOUT_S = 60
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB

# Map size strings to fal-compatible image_size values
_SIZE_MAP: dict[str, str] = {
    "1024x1024": "square_hd",
    "1024x1536": "portrait_4_3",
    "768x1024": "portrait_4_3",
    "512x768": "portrait_4_3",
}


class FalImageProvider(ImageProviderBase):
    """fal.ai provider for text-to-image generation."""

    name = "fal"

    def __init__(self) -> None:
        if not settings.FAL_KEY:
            raise RuntimeError(
                "FAL_KEY is not configured. "
                "Set it in your environment or .env to use the fal provider."
            )
        self._api_key = settings.FAL_KEY
        self._model = settings.FAL_MODEL_CHARACTER_PACK

    def generate_text_to_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        style: str = "realistic",
    ) -> bytes:
        """Call fal.ai synchronous endpoint and return raw image bytes."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        image_size = _SIZE_MAP.get(size, "portrait_4_3")
        payload = {
            "prompt": prompt[:2000],  # fal accepts longer prompts than OpenAI
            "image_size": image_size,
            "num_images": 1,
            "enable_safety_checker": False,
        }

        url = f"{_FAL_RUN_BASE}/{self._model}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Key {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode()[:500]
            except Exception:
                pass
            logger.warning("fal_api_error status=%s body=%s", exc.code, error_body)
            raise RuntimeError(
                f"fal.ai image generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"fal.ai request failed: {exc}") from exc

        # Extract the first image URL from the response
        images = body.get("images") or []
        if not images:
            raise RuntimeError("fal.ai returned no images.")

        image_url = images[0].get("url", "")
        if not image_url:
            raise RuntimeError("fal.ai returned an image entry with no URL.")

        # Download the image bytes
        return self._download_image(image_url)

    @staticmethod
    def _download_image(url: str) -> bytes:
        """Download image bytes from a URL."""
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                data = resp.read(_MAX_IMAGE_BYTES + 1)
                if len(data) > _MAX_IMAGE_BYTES:
                    raise RuntimeError("fal.ai returned an image exceeding size limit.")
                return data
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Failed to download fal.ai image: {exc}") from exc

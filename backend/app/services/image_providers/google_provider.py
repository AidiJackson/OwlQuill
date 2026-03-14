"""Google AI (Gemini native image generation) provider.

Uses the Google AI Studio generativelanguage REST API with generateContent.
Supports text-to-image only (no reference-image edits).
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.request
import urllib.error

from app.core.config import settings
from app.services.image_providers.base import ImageProviderBase

logger = logging.getLogger(__name__)

_TIMEOUT_S = 60


class GoogleImageProvider(ImageProviderBase):
    """Google Gemini native image generation via Google AI Studio."""

    name = "google"

    def __init__(self) -> None:
        if not settings.GOOGLE_AI_API_KEY:
            raise RuntimeError(
                "GOOGLE_AI_API_KEY is not configured. "
                "Set it in your environment or .env file to use the Google image provider."
            )
        self._api_key = settings.GOOGLE_AI_API_KEY
        self._model = settings.GOOGLE_IMAGE_MODEL

    def generate_text_to_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        style: str = "realistic",
    ) -> bytes:
        """Call Gemini generateContent and return raw image bytes."""
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ]
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Do not log the key or prompt
            logger.warning("google_gemini_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini image generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Google Gemini request failed: {exc}") from exc

        # Detect Google content refusal before parsing image parts.
        _cands = body.get("candidates", [])
        if _cands:
            _c0 = _cands[0]
            if (
                _c0.get("finishReason") == "IMAGE_RECITATION"
                or "unable to show the generated image" in str(
                    _c0.get("finishMessage") or ""
                ).lower()
                or _c0.get("content") == {}
            ):
                raise RuntimeError("google_refused_image: IMAGE_RECITATION")

        # Parse: candidates[0].content.parts[] — find part with inlineData
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"Google Gemini response missing expected structure: {snippet}"
            )

        for part in parts:
            inline = part.get("inlineData")
            if inline:
                encoded = inline.get("data", "")
                if encoded:
                    return base64.b64decode(encoded)

        snippet = json.dumps(body)[:300]
        raise RuntimeError(
            f"Google Gemini response contained no inlineData image: {snippet}"
        )

    def generate_with_multi_reference(
        self,
        *,
        prompt: str,
        reference_images: list[bytes],
        size: str = "1024x1024",
    ) -> bytes:
        """Generate conditioned on multiple identity anchor images (B19).

        Sends all anchor images as inlineData parts before the text prompt,
        giving the model multi-angle visual identity context.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not reference_images:
            raise ValueError("reference_images must not be empty.")

        parts: list[dict] = []
        for img_bytes in reference_images:
            encoded = base64.b64encode(img_bytes).decode("ascii")
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": encoded,
                }
            })
        parts.append({"text": prompt})

        payload = {"contents": [{"parts": parts}]}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("google_gemini_multi_anchor_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini multi-anchor generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Google Gemini multi-anchor request failed: {exc}") from exc

        _cands = body.get("candidates", [])
        if _cands:
            _c0 = _cands[0]
            if (
                _c0.get("finishReason") == "IMAGE_RECITATION"
                or "unable to show the generated image" in str(
                    _c0.get("finishMessage") or ""
                ).lower()
                or _c0.get("content") == {}
            ):
                raise RuntimeError("google_refused_image: IMAGE_RECITATION")

        try:
            resp_parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"Google Gemini multi-anchor response missing expected structure: {snippet}"
            )

        for part in resp_parts:
            inline = part.get("inlineData")
            if inline:
                encoded_out = inline.get("data", "")
                if encoded_out:
                    return base64.b64decode(encoded_out)

        snippet = json.dumps(body)[:300]
        raise RuntimeError(
            f"Google Gemini multi-anchor response contained no inlineData image: {snippet}"
        )

    def generate_with_reference(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str = "1024x1024",
    ) -> bytes:
        """Generate an image grounded by a seed image (inlineData).

        Sends the seed bytes as an image part alongside the pose prompt so the
        model preserves identity across angles.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not reference_image_bytes:
            raise ValueError("reference_image_bytes must not be empty.")

        encoded_seed = base64.b64encode(reference_image_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": encoded_seed,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ]
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("google_gemini_grounded_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini grounded generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Google Gemini grounded request failed: {exc}") from exc

        # Detect Google content refusal before parsing image parts.
        _cands = body.get("candidates", [])
        if _cands:
            _c0 = _cands[0]
            if (
                _c0.get("finishReason") == "IMAGE_RECITATION"
                or "unable to show the generated image" in str(
                    _c0.get("finishMessage") or ""
                ).lower()
                or _c0.get("content") == {}
            ):
                raise RuntimeError("google_refused_image: IMAGE_RECITATION")

        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"Google Gemini grounded response missing expected structure: {snippet}"
            )

        for part in parts:
            inline = part.get("inlineData")
            if inline:
                encoded = inline.get("data", "")
                if encoded:
                    return base64.b64decode(encoded)

        snippet = json.dumps(body)[:300]
        raise RuntimeError(
            f"Google Gemini grounded response contained no inlineData image: {snippet}"
        )

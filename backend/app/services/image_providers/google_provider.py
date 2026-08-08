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
from app.core.storage import detect_image_format
from app.services.image_providers.base import ImageProviderBase

logger = logging.getLogger(__name__)

# ── Prompt-level block marker ─────────────────────────────────────────
# Gemini answers a REFUSED prompt with HTTP 200 and a body carrying
# ``promptFeedback.blockReason`` and NO ``candidates`` key. Parsing that body
# for image parts therefore fails on a KeyError, and the resulting
# "response missing expected structure: {...json...}" message buried the real
# reason inside a truncated JSON snippet — the caller could not tell a benign
# block (blockReason=OTHER, no safety category) apart from a genuine sexual
# refusal, and reported both to the user as adult content.
#
# The block is now raised as a parseable marker instead:
#
#     google_prompt_blocked:<BLOCK_REASON>:<CATEGORY=PROBABILITY,...>
#
# Callers classify it with :func:`parse_prompt_block`. The category list is
# whatever Google returned in promptFeedback.safetyRatings and is frequently
# EMPTY for blockReason=OTHER — an empty list means Google supplied no safety
# category, NOT that the content was safe or unsafe.
GOOGLE_PROMPT_BLOCKED_PREFIX = "google_prompt_blocked:"


def parse_prompt_block(reason: str) -> tuple[str | None, list[str]]:
    """Parse a ``google_prompt_blocked`` marker into (block_reason, categories).

    Returns ``(None, [])`` for any string that is not such a marker, so callers
    can pass an arbitrary provider-failure message in without pre-checking.
    """
    if not reason or GOOGLE_PROMPT_BLOCKED_PREFIX not in reason:
        return None, []
    tail = reason.split(GOOGLE_PROMPT_BLOCKED_PREFIX, 1)[1]
    block_reason, _, cats = tail.partition(":")
    categories = [c for c in (p.strip() for p in cats.split(",")) if c]
    return (block_reason.strip() or None), categories


def _raise_if_prompt_blocked(body: dict) -> None:
    """Raise a parseable marker when Google blocked the prompt outright."""
    feedback = body.get("promptFeedback") or {}
    block_reason = feedback.get("blockReason")
    if not block_reason:
        return
    categories = ",".join(
        f"{r.get('category')}={r.get('probability')}"
        for r in (feedback.get("safetyRatings") or [])
        if r.get("category")
    )
    raise RuntimeError(f"{GOOGLE_PROMPT_BLOCKED_PREFIX}{block_reason}:{categories}")


def _inline_image_part(image_bytes: bytes) -> dict:
    """Build an inlineData part declaring the image's ACTUAL media type.

    The mime type was previously hardcoded to image/png for every reference,
    which mislabelled the JPEG/WebP cards the admin canon-upload route accepts
    and stores untranscoded. ``detect_image_format`` falls back to image/png for
    unrecognised bytes, so anything that is not sniffable is sent exactly as it
    was before.
    """
    _, mime_type = detect_image_format(image_bytes)
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(image_bytes).decode("ascii"),
        }
    }


def _timeout() -> int:
    return settings.GOOGLE_IMAGE_TIMEOUT_S


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

        _t = _timeout()
        try:
            with urllib.request.urlopen(req, timeout=_t) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Do not log the key or prompt
            logger.warning("google_gemini_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini image generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "google_gemini_timeout provider=google timeout_seconds=%s error=%r",
                _t, exc,
            )
            raise RuntimeError(f"Google Gemini request failed: {exc}") from exc

        # Detect Google content refusal before parsing image parts.
        _raise_if_prompt_blocked(body)
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

        parts: list[dict] = [_inline_image_part(b) for b in reference_images]
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

        _t = _timeout()
        try:
            with urllib.request.urlopen(req, timeout=_t) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("google_gemini_multi_anchor_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini multi-anchor generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "google_gemini_timeout provider=google timeout_seconds=%s error=%r",
                _t, exc,
            )
            raise RuntimeError(f"Google Gemini multi-anchor request failed: {exc}") from exc

        _raise_if_prompt_blocked(body)
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

        payload = {
            "contents": [
                {
                    "parts": [
                        _inline_image_part(reference_image_bytes),
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

        _t = _timeout()
        try:
            with urllib.request.urlopen(req, timeout=_t) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            logger.warning("google_gemini_grounded_api_error status=%s", exc.code)
            raise RuntimeError(
                f"Google Gemini grounded generation failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "google_gemini_timeout provider=google timeout_seconds=%s error=%r",
                _t, exc,
            )
            raise RuntimeError(f"Google Gemini grounded request failed: {exc}") from exc

        # Detect Google content refusal before parsing image parts.
        _raise_if_prompt_blocked(body)
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

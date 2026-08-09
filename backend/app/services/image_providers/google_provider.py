"""Google AI (Gemini native image generation) provider.

Uses the Google AI Studio generativelanguage REST API with generateContent.
Supports text-to-image only (no reference-image edits).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
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


def google_credential_fingerprint() -> str:
    """One-way 12-char fingerprint of the Google credential this process uses.

    Two runtimes holding the SAME key produce the same fingerprint; two runtimes
    holding different keys cannot collide in practice. The key itself is not
    recoverable from it, so this is safe to log and safe to return from the
    admin diagnostics endpoint.

    It exists because a workspace and a Replit deployment are separate secret
    scopes: deployment secrets are not readable from the workspace shell, so the
    ONLY way to establish whether dev and production authenticate to Google as
    the same project is to have each runtime report a comparable derivative of
    its own key. Returns "unset" when no key is configured — an answer in its
    own right.

    Read from the live environment first so it reflects the running process
    rather than a settings snapshot captured at import time.
    """
    key = os.getenv("GOOGLE_AI_API_KEY") or settings.GOOGLE_AI_API_KEY or ""
    if not key:
        return "unset"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def google_effective_config() -> dict:
    """Every Google knob that can differ between two runtimes, credential-safe.

    Mirrors exactly what the request builders below consult, so a dev/prod diff
    of this dict is a diff of the outgoing request's non-content parameters.
    """
    key = os.getenv("GOOGLE_AI_API_KEY") or settings.GOOGLE_AI_API_KEY or ""
    return {
        "credential_fingerprint": google_credential_fingerprint(),
        "credential_present": bool(key),
        "credential_length": len(key),
        "api_host": "generativelanguage.googleapis.com",
        "api_version": "v1beta",
        "model": settings.GOOGLE_IMAGE_MODEL,
        "timeout_s": settings.GOOGLE_IMAGE_TIMEOUT_S,
        # The payload builders send contents[] only. Declaring the absence
        # explicitly is the point: it rules both out as a dev/prod variable.
        "generation_config": None,
        "safety_settings": None,
        "system_instruction": None,
        "image_provider": settings.IMAGE_PROVIDER,
        "identity_image_provider": settings.IDENTITY_IMAGE_PROVIDER or None,
        "identity_seed_provider": settings.IDENTITY_SEED_PROVIDER,
        "identity_angles_provider": settings.IDENTITY_ANGLES_PROVIDER,
    }


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

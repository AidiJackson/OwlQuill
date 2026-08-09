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
import random
import time
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


# ── Bounded retry policy ──────────────────────────────────────────────
#
# Google's failure signals fall on two sides of a line, and the side decides
# whether a retry can possibly help:
#
#   promptFeedback.blockReason  — evaluated on the INPUT, before generation.
#       Deterministic for a fixed request: the same bytes produce the same
#       verdict. Google documents OTHER as a non-configurable policy filter that
#       neither threshold changes nor retries affect. Proven here too — the
#       production one-reference run sent a byte-identical request twice (the
#       multi-anchor and grounded payloads are identical when there is exactly
#       one reference) and was blocked both times. NEVER retried.
#
#   finishReason IMAGE_RECITATION — evaluated on the OUTPUT that was sampled.
#       Genuinely stochastic, so a resample can differ. Google's documented
#       remedy is to raise the temperature; that is applied on the single retry
#       and nowhere else, so a first attempt is byte-for-byte what it always was.
#
#   HTTP 408 / 429 / 5xx — transport. The only class Google documents as
#       retryable, and observed here (one 503 in eighteen dev calls). Retried
#       once with the IDENTICAL payload.
#
# Every retry re-sends the same references, in the same order, with the same
# prompt and model. Availability is never bought by weakening identity evidence.
_RETRY_TRANSIENT_CODES = (408, 429)
_RETRY_BACKOFF_S = 0.75
_RETRY_JITTER_S = 0.5
# Hard ceiling: one initial attempt + at most one transient retry + at most one
# recitation retry. A counter (not just the per-class flags) guarantees no loop
# can outlive its budget however the classes interleave.
_MAX_ATTEMPTS = 3
# Google's documented recitation remedy. The default is unset — the first
# attempt sends no generationConfig at all, exactly as before.
_RECITATION_RETRY_TEMPERATURE = 1.3


class _TransientHTTP(Exception):
    """Internal marker: an HTTP status Google documents as retryable."""

    def __init__(self, code: int) -> None:
        super().__init__(f"transient HTTP {code}")
        self.code = code


def _is_transient_http(code: int) -> bool:
    """True for the HTTP classes Google documents as retryable."""
    return code in _RETRY_TRANSIENT_CODES or 500 <= code < 600


def _is_image_recitation(body: dict) -> bool:
    """True when Google generated an image but declined to return it."""
    cands = body.get("candidates") or []
    if not cands:
        return False
    c0 = cands[0]
    return bool(
        c0.get("finishReason") == "IMAGE_RECITATION"
        or "unable to show the generated image" in str(
            c0.get("finishMessage") or ""
        ).lower()
        or c0.get("content") == {}
    )


def _extract_inline_image(body: dict) -> bytes | None:
    """Return the first inlineData image in the response, if any."""
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError):
        return None
    for part in parts:
        inline = part.get("inlineData")
        if inline and inline.get("data"):
            return base64.b64decode(inline["data"])
    return None


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

    # ── Transport ─────────────────────────────────────────────────────

    def _post_once(self, payload: dict, *, refs: int, label: str, short: str) -> dict:
        """POST one generateContent request and return the parsed body.

        Raises ``_TransientHTTP`` for the documented retryable HTTP classes and
        ``RuntimeError`` for everything else, so the caller's retry policy sees
        exactly one signal per class.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )
        data = json.dumps(payload).encode()
        # Permanent operational diagnostic: this is the only place the true
        # serialized request size exists — callers can only estimate it. Counts
        # and byte totals only; never bytes, prompt text, URLs or credentials.
        logger.info(
            "GOOGLE_MULTI_REF_PAYLOAD refs=%d payload_bytes=%d model=%s",
            refs, len(data), self._model,
        )
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        _t = _timeout()
        try:
            with urllib.request.urlopen(req, timeout=_t) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Never log the key or the prompt.
            logger.warning("google_gemini_api_error label=%s status=%s", label, exc.code)
            if _is_transient_http(exc.code):
                raise _TransientHTTP(exc.code) from exc
            raise RuntimeError(
                f"Google Gemini {label} failed (HTTP {exc.code})"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning(
                "google_gemini_timeout provider=google label=%s timeout_seconds=%s error=%r",
                label, _t, exc,
            )
            raise RuntimeError(f"Google Gemini {short}request failed: {exc}") from exc

    def _generate(self, payload: dict, *, refs: int, label: str, short: str) -> bytes:
        """Run one generation under the bounded retry policy.

        The payload is sent unchanged on the first attempt and on any transient
        retry. Only a recitation retry alters it, and only by adding the
        documented temperature remedy — never the references, their order, the
        prompt or the model.
        """
        attempt_payload = dict(payload)
        transient_retried = False
        recitation_retried = False

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                body = self._post_once(attempt_payload, refs=refs, label=label, short=short)
            except _TransientHTTP as exc:
                if transient_retried:
                    logger.warning(
                        "GOOGLE_RETRY_EXHAUSTED label=%s class=transient status=%s",
                        label, exc.code,
                    )
                    raise RuntimeError(
                        f"Google Gemini {label} failed (HTTP {exc.code})"
                    ) from exc
                transient_retried = True
                delay = _RETRY_BACKOFF_S + random.uniform(0, _RETRY_JITTER_S)
                logger.info(
                    "GOOGLE_RETRY label=%s class=transient status=%s attempt=%d "
                    "delay_s=%.2f identical_payload=true refs=%d",
                    label, exc.code, attempt, delay, refs,
                )
                time.sleep(delay)
                continue

            # Input-side block: deterministic for a fixed request. Never retried.
            _raise_if_prompt_blocked(body)

            if _is_image_recitation(body):
                if recitation_retried:
                    logger.warning(
                        "GOOGLE_RETRY_EXHAUSTED label=%s class=image_recitation", label,
                    )
                    raise RuntimeError("google_refused_image: IMAGE_RECITATION")
                recitation_retried = True
                attempt_payload = {
                    **payload,
                    "generationConfig": {
                        **(payload.get("generationConfig") or {}),
                        "temperature": _RECITATION_RETRY_TEMPERATURE,
                    },
                }
                logger.info(
                    "GOOGLE_RETRY label=%s class=image_recitation attempt=%d "
                    "temperature=%s refs=%d same_refs=true same_prompt=true",
                    label, attempt, _RECITATION_RETRY_TEMPERATURE, refs,
                )
                continue

            image = _extract_inline_image(body)
            if image is not None:
                return image

            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"Google Gemini {short}response contained no inlineData image: {snippet}"
            )

        # Unreachable: every branch above either returns or raises, and the
        # per-class flags cap the loop well inside _MAX_ATTEMPTS. Present so a
        # future class cannot silently fall out of the loop without a signal.
        raise RuntimeError(f"Google Gemini {short}exhausted retry budget")

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

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        return self._generate(payload, refs=0, label="image generation", short="")

    def generate_with_multi_reference(
        self,
        *,
        prompt: str,
        reference_images: list[bytes],
        size: str = "1024x1024",
    ) -> bytes:
        """Generate conditioned on multiple identity anchor images (B19).

        Sends all anchor images as inlineData parts before the text prompt,
        giving the model multi-angle visual identity context. Every retry
        carries the SAME complete set in the SAME order — a retry must never
        improve availability by sending weaker identity evidence.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not reference_images:
            raise ValueError("reference_images must not be empty.")

        parts: list[dict] = [_inline_image_part(b) for b in reference_images]
        parts.append({"text": prompt})
        payload = {"contents": [{"parts": parts}]}
        return self._generate(
            payload, refs=len(reference_images),
            label="multi-anchor generation", short="multi-anchor ",
        )

    def generate_with_reference(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str = "1024x1024",
    ) -> bytes:
        """Generate an image grounded by a single seed image (inlineData).

        Used by providers/paths whose capability is genuinely single-reference.
        The Canon route no longer calls this as a fallback after a failed
        multi-reference attempt — see image_generator.generate_image().
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
        return self._generate(payload, refs=1, label="grounded generation", short="grounded ")

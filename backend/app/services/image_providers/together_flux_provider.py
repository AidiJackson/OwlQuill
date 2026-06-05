"""Together AI FLUX.2 image provider (admin/internal testing only).

References are accepted as PUBLIC HTTPS URLs only — Together AI's backend
fetches them directly; local disk paths and relative URLs are inaccessible.
When no public HTTPS URLs survive filtering the caller should fall back to
text-to-image rather than trying to pass local paths.

API: POST https://api.together.ai/v1/images/generations
Docs: https://docs.together.ai/reference/post_v1-images-generations
Model: black-forest-labs/FLUX.1-schnell-Free (configurable via TOGETHER_FLUX_MODEL)

refs_support_level = "url_required"
  — references ARE supported, but only via public HTTPS URLs, not raw bytes.
  — compare with "none" (FLUX/OpenRouter) where references are never forwarded.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

REFS_SUPPORT_LEVEL = "url_required"

_TOGETHER_API_BASE = "https://api.together.ai"
_DEFAULT_TIMEOUT_S = 180
_MAX_REFERENCE_IMAGES = 8  # Together API cap (pro/dev tier)


class TogetherFluxProvider:
    """Together AI FLUX.2 image provider.

    Supports reference images as a flat array of public HTTPS URL strings.
    Local paths (``/static/...``) are silently filtered before the payload
    is sent; if none survive the filter, ``generate_with_reference_urls``
    raises ``ValueError`` so the caller can fall back cleanly.
    """

    name = "together_flux"
    refs_support_level: str = REFS_SUPPORT_LEVEL

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        disable_safety_checker: bool = False,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "TOGETHER_API_KEY is required to use the Together AI FLUX.2 provider."
            )
        self._api_key = api_key
        self._model = model
        self._disable_safety_checker = disable_safety_checker
        self._timeout_s = timeout_s

    @property
    def model_name(self) -> str:
        return self._model

    # ── Public generation methods ────────────────────────────────────────

    def generate_text_to_image(self, *, prompt: str, size: str = "1024x1024") -> bytes:
        """Text-to-image with no reference conditioning."""
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty.")
        payload = self._build_payload(prompt, size, reference_urls=[])
        return self._post(payload)

    def generate_with_reference_urls(
        self,
        *,
        prompt: str,
        anchor_urls: list[str],
        size: str = "1024x1024",
    ) -> bytes:
        """Text-to-image conditioned on public HTTPS reference URL strings.

        Together AI's backend fetches reference images directly from these URLs,
        so they must be publicly reachable HTTPS endpoints.

        Raises:
            ValueError: If prompt is empty or no valid public HTTPS URLs remain
                after filtering (caller should fall back to text-to-image).
            RuntimeError: On API-side failure or malformed response.
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty.")
        public_urls = [u for u in anchor_urls if u.startswith("https://")]
        if not public_urls:
            raise ValueError(
                "No public HTTPS URLs provided; Together AI cannot access local paths. "
                "Fall back to text-to-image."
            )
        capped = public_urls[:_MAX_REFERENCE_IMAGES]
        payload = self._build_payload(prompt, size, reference_urls=capped)
        return self._post(payload)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _build_payload(
        self,
        prompt: str,
        size: str,
        *,
        reference_urls: list[str],
    ) -> dict:
        width, height = self._parse_size(size)
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "width": width,
            "height": height,
            "response_format": "b64_json",
        }
        if reference_urls:
            payload["reference_images"] = reference_urls
        if self._disable_safety_checker:
            payload["disable_safety_checker"] = True
        return payload

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        """Parse "WxH" string into (width, height) ints."""
        parts = size.lower().split("x")
        if len(parts) != 2:
            raise ValueError(f"Invalid size format: {size!r}. Expected 'WxH'.")
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError(f"Non-integer dimensions in size: {size!r}.") from None

    def _post(self, payload: dict) -> bytes:
        """POST to Together AI images endpoint and return image bytes."""
        url = f"{_TOGETHER_API_BASE}/v1/images/generations"
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode(errors="replace")
            except Exception:
                detail = str(exc)
            raise RuntimeError(
                f"Together AI API error {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Together AI network error: {exc}") from exc

        elapsed = time.monotonic() - t0
        logger.info(
            "TOGETHER_FLUX_API_OK model=%s refs=%d elapsed_s=%.1f",
            self._model,
            len(payload.get("reference_images", [])),
            elapsed,
        )
        return self._parse_response(raw)

    @staticmethod
    def _parse_response(raw: bytes) -> bytes:
        """Extract image bytes from Together AI images response."""
        try:
            body = json.loads(raw)
        except Exception as exc:
            raise RuntimeError(
                f"Together AI returned non-JSON body: {raw[:200]!r}"
            ) from exc

        # Together returns either {"data": [...]} or {"images": [...]}
        data = body.get("data") or body.get("images")
        if not data or not isinstance(data, list):
            raise RuntimeError(
                f"Together AI response has no 'data' or 'images' array: {body}"
            )

        entry = data[0]
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"Together AI response entry is not a dict: {entry!r}"
            )

        b64 = entry.get("b64_json") or entry.get("b64")
        if b64:
            return base64.b64decode(b64)

        img_url = entry.get("url")
        if img_url:
            req = urllib.request.Request(img_url)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.read()
            except Exception as exc:
                raise RuntimeError(
                    f"Together AI returned a URL but fetch failed: {exc}"
                ) from exc

        raise RuntimeError(
            f"Together AI response entry has no usable image field (b64_json/url): {entry}"
        )

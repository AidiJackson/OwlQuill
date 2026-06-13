"""ReplicateImg2ImgProvider — Adult Studio's experimental fourth provider (Sprint E9).

A pure image-to-image provider: it takes an EXISTING canon source image, sends it to
Replicate with a prompt, and returns the transformed image bytes. That's it.

    source image bytes ─▶ provider ─▶ result bytes ─▶ (caller saves to library)

It is intentionally SEPARATE from everything else in Adult Studio:
  - NOT a replacement for the OpenAI / Gemini / Grok generation paths.
  - NO mask logic, NO compositing, NO editor-job architecture, NO LoRA training.
  - It never touches Canon Studio and never mutates canon.

Construction is gated: it requires a ``REPLICATE_API_TOKEN``. With an empty token the
class refuses to construct, so no half-configured network call is possible. The model is
switchable by env (``ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL``) with a configurable fallback
(``ADULT_STUDIO_REPLICATE_IMG2IMG_FALLBACK``) tried when the primary model errors. The
img2img ``strength`` (Replicate ``prompt_strength``) defaults to 0.65 and is configurable.

The HTTP layer is injected as a ``session`` (a ``requests.Session``-shaped object) so tests
can supply a fake transport and assert the exact request sequence WITHOUT any live API call.
This mirrors the proven pattern in ``replicate_training_provider.py``.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

API_BASE = "https://api.replicate.com/v1"

# img2img defaults — conservative settings tuned for identity/tattoo preservation.
DEFAULT_STRENGTH = 0.65
DEFAULT_NEGATIVE_PROMPT = (
    "different person, different face, deformed, disfigured, extra limbs, "
    "missing tattoos, wrong tattoos, watermark, text, logo, low quality"
)
# Terminal Replicate prediction statuses.
_TERMINAL = {"succeeded", "failed", "canceled"}


class ReplicateImg2ImgError(Exception):
    """Raised when Replicate returns an unexpected/non-2xx response or a failed run."""


class ReplicateImg2ImgProvider:
    """Replicate image-to-image provider. Source image + prompt → transformed image.

    Lifecycle for a single call (``img2img``): upload the source bytes to Replicate's
    file store (so Replicate can fetch them regardless of where the canon image lives) →
    create a prediction against the configured model → poll until terminal → download the
    output image bytes. On a primary-model failure the fallback model is tried once.
    """

    slug = "replicate_nsfw"
    label = "Replicate (Experimental Adult)"

    def __init__(
        self,
        *,
        api_token: str,
        model_ref: str,
        fallback_model_ref: str = "",
        strength: float = DEFAULT_STRENGTH,
        session: Any = None,
        timeout: float = 120.0,
        poll_interval: float = 2.0,
        max_poll_seconds: float = 300.0,
    ) -> None:
        if not api_token:
            raise ValueError("ReplicateImg2ImgProvider requires a REPLICATE_API_TOKEN")
        if not model_ref:
            raise ValueError("ReplicateImg2ImgProvider requires a model_ref")
        self._token = api_token
        self._model_ref = model_ref.strip()
        self._fallback_model_ref = (fallback_model_ref or "").strip()
        self._strength = float(strength)
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._max_poll_seconds = max_poll_seconds
        if session is None:  # pragma: no cover - exercised only with real creds
            import requests  # local import keeps requests off the gated path

            session = requests.Session()
        self._session = session

    # ── HTTP seam ────────────────────────────────────────────────────────────────
    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, method: str, url: str, **kwargs) -> dict:
        resp = self._session.request(
            method, url, headers={**self._headers, **kwargs.pop("headers", {})},
            timeout=self._timeout, **kwargs,
        )
        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code >= 400:
            body = getattr(resp, "text", "")
            raise ReplicateImg2ImgError(f"{method} {url} -> {status_code}: {body}")
        return resp.json()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _upload_source(self, image_bytes: bytes) -> str:
        """Upload source bytes to Replicate's file store; return the fetchable URL."""
        out = self._request(
            "POST", f"{API_BASE}/files",
            files={"content": ("source.png", image_bytes, "image/png")},
        )
        url = (out.get("urls") or {}).get("get")
        if not url:
            raise ReplicateImg2ImgError(f"file upload returned no url: {out}")
        return url

    @staticmethod
    def _retry_after(resp: Any) -> Optional[float]:
        """Read a Retry-After header (seconds) from a 429 response, if present."""
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _resolve_version(self, model_ref: str) -> str:
        """Resolve a model_ref to a concrete version hash.

        ``owner/name:version`` is used as-is. ``owner/name`` is resolved to its
        ``latest_version`` via ``GET /v1/models/{owner}/{name}`` — the reliable path for
        community models (the model-level predictions endpoint is not available for them).
        """
        if ":" in model_ref:
            return model_ref.split(":", 1)[1]
        info = self._request("GET", f"{API_BASE}/models/{model_ref}")
        version = (info.get("latest_version") or {}).get("id")
        if not version:
            raise ReplicateImg2ImgError(f"model {model_ref} has no latest_version")
        return version

    def _create_prediction(self, model_ref: str, payload: dict) -> dict:
        """Create a prediction via ``POST /v1/predictions`` against the resolved version.

        Throttle handling: on a 429 we honor Retry-After (default 10s), sleep that
        many seconds + 1, and retry the prediction exactly ONCE before failing. Only
        429 is retried — all other non-2xx responses raise immediately.
        """
        version = self._resolve_version(model_ref)
        url = f"{API_BASE}/predictions"
        json_body = {"version": version, "input": payload}
        headers = {**self._headers, "Content-Type": "application/json"}

        resp = self._session.request("POST", url, headers=headers, json=json_body, timeout=self._timeout)

        if getattr(resp, "status_code", None) == 429:
            wait = self._retry_after(resp) or 10
            logger.warning("REPLICATE_THROTTLE 429 model=%s retry_after=%ss", model_ref, wait)
            time.sleep(wait + 1)
            resp = self._session.request("POST", url, headers=headers, json=json_body, timeout=self._timeout)

        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code >= 400:
            raise ReplicateImg2ImgError(f"POST {url} -> {status_code}: {getattr(resp, 'text', '')}")
        return resp.json()

    def _await_prediction(self, prediction: dict) -> dict:
        """Poll the prediction until it reaches a terminal status."""
        status = prediction.get("status")
        poll_url = (prediction.get("urls") or {}).get("get")
        deadline = self._max_poll_seconds
        elapsed = 0.0
        while status not in _TERMINAL:
            if not poll_url:
                raise ReplicateImg2ImgError("prediction has no poll url")
            if elapsed >= deadline:
                raise ReplicateImg2ImgError(
                    f"prediction timed out after {deadline}s (last status={status})"
                )
            time.sleep(self._poll_interval)
            elapsed += self._poll_interval
            prediction = self._request("GET", poll_url)
            status = prediction.get("status")
        return prediction

    @staticmethod
    def _output_url(prediction: dict) -> str:
        """Extract the single result image URL from a succeeded prediction."""
        output = prediction.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if not isinstance(output, str) or not output:
            raise ReplicateImg2ImgError(f"prediction produced no image output: {output!r}")
        return output

    def _download(self, url: str) -> bytes:
        resp = self._session.request("GET", url, timeout=self._timeout)
        status_code = getattr(resp, "status_code", None)
        if status_code is None or status_code >= 400:
            raise ReplicateImg2ImgError(f"GET {url} -> {status_code}")
        return resp.content

    def _run_model(self, model_ref: str, payload: dict, source_url: str, prompt: str) -> bytes:
        """Create → await → download for one model. Raises on any failure."""
        logger.info(
            "REPLICATE_TEST model=%s strength=%s source=%s prompt=%s",
            model_ref, payload["prompt_strength"], source_url, prompt,
        )
        prediction = self._create_prediction(model_ref, payload)
        prediction = self._await_prediction(prediction)
        if prediction.get("status") != "succeeded":
            raise ReplicateImg2ImgError(
                f"model {model_ref} run {prediction.get('status')}: {prediction.get('error')}"
            )
        output_url = self._output_url(prediction)
        logger.info("REPLICATE_SUCCESS output=%s", output_url)
        return self._download(output_url)

    # ── public API ───────────────────────────────────────────────────────────────
    def img2img(
        self,
        *,
        source_image_bytes: bytes,
        prompt: str,
        strength: Optional[float] = None,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    ) -> tuple[bytes, str]:
        """Transform ``source_image_bytes`` per ``prompt``. Returns (png_bytes, model_used).

        Uploads the source to Replicate, runs the primary model, and on failure tries the
        configured fallback model (once). Raises ``ReplicateImg2ImgError`` if both fail.
        """
        if not source_image_bytes:
            raise ReplicateImg2ImgError("img2img requires source_image_bytes")
        if not prompt or not prompt.strip():
            raise ReplicateImg2ImgError("img2img requires a non-empty prompt")

        source_url = self._upload_source(source_image_bytes)
        payload = {
            "image": source_url,
            "prompt": prompt.strip(),
            "negative_prompt": negative_prompt,
            "prompt_strength": float(self._strength if strength is None else strength),
        }

        candidates = [self._model_ref]
        if self._fallback_model_ref and self._fallback_model_ref != self._model_ref:
            candidates.append(self._fallback_model_ref)

        last_error: Optional[Exception] = None
        for model_ref in candidates:
            try:
                png = self._run_model(model_ref, payload, source_url, prompt.strip())
                return png, model_ref
            except Exception as exc:  # noqa: BLE001 - try fallback, then re-raise
                last_error = exc
                logger.error("REPLICATE_FAIL %s", exc)

        raise ReplicateImg2ImgError(f"all replicate models failed: {last_error}")


def get_replicate_img2img_provider(settings) -> ReplicateImg2ImgProvider:
    """Construct the provider from settings. Raises ValueError if the token is unset.

    Kept tiny and lazy: the route constructs this ONLY after the admin gate passes,
    so an unconfigured environment never reaches a network call.
    """
    return ReplicateImg2ImgProvider(
        api_token=settings.REPLICATE_API_TOKEN,
        model_ref=settings.ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL,
        fallback_model_ref=settings.ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL_FALLBACK,
        strength=settings.ADULT_STUDIO_REPLICATE_IMG2IMG_STRENGTH,
    )

"""Editor Studio service — image-to-image editing of existing character images.

Sprint E1 foundation. This is the EDITOR path: it transforms 1-3 existing
source images with a prompt via the OpenAI Images edit API (gpt-image).
It deliberately does NOT touch Canon Studio generation, Adult Studio,
LoRA/RunPod, or tattoo enforcement — identity preservation comes from the
source images themselves plus a high input-fidelity edit.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from openai import OpenAI, OpenAIError

from app.core.config import settings

logger = logging.getLogger(__name__)

EDITOR_VERSION = "e1"  # legacy alias — editors now carry their own editor_version

MIN_STRENGTH = 0.1
MAX_STRENGTH = 0.5
DEFAULT_STRENGTH = 0.25
MAX_SOURCE_IMAGES = 3

# Strength → input_fidelity mapping. gpt-image edits expose a binary
# input-fidelity control, not a continuous strength. Low strength (subtle
# transformation, maximum identity preservation) maps to "high" fidelity.
HIGH_FIDELITY_STRENGTH_CUTOFF = 0.35

# Identity-preservation wrapper prepended to every editor prompt. The source
# images are the identity truth; this confirms the contract in text.
_EDITOR_IDENTITY_PREFIX = (
    "Edit the provided image(s) of this character. Keep the SAME person: "
    "identical face, facial structure, hair, body proportions, and all "
    "tattoos/markings in their exact placements. Only change what the "
    "instruction asks for. Instruction: "
)


def clamp_strength(value: float | None) -> float:
    """Clamp strength into the allowed editor range [0.1, 0.5]."""
    if value is None:
        return DEFAULT_STRENGTH
    return max(MIN_STRENGTH, min(MAX_STRENGTH, float(value)))


def strength_to_input_fidelity(strength: float) -> str:
    """Map a clamped strength to the gpt-image input_fidelity parameter."""
    return "high" if strength <= HIGH_FIDELITY_STRENGTH_CUTOFF else "low"


def build_editor_prompt(prompt: str) -> str:
    """Wrap the user instruction with the identity-preservation contract."""
    return _EDITOR_IDENTITY_PREFIX + prompt.strip()


class GptImageEditor:
    """gpt-image editor backend — image-to-image edits only, never text-to-image."""

    provider_name = "gpt-image"
    editor_version = "e1"

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured — required for the gpt-image editor."
            )
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def edit(
        self,
        *,
        prompt: str,
        source_images: list[bytes],
        strength: float,
        size: str = "1024x1024",
    ) -> bytes:
        """Edit 1-3 source images per the prompt. Returns raw PNG bytes.

        Raises:
            ValueError: invalid inputs.
            RuntimeError: provider-side failure.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not source_images:
            raise ValueError("At least one source image is required.")
        if len(source_images) > MAX_SOURCE_IMAGES:
            raise ValueError(f"At most {MAX_SOURCE_IMAGES} source images are allowed.")

        fidelity = strength_to_input_fidelity(strength)
        full_prompt = build_editor_prompt(prompt)

        tmp_paths: list[Path] = []
        handles: list = []
        try:
            for img in source_images:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(img)
                tmp.flush()
                tmp.close()
                tmp_paths.append(Path(tmp.name))
                handles.append(open(tmp.name, "rb"))  # noqa: WPS515

            image_arg = handles if len(handles) > 1 else handles[0]
            import base64

            # input_fidelity is a MODEL capability, not an SDK constant:
            # gpt-image-2 rejects the parameter outright (it always processes
            # inputs at high fidelity), while gpt-image-1/1.5 accept it. The
            # profile gate prevents a model upgrade from turning every editor
            # call into an API error.
            from app.services.model_profiles import supports_input_fidelity

            if supports_input_fidelity(settings.IMAGE_MODEL):
                try:
                    response = self._client.images.edit(
                        model=settings.IMAGE_MODEL,
                        image=image_arg,
                        prompt=full_prompt,
                        n=1,
                        size=size,
                        input_fidelity=fidelity,
                    )
                except TypeError:
                    # Older SDK without input_fidelity — retry without it.
                    logger.warning("editor_input_fidelity_unsupported — retrying without param")
                    response = self._client.images.edit(
                        model=settings.IMAGE_MODEL,
                        image=image_arg,
                        prompt=full_prompt,
                        n=1,
                        size=size,
                    )
            else:
                response = self._client.images.edit(
                    model=settings.IMAGE_MODEL,
                    image=image_arg,
                    prompt=full_prompt,
                    n=1,
                    size=size,
                )
            return base64.b64decode(response.data[0].b64_json)
        except OpenAIError as exc:
            raise RuntimeError(f"gpt-image edit failed: {exc}") from exc
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass
            for p in tmp_paths:
                p.unlink(missing_ok=True)


class GrokImageEditor:
    """Grok Imagine editor backend (E2) — image-to-image edits via OpenRouter.

    Posts to the OpenRouter chat-completions endpoint with the
    x-ai/grok-imagine-image-quality model: source images travel as data-URI
    image_url parts, the edit instruction as the text part, and the edited
    image comes back as a base64 data URL. Same request/response shape as the
    existing OpenRouter Canon provider, but kept self-contained here so no
    shared Canon Studio provider files change.

    Note: the Grok edit API exposes no strength/fidelity control — strength is
    accepted for interface parity and recorded by the caller, but not sent.
    """

    provider_name = "grok"
    editor_version = "e2"

    _API_URL = "https://openrouter.ai/api/v1/chat/completions"
    _READ_TIMEOUT_S = 120  # image editing can be slow

    def __init__(self) -> None:
        if not settings.OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured — required for the grok editor."
            )
        self._api_key = settings.OPENROUTER_API_KEY
        self._model = settings.OPENROUTER_GROK_IMAGE_MODEL

    def edit(
        self,
        *,
        prompt: str,
        source_images: list[bytes],
        strength: float,
        size: str = "1024x1024",
    ) -> bytes:
        """Edit 1-3 source images per the prompt. Returns raw image bytes.

        Raises:
            ValueError: invalid inputs.
            RuntimeError: provider-side failure.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not source_images:
            raise ValueError("At least one source image is required.")
        if len(source_images) > MAX_SOURCE_IMAGES:
            raise ValueError(f"At most {MAX_SOURCE_IMAGES} source images are allowed.")

        payload = self._build_payload(prompt=prompt, source_images=source_images)
        body = self._post(payload)
        return _ensure_png(self._parse_image_bytes(body))

    def _build_payload(self, *, prompt: str, source_images: list[bytes]) -> dict:
        """Build the OpenRouter chat-completions payload for an edit request."""
        import base64

        content: list[dict] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/png;base64,"
                    + base64.b64encode(img).decode("ascii")
                },
            }
            for img in source_images
        ]
        content.append({"type": "text", "text": build_editor_prompt(prompt)})
        return {
            "model": self._model,
            "messages": [{"role": "user", "content": content}],
            # grok-imagine endpoints are image-output-only; requesting
            # ["image", "text"] returns 404 "No endpoints found".
            "modalities": ["image"],
        }

    def _post(self, payload: dict) -> dict:
        """POST the payload to OpenRouter; return the parsed JSON body."""
        import json
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            self._API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._READ_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode(errors="replace")[:300]
            except Exception:
                pass
            logger.warning(
                "grok_editor_api_error status=%s snippet=%r", exc.code, error_body[:150]
            )
            raise RuntimeError(
                f"grok edit failed (HTTP {exc.code}): {error_body[:200]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"grok edit request failed: {exc}") from exc

    @staticmethod
    def _parse_image_bytes(body: dict) -> bytes:
        """Extract image bytes from the OpenRouter response data URL."""
        import base64
        import json

        try:
            image_url: str = (
                body["choices"][0]["message"]["images"][0]["image_url"]["url"]
            )
        except (KeyError, IndexError, TypeError):
            snippet = json.dumps(body)[:300]
            raise RuntimeError(
                f"grok edit response missing expected image structure: {snippet}"
            )
        if not image_url.startswith("data:"):
            raise RuntimeError(
                f"grok edit returned an unexpected image URL format: {image_url[:80]}"
            )
        try:
            _, encoded = image_url.split(",", 1)
            return base64.b64decode(encoded)
        except Exception as exc:
            raise RuntimeError(f"Failed to decode grok edit data URL: {exc}") from exc


def _ensure_png(image_bytes: bytes) -> bytes:
    """Re-encode to PNG when the provider returns another format (grok → JPEG).

    The storage layer names files .png with a PNG content type, so editor
    backends must hand back real PNG bytes. Returns the input unchanged when
    it already is PNG or when Pillow cannot decode it.
    """
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return image_bytes
    try:
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.open(io.BytesIO(image_bytes)).convert("RGB").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.warning("editor_png_reencode_failed — storing original bytes")
        return image_bytes


def _self_hosted_editor():
    """Factory for the self_hosted backend (E4) — imported lazily so the
    RunPod/R2 supervisor module only loads when the provider is requested."""
    from app.services.editor_self_hosted import SelfHostedImageEditor

    return SelfHostedImageEditor()


SUPPORTED_EDITOR_PROVIDERS = ("gpt-image", "grok", "self_hosted")

_EDITOR_CLASSES = {
    "gpt-image": GptImageEditor,
    "grok": GrokImageEditor,
    "self_hosted": _self_hosted_editor,
}


def get_editor(provider: str):
    """Return the editor backend for a provider name.

    Raises:
        ValueError: unsupported provider name.
        RuntimeError: missing credentials.
    """
    editor_cls = _EDITOR_CLASSES.get(provider)
    if editor_cls is None:
        raise ValueError(
            f"Unsupported editor provider: {provider!r}. "
            f"Supported: {', '.join(SUPPORTED_EDITOR_PROVIDERS)}."
        )
    return editor_cls()

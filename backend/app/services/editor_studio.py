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

EDITOR_VERSION = "e1"

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


SUPPORTED_EDITOR_PROVIDERS = ("gpt-image",)


def get_editor(provider: str) -> GptImageEditor:
    """Return the editor backend for a provider name.

    Raises:
        ValueError: unsupported provider name.
        RuntimeError: missing credentials.
    """
    if provider not in SUPPORTED_EDITOR_PROVIDERS:
        raise ValueError(
            f"Unsupported editor provider: {provider!r}. "
            f"Supported: {', '.join(SUPPORTED_EDITOR_PROVIDERS)}."
        )
    return GptImageEditor()

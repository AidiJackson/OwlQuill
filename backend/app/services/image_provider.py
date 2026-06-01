"""Image generation provider abstraction.

Provides a pluggable interface for image generation backends.
Currently supports OpenAI Images API (gpt-image-1.5).
"""
from __future__ import annotations

import base64
import tempfile
import urllib.request
from pathlib import Path

from openai import OpenAI, OpenAIError

from app.core.config import settings

_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_DOWNLOAD_TIMEOUT_S = 10


class ImageProvider:
    """Base image provider with prompt validation and delegation."""

    # Subclasses that support seed-image grounding set this to True.
    supports_image_guidance: bool = False

    # B19: subclasses that accept multiple reference images set this to True.
    supports_multi_image_input: bool = False

    def generate_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        reference_image_url: str | None = None,
    ) -> bytes:
        """Validate inputs and delegate to provider-specific implementation.

        Returns raw PNG bytes.

        Raises:
            ValueError: If prompt is empty or exceeds 250 characters.
        """
        if not prompt or len(prompt.strip()) == 0:
            raise ValueError("Prompt must not be empty.")
        return self._generate(prompt=prompt, size=size, reference_image_url=reference_image_url)

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        raise NotImplementedError

    def generate_grounded_image(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str = "1024x1024",
    ) -> bytes:
        """Generate an image grounded by a seed image supplied as raw bytes.

        Used for identity pack angle shots after the seed (front) image is
        generated.  The seed bytes are passed directly so we avoid an extra
        HTTP round-trip through our own static server.

        Raises:
            NotImplementedError: If the provider does not support image guidance.
            ValueError: On invalid inputs.
            RuntimeError: On provider-side failure.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not reference_image_bytes:
            raise ValueError("reference_image_bytes must not be empty.")
        return self._generate_grounded(
            prompt=prompt,
            reference_image_bytes=reference_image_bytes,
            size=size,
        )

    def _generate_grounded(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str,
    ) -> bytes:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support image guidance."
        )

    def generate_with_anchors(
        self,
        *,
        prompt: str,
        anchor_images: list[bytes],
        size: str = "1024x1024",
    ) -> bytes:
        """Generate conditioned on multiple identity anchor images (B19).

        Raises:
            NotImplementedError: If the provider does not support multi-image input.
            ValueError: On invalid inputs.
            RuntimeError: On provider-side failure.
        """
        if not prompt or not prompt.strip():
            raise ValueError("Prompt must not be empty.")
        if not anchor_images:
            raise ValueError("anchor_images must not be empty.")
        return self._generate_with_anchors(
            prompt=prompt, anchor_images=anchor_images, size=size
        )

    def _generate_with_anchors(
        self,
        *,
        prompt: str,
        anchor_images: list[bytes],
        size: str,
    ) -> bytes:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support multi-image anchor conditioning."
        )


def _download_image(url: str) -> Path:
    """Download an image URL to a temporary file.

    Enforces https/http, max size, and timeout.
    Returns the Path to the temp file (caller must clean up).
    """
    if not url.startswith(("http://", "https://")):
        raise ValueError("reference_image_url must be an http or https URL.")

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_S) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Reference image too large ({int(content_length)} bytes, "
                f"max {_MAX_DOWNLOAD_BYTES})."
            )
        data = resp.read(_MAX_DOWNLOAD_BYTES + 1)
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"Reference image exceeds {_MAX_DOWNLOAD_BYTES} byte limit."
            )

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        tmp.write(data)
        tmp.flush()
    finally:
        tmp.close()
    return Path(tmp.name)


class _OpenAIImageProvider(ImageProvider):
    """OpenAI Images API provider."""

    supports_image_guidance = True
    supports_multi_image_input = True

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. "
                "Set it in your environment or .env file to use the OpenAI image provider."
            )
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        try:
            if reference_image_url:
                return self._edit(prompt=prompt, size=size, url=reference_image_url)
            return self._text_to_image(prompt=prompt, size=size)
        except OpenAIError as exc:
            raise RuntimeError(f"OpenAI image generation failed: {exc}") from exc

    def _generate_grounded(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str,
    ) -> bytes:
        """Edit using seed bytes directly — no URL round-trip required."""
        try:
            return self._edit_from_bytes(
                prompt=prompt, size=size, image_bytes=reference_image_bytes
            )
        except OpenAIError as exc:
            raise RuntimeError(f"OpenAI grounded image generation failed: {exc}") from exc

    def _text_to_image(self, *, prompt: str, size: str) -> bytes:
        response = self._client.images.generate(
            model=settings.IMAGE_MODEL,
            prompt=prompt,
            n=1,
            size=size,
        )
        return base64.b64decode(response.data[0].b64_json)

    def _edit(self, *, prompt: str, size: str, url: str) -> bytes:
        tmp_path = _download_image(url)
        try:
            with open(tmp_path, "rb") as fh:
                response = self._client.images.edit(
                    model=settings.IMAGE_MODEL,
                    image=fh,
                    prompt=prompt,
                    n=1,
                    size=size,
                )
            return base64.b64decode(response.data[0].b64_json)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _edit_from_bytes(self, *, prompt: str, size: str, image_bytes: bytes) -> bytes:
        """Run images.edit with seed bytes written to a temp file."""
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = Path(tmp.name)
        try:
            tmp.write(image_bytes)
            tmp.flush()
            tmp.close()
            with open(tmp_path, "rb") as fh:
                response = self._client.images.edit(
                    model=settings.IMAGE_MODEL,
                    image=fh,
                    prompt=prompt,
                    n=1,
                    size=size,
                )
            return base64.b64decode(response.data[0].b64_json)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _generate_with_anchors(
        self,
        *,
        prompt: str,
        anchor_images: list[bytes],
        size: str,
    ) -> bytes:
        """Call images.edit with multiple anchor images as reference inputs (B19)."""
        tmp_paths: list[Path] = []
        file_handles: list = []
        try:
            for img_bytes in anchor_images:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp_path = Path(tmp.name)
                tmp.write(img_bytes)
                tmp.flush()
                tmp.close()
                tmp_paths.append(tmp_path)
                file_handles.append(open(tmp_path, "rb"))  # noqa: WPS515

            image_arg = file_handles if len(file_handles) > 1 else file_handles[0]
            try:
                response = self._client.images.edit(
                    model=settings.IMAGE_MODEL,
                    image=image_arg,
                    prompt=prompt,
                    n=1,
                    size=size,
                )
                return base64.b64decode(response.data[0].b64_json)
            except OpenAIError as exc:
                raise RuntimeError(
                    f"OpenAI multi-anchor image generation failed: {exc}"
                ) from exc
        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass
            for p in tmp_paths:
                p.unlink(missing_ok=True)


class _GoogleImageProviderAdapter(ImageProvider):
    """Adapt GoogleImageProvider to the legacy ImageProvider interface."""

    supports_image_guidance = True
    supports_multi_image_input = True

    def __init__(self) -> None:
        from app.services.image_providers.google_provider import GoogleImageProvider
        self._google = GoogleImageProvider()

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        # Text-to-image only for scene/fallback calls; reference_image_url ignored
        return self._google.generate_text_to_image(prompt=prompt, size=size)

    def _generate_grounded(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str,
    ) -> bytes:
        return self._google.generate_with_reference(
            prompt=prompt,
            reference_image_bytes=reference_image_bytes,
            size=size,
        )

    def _generate_with_anchors(
        self,
        *,
        prompt: str,
        anchor_images: list[bytes],
        size: str,
    ) -> bytes:
        """Delegate to Google multi-reference generation (B19)."""
        return self._google.generate_with_multi_reference(
            prompt=prompt,
            reference_images=anchor_images,
            size=size,
        )


def get_image_provider() -> ImageProvider:
    """Factory: return the configured image provider instance.

    Raises:
        ValueError: If IMAGE_PROVIDER names an unsupported backend.
    """
    provider = settings.IMAGE_PROVIDER.lower()
    if provider == "openai":
        return _OpenAIImageProvider()
    if provider == "google":
        return _GoogleImageProviderAdapter()
    if provider == "openrouter":
        return _OpenRouterImageProviderAdapter()
    raise ValueError(
        f"Unsupported IMAGE_PROVIDER: {settings.IMAGE_PROVIDER!r}. "
        f"Supported providers: 'openai', 'google', 'openrouter'."
    )


def get_identity_image_provider() -> ImageProvider:
    """Return the image provider for Identity Pack generation.

    Respects IDENTITY_IMAGE_PROVIDER override; falls back to IMAGE_PROVIDER.
    Only affects identity pack generation — scene generation uses get_image_provider().

    Raises:
        RuntimeError: If the configured provider is missing required credentials.
        ValueError: If the provider name is unsupported, or if the provider
            does not support image guidance (required for identity consistency).
    """
    effective = (settings.IDENTITY_IMAGE_PROVIDER or settings.IMAGE_PROVIDER).lower()
    if effective == "openai":
        provider: ImageProvider = _OpenAIImageProvider()
    elif effective == "google":
        provider = _GoogleImageProviderAdapter()
    elif effective == "openrouter":
        provider = _OpenRouterImageProviderAdapter()
    else:
        raise ValueError(
            f"Unsupported provider: {effective!r}. "
            f"Supported: 'openai', 'google', 'openrouter'."
        )
    if not provider.supports_image_guidance:
        raise ValueError(
            f"Provider '{effective}' does not support image guidance, which is required "
            f"for identity pack generation. Use 'openai' or 'google'."
        )
    return provider


def get_identity_provider_by_name(name: str) -> ImageProvider:
    """Instantiate an identity-compatible image provider by explicit name.

    Unlike get_identity_image_provider(), accepts a provider name directly
    rather than reading from settings.  Used by the B7 split-provider path
    to independently instantiate the seed (front) and angles providers.

    Raises:
        RuntimeError: If the provider's required credentials are missing.
        ValueError: If the name is unsupported or the provider lacks image-guidance support.
    """
    n = name.lower()
    if n == "openai":
        provider: ImageProvider = _OpenAIImageProvider()
    elif n == "google":
        provider = _GoogleImageProviderAdapter()
    elif n == "openrouter":
        provider = _OpenRouterImageProviderAdapter()
    else:
        raise ValueError(
            f"Unsupported provider: {n!r}. Supported: 'openai', 'google', 'openrouter'."
        )
    if not provider.supports_image_guidance:
        raise ValueError(
            f"Provider '{n}' does not support image guidance, which is required "
            f"for identity pack generation. Use 'openai' or 'google'."
        )
    return provider


def get_provider_for_option(option: str) -> ImageProvider:
    """Return the image provider mapped to a B17 provider option key.

    Mapping (internal, not exposed to end users):
      option1 -> openai
      option2 -> google

    When IMAGE_GENERATOR_PROVIDER_TOGGLE is False, always returns the openai
    provider regardless of the option value (easy rollback path).

    Raises:
        RuntimeError: If the resolved provider is missing required credentials.
        ValueError: If the option key is unrecognised.
    """
    _OPTION_MAP = {
        "option1": "openai",
        "option2": "google",
    }
    effective = option.lower() if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    provider_name = _OPTION_MAP.get(effective)
    if provider_name is None:
        raise ValueError(f"Unknown provider option: {option!r}. Expected 'option1' or 'option2'.")
    if provider_name == "openai":
        return _OpenAIImageProvider()
    if provider_name == "google":
        return _GoogleImageProviderAdapter()
    raise ValueError(f"No provider implementation for resolved name: {provider_name!r}")


# ── Beta provider gating ──────────────────────────────────────────────
# Closed beta: Google (option2) is the primary Canon image provider for ALL
# users. OpenAI (option1) is gated to admin/internal testing — it is currently
# less stable around reference order, tattoo detail, and images.edit weighting
# for the visual-card routed identity flow. A non-admin OpenAI request safely
# falls back to Google with audit metadata rather than being hard-rejected.

_ADMIN_ONLY_PROVIDER_OPTIONS = frozenset({"option1"})  # option1 == openai
CANON_DEFAULT_PROVIDER_OPTION = "option2"              # option2 == google
_PROVIDER_OPTION_NAMES = {"option1": "openai", "option2": "google"}


def resolve_canon_provider_option(
    requested_option: str,
    *,
    is_admin: bool,
) -> tuple[str, dict]:
    """Apply beta provider gating to a requested provider option.

    Google (option2) is allowed for everyone. OpenAI (option1) is admin-only;
    a non-admin OpenAI request falls back to Google instead of failing.

    Returns ``(effective_option, fallback_metadata)``. ``fallback_metadata`` is
    ``{}`` when the requested option is allowed; on fallback it records::

        original_requested_provider = "openai"
        provider_fallback_reason    = "openai_admin_only_beta"
    """
    opt = (requested_option or CANON_DEFAULT_PROVIDER_OPTION).lower()
    if opt in _ADMIN_ONLY_PROVIDER_OPTIONS and not is_admin:
        return CANON_DEFAULT_PROVIDER_OPTION, {
            "original_requested_provider": _PROVIDER_OPTION_NAMES.get(opt, opt),
            "provider_fallback_reason": "openai_admin_only_beta",
        }
    # Unknown option keys collapse to the safe default (defensive).
    if opt not in _PROVIDER_OPTION_NAMES:
        return CANON_DEFAULT_PROVIDER_OPTION, {}
    return opt, {}


def get_fallback_provider() -> ImageProvider | None:
    """Factory: return a fallback provider for tier-C generation.

    Returns None if no fallback is configured (missing FAL_KEY, etc.).
    Never raises — callers should treat None as "no fallback available".
    """
    fallback = settings.IMAGE_PROVIDER_FALLBACK.lower()
    if fallback == "fal" and settings.FAL_KEY:
        try:
            from app.services.image_providers.fal_provider import FalImageProvider

            # Wrap FalImageProvider in an ImageProvider adapter so the
            # route can call .generate_image() uniformly.
            return _FalProviderAdapter()
        except Exception:
            return None
    return None


class _OpenRouterImageProviderAdapter(ImageProvider):
    """Adapt OpenRouterImageProvider to the ImageProvider interface."""

    supports_image_guidance = True

    def __init__(self) -> None:
        from app.services.image_providers.openrouter_provider import (
            OpenRouterImageProvider,
        )
        self._openrouter = OpenRouterImageProvider()

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        # Text-to-image only for generic calls; reference_image_url ignored
        return self._openrouter.generate_text_to_image(prompt=prompt, size=size)

    def _generate_grounded(
        self,
        *,
        prompt: str,
        reference_image_bytes: bytes,
        size: str,
    ) -> bytes:
        return self._openrouter.generate_with_reference(
            prompt=prompt,
            reference_image_bytes=reference_image_bytes,
            size=size,
        )


class _FalProviderAdapter(ImageProvider):
    """Adapt the new FalImageProvider to the legacy ImageProvider interface."""

    def __init__(self) -> None:
        from app.services.image_providers.fal_provider import FalImageProvider

        self._fal = FalImageProvider()

    def _generate(
        self,
        *,
        prompt: str,
        size: str,
        reference_image_url: str | None,
    ) -> bytes:
        # Fal only supports text-to-image; ignore reference_image_url
        return self._fal.generate_text_to_image(prompt=prompt, size=size)


def test_image_generation() -> bytes:
    """Quick smoke-test helper (not wired to any route).

    Returns raw PNG bytes of a generated test image.
    """
    provider = get_image_provider()
    return provider.generate_image(
        prompt="A cinematic portrait of a fictional character, dramatic lighting",
    )

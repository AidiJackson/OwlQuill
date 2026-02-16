"""Base interface for pluggable image generation providers.

Every provider MUST implement ``generate_text_to_image``.
``generate_edit`` is optional — providers that do not support
reference-image edits should leave the default (raises).
"""
from __future__ import annotations


class ImageProviderBase:
    """Abstract base for image generation backends."""

    name: str = "base"

    def generate_text_to_image(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        style: str = "realistic",
    ) -> bytes:
        """Generate an image from a text prompt.

        Returns raw image bytes (PNG or JPEG).

        Raises:
            NotImplementedError: If the provider does not implement this.
            ValueError: On invalid input.
            RuntimeError: On provider-side failure (network, moderation, etc.).
        """
        raise NotImplementedError

    def generate_edit(
        self,
        *,
        prompt: str,
        reference_image_url: str,
        size: str = "1024x1024",
    ) -> bytes:
        """Generate an edited image using a reference image (optional).

        Not all providers support this — the default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.name} provider does not support reference-image edits."
        )

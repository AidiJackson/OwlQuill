"""Provider capability model (Sprint 36).

The platform asks "which capability do I need?" instead of "which provider am
I using?". Each provider declares a ``capabilities: frozenset[Capability]``
class attribute; business logic queries it through :func:`provider_supports`
rather than probing provider names, ``hasattr`` or per-feature boolean flags.

Design constraints (deliberate):
  * No plugin framework, no runtime discovery — providers are registered in an
    explicit table in ``image_provider.py``.
  * Backwards tolerant — test doubles and legacy objects that only carry the
    old boolean flags (``supports_image_guidance`` /
    ``supports_multi_image_input``) or the legacy ``generate_with_anchor_urls``
    method are answered via those, so behaviour is unchanged for any object
    that has not adopted the capability declaration yet.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Capability(str, Enum):
    """Platform capability vocabulary.

    The first four are consumed by the image pipeline today. The remainder
    are reserved vocabulary for the text/vision pipeline (StoryLab selects its
    text provider by configuration value, not by provider object) so future
    providers declare against a single shared enum.
    """

    # Image pipeline — consumed now.
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_GUIDANCE = "image_guidance"          # grounded generation from one reference (bytes)
    MULTI_IMAGE_ANCHORS = "multi_image_anchors"  # multi-reference conditioning (bytes)
    URL_ANCHORS = "url_anchors"                # multi-reference via public HTTPS URLs only

    # Reserved vocabulary — no object-based consumer yet.
    TEXT_GENERATION = "text_generation"
    STRUCTURED_JSON = "structured_json"
    VISION = "vision"
    STREAMING = "streaming"
    LORA_TRAINING = "lora_training"


# Legacy probes, used when an object predates capability declarations. Kept
# EXACTLY equivalent to the checks each call site performed before Sprint 36.
_LEGACY_FLAG_FOR: dict[Capability, str] = {
    Capability.IMAGE_GUIDANCE: "supports_image_guidance",
    Capability.MULTI_IMAGE_ANCHORS: "supports_multi_image_input",
}


def provider_supports(provider: object, cap: Capability) -> bool:
    """True when ``provider`` supports ``cap``.

    Prefers a declared ``capabilities`` set; otherwise falls back to the
    legacy per-feature probe for that capability. ``None`` never supports
    anything, so call sites may pass an unresolved provider directly.
    """
    if provider is None:
        return False
    caps = getattr(provider, "capabilities", None)
    if isinstance(caps, (set, frozenset)):
        return cap in caps
    if cap is Capability.URL_ANCHORS:
        return callable(getattr(provider, "generate_with_anchor_urls", None))
    flag = _LEGACY_FLAG_FOR.get(cap)
    if flag is not None:
        return bool(getattr(provider, flag, False))
    return False


def ref_support_level(provider: object) -> Optional[str]:
    """Reference-image support level for admin metadata.

    Returns ``"bytes"`` (references accepted as raw bytes), ``"url_required"``
    (public HTTPS URLs only), ``"none"`` (references never forwarded), or
    ``None`` when the object declares nothing. String values and their
    consumers in image_generator metadata are unchanged from pre-Sprint 36.
    """
    explicit = getattr(provider, "refs_support_level", None)
    if isinstance(explicit, str):
        return explicit
    caps = getattr(provider, "capabilities", None)
    if not isinstance(caps, (set, frozenset)):
        return None
    if Capability.IMAGE_GUIDANCE in caps or Capability.MULTI_IMAGE_ANCHORS in caps:
        return "bytes"
    if Capability.URL_ANCHORS in caps:
        return "url_required"
    return "none"

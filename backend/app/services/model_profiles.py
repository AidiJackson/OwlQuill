"""Per-model capability profiles (PROVIDER MODERNISATION sprint).

The Capability enum (provider_capabilities.py) answers "what can this
PROVIDER object do" — text-to-image, byte anchors, URL anchors. Some
behaviour differs per MODEL within one provider, and those differences are
what silently break assumptions on a model upgrade. This registry records
exactly the model-level facts Ficshon consumes — nothing speculative:

  * ``supports_input_fidelity`` — OpenAI images.edit accepted an
    ``input_fidelity`` parameter up to gpt-image-1.5; gpt-image-2 REJECTS it
    (every input is processed at high fidelity automatically, per the official
    image-generation guide). The editor's strength control consults this
    instead of assuming the parameter exists.
  * ``max_reference_images`` — the provider-documented HARD limit on input
    images per request (OpenAI images.edit: 16). ``None`` = no documented
    limit (Google generateContent). This is an API fact, distinct from the
    app's own routing budget (scene_router.MAX_PROVIDER_REFS = 6), which
    stays the operative cap and must never exceed the hard limit.

Matching is by (provider, longest model-id prefix) so versioned ids like
"gpt-image-2-2026-04-21" resolve without new entries. Unknown models get a
conservative default profile — never an exception: an unrecognised model must
degrade to safe behaviour, not break generation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    """Model-level facts Ficshon's pipeline actually consumes."""
    supports_input_fidelity: bool = False
    max_reference_images: int | None = None


# (provider, model-id prefix) → profile. Longest prefix wins.
_PROFILES: dict[tuple[str, str], ModelProfile] = {
    # OpenAI Images API — images.edit hard limit is 16 input images.
    ("openai", "gpt-image-1"):   ModelProfile(supports_input_fidelity=True,  max_reference_images=16),
    ("openai", "gpt-image-1.5"): ModelProfile(supports_input_fidelity=True,  max_reference_images=16),
    ("openai", "gpt-image-2"):   ModelProfile(supports_input_fidelity=False, max_reference_images=16),
    # Google generateContent — no documented per-request reference cap; the
    # app budget (MAX_PROVIDER_REFS) is the operative limit.
    ("google", "gemini-3.1-flash-image"):      ModelProfile(),
    ("google", "gemini-3.1-flash-lite-image"): ModelProfile(),
    ("google", "gemini-3-pro-image"):          ModelProfile(),
}

# Conservative default for unknown models: no optional parameters assumed
# supported, no documented reference limit assumed.
_DEFAULT = ModelProfile()


def model_profile(provider: str, model: str) -> ModelProfile:
    """Resolve the profile for a provider/model pair.

    Longest matching prefix for the provider wins; unknown models return the
    conservative default (assume optional parameters are unsupported).
    """
    p = (provider or "").lower()
    m = model or ""
    best: tuple[int, ModelProfile] | None = None
    for (prov, prefix), profile in _PROFILES.items():
        if prov == p and m.startswith(prefix):
            if best is None or len(prefix) > best[0]:
                best = (len(prefix), profile)
    return best[1] if best else _DEFAULT


def supports_input_fidelity(model: str) -> bool:
    """True when OpenAI's images.edit accepts input_fidelity for this model."""
    return model_profile("openai", model).supports_input_fidelity

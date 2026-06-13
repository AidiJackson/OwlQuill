"""Adult Studio provider implementations (Phase 3+).

Real provider implementations live here, behind the protocols/feature gates defined in
``app.services.adult_identity_provider``. Nothing in this package is imported or
constructed unless the corresponding feature flags are explicitly enabled — see
``app.services.adult_identity_provider.get_training_provider``.
"""

# ── Adult Studio generation provider registry ──────────────────────────────────
#
# Slug → human label for the providers Adult Studio can route a generation through.
# This is a lightweight, descriptive registry (no construction here) so the admin UI
# and diagnostics can enumerate available providers. ``replicate_nsfw`` (Sprint E9) is
# an EXPERIMENTAL, additive fourth provider — it does NOT replace the others.
ADULT_STUDIO_PROVIDERS: dict[str, str] = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "grok": "Grok",
    "replicate_nsfw": "Replicate (Experimental Adult)",
}

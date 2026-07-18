"""Sprint 36 — provider capability abstraction.

Focused tests only: capability declarations, tolerant dispatch (including the
legacy-flag fallback that keeps pre-Sprint-36 test doubles working), derived
legacy attributes, and the explicit provider registry.
"""
import pytest

from app.services.provider_capabilities import (
    Capability,
    provider_supports,
    ref_support_level,
)
from app.services.image_provider import (
    ImageProvider,
    _CONFIGURABLE_PROVIDERS,
    _FluxOpenRouterAdapter,
    _GoogleImageProviderAdapter,
    _OpenAIImageProvider,
    _OpenRouterImageProviderAdapter,
    _PROVIDER_FACTORIES,
    _PROVIDER_OPTION_NAMES,
    _TogetherFluxAdapter,
    _require_capability,
    create_provider,
)


# ── Declarations ───────────────────────────────────────────────────────


class TestCapabilityDeclarations:
    """Each provider class declares the capabilities it actually implements."""

    def test_openai(self):
        assert _OpenAIImageProvider.capabilities == frozenset({
            Capability.TEXT_TO_IMAGE,
            Capability.IMAGE_GUIDANCE,
            Capability.MULTI_IMAGE_ANCHORS,
        })

    def test_google(self):
        assert _GoogleImageProviderAdapter.capabilities == frozenset({
            Capability.TEXT_TO_IMAGE,
            Capability.IMAGE_GUIDANCE,
            Capability.MULTI_IMAGE_ANCHORS,
        })

    def test_openrouter(self):
        assert _OpenRouterImageProviderAdapter.capabilities == frozenset({
            Capability.TEXT_TO_IMAGE,
            Capability.IMAGE_GUIDANCE,
        })

    def test_flux_is_text_to_image_only(self):
        assert _FluxOpenRouterAdapter.capabilities == frozenset({
            Capability.TEXT_TO_IMAGE,
        })

    def test_together_declares_url_anchors_not_bytes(self):
        caps = _TogetherFluxAdapter.capabilities
        assert Capability.URL_ANCHORS in caps
        assert Capability.MULTI_IMAGE_ANCHORS not in caps
        assert Capability.IMAGE_GUIDANCE not in caps


# ── Derived legacy attributes (behaviour-preservation contract) ────────


class _NoInit(ImageProvider):
    """Capability-only subclass, no provider construction."""


class _GuidedOnly(_NoInit):
    capabilities = frozenset({Capability.TEXT_TO_IMAGE, Capability.IMAGE_GUIDANCE})


class _UrlOnly(_NoInit):
    capabilities = frozenset({Capability.TEXT_TO_IMAGE, Capability.URL_ANCHORS})


class _TextOnly(_NoInit):
    capabilities = frozenset({Capability.TEXT_TO_IMAGE})


class TestDerivedLegacyFlags:
    def test_supports_image_guidance_derives(self):
        assert _GuidedOnly().supports_image_guidance is True
        assert _TextOnly().supports_image_guidance is False

    def test_supports_multi_image_input_derives(self):
        assert _GuidedOnly().supports_multi_image_input is False
        p = _NoInit()
        p.capabilities = frozenset({Capability.MULTI_IMAGE_ANCHORS})
        assert p.supports_multi_image_input is True

    def test_refs_support_level_derives_exact_legacy_strings(self):
        assert _GuidedOnly().refs_support_level == "bytes"
        assert _UrlOnly().refs_support_level == "url_required"
        assert _TextOnly().refs_support_level == "none"


# ── Tolerant dispatch ──────────────────────────────────────────────────


class TestProviderSupports:
    def test_declared_capabilities_win(self):
        assert provider_supports(_GuidedOnly(), Capability.IMAGE_GUIDANCE)
        assert not provider_supports(_GuidedOnly(), Capability.MULTI_IMAGE_ANCHORS)

    def test_none_supports_nothing(self):
        for cap in Capability:
            assert provider_supports(None, cap) is False

    def test_legacy_boolean_flag_fallback(self):
        class Legacy:
            supports_image_guidance = True
            supports_multi_image_input = False

        assert provider_supports(Legacy(), Capability.IMAGE_GUIDANCE) is True
        assert provider_supports(Legacy(), Capability.MULTI_IMAGE_ANCHORS) is False

    def test_legacy_url_anchor_method_fallback(self):
        class LegacyTogether:
            def generate_with_anchor_urls(self, **kw):
                return b""

        assert provider_supports(LegacyTogether(), Capability.URL_ANCHORS) is True
        assert provider_supports(object(), Capability.URL_ANCHORS) is False

    def test_undeclared_object_supports_nothing_else(self):
        assert provider_supports(object(), Capability.TEXT_TO_IMAGE) is False


class TestRefSupportLevel:
    def test_explicit_string_attribute_wins(self):
        class LegacyFlux:
            refs_support_level = "none"

        assert ref_support_level(LegacyFlux()) == "none"

    def test_derived_from_capabilities(self):
        assert ref_support_level(_GuidedOnly()) == "bytes"
        assert ref_support_level(_UrlOnly()) == "url_required"

    def test_undeclared_returns_none(self):
        assert ref_support_level(object()) is None


# ── Registry ───────────────────────────────────────────────────────────


class TestRegistry:
    def test_unknown_name_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            create_provider("does-not-exist")

    def test_every_option_maps_to_a_registered_factory(self):
        assert set(_PROVIDER_OPTION_NAMES) == {
            "option1", "option2", "option3", "option4", "option5", "option6",
        }
        for name in _PROVIDER_OPTION_NAMES.values():
            assert name in _PROVIDER_FACTORIES, name

    def test_configurable_names_are_registered(self):
        assert _CONFIGURABLE_PROVIDERS <= set(_PROVIDER_FACTORIES)

    def test_require_capability_rejects_missing_capability(self):
        with pytest.raises(ValueError, match="image guidance"):
            _require_capability(_TextOnly(), "textonly", Capability.IMAGE_GUIDANCE)

    def test_require_capability_passes_through(self):
        p = _GuidedOnly()
        assert _require_capability(p, "guided", Capability.IMAGE_GUIDANCE) is p

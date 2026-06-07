"""Deterministic permanent-mark routing for Adult Studio (Phase 1, Sprint 2).

Given a canon permanent body mark, decide HOW it should be rendered by the
LoRA-identity + regional-inpaint pipeline (docs/ADULT_STUDIO_PHASE1_DESIGN.md §6):

  texture / sleeve / floral / butterfly / pattern  → ip_adapter
  figural / ballerina / person / portrait / symbol → controlnet_canny
  scar / birthmark / mole (skin marks)             → inpaint_direct
  unknown / no keyword match                        → ip_adapter (fallback)

Pure, deterministic, no DB writes, no canon writes. Operates only on the mark's own
canon fields (type, label, description, body_region, side, reference URLs).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.services.adult_identity_fingerprint import _as_dict, mark_fingerprint

# Skin-blemish mark types → plain masked inpaint (no design reference to transfer).
_SKIN_MARK_TYPES = frozenset({"scar", "birthmark", "mole", "burn"})

# Coverage indicator: a sleeve is a region-filling texture → IP-Adapter.
_SLEEVE_KEYWORDS = ("full sleeve", "full_sleeve", "sleeve")

# Figural / specific-shape designs → need structure → ControlNet-Canny.
_FIGURAL_KEYWORDS = (
    "ballerina", "dancer", "person", "portrait", "figure", "face", "skull", "lady",
    "woman", "man", "child", "angel", "saint", "deity", "animal", "bird", "eagle",
    "dragon", "snake", "tiger", "lion", "wolf", "horse", "koi", "fish",
    "lettering", "script", "calligraphy", "text", "word", "name", "quote", "number",
    "symbol", "logo", "crest", "emblem", "anchor", "cross", "star", "heart", "skeleton",
)

# Texture / pattern / ornamental designs → IP-Adapter.
_TEXTURE_KEYWORDS = (
    "floral", "flower", "butterfly", "rose", "vine", "leaves", "leaf", "pattern",
    "mandala", "tribal", "ornamental", "lace", "geometric", "abstract", "watercolour",
    "watercolor", "swirl", "paisley", "dots", "filigree", "henna", "damask",
)


@dataclass(frozen=True)
class MarkRoutePlan:
    """How a single permanent mark should be rendered."""
    canon_mark_id: Optional[str]
    region: Optional[str]
    side: Optional[str]
    route: str
    reason: str
    reference_url: Optional[str]
    mark_fingerprint: Optional[str] = None


def _first_keyword(text: str, keywords) -> Optional[str]:
    for kw in keywords:
        if kw in text:
            return kw
    return None


def _reference_url(d: dict) -> Optional[str]:
    """Prefer the tight detail crop, fall back to the general reference image."""
    return d.get("detail_crop_url") or d.get("reference_image_url")


def resolve_mark_route(mark: Any) -> MarkRoutePlan:
    """Resolve a single mark to a render route + reason. Deterministic."""
    d = _as_dict(mark)
    mark_id = d.get("id")
    region = d.get("body_region")
    side = d.get("side")
    mtype = (d.get("type") or "").lower().strip()
    ref = _reference_url(d)
    haystack = f"{d.get('label') or ''} {d.get('description') or ''}".lower()

    def plan(route: str, reason: str) -> MarkRoutePlan:
        return MarkRoutePlan(
            canon_mark_id=mark_id, region=region, side=side, route=route,
            reason=reason, reference_url=ref, mark_fingerprint=mark_fingerprint(mark),
        )

    # 1. Skin-blemish types have no transferable design → plain masked inpaint.
    if mtype in _SKIN_MARK_TYPES:
        return plan("inpaint_direct", f"type={mtype} → inpaint_direct")

    # 2. Sleeves are region-filling texture coverage → IP-Adapter (precedes figural,
    #    so "butterfly and floral sleeve" routes by texture, not by any figural token).
    sleeve_kw = _first_keyword(haystack, _SLEEVE_KEYWORDS)
    if sleeve_kw:
        return plan("ip_adapter", f"matched sleeve/coverage keyword '{sleeve_kw}' → ip_adapter")

    # 3. Specific figural designs need structure → ControlNet-Canny.
    fig_kw = _first_keyword(haystack, _FIGURAL_KEYWORDS)
    if fig_kw:
        return plan("controlnet_canny", f"matched figural keyword '{fig_kw}' → controlnet_canny")

    # 4. Texture/pattern designs → IP-Adapter.
    tex_kw = _first_keyword(haystack, _TEXTURE_KEYWORDS)
    if tex_kw:
        return plan("ip_adapter", f"matched texture keyword '{tex_kw}' → ip_adapter")

    # 5. Unknown design → IP-Adapter fallback.
    return plan("ip_adapter", "no keyword match → ip_adapter (fallback)")


def resolve_marks(marks) -> list[MarkRoutePlan]:
    """Resolve a list of marks; order-stable (input order preserved)."""
    return [resolve_mark_route(m) for m in (marks or [])]

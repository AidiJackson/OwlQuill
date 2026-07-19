"""V2 canon card generator (S24AL).

The missing piece between "v2 canon storage" (S24AK) and "founder rebuild": a
provider-driven generator that produces ONE canon card image and returns it for
the harness to assign into a v2 slot. It reuses the existing provider stack and
consistency gate — it adds NO provider internals and writes NO DB rows itself
(the harness owns DB writes), so it composes with the dry-run flow cleanly.

Key properties:
  * dry_run (default): compiles the prompt, resolves the provider, computes the
    grounding plan and estimated cost — and returns WITHOUT calling any provider
    or touching storage. Zero side effects, zero spend.
  * commit: generates via the same 3-tier chain the canon scene route uses
    (multi-anchor → grounded → text-only → Fal fallback), runs the face
    consistency gate against the approved face_front, and saves the PNG.
  * SpendTracker enforces a hard $ ceiling BEFORE every paid call.

Provider policy (S24AL §2) is delegated to resolve_canon_provider_option:
  option2 → Google/Gemini (default, all users)
  option1 → OpenAI (admin-only; non-admins auto-downgraded). No Grok.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from app.core.config import settings
from app.core.storage import load_image_bytes, save_image
from app.schemas.canon import SLOT_FIELD_MAP
from app.services.canon_card_prompts import (
    CARD_BY_SLOT,
    FounderIdentity,
    build_card_prompt,
)
from app.services.canon_service import load_body_canon, load_face_canon
from app.services.face_verifier import passes as face_passes
from app.services.face_verifier import verify_face_match
from app.services.image_provider import (
    get_fallback_provider,
    get_provider_for_option,
    resolve_canon_provider_option,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon

logger = logging.getLogger(__name__)


# ── Cost model (S24AL §8) ─────────────────────────────────────────────
# Approximate $/image. Verify against current provider pricing before a real
# run; these are intentionally conservative so the cap trips early rather than
# late. Unknown providers fall back to the highest known rate.
_COST_PER_IMAGE: dict[str, float] = {
    "google": 0.04,
    "openai": 0.08,
    "fal": 0.02,
}
_DEFAULT_COST = 0.08


class SpendCapExceeded(RuntimeError):
    """Raised when a generation would push estimated spend past the hard cap."""


@dataclass
class SpendTracker:
    """Accumulates estimated image-generation spend against a hard ceiling."""
    cap_usd: float
    spent_usd: float = 0.0
    image_count: int = 0

    @staticmethod
    def cost_for(provider_name: str) -> float:
        return _COST_PER_IMAGE.get((provider_name or "").lower(), _DEFAULT_COST)

    def remaining(self) -> float:
        return max(0.0, self.cap_usd - self.spent_usd)

    def would_exceed(self, provider_name: str) -> bool:
        return (self.spent_usd + self.cost_for(provider_name)) > self.cap_usd + 1e-9

    def charge(self, provider_name: str) -> float:
        cost = self.cost_for(provider_name)
        if (self.spent_usd + cost) > self.cap_usd + 1e-9:
            raise SpendCapExceeded(
                f"Spend cap ${self.cap_usd:.2f} would be exceeded "
                f"(spent ${self.spent_usd:.2f} + ${cost:.2f})."
            )
        self.spent_usd += cost
        self.image_count += 1
        return cost


# ── Result ────────────────────────────────────────────────────────────

@dataclass
class CardResult:
    """Outcome of generating (or planning) one card."""
    slot: str
    planned: bool                         # True = dry-run, nothing generated
    prompt: str
    provider_option: str                  # effective option (post-gating)
    provider_name: str                    # effective provider name
    grounds_on: tuple[str, ...]           # slot names this card anchors on
    grounding_urls: list[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    # Populated only on commit:
    url: Optional[str] = None
    png_bytes: Optional[bytes] = None
    face_verify: Optional[dict] = None    # consistency-gate verdict
    status: str = "planned"               # planned | generated | gate_failed | error
    error: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────

def _slot_url(canon: "CharacterIdentityCanon", slot: str) -> Optional[str]:
    """Read the currently-assigned URL for a canon slot from the canon object.

    Pure read of the deserialized JSON — no DB query.
    """
    section, attr = SLOT_FIELD_MAP[slot]
    obj = load_face_canon(canon) if section == "face" else load_body_canon(canon)
    return getattr(obj, attr, None) if obj else None


def _grounding_urls(canon: "CharacterIdentityCanon", grounds_on: tuple[str, ...]) -> list[str]:
    return [u for s in grounds_on if (u := _slot_url(canon, s))]


def _generate_png(provider, prompt: str, anchor_bytes: list[bytes]) -> Optional[bytes]:
    """Run the canon scene route's 3-tier generation chain for one image."""
    # Tier A — multi-anchor (best identity grounding).
    if anchor_bytes:
        try:
            return provider.generate_with_anchors(prompt=prompt, anchor_images=anchor_bytes)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("CARD_GEN tier=multi failed; falling back")
    # Tier B — single grounded reference.
    if anchor_bytes:
        try:
            return provider.generate_grounded_image(
                prompt=prompt, reference_image_bytes=anchor_bytes[0]
            )
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("CARD_GEN tier=grounded failed; falling back")
    # Tier C — text only.
    try:
        return provider.generate_image(prompt=prompt)
    except (ValueError, RuntimeError):
        logger.info("CARD_GEN tier=text failed")
    return None


# ── Public API ────────────────────────────────────────────────────────

def generate_card(
    *,
    canon: "CharacterIdentityCanon",
    slot: str,
    identity: FounderIdentity,
    spend: SpendTracker,
    provider_option: str = "option2",
    is_admin: bool = False,
    admin_fallback: bool = False,
    dry_run: bool = True,
) -> CardResult:
    """Generate (or, in dry-run, plan) a single canon card.

    In dry-run NOTHING is generated or saved: the returned CardResult carries
    the compiled prompt, the resolved provider, the grounding plan, and the
    estimated cost. On commit the image is generated, gated, and saved (the
    caller assigns ``result.url`` into the slot and commits the DB).
    """
    spec = CARD_BY_SLOT.get(slot)
    if spec is None:
        raise KeyError(f"Unknown card slot: {slot!r}")

    prompt = build_card_prompt(identity, slot)

    # Provider policy (Gemini default; OpenAI admin-only) — single source of truth.
    effective_option, _gate_meta = resolve_canon_provider_option(
        provider_option, is_admin=is_admin
    )
    provider_name = {"option1": "openai", "option2": "google"}.get(
        effective_option, effective_option
    )
    grounding_urls = _grounding_urls(canon, spec.grounds_on)
    est_cost = SpendTracker.cost_for(provider_name)

    result = CardResult(
        slot=slot,
        planned=dry_run,
        prompt=prompt,
        provider_option=effective_option,
        provider_name=provider_name,
        grounds_on=spec.grounds_on,
        grounding_urls=grounding_urls,
        estimated_cost=est_cost,
    )

    if dry_run:
        # Plan only — no provider call, no storage, no spend.
        result.status = "planned"
        return result

    # ── Commit path (only reached under --commit, run later, not now) ──
    if spend.would_exceed(provider_name):
        raise SpendCapExceeded(
            f"Generating {slot!r} on {provider_name!r} would exceed the "
            f"${spend.cap_usd:.2f} cap (spent ${spend.spent_usd:.2f})."
        )

    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError) as exc:
        result.status = "error"
        result.error = f"provider_resolve_failed: {exc}"
        return result

    anchor_bytes: list[bytes] = []
    for url in grounding_urls:
        try:
            anchor_bytes.append(load_image_bytes(url))
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the pack
            logger.warning("CARD_GEN ref_load_failed slot=%s url=%s err=%r", slot, url, exc)

    png = _generate_png(provider, prompt, anchor_bytes)
    if png is None:
        fb = get_fallback_provider()
        if fb is not None:
            try:
                png = fb.generate_image(prompt=prompt)
                provider_name = "fal"
            except (ValueError, RuntimeError):
                png = None
    if png is None:
        result.status = "error"
        result.error = "all_generation_tiers_failed"
        return result

    spend.charge(provider_name)
    result.provider_name = provider_name

    # ── Consistency gate (S24AL §5): every non-face_front card must match the
    # approved face_front. Degrades to a no-op without an OpenAI key. ──────
    if slot != "face_front":
        face_url = _slot_url(canon, "face_front")
        if face_url:
            try:
                ref_png = load_image_bytes(face_url)
                verdict = verify_face_match(ref_png, png)
                result.face_verify = verdict
                threshold = settings.IDENTITY_FACE_VERIFY_THRESHOLD
                if settings.IDENTITY_FACE_VERIFY and not face_passes(verdict, threshold):
                    # One escalated retry; optionally on the admin OpenAI path.
                    retry_option = effective_option
                    if admin_fallback and is_admin and effective_option != "option1":
                        retry_option = "option1"
                    if not spend.would_exceed(
                        {"option1": "openai", "option2": "google"}.get(retry_option, retry_option)
                    ):
                        try:
                            retry_provider = get_provider_for_option(retry_option)
                            cand = _generate_png(retry_provider, prompt, anchor_bytes)
                            if cand is not None:
                                rp_name = {"option1": "openai", "option2": "google"}.get(
                                    retry_option, retry_option
                                )
                                spend.charge(rp_name)
                                cand_verdict = verify_face_match(ref_png, cand)
                                if face_passes(cand_verdict, threshold):
                                    png, result.face_verify = cand, cand_verdict
                                    result.provider_name = rp_name
                                else:
                                    result.status = "gate_failed"
                        except (RuntimeError, ValueError):
                            pass
                    else:
                        result.status = "gate_failed"
            except Exception as exc:  # noqa: BLE001
                logger.warning("CARD_GEN gate_skipped slot=%s err=%r", slot, exc)

    result.url = save_image(png)
    result.png_bytes = png
    if result.status not in ("gate_failed",):
        result.status = "generated"
    return result

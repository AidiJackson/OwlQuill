"""Interactive image generation — the pipeline, callable outside a request.

This module holds what used to be the body of
``POST /characters/{id}/image-generator/generate``. It was extracted for one
reason: the published deployment target is Cloud Run, which enforces a request
deadline, and this pipeline can legitimately spend up to four provider calls
(first pass + two escalated face-verification retries + one cover retry) each
bounded by ``GOOGLE_IMAGE_TIMEOUT_S`` (180s). Holding an HTTP request open for
that long from a tablet is how a founder pays for an image and never receives
it. The same code now runs either inside the request (the preserved synchronous
route) or inside a detached job driver (the founder workflow), because it is one
function instead of a route body.

The logic is otherwise the code that was already here. Every safeguard is
carried over unchanged and by construction, not by re-implementation:

  * canon is the only identity truth (``canon_compiler`` + ``scene_router``);
  * no silent fallback — a canon generation whose reference-bearing calls all
    fail raises rather than returning a generic person;
  * no silent multi-reference → single-reference degradation;
  * provider capability gating;
  * byte-identical reference dedup;
  * closed-loop face verification with escalated regeneration;
  * permanent-mark placement verification (flag-only);
  * failure classification (sexual refusal vs provider block vs recitation);
  * full provenance/diagnostic metadata on the saved row.

MANUAL REFERENCES. A founder may hand-pick up to four of their own character
images as evidence for one generation. What grounds that generation is decided
by ``params.reference_mode``:

  * ``augment`` (default, and what /images sends) — canon-driven. The cards
    AUGMENT canon and never replace it: canon compiled into the prompt, canon
    references routed first, cards in the remaining capacity.
  * ``deliberate`` (Admin Creator) — reference-driven. The cards and the prompt
    are the entire brief: canon is not queried, compiled or routed, and the
    selected character serves only as the owner of the resulting row.

See ``app.services.manual_references`` for the merge policy. Both modes save an
ordinary SCENE_ONLY row against the selected character, and canon is never
written by this module under either.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.storage import save_image, load_image_bytes, detect_image_format
from app.models.character_identity_canon import CharacterIdentityCanon
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.services.canon_compiler import compile_canon_prompt, has_any_canon_content
from app.services.canon_service import load_face_canon
from app.services.face_verifier import verify_face_match, passes as _face_passes
from app.services.image_provider import (
    get_provider_for_option,
    get_fallback_provider,
    is_moderation_block,
    resolve_canon_provider_option,
)
from app.services.image_providers.google_provider import (
    google_credential_fingerprint,
    parse_prompt_block,
)
from app.services.manual_references import (
    MAX_MANUAL_REFERENCES,
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    ResolvedReference,
    build_reference_notes,
    describe_board_operation,
    merge_reference_sets,
    normalise_reference_mode,
    refs_source as _refs_source,
    resolve_manual_references,
)
from app.services.reference_isolation import (
    DERIVATION_VERSION,
    IsolationError,
    isolate as isolate_reference,
    isolation_audit,
    should_isolate,
)

#: Founder-facing names for the roles that can fail isolation. The error names
#: the CARD the founder chose, so "Hair reference 2" points at something they
#: can see and replace — never at a detector or a coordinate frame.
_ROLE_DISPLAY: dict[str, str] = {
    "hair": "Hair",
    "eyes": "Eyes",
    "eyebrows": "Eyebrows",
    "nose": "Nose",
    "mouth_lips": "Mouth / Lips",
    "skin_complexion": "Skin / Complexion",
    "face_shape": "Face Shape / Jaw",
}


def _role_display(role) -> str:
    return _ROLE_DISPLAY.get(getattr(role, "value", str(role)), "Feature")
from app.services.provider_capabilities import Capability, provider_supports, ref_support_level
from app.services.scene_router import (
    MAX_PROVIDER_REFS,
    route_canon_refs,
    routing_diagnostics as _routing_diagnostics,
    slot_names_for_urls,
)
from app.services.stub_image_generator import generate_placeholder_png

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

    from app.models.character import Character as CharacterModel
    from app.models.user import User

logger = logging.getLogger(__name__)

# Bound on the diagnostic copy of the compiled prompt stored on each image
# record. Comfortably above _PROMPT_CAP (2400) so the stored value is the
# whole prompt in every non-pathological case, while still capping storage.
_STORED_PROMPT_CHARS = 4000

# B17 provider option → internal provider name (not exposed to end users).
_OPTION_PROVIDER_NAMES: dict[str, str] = {
    "option1": "openai",
    "option2": "google",
    "option3": "flux_pro",
    "option4": "flux_max",
    "option5": "together_flux",
    "option6": "grok",
}

# ── Cover-generation prompt directives ────────────────────────────────
#
# _COVER_BANNER_PREFIX   — always prepended when is_cover=True (~225 chars).
# _COVER_CHARACTER_FRAMING — appended additionally when is_cover=True AND
#                            include_character=True (~140 chars).
#
# Combined budget: up to ~365 chars of cover instructions.
# When include_character=True, canon_compiler.compile_canon_prompt wraps the result;
# cover instructions travel at the tail of the prompt where image models weight them well.

_COVER_BANNER_PREFIX = (
    "PROFILE HEADER BANNER — ultra-wide 2.84:1 panoramic ratio. Not a portrait, not centered. "
    "COMPOSITION: subject in LEFT THIRD only. "
    "RIGHT two-thirds: open background, sky, or environment — no subject there. "
    "Full face and head completely visible. No head or face cropping. "
    "Intentional website profile banner layout. "
)

# Applied additionally when the character is included in the cover image.
# Enforces medium-shot framing so the face is reliably visible at banner scale.
_COVER_CHARACTER_FRAMING = (
    "CHARACTER: chest-up or waist-up framing. Full face clearly visible. No full-body shot. "
)

# Used for the single deterministic retry issued when a character-inclusive
# cover is generated. The retry escalates framing language and re-anchors
# the composition rule to give the model a second chance at banner layout.
# Kept to ~230 chars — travels comfortably inside the compiled canon prompt.
_COVER_RETRY_PROMPT = (
    "COVER RETRY — PROFILE HEADER BANNER, ultra-wide 2.84:1. "
    "Subject in LEFT THIRD, chest-up or waist-up ONLY, full face visible. "
    "Right two-thirds: open background — no subject. "
    "No full-body shot. No face crop. Intentional banner layout. "
)

# Escalated identity directive prepended on a verification-triggered retry.
_FACE_REGEN_PREFIX = (
    "CRITICAL IDENTITY MATCH: reproduce the exact same person as the reference "
    "images — identical face shape, jaw, nose, eye shape, brow, and bone "
    "structure. Do not drift toward a generic or different face. "
)

# ── Canon-failure classification ──────────────────────────────────────
#
# A canon generation whose reference-bearing calls all failed used to return ONE
# message — "reduce adult/explicit wording" — no matter why. That is actively
# misleading for a benign prompt: Gemini answers a blocked prompt with
# blockReason=OTHER and NO safety category, which says nothing about sexual
# content, and a plain timeout or an unsupported-provider error said nothing
# about content at all. The three outcomes are now distinguished.

_DETAIL_SEXUAL_REFUSAL = (
    "Canon provider declined this scene. "
    "Try Adult Studio or reduce adult/explicit wording."
)
_DETAIL_PROVIDER_BLOCKED = (
    "Google could not process this character reference set. "
    "Try again or use another provider."
)
# Gemini IMAGE_RECITATION — the model declined to RETURN an image it judged too
# close to its training data. It is a recitation/copyright guard, NOT a safety
# verdict: Google attaches no harm category to it and it fires on entirely
# non-sexual references (Angelo, 2026-08). Classifying it as a sexual refusal
# sent benign canon generations to Adult Studio and made the operator logs read
# as an adult-content event when no safety signal existed at all.
_DETAIL_IMAGE_RECITATION = (
    "Google could not process this character reference combination. "
    "Try another provider or adjust the reference set."
)
_DETAIL_GENERIC_FAILURE = (
    "Image generation failed for this character. Please try again."
)

# Google safety-category substrings that genuinely denote sexual content. A
# category list that contains none of these (including the common EMPTY list
# accompanying blockReason=OTHER) must NOT produce adult-content guidance.
_SEXUAL_CATEGORY_MARKERS = ("SEXUALLY_EXPLICIT", "HARM_CATEGORY_SEXUAL")


# ── Parameters ────────────────────────────────────────────────────────


@dataclass
class GenerationParams:
    """One generation intent, in a form that survives a JSON round-trip.

    The job row stores exactly this (``params_json``), so the detached driver
    reconstructs the request without re-reading anything client-supplied. It
    holds no credentials and no resolved entitlement decisions beyond the two
    booleans the provider gate needs, which are computed from the caller's
    account at submission time and never sent by the client.
    """

    prompt: str
    include_character: bool = False
    provider_option: str = "option2"
    is_cover: bool = False
    reference_image_ids: list[int] = field(default_factory=list)
    reference_roles: list[str] = field(default_factory=list)
    # Which surface submitted this, expressed as the reference-merge policy it
    # asked for: "augment" (canon-first — the Image Generator and every existing
    # caller) or "deliberate" (manual-first — Admin Creator). Stored inside the
    # existing params_json blob, so a job row written before this field existed
    # deserialises to "augment" and replays under the original policy.
    reference_mode: str = REFERENCE_MODE_AUGMENT
    # Entitlement snapshot taken at submission — never client input.
    is_admin: bool = False
    is_founder: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "include_character": self.include_character,
            "provider_option": self.provider_option,
            "is_cover": self.is_cover,
            "reference_image_ids": list(self.reference_image_ids),
            "reference_roles": list(self.reference_roles),
            "reference_mode": self.reference_mode,
            "is_admin": self.is_admin,
            "is_founder": self.is_founder,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "GenerationParams":
        return cls(
            prompt=data.get("prompt") or "",
            include_character=bool(data.get("include_character")),
            provider_option=data.get("provider_option") or "option2",
            is_cover=bool(data.get("is_cover")),
            reference_image_ids=list(data.get("reference_image_ids") or []),
            reference_roles=list(data.get("reference_roles") or []),
            reference_mode=normalise_reference_mode(data.get("reference_mode")),
            is_admin=bool(data.get("is_admin")),
            is_founder=bool(data.get("is_founder")),
        )


# ── Helpers (moved verbatim from the route) ───────────────────────────


def _classify_ref_failure(reason: str | None) -> tuple[str, str | None, list[str]]:
    """Classify why every reference-bearing provider call failed.

    Returns ``(kind, block_reason, safety_categories)`` where kind is one of:

      ``"sexual_refusal"``  — the provider refused on sexual/adult grounds.
          ONLY returned when there is actual sexual/safety evidence: a Google
          safety category naming sexual content, or the OpenAI moderation
          vocabulary. This is the only kind that may mention Adult Studio.
      ``"provider_blocked"`` — Google blocked the prompt for a NON-sexual or
          unspecified reason (blockReason=OTHER and friends).
      ``"image_recitation"`` — Gemini returned IMAGE_RECITATION: it would not
          emit the image it generated. Carries no safety category and is not a
          content verdict; see _DETAIL_IMAGE_RECITATION.
      ``"unknown"`` — anything else: timeout, HTTP error, a provider that cannot
          consume references at all.
    """
    reason = reason or ""
    block_reason, categories = parse_prompt_block(reason)
    if block_reason:
        joined = " ".join(categories).upper()
        if any(m in joined for m in _SEXUAL_CATEGORY_MARKERS):
            return "sexual_refusal", block_reason, categories
        return "provider_blocked", block_reason, categories
    if "google_refused_image" in reason:
        return "image_recitation", "IMAGE_RECITATION", []
    # OpenAI moderation vocabulary shared with scene_images / character_visual —
    # a real content verdict, unchanged.
    if is_moderation_block(reason):
        return "sexual_refusal", None, []
    return "unknown", None, []


def _provider_model_slug(provider) -> str:
    """Best-effort model identifier for logging.

    The Google adapter wraps GoogleImageProvider, so the model lives at
    ``provider._google._model``; probing the adapter alone (as this log line
    once did) always yielded "?" and left every Google failure unattributable to
    a model. FLUX/Together adapters expose ``model_name`` instead.
    """
    for obj in (provider, getattr(provider, "_google", None)):
        if obj is None:
            continue
        for attr in ("model_name", "_model", "model"):
            value = getattr(obj, attr, None)
            if isinstance(value, str) and value:
                return value
    return "?"


def _ref_digest(url: str) -> str:
    """Stable, non-reversible 8-char identifier for a reference URL.

    The query string is dropped before hashing so a re-signed URL for the same
    object keeps the same digest — and so no credential can reach the log even
    in digested form.
    """
    return hashlib.sha256(url.split("?", 1)[0].encode()).hexdigest()[:8]


def _ref_audit(
    db: "Session",
    urls: list[str],
    slots: list[str],
    load_flags: list[bool],
    ref_bytes: list[bytes] | None = None,
) -> list[str]:
    """Build per-reference audit tokens: position, slot, DB image id, digests.

    Deliberately carries NO URL, signed or otherwise. The DB id is looked up by
    file_path and is absent for canon cards uploaded through the admin route
    (which stores bytes without creating a CharacterImage row) — those are still
    identifiable by slot name plus digest.

    Two independent digests are emitted per position:

      ``h=``  sha256 of the reference URL path — identifies WHICH object was
              selected. It says nothing about the object's contents.
      ``b=``  sha256 of the bytes actually sent to the provider, with the size
              and sniffed mime type that accompany them in the payload.

    ``b=`` exists because ``h=`` alone cannot settle a prod-vs-dev comparison:
    two deployments can select the same slot at the same path and still send
    different bytes (a re-encode, a different upload behind the same name, a
    truncated read). Only a content hash proves the provider received the same
    input. ``ref_bytes`` holds ONLY the successfully loaded references, so it is
    walked positionally against ``load_flags`` rather than indexed directly.
    """
    ids_by_path: dict[str, int] = {}
    try:
        rows = (
            db.query(CharacterImage.id, CharacterImage.file_path)
            .filter(CharacterImage.file_path.in_(urls))
            .all()
        )
        for image_id, path in rows:
            ids_by_path.setdefault(path, image_id)
    except Exception:  # diagnostics must never mask the provider failure
        logger.debug("IMAGE_GEN_REF_AUDIT_ID_LOOKUP_FAILED", exc_info=True)

    loaded_bytes = list(ref_bytes or [])
    cursor = 0
    tokens: list[str] = []
    for i, url in enumerate(urls):
        slot = slots[i] if i < len(slots) else "unknown"
        loaded = load_flags[i] if i < len(load_flags) else False
        image_id = ids_by_path.get(url)
        content = "-"
        size = "-"
        mime = "-"
        if loaded and cursor < len(loaded_bytes):
            raw = loaded_bytes[cursor]
            cursor += 1
            content = hashlib.sha256(raw).hexdigest()[:8]
            size = str(len(raw))
            try:
                _, mime = detect_image_format(raw)
            except Exception:
                mime = "?"
        tokens.append(
            f"{i}:slot={slot}:id={image_id if image_id is not None else '-'}"
            f":h={_ref_digest(url)}:b={content}:bytes={size}:mime={mime}"
            f":loaded={int(loaded)}"
        )
    return tokens


def _generate_scene_png(
    provider,
    *,
    prompt: str,
    ref_bytes: list[bytes],
    provider_supports_multi: bool,
) -> bytes | None:
    """Run the multi-image → grounded → text generation tiers for one prompt.

    Returns PNG bytes, or None if every tier failed. Mirrors the inline tier
    chain used for the first pass so a verification retry takes the identical
    path with an escalated prompt.
    """
    multi_attempted = bool(ref_bytes and provider_supports_multi)
    if multi_attempted:
        try:
            return provider.generate_with_anchors(prompt=prompt, anchor_images=ref_bytes)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            pass
    # Single-reference grounding only when multi-reference was never available —
    # never as a downgrade after a failed multi-reference attempt. See the
    # matching note in run_image_generation().
    if ref_bytes and not multi_attempted:
        try:
            return provider.generate_grounded_image(prompt=prompt, reference_image_bytes=ref_bytes[0])
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            pass
    if ref_bytes:
        # References were selected, so a reference-LESS regeneration is weaker
        # evidence than the router chose. A text-only candidate that happened to
        # score better on face verification would have been saved as the final
        # image — a generic person passing as the character. Give up instead;
        # the caller keeps the initial, properly-grounded image.
        return None
    try:
        return provider.generate_image(prompt=prompt)
    except (ValueError, RuntimeError):
        return None


def _verify_and_regenerate(
    *,
    provider,
    canon,
    compiled_prompt: str,
    ref_bytes: list[bytes],
    provider_supports_multi: bool,
    initial_png: bytes,
    character_id: int,
) -> tuple[bytes, dict]:
    """Score the initial image against canon face; regenerate on confident drift.

    Returns ``(best_png, meta)``. ``meta`` records the verification outcome for
    the image record. The initial image is always a valid fallback — if no
    retry scores better, it is returned unchanged.
    """
    meta: dict = {"face_verify_enabled": True}

    face = load_face_canon(canon)
    face_ref_url = getattr(face, "face_front_image_url", None) if face else None
    if not face_ref_url:
        return initial_png, {**meta, "face_verify_skipped": "no_face_ref"}
    try:
        ref_png = load_image_bytes(face_ref_url)
    except Exception:
        return initial_png, {**meta, "face_verify_skipped": "face_ref_load_failed"}

    threshold = settings.IDENTITY_FACE_VERIFY_THRESHOLD
    max_retries = max(0, int(settings.IDENTITY_FACE_VERIFY_MAX_RETRIES))

    verdict = verify_face_match(ref_png, initial_png)
    meta["face_verify_initial"] = {
        "similarity": verdict.get("similarity"),
        "match": verdict.get("match"),
        "skip_reason": verdict.get("skip_reason"),
    }
    if _face_passes(verdict, threshold):
        meta["face_verify_result"] = "passed" if verdict.get("ok") else "unverified"
        return initial_png, meta

    # Confident mismatch → regenerate with escalated grounding, keep best score.
    best_png = initial_png
    best_sim = float(verdict.get("similarity", 0.0))
    retry_prompt = _FACE_REGEN_PREFIX + compiled_prompt
    attempts = 0
    for _ in range(max_retries):
        attempts += 1
        cand = _generate_scene_png(
            provider,
            prompt=retry_prompt,
            ref_bytes=ref_bytes,
            provider_supports_multi=provider_supports_multi,
        )
        if cand is None:
            break
        cand_verdict = verify_face_match(ref_png, cand)
        cand_sim = float(cand_verdict.get("similarity", 0.0))
        if _face_passes(cand_verdict, threshold):
            logger.info(
                "IMAGE_GEN_FACE_VERIFY character_id=%s result=recovered attempt=%d sim=%.2f",
                character_id, attempts, cand_sim,
            )
            return cand, {
                **meta,
                "face_verify_result": "recovered",
                "face_verify_attempts": attempts,
                "face_verify_final_similarity": cand_sim,
            }
        if cand_sim > best_sim:
            best_png, best_sim = cand, cand_sim

    # S24I: a below-threshold result after all retries is no longer a silent
    # save. Surface a user-visible warning in the image metadata so the client
    # can flag "identity may not fully match" rather than presenting a drifted
    # face as a clean result. The best-scoring candidate is still returned as the
    # graceful fallback (never a hard failure).
    logger.warning(
        "IMAGE_GEN_FACE_VERIFY character_id=%s result=below_threshold attempts=%d "
        "best_sim=%.2f threshold=%.2f (surfaced as user warning)",
        character_id, attempts, best_sim, threshold,
    )
    return best_png, {
        **meta,
        "face_verify_result": "below_threshold",
        "face_verify_attempts": attempts,
        "face_verify_final_similarity": best_sim,
        "face_verify_warning": (
            "Generated face may not fully match this character's locked identity. "
            "Try regenerating or use a clearer scene description."
        ),
    }


# Human-readable policy names. Two mappings because the log line and the image
# metadata have always carried slightly different strings, and both augment
# values are kept EXACTLY as they were before deliberate mode existed: an
# /images record stays byte-identical to its predecessors and an existing log
# grep still matches.
_REF_LOG_POLICY = {
    REFERENCE_MODE_AUGMENT: "canon_first_manual_tail_trimmed",
    REFERENCE_MODE_DELIBERATE: "manual_first_canon_tail_trimmed",
}
_REF_META_POLICY = {
    REFERENCE_MODE_AUGMENT: "canon_first_manual_appended_tail_trimmed",
    REFERENCE_MODE_DELIBERATE: "manual_first_canon_tail_trimmed",
}


def _reference_budget(provider, provider_name: str) -> int:
    """How many references may be sent to this provider in one request.

    ``MAX_PROVIDER_REFS`` (6) is the app's own routing budget and stays the
    operative cap — it is what canon routing has always been bounded by, so
    canon-only generations keep byte-identical behaviour. A model that documents
    a SMALLER hard limit narrows it further; ``model_profiles`` returns ``None``
    for models with no documented limit, which leaves the app budget in charge.
    This never widens past 6.
    """
    if provider is None:
        return MAX_PROVIDER_REFS
    try:
        from app.services.model_profiles import model_profile

        profile = model_profile(provider_name, _provider_model_slug(provider))
        if profile.max_reference_images is not None:
            return max(1, min(MAX_PROVIDER_REFS, profile.max_reference_images))
    except Exception:  # a profile lookup must never break generation
        logger.debug("IMAGE_GEN_REF_BUDGET_LOOKUP_FAILED", exc_info=True)
    return MAX_PROVIDER_REFS


# ── The pipeline ──────────────────────────────────────────────────────


def run_image_generation(
    db: "Session",
    *,
    character: "CharacterModel",
    user: "User",
    params: GenerationParams,
) -> tuple[CharacterImage, dict]:
    """Generate one image and persist it as a CharacterImage row.

    Returns ``(image, summary)``. ``summary`` is the safe, user-facing account of
    what actually reached the provider (reference counts, refs_source, anything
    dropped for budget) — the job layer stores it so the client can warn without
    reading raw metadata.

    Architecture (Identity OS — canon single source):
        Generate Images → CharacterIdentityCanon → canon_compiler → provider

    When ``include_character`` is set AND the mode is ``augment`` (i.e. every
    /images generation):
      - CharacterIdentityCanon is required. If missing or incomplete, raises a
        409 "Character canon incomplete".
      - The prompt is compiled by canon_compiler.compile_canon_prompt in strict
        order: face → body → permanent marks → requested accessories → scene →
        locked-canon clause.
      - Canon reference images are the locked face/body slots selected by the
        scene-aware reference router (route_canon_refs).
      - Manual references (``params.reference_image_ids``) are appended AFTER
        the canon set, never in place of it, and never written back to canon.

    When the mode is ``deliberate`` (Admin Creator) none of that runs. The
    character is an ownership and storage destination only: canon is not queried,
    not compiled, not routed, and not required to be complete; the scene router
    is never consulted; and the provider receives the founder's cards and prompt
    alone. See the bypass below.

    Scene images always save as SCENE_ONLY (or COVER for is_cover) against the
    selected character in both modes; canon is never mutated here.

    Ownership and entitlement are the CALLER's responsibility — both the
    synchronous route and the job submission validate them before this runs.
    """
    character_id = int(character.id)

    # ── Manual references: re-validated against the DB, never trusted ──
    # Resolved here as well as at submission so the driver's fresh session
    # revalidates: an image deleted between submit and run must not be sent.
    manual_refs: list[ResolvedReference] = resolve_manual_references(
        db,
        character_id=character_id,
        image_ids=params.reference_image_ids,
        roles=params.reference_roles,
    )

    # ── Reference mode: what grounds this generation ──────────────────
    # Resolved before anything reads canon, because in deliberate mode the
    # answer is "nothing does" and the canon block below must not run at all.
    ref_mode = normalise_reference_mode(params.reference_mode)
    deliberate = ref_mode == REFERENCE_MODE_DELIBERATE

    # ── Provider resolution + beta gating ──────────────────────────
    requested_option = (
        params.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    )
    effective_option, provider_gate_meta = resolve_canon_provider_option(
        requested_option, is_admin=params.is_admin, is_founder=params.is_founder
    )
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]
    if provider_gate_meta:
        logger.info(
            "IMAGE_GEN_PROVIDER_GATED character_id=%s user_id=%s requested=%s effective=%s reason=%s",
            character_id, user.id, requested_option, effective_option,
            provider_gate_meta.get("provider_fallback_reason"),
        )

    base_prompt = params.prompt.strip()

    # Filled by the compiler on the pass it already performs (which clauses were
    # emitted, whether fitting ran) and persisted below, so a visual-QA failure
    # can be diagnosed from the record rather than by replaying the compiler.
    prompt_diag: dict = {}

    # Cover mode: prepend banner-composition directives before the user's prompt.
    if params.is_cover:
        cover_block = _COVER_BANNER_PREFIX
        if params.include_character:
            cover_block += _COVER_CHARACTER_FRAMING
        base_prompt = cover_block + base_prompt

    # ── Identity truth: CharacterIdentityCanon ONLY ───────────────
    canon: CharacterIdentityCanon | None = None
    canon_urls: list[str] = []
    using_canon = False
    scene_meta = None

    # Deliberate mode is reference-driven: the selected character is an ownership
    # and storage destination, not a generation input. Its canon is neither
    # compiled into the prompt nor routed into the reference set, the scene
    # router is never consulted, and incomplete canon is not an error — the
    # founder's cards and prompt are the whole brief.
    #
    # The bypass is enforced HERE rather than trusted from the client. A client
    # that sends include_character=true alongside reference_mode="deliberate" —
    # by regression, by a stale bundle, or by hand — must not be able to
    # reintroduce the silent canon injection this mode exists to prevent.
    canon_grounded = params.include_character and not deliberate
    if deliberate and params.include_character:
        logger.info(
            "IMAGE_GEN_CANON_BYPASS character_id=%s mode=%s reason=deliberate_overrides_"
            "include_character",
            character_id, ref_mode,
        )

    if canon_grounded:
        canon = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == character_id)
            .first()
        )
        if canon is None or not has_any_canon_content(canon):
            # Graceful fallback — no legacy identity sources are consulted.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Character canon incomplete",
            )
        compiled_prompt = compile_canon_prompt(
            canon,
            base_prompt,
            include_accessories=True,
            diagnostics=prompt_diag,
        )
        # P10: scene-aware reference routing replaces static ordering.
        # Route on the raw user scene text (not the cover-prefixed prompt).
        canon_urls, scene_meta = route_canon_refs(params.prompt, canon)
        using_canon = True
    else:
        compiled_prompt = base_prompt

    # ── Resolve provider (needed before merging: it sets the budget) ──
    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError):
        logger.warning(
            "image_generator provider_unavailable option=%s provider=%s character_id=%s",
            effective_option, resolved_provider_name, character_id,
        )
        provider = None

    # ── Merge canon + manual references under one bounded budget ──────
    # augment (default, /images): canon first and never trimmed; manual appended
    # in the founder's order; overflow dropped from the manual tail.
    # deliberate (Admin Creator): canon_urls is empty by the bypass above, so
    # this resolves to the cards alone. The manual-first branch is retained as a
    # SAFETY NET rather than as live policy: if the bypass ever regresses, the
    # founder's cards still lead the payload instead of being silently crowded
    # out — the exact failure this whole surface exists to fix.
    # Either way every omission is REPORTED. See app.services.manual_references
    # for the full policy — this call is the only place the two differ.
    budget = _reference_budget(provider, resolved_provider_name)
    reference_urls, manual_sent, manual_dropped = merge_reference_sets(
        canon_urls=canon_urls, manual=manual_refs, budget=budget, mode=ref_mode
    )
    # Whatever is in the payload that is not a manual reference is canon, in both
    # orderings. Derived rather than re-computed so the two can never disagree.
    canon_sent_count = len(reference_urls) - len(manual_sent)
    canon_dropped_count = max(0, len(canon_urls) - canon_sent_count)
    if manual_dropped:
        logger.warning(
            "IMAGE_GEN_REF_BUDGET character_id=%s mode=%s budget=%d canon=%d "
            "manual_selected=%d manual_sent=%d manual_dropped=%s policy=%s",
            character_id, ref_mode, budget, canon_sent_count, len(manual_refs),
            len(manual_sent), [r.image_id for r in manual_dropped],
            _REF_LOG_POLICY[ref_mode],
        )
    if canon_dropped_count:
        # Canon losing capacity is the deliberate mode's whole trade, and it is
        # stated rather than left for someone to infer from a reference count.
        logger.info(
            "IMAGE_GEN_REF_CANON_TRIMMED character_id=%s mode=%s budget=%d "
            "canon_selected=%d canon_sent=%d canon_dropped=%d manual_sent=%d policy=%s",
            character_id, ref_mode, budget, len(canon_urls), canon_sent_count,
            canon_dropped_count, len(manual_sent), _REF_LOG_POLICY[ref_mode],
        )

    # Role notes ride at the TAIL of the compiled prompt, so canon compilation
    # is byte-identical to what it produced before manual references existed.
    # The numbering follows the PAYLOAD order, which the mode decides: under
    # deliberate the manual block leads, so nothing precedes it.
    reference_notes = build_reference_notes(
        manual_sent,
        canon_ref_count=canon_sent_count,
        canon_grounded=using_canon,
        refs_before_manual=0 if deliberate else canon_sent_count,
        mode=ref_mode,
    )
    if reference_notes:
        compiled_prompt = compiled_prompt + reference_notes

    logger.info(
        "IMAGE_GEN_START character_id=%s include_character=%s using_canon=%s "
        "camera=%s routed=%s exposure=%s refs=%d canon_refs=%d manual_refs=%d "
        "prompt_len=%d prompt_preview=%r",
        character_id, params.include_character, using_canon,
        scene_meta.camera if using_canon else "n/a",
        scene_meta.routed if using_canon else False,
        scene_meta.exposure if using_canon else [],
        len(reference_urls), canon_sent_count, len(manual_sent),
        len(compiled_prompt), compiled_prompt[:120],
    )

    # ── Load reference image bytes ────────────────────────────────
    # Query strings are stripped before logging: a signed storage URL carries its
    # credential there, and reference URLs are operator diagnostics, not secrets.
    requested_refs = reference_urls[:budget]
    # Role per PAYLOAD POSITION, derived from the same ordering the merge just
    # chose — deliberate puts the cards first, augment puts canon first. This is
    # what lets the loader below know that position 2 is a Hair card and must be
    # isolated; the loop otherwise sees only URLs. Canon positions are None:
    # canon is identity truth and is never transformed.
    payload_roles: list[Any] = (
        [r.role for r in manual_sent] + [None] * (len(reference_urls) - len(manual_sent))
        if deliberate
        else [None] * canon_sent_count + [r.role for r in manual_sent]
    )
    payload_roles = payload_roles[:budget]
    logger.info(
        "IMAGE_GEN_REF_LOAD_START character_id=%s refs_requested=%d",
        character_id, len(requested_refs),
    )
    ref_bytes: list[bytes] = []
    # Positional load outcome per requested ref — lets the block diagnostic name
    # exactly which selected references reached the provider. ref_bytes alone
    # cannot: it silently drops failures and loses the correlation to the slot.
    ref_load_flags: list[bool] = []
    # Byte-identical duplicate suppression (REF EFFICIENCY): canon slots may
    # legitimately share one card (same URL under two slot names, or the same
    # bytes uploaded twice), and a manual reference may repeat a canon card. A
    # duplicate adds zero identity information and only inflates the provider
    # payload — the Angelo investigation measured a six-reference request at
    # ~17 MB. Deduped positions are logged distinctly from load failures; the
    # FIRST occurrence always survives, so identity grounding is untouched and
    # canon (which is always first) always wins a tie against a manual repeat.
    refs_deduped = 0
    _seen_ref_hashes: set[str] = set()
    # Isolation provenance per manual reference, keyed by image id. Consumed by
    # the audit below so a past generation records what the provider actually
    # received, without any derived image ever being persisted.
    isolation_audit_by_id: dict[int, dict[str, Any]] = {}
    for _pos, url in enumerate(requested_refs):
        safe_url = url.split("?", 1)[0]
        _role = payload_roles[_pos] if _pos < len(payload_roles) else None
        try:
            b = load_image_bytes(url)
        except Exception as exc:
            ref_load_flags.append(False)
            # exc_type is logged separately because str(exc) alone hid a
            # ModuleNotFoundError behind a misleading message once already.
            logger.warning(
                "IMAGE_GEN_REF_LOAD_FAILED character_id=%s url=%s exc_type=%s error=%r",
                character_id, safe_url, type(exc).__name__, str(exc),
            )
            continue
        # ── Feature isolation (deliberate Admin Creator boards only) ──
        # The donor's whole face would otherwise reach the provider with only
        # prose scoping it, which is the leak this closes. A failure here is
        # FATAL for the generation: sending the untouched donor instead would
        # silently restore the leak the founder believes was removed.
        if deliberate and should_isolate(_role):
            try:
                b = isolate_reference(b, _role)
            except IsolationError as exc:
                logger.warning(
                    "IMAGE_GEN_REF_ISOLATION_FAILED character_id=%s position=%d "
                    "role=%s status=%s",
                    character_id, _pos + 1, _role.value, exc.status,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"{_role_display(_role)} reference {_pos + 1} could not be "
                        f"safely isolated. {exc.reason}"
                    ),
                ) from exc
            # Under deliberate the cards lead the payload, so the position IS
            # the card index — the same correspondence payload_roles was built
            # from.
            if _pos < len(manual_sent):
                isolation_audit_by_id[manual_sent[_pos].image_id] = isolation_audit(
                    _role, "applied", applied=True
                )
            logger.info(
                "IMAGE_GEN_REF_ISOLATED character_id=%s position=%d role=%s version=%d",
                character_id, _pos + 1, _role.value, DERIVATION_VERSION,
            )

        # Dedup on the bytes actually SENT, not the bytes loaded. One donor
        # selected as both Hair and Eyebrows derives two different images and
        # must reach the provider as two references; hashing the original would
        # drop the second as a duplicate and silently lose a card. For every
        # untransformed reference the derived bytes ARE the original, so this is
        # byte-identical to the previous behaviour.
        content_hash = hashlib.sha256(b).hexdigest()
        if content_hash in _seen_ref_hashes:
            refs_deduped += 1
            ref_load_flags.append(False)
            logger.info(
                "IMAGE_GEN_REF_DEDUP character_id=%s url=%s bytes=%d b=%s "
                "reason=duplicate_content",
                character_id, safe_url, len(b), content_hash[:8],
            )
            continue
        _seen_ref_hashes.add(content_hash)
        ref_bytes.append(b)
        ref_load_flags.append(True)
        logger.info(
            "IMAGE_GEN_REF_LOAD_OK character_id=%s url=%s bytes=%d",
            character_id, safe_url, len(b),
        )
    logger.info(
        "IMAGE_GEN_REF_LOAD_SUMMARY character_id=%s refs_requested=%d refs_loaded=%d "
        "refs_deduped=%d",
        character_id, len(requested_refs), len(ref_bytes), refs_deduped,
    )

    # A generation whose references ALL failed would silently produce a generic
    # person wearing none of the character's locked identity — the exact silent
    # degradation this pipeline refuses further down (S24AD). Refuse it here too,
    # before spending a provider call, rather than returning an identity-weak
    # image the caller cannot distinguish from a good one. Partial loads still
    # proceed: some grounding beats none.
    #
    # The condition covers manual references as well as canon ones. It could not
    # fire on a reference-less generation before manual references existed, so
    # widening it changes no pre-existing path.
    if requested_refs and not ref_bytes:
        logger.error(
            "IMAGE_GEN_REF_LOAD_ALL_FAILED character_id=%s refs_requested=%d "
            "canon=%s manual=%d fallback_blocked=true",
            character_id, len(requested_refs), using_canon, len(manual_sent),
        )
        # Two messages because they are two different problems for the founder:
        # unreachable CANON cards are a storage/platform fault they can only
        # retry, whereas unreachable hand-picked references point at the images
        # they chose. The canon wording is unchanged from before manual
        # references existed.
        detail = (
            "Character reference images could not be loaded. Please try again."
            if canon_sent_count
            else "Your selected reference images could not be loaded. Please try again."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )

    png_bytes: bytes | None = None
    actual_provider_name = "stub"
    multi_image_used = False
    used_ref = False

    # ── Together AI: URL-based multi-reference (option5 only) ────────────
    # Together AI requires public HTTPS URLs for reference_images — its backend
    # fetches them directly, so local /static/ paths are not accessible.
    # This path runs before the bytes-based tier chain because _TogetherFluxAdapter
    # declares URL_ANCHORS but not MULTI_IMAGE_ANCHORS (bytes tier skipped) and
    # exposes generate_with_anchor_urls() for URL-based conditioning.
    together_urls_sent: list[str] = []
    together_response_mode: str = "not_applicable"

    if png_bytes is None and reference_urls and provider_supports(provider, Capability.URL_ANCHORS):
        public_urls = [u for u in requested_refs if u.startswith("https://")]
        local_refs = [u for u in requested_refs if not u.startswith("https://")]
        logger.info(
            "TOGETHER_DIAG character_id=%s selected_refs=%d loaded_bytes=%d "
            "public_refs=%d local_refs=%d",
            character_id, len(reference_urls), len(ref_bytes),
            len(public_urls), len(local_refs),
        )
        if public_urls:
            try:
                png_bytes = provider.generate_with_anchor_urls(
                    prompt=compiled_prompt,
                    anchor_urls=public_urls,
                )
                actual_provider_name = resolved_provider_name
                multi_image_used = True
                together_urls_sent = public_urls
                together_response_mode = "multi_url"
                logger.info(
                    "TOGETHER_DIAG character_id=%s provider_refs_sent=%d "
                    "provider_response_mode=multi_url",
                    character_id, len(public_urls),
                )
            except (ValueError, RuntimeError) as exc:
                together_response_mode = "multi_url_failed"
                logger.warning(
                    "TOGETHER_DIAG character_id=%s provider_refs_sent=%d "
                    "provider_response_mode=multi_url_failed failure_reason=%r",
                    character_id, len(public_urls), str(exc),
                )
        else:
            together_response_mode = "local_refs_only"
            logger.info(
                "TOGETHER_DIAG character_id=%s provider_refs_sent=0 "
                "provider_response_mode=local_refs_only reason=no_public_https_urls",
                character_id,
            )

    # ── Generate: multi-image → grounded → text-only → fal → stub ──
    provider_supports_multi = provider_supports(provider, Capability.MULTI_IMAGE_ANCHORS)
    # S24AD: remember why the reference-bearing calls (multi-image / grounded)
    # failed so a generation can fail loudly instead of silently dropping
    # to a ref-less path. None until a ref-bearing attempt raises.
    ref_failure_reason: str | None = None
    multi_attempted = bool(provider is not None and ref_bytes and provider_supports_multi)
    if multi_attempted:
        try:
            png_bytes = provider.generate_with_anchors(
                prompt=compiled_prompt,
                anchor_images=ref_bytes,
            )
            actual_provider_name = resolved_provider_name
            multi_image_used = True
            logger.info("IMAGE_GEN_MULTI_IMAGE_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError) as exc:
            ref_failure_reason = str(exc)
            logger.info("IMAGE_GEN_MULTI_IMAGE_FAILED character_id=%s fallback=none reason=%r",
                        character_id, str(exc)[:200])

    # ── No silent multi-ref → one-ref degradation ─────────────────────
    # The grounded call runs ONLY when the multi-reference attempt never ran —
    # i.e. the provider cannot consume multiple references, so one reference is
    # its genuine best capability rather than a downgrade. It is no longer a
    # fallback after a failed multi-reference attempt, for two reasons:
    #
    #   * It sends ref_bytes[0] alone. Retrying a failed six-reference canon
    #     generation with ONE reference buys availability by discarding five
    #     pieces of the identity evidence the router selected, and the result is
    #     saved as if it were the real thing. Weaker evidence must never be a
    #     silent consolation prize.
    #   * When exactly one reference was selected the two payloads are
    #     byte-identical (proven: same serialized SHA), so the call could only
    #     ever repeat the first failure at full cost.
    #
    # Transient and recitation retries now live in the provider, where they
    # re-send the COMPLETE reference set — that is where availability is
    # recovered, without touching identity grounding.
    if png_bytes is None and provider is not None and ref_bytes and not multi_attempted:
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=compiled_prompt,
                reference_image_bytes=ref_bytes[0],
            )
            actual_provider_name = resolved_provider_name
            used_ref = True
            logger.info("IMAGE_GEN_GROUNDED_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError) as exc:
            ref_failure_reason = str(exc)
            logger.info("IMAGE_GEN_GROUNDED_FAILED character_id=%s fallback=text reason=%r",
                        character_id, str(exc)[:200])

    # ── S24AD: block the ref-less fallback for reference-bearing runs ──
    # When references were loaded and a real provider's reference-bearing calls
    # (multi-image AND grounded) have all failed or been REFUSED (e.g. Gemini
    # "google_refused_image" on adult-adjacent prompts), DO NOT silently degrade
    # to text-only / FAL / stub. Those drop every reference and return a generic
    # person, not the character (the S24AC2 Summer-bikini failure). Fail loudly
    # so the caller can reword or route to Adult Studio.
    #
    # This now covers a manual-reference generation as well as a canon one: a
    # founder who hand-picked four references and silently received a text-only
    # image would be misled in exactly the same way. The ref-less fallbacks below
    # stay intact for genuine non-ref flows (no references selected at all, or no
    # provider configured → offline/stub path).
    if png_bytes is None and ref_bytes and provider is not None:
        kind, block_reason, safety_categories = _classify_ref_failure(ref_failure_reason)
        model_slug = _provider_model_slug(provider)
        refused = kind == "sexual_refusal"

        logger.warning(
            "IMAGE_GEN_CANON_REFUSED_BLOCKED character_id=%s provider=%s model=%s "
            "failure_kind=%s refused=%s block_reason=%s fallback_blocked=true reason=%r",
            character_id, resolved_provider_name, model_slug,
            kind, refused, block_reason or "-", (ref_failure_reason or "")[:200],
        )

        # Reference-set diagnostic. Emitted only when the provider reported a
        # prompt-level block, which is the case that needs the exact input set
        # identified — and only there, so the ordinary failure path stays cheap.
        # Carries no URL (signed or otherwise), no bytes, no prompt text and no
        # credential: slot names, DB image ids and stable digests are enough to
        # pin the set.
        #
        # Why this exists: a character generating fine in dev while production
        # returns blockReason=OTHER for the same source images (Angelo, 2026-08)
        # left no way to compare the two runs — the block surfaced only as a
        # truncated JSON snippet with no record of WHICH references were sent.
        # This line is what makes a prod-vs-dev comparison possible. Note that
        # the workspace and published databases are NOT the same store, so the
        # production reference set can only be read from production's own logs.
        if block_reason:
            try:
                if using_canon and canon is not None:
                    canon_slots = list(scene_meta.route_slots) or slot_names_for_urls(
                        canon, canon_urls[:canon_sent_count]
                    )
                else:
                    canon_slots = []
                slots = canon_slots[:canon_sent_count] + [
                    f"manual:{r.role.value}" for r in manual_sent
                ]
                logger.warning(
                    "IMAGE_GEN_GOOGLE_BLOCKED character_id=%s provider=%s model=%s "
                    "cred_fp=%s block_reason=%s safety_categories=%s refs_requested=%d "
                    "refs_loaded=%d camera=%s routed=%s exposure=%s "
                    "prompt_len=%d prompt_sha=%s slots=%s refs=[%s]",
                    character_id, resolved_provider_name, model_slug,
                    google_credential_fingerprint(),
                    block_reason, safety_categories or [],
                    len(requested_refs), len(ref_bytes),
                    scene_meta.camera if scene_meta is not None else "n/a",
                    scene_meta.routed if scene_meta is not None else False,
                    scene_meta.exposure if scene_meta is not None else [],
                    len(compiled_prompt),
                    hashlib.sha256(compiled_prompt.encode()).hexdigest()[:8],
                    slots,
                    ", ".join(
                        _ref_audit(db, requested_refs, slots, ref_load_flags, ref_bytes)
                    ),
                )
            except Exception:  # never let diagnostics replace the real failure
                logger.warning(
                    "IMAGE_GEN_GOOGLE_BLOCKED_DIAG_FAILED character_id=%s block_reason=%s",
                    character_id, block_reason, exc_info=True,
                )

        if kind == "sexual_refusal":
            detail = _DETAIL_SEXUAL_REFUSAL
        elif kind == "image_recitation":
            detail = _DETAIL_IMAGE_RECITATION
        elif kind == "provider_blocked":
            detail = _DETAIL_PROVIDER_BLOCKED
        else:
            detail = _DETAIL_GENERIC_FAILURE
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )

    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=compiled_prompt)
            actual_provider_name = resolved_provider_name
            logger.info("IMAGE_GEN_TEXT_ONLY_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError):
            logger.info("IMAGE_GEN_TEXT_FAILED character_id=%s fallback=fal", character_id)

    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=compiled_prompt)
                actual_provider_name = "fal"
                logger.info("IMAGE_GEN_FAL_SUCCESS character_id=%s", character_id)
            except (ValueError, RuntimeError):
                pass

    # ── Closed-loop face verification + regeneration ──────────────────
    # Confirm the generated face actually matches the locked identity; if it
    # confidently drifted, regenerate with escalated grounding and keep the
    # best-scoring result. Best-effort and tightly gated (real provider + canon
    # face ref + enabled + not a cover) so it is a no-op in tests/offline.
    face_verify_meta: dict = {}
    if (
        png_bytes is not None
        and params.include_character
        and not params.is_cover
        and using_canon
        and provider is not None
        and actual_provider_name not in ("stub", "fal")
        and settings.IDENTITY_FACE_VERIFY
    ):
        png_bytes, face_verify_meta = _verify_and_regenerate(
            provider=provider,
            canon=canon,
            compiled_prompt=compiled_prompt,
            ref_bytes=ref_bytes,
            provider_supports_multi=provider_supports_multi,
            initial_png=png_bytes,
            character_id=character_id,
        )

    # ── Permanent-mark placement verification (flag-only) ─────────────
    # Runs only for canons that carry mark-location authority. A violation is
    # surfaced as a metadata warning — never a rejection or regeneration:
    # generation-time grounding (routed cards + clean-skin/occlusion clauses)
    # is the primary defence; this detects the gross drift that slips through.
    mark_verify_meta: dict = {}
    if (
        png_bytes is not None
        and using_canon
        and canon is not None
        and actual_provider_name not in ("stub", "fal")
        and settings.CANON_MARK_VERIFY
    ):
        from app.services.canon_service import load_body_canon
        from app.services.card_coverage import mark_location_authority
        from app.services.mark_verifier import verify_mark_regions

        authority = mark_location_authority(load_body_canon(canon))
        if authority is not None:
            verdict = verify_mark_regions(png_bytes, authority)
            if verdict.get("ok"):
                mark_verify_meta = {
                    "mark_verify_observed": verdict["observed"],
                    "mark_verify_violations": verdict["violations"],
                    "mark_verify_on_clothing": verdict["on_clothing"],
                }
                if verdict["violations"] or verdict["on_clothing"]:
                    mark_verify_meta["mark_verify_warning"] = (
                        "Generated image may show permanent markings outside this "
                        "character's canon (regions: "
                        + (", ".join(verdict["violations"]) or "clothing surface")
                        + "). Consider regenerating."
                    )
                    logger.warning(
                        "IMAGE_GEN_MARK_VERIFY character_id=%s result=violation "
                        "violations=%s on_clothing=%s",
                        character_id, verdict["violations"], verdict["on_clothing"],
                    )
            else:
                mark_verify_meta = {
                    "mark_verify_skipped": verdict.get("skip_reason") or "unknown"
                }

    # Storage checkpoints. save_image() is the last unguarded step before the DB
    # write, and a failure there is indistinguishable from a provider failure in
    # the logs unless the boundary is marked on both sides — a START with no OK
    # localises the fault to storage without needing a traceback.
    #
    # BYTES_RECEIVED fires only when a provider actually returned bytes, so it
    # stays truthful. STORAGE_START/STORAGE_OK bracket BOTH branches: the
    # placeholder path writes a file too, and it is the path production takes
    # whenever no provider resolves — leaving it uninstrumented would blind
    # exactly the case where a provider is misconfigured in one environment only.
    #
    # Byte counts, ids and paths only — never prompt text or credentials.
    if png_bytes is not None:
        logger.info(
            "IMAGE_GEN_BYTES_RECEIVED character_id=%s provider=%s bytes=%d",
            character_id, actual_provider_name, len(png_bytes),
        )
        logger.info(
            "IMAGE_GEN_STORAGE_START character_id=%s source=provider_bytes bytes=%d object_storage=%s",
            character_id, len(png_bytes), settings.USE_OBJECT_STORAGE,
        )
        file_path = save_image(png_bytes)
    else:
        logger.info(
            "IMAGE_GEN_STORAGE_START character_id=%s source=placeholder bytes=0 object_storage=%s",
            character_id, settings.USE_OBJECT_STORAGE,
        )
        file_path = generate_placeholder_png(
            label=character.name,
            sublabel=params.prompt[:80],
            role="generated",
        )
        actual_provider_name = "stub"
        logger.info("IMAGE_GEN_STUB character_id=%s", character_id)

    logger.info(
        "IMAGE_GEN_STORAGE_OK character_id=%s file_path=%s",
        character_id, file_path,
    )

    # ── Cover composition retry (character-inclusive covers only) ──
    # One deterministic retry with an escalated cover prompt, still sourced
    # entirely from canon. Supersedes the first pass on success.
    cover_retry_attempted = False
    cover_retry_succeeded = False
    if (
        params.is_cover
        and params.include_character
        and canon is not None
        and provider is not None
        and png_bytes is not None
    ):
        cover_retry_attempted = True
        retry_prompt = compile_canon_prompt(
            canon,
            _COVER_RETRY_PROMPT + params.prompt.strip(),
            include_accessories=True,
        )
        if reference_notes:
            retry_prompt = retry_prompt + reference_notes
        cover_retry_png: bytes | None = None
        cover_multi_attempted = bool(ref_bytes and provider_supports_multi)
        if cover_multi_attempted:
            try:
                cover_retry_png = provider.generate_with_anchors(prompt=retry_prompt, anchor_images=ref_bytes)
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        # Same rule as the main path: one-reference grounding only when
        # multi-reference was never available for this provider.
        if cover_retry_png is None and ref_bytes and not cover_multi_attempted:
            try:
                cover_retry_png = provider.generate_grounded_image(prompt=retry_prompt, reference_image_bytes=ref_bytes[0])
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        # Same rule again: when references were selected, a reference-less cover
        # retry is weaker evidence than the router chose and must not replace
        # the first-pass image. Ref-less covers (no canon refs) are unaffected.
        if cover_retry_png is None and not ref_bytes:
            try:
                cover_retry_png = provider.generate_image(prompt=retry_prompt)
            except (ValueError, RuntimeError):
                pass
        if cover_retry_png is not None:
            file_path = save_image(cover_retry_png)
            png_bytes = cover_retry_png
            cover_retry_succeeded = True
            logger.info("cover_retry_succeeded character_id=%s", character_id)
        else:
            logger.info("cover_retry_failed_using_first_pass character_id=%s", character_id)

    # ── Reference audit: what was ACTUALLY sent, and what was not ─────
    manual_audit = [
        r.describe(sent=True, isolation=isolation_audit_by_id.get(r.image_id))
        for r in manual_sent
    ] + [
        r.describe(sent=False, reason="reference_budget_exceeded") for r in manual_dropped
    ]
    source = _refs_source(canon_count=canon_sent_count, manual_count=len(manual_sent))

    # ── Persist image record — SCENE_ONLY / COVER, never canon ────
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        # Model slug used for generation (populated for FLUX providers; None for others).
        "model": (lambda v: v if isinstance(v, str) else None)(
            getattr(provider, "model_name", None) if provider is not None else None
        ),
        "include_character": params.include_character,
        "character_id": character_id if params.include_character else None,
        "prompt": params.prompt,
        "is_cover": params.is_cover,
        # Identity OS: generated scenes are not canon.
        "scene_only": not params.is_cover,
        # Canon-contract diagnostics (replace legacy strict-identity metadata).
        # canon_used keeps its exact original meaning: "this generation was
        # compiled from locked canon". It is NOT a statement about the reference
        # payload — refs_source below is.
        "canon_used": using_canon,
        # canon_used=False has two very different causes and they must not read
        # the same in a diagnostic. False with canon_bypassed=False means "no
        # character was included in this generation"; False with
        # canon_bypassed=True means "a character WAS selected and its canon was
        # deliberately withheld as an input" — the Admin Creator contract. The
        # character still owns the row either way.
        "canon_bypassed": deliberate,
        "canon_bypass_reason": "deliberate_reference_mode" if deliberate else None,
        "refs_count": len(ref_bytes),
        "refs_deduped": refs_deduped,
        # Reference provenance (founder image workflow).
        "refs_source": source,
        "refs_budget": budget,
        "canon_refs_sent": canon_sent_count,
        # Canon references the router selected but the payload could not carry.
        # Always zero for an /images generation under the default budget, and the
        # measured cost of the deliberate cards when Admin Creator supplied them.
        "canon_refs_dropped": canon_dropped_count,
        "manual_refs_selected": len(manual_refs),
        "manual_refs_sent": len(manual_sent),
        "manual_refs_dropped": len(manual_dropped),
        "manual_refs": manual_audit,
        "reference_mode": ref_mode,
        "manual_ref_policy": _REF_META_POLICY[ref_mode],
        # Bounded well above a normal compiled prompt (_PROMPT_CAP is 2400) so
        # the stored value IS the prompt in every non-pathological case. The old
        # 400-char cut silently discarded most of it, and a real visual-QA
        # investigation had to replay the compiler to recover what was actually
        # sent. Hash included so a truncated or edited value is still comparable.
        "compiled_prompt": compiled_prompt[:_STORED_PROMPT_CHARS],
        "compiled_prompt_len": len(compiled_prompt),
        "compiled_prompt_sha8": hashlib.sha256(
            compiled_prompt.encode()).hexdigest()[:8],
    }
    if reference_notes:
        metadata["manual_reference_notes"] = reference_notes.strip()
    if prompt_diag:
        metadata["prompt_diagnostics"] = prompt_diag
    if params.include_character:
        metadata["multi_image_used"] = multi_image_used
        metadata["used_ref"] = used_ref
        metadata["cover_retry_attempted"] = cover_retry_attempted
        metadata["cover_retry_succeeded"] = cover_retry_succeeded
        if using_canon and scene_meta is not None:
            metadata.update(_routing_diagnostics(scene_meta))
        if face_verify_meta:
            metadata.update(face_verify_meta)
        if mark_verify_meta:
            metadata.update(mark_verify_meta)
        # Together AI URL-based ref diagnostics (option5 only).
        if together_response_mode != "not_applicable":
            metadata["together_response_mode"] = together_response_mode
            metadata["together_refs_sent"] = len(together_urls_sent)

        # When refs were loaded but not forwarded to the provider, record why so
        # admins can see the explicit reason rather than inferring from False flags.
        if ref_bytes and not multi_image_used and not used_ref and provider is not None:
            ref_support = ref_support_level(provider)
            if ref_support == "none":
                metadata["refs_not_used_reason"] = "provider_does_not_support_reference_input"
                metadata["refs_support_level"] = "none"
            elif ref_support == "url_required":
                metadata["refs_support_level"] = "url_required"
                if together_response_mode == "local_refs_only":
                    metadata["refs_not_used_reason"] = "all_refs_are_local_paths_not_accessible_by_provider"
                elif together_response_mode == "multi_url_failed":
                    metadata["refs_not_used_reason"] = "provider_multi_url_failed"
                else:
                    metadata["refs_not_used_reason"] = "url_based_refs_unavailable"

    # Beta provider-gating audit trail (empty unless a fallback occurred).
    metadata.update(provider_gate_meta)

    img = CharacterImage(
        character_id=character_id,
        # Owner, not requester. Both entry points to this pipeline go through
        # an owner-only guard with no admin bypass, so ``user`` IS the owner —
        # but ownership is the character's, and saying so keeps one rule across
        # every writer. The weekly quota still reads this column (B22).
        user_id=character.owner_id,
        # Identity OS: generated scenes default to SCENE_ONLY — promotion to
        # face/body canon must be explicit via the canon flow. A manual
        # reference NEVER changes this: hand-picking an image as evidence does
        # not promote it, and the output of doing so is still scene material.
        kind=ImageKindEnum.COVER if params.is_cover else ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=actual_provider_name,
        # A promptless Admin Creator generation would otherwise save a blank
        # summary, leaving an unidentifiable row in the founder's library. The
        # board states the operation, so the board names the row.
        prompt_summary=(
            params.prompt[:200]
            if params.prompt.strip()
            else describe_board_operation([r.role for r in manual_sent])[:200]
        ),
        metadata_json=metadata,
        file_path=file_path,
    )
    # DB checkpoints bracket the commit for the same reason as storage: a
    # START without an OK isolates a persistence fault (connection drop, pool
    # exhaustion, constraint) from everything upstream that already succeeded.
    logger.info(
        "IMAGE_GEN_DB_WRITE_START character_id=%s file_path=%s", character_id, file_path
    )
    db.add(img)
    db.commit()
    db.refresh(img)
    logger.info(
        "IMAGE_GEN_DB_WRITE_OK character_id=%s image_id=%s", character_id, img.id
    )

    logger.info(
        "image_generator_result image_id=%s character_id=%s provider=%s "
        "provider_option=%s include_character=%s canon_used=%s canon_bypassed=%s "
        "mode=%s refs=%d refs_source=%s manual_sent=%d manual_dropped=%d",
        img.id, character_id, actual_provider_name, effective_option,
        params.include_character, using_canon, deliberate, ref_mode,
        len(ref_bytes), source, len(manual_sent), len(manual_dropped),
    )

    summary = build_summary(
        refs_source=source,
        budget=budget,
        canon_refs_sent=canon_sent_count,
        manual_refs=manual_audit,
        manual_sent=len(manual_sent),
        manual_dropped=len(manual_dropped),
        refs_loaded=len(ref_bytes),
        provider=actual_provider_name,
        reference_mode=ref_mode,
        canon_dropped=canon_dropped_count,
        canon_bypassed=deliberate,
    )
    return img, summary


def build_summary(
    *,
    refs_source: str,
    budget: int,
    canon_refs_sent: int,
    manual_refs: list[dict[str, Any]],
    manual_sent: int,
    manual_dropped: int,
    refs_loaded: int,
    provider: str,
    reference_mode: str = REFERENCE_MODE_AUGMENT,
    canon_dropped: int = 0,
    canon_bypassed: bool = False,
) -> dict[str, Any]:
    """Safe, user-facing account of what reached the provider.

    Carries no prompt text, no URL and no credential — counts, ids and roles
    only. ``warning`` is populated ONLY when something the founder chose did not
    reach the provider, so the client can say so plainly instead of the founder
    discovering it by looking at the image.

    ``canon_bypassed`` records that canon was WITHHELD on purpose rather than
    simply absent, so a deliberate result is never mistaken for a canon-grounded
    one that happened to route nothing.

    The canon-displacement note below cannot fire while the bypass holds
    (deliberate generations carry no canon references to displace). It is kept
    as the reporting half of that safety net: if the bypass ever regressed, the
    founder would be told their cards had cost canon capacity rather than
    discovering it in the image.
    """
    summary: dict[str, Any] = {
        "refs_source": refs_source,
        "refs_budget": budget,
        "canon_refs_sent": canon_refs_sent,
        "canon_refs_dropped": canon_dropped,
        "canon_bypassed": canon_bypassed,
        "manual_refs_sent": manual_sent,
        "manual_refs_dropped": manual_dropped,
        "refs_loaded": refs_loaded,
        "provider": provider,
        "manual_refs": manual_refs,
        "reference_mode": reference_mode,
    }
    notes: list[str] = []
    if manual_dropped:
        notes.append(
            f"{manual_dropped} of your reference images could not be sent: this "
            f"character's canon already fills the {budget}-reference limit for "
            "this provider. Canon references are never dropped."
            if reference_mode == REFERENCE_MODE_AUGMENT
            else (
                f"{manual_dropped} of your reference cards could not be sent: this "
                f"provider accepts only {budget} reference images in one request."
            )
        )
    if canon_dropped and reference_mode == REFERENCE_MODE_DELIBERATE:
        notes.append(
            f"Your {manual_sent} selected reference "
            f"{'card' if manual_sent == 1 else 'cards'} took priority, so "
            f"{canon_dropped} lower-priority canon reference "
            f"{'image was' if canon_dropped == 1 else 'images were'} not sent. "
            "The character's locked canon description still governs identity."
        )
    if notes:
        summary["warning"] = " ".join(notes)
    return summary


def params_from_request(
    body: Any,
    *,
    is_admin: bool,
    is_founder: bool,
) -> GenerationParams:
    """Build :class:`GenerationParams` from a request model.

    ``is_admin``/``is_founder`` come from the authenticated account, never from
    the request body — the client cannot name its own entitlement.
    """
    return GenerationParams(
        prompt=body.prompt,
        include_character=bool(getattr(body, "include_character", False)),
        provider_option=getattr(body, "provider_option", "option2"),
        is_cover=bool(getattr(body, "is_cover", False)),
        reference_image_ids=list(getattr(body, "reference_image_ids", None) or []),
        reference_roles=list(getattr(body, "reference_roles", None) or []),
        # A request model that predates the field (or any caller that simply does
        # not set it) resolves to augment — the pre-existing policy.
        reference_mode=normalise_reference_mode(getattr(body, "reference_mode", None)),
        is_admin=is_admin,
        is_founder=is_founder,
    )


__all__ = [
    "GenerationParams",
    "MAX_MANUAL_REFERENCES",
    "build_summary",
    "params_from_request",
    "run_image_generation",
]

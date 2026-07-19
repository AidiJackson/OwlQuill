"""Simplified image generator endpoint with provider toggle (B17).

Replaces the mental model of 'scene generator' with a plain image generator:
  - Always tied to a character for ownership/auth
  - include_character controls whether identity references are injected
  - provider_option selects the backend provider (option1=OpenAI, option2=Google)

B18: Strict identity mode is automatically enabled when include_character=True.
  - Blocks silent fallback to plain generic generation or stub placeholder
  - Allows at most one retry with escalated wording before controlled failure

B19: Anchor-image conditioning.
  - Loads identity pack images (front, three-quarter, torso, full-body) from disk
  - Passes them as real provider inputs via generate_with_anchors when supported
  - Falls back to single-image grounded generation (face-ref crop) when not
  - Tightens the strict identity text wrapper to be short and punchy
"""
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import save_image, load_image_bytes
from app.models.user import User
from app.services.image_quota import check_weekly_quota
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.character_image import CharacterImageRead
from app.services.provider_capabilities import Capability, provider_supports, ref_support_level
from app.services.image_provider import (
    get_provider_for_option,
    get_fallback_provider,
    resolve_canon_provider_option,
)
from app.services.stub_image_generator import generate_placeholder_png
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services.canon_compiler import (
    compile_canon_prompt,
    has_any_canon_content,
)
from app.services.canon_service import load_face_canon
from app.services.face_verifier import verify_face_match, passes as _face_passes
from app.services.scene_router import route_canon_refs

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"

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


# ── Request schema ────────────────────────────────────────────────────


class ImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/image-generator/generate."""

    prompt: str = Field(..., min_length=1, max_length=800)
    include_character: bool = False
    # Beta: Google (option2) is the default Canon provider. OpenAI (option1),
    # FLUX Pro (option3), FLUX Max (option4), and Together FLUX.2 (option5) are
    # admin-only and fall back to Google for non-admins (enforced server-side).
    # FLUX options generate text-to-image only — refs are not forwarded.
    # Together (option5) supports URL-based refs when public HTTPS URLs are available.
    provider_option: Literal["option1", "option2", "option3", "option4", "option5", "option6"] = "option2"
    is_cover: bool = False  # When True, saves with kind=COVER for use as a character cover banner


# ── Closed-loop face verification helper ──────────────────────────────

# Escalated identity directive prepended on a verification-triggered retry.
_FACE_REGEN_PREFIX = (
    "CRITICAL IDENTITY MATCH: reproduce the exact same person as the reference "
    "images — identical face shape, jaw, nose, eye shape, brow, and bone "
    "structure. Do not drift toward a generic or different face. "
)


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
    if ref_bytes and provider_supports_multi:
        try:
            return provider.generate_with_anchors(prompt=prompt, anchor_images=ref_bytes)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            pass
    if ref_bytes:
        try:
            return provider.generate_grounded_image(prompt=prompt, reference_image_bytes=ref_bytes[0])
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            pass
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


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image with optional character identity and provider selection (B17-B19)",
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a single image using CharacterIdentityCanon as the only identity truth.

    Architecture (Identity OS — canon single source):
        Generate Images → CharacterIdentityCanon → canon_compiler → provider

    When include_character=True:
      - CharacterIdentityCanon is required. If missing or incomplete, returns a
        graceful 409 "Character canon incomplete".
      - The prompt is compiled by canon_compiler.compile_canon_prompt in strict
        order: face → body → permanent marks → requested accessories → scene →
        locked-canon clause. Removable accessories inject ONLY when their trigger
        keywords appear in the scene prompt.
      - Reference images are the locked face/body canon slots selected by the
        scene-aware reference router (route_canon_refs), which deterministically
        picks scene-relevant slots from the prompt and falls back to the static
        canonical ordering when the prompt is ambiguous. No identity_anchor_json,
        body_identity_json, or CharacterStyleElements are consulted as identity truth.

    When include_character=False, the user's prompt is used as-is (plain scene, no
    identity conditioning).

    Scene images always save as SCENE_ONLY (or COVER for is_cover); canon is never
    mutated here.

    provider_option: option1 → OpenAI | option2 → Google
    """
    # ── Auth + ownership ──────────────────────────────────────────
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to use this character.",
        )

    # ── B22: Weekly allowance check (admins bypass; deducted on success) ──
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Provider resolution + beta gating ──────────────────────────
    requested_option = body.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    # OpenAI (option1) is admin-only for beta; non-admins fall back to Google.
    effective_option, provider_gate_meta = resolve_canon_provider_option(
        requested_option, is_admin=bool(current_user.is_admin)
    )
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]
    if provider_gate_meta:
        logger.info(
            "IMAGE_GEN_PROVIDER_GATED character_id=%s user_id=%s requested=%s effective=%s reason=%s",
            character_id, current_user.id, requested_option, effective_option,
            provider_gate_meta.get("provider_fallback_reason"),
        )

    base_prompt = body.prompt.strip()

    # Cover mode: prepend banner-composition directives before the user's prompt.
    if body.is_cover:
        cover_block = _COVER_BANNER_PREFIX
        if body.include_character:
            cover_block += _COVER_CHARACTER_FRAMING
        base_prompt = cover_block + base_prompt

    # ── Identity truth: CharacterIdentityCanon ONLY ───────────────
    canon: CharacterIdentityCanon | None = None
    reference_urls: list[str] = []
    using_canon = False

    if body.include_character:
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
        )
        # P10: scene-aware reference routing replaces static ordering.
        # Route on the raw user scene text (not the cover-prefixed prompt).
        reference_urls, scene_meta = route_canon_refs(body.prompt, canon)
        using_canon = True
    else:
        compiled_prompt = base_prompt

    logger.info(
        "IMAGE_GEN_START character_id=%s include_character=%s using_canon=%s "
        "camera=%s routed=%s exposure=%s refs=%d prompt_len=%d prompt_preview=%r",
        character_id, body.include_character, using_canon,
        scene_meta.camera if using_canon else "n/a",
        scene_meta.routed if using_canon else False,
        scene_meta.exposure if using_canon else [],
        len(reference_urls), len(compiled_prompt), compiled_prompt[:120],
    )

    # ── Load reference image bytes (cap at 6) ─────────────────────
    ref_bytes: list[bytes] = []
    for url in reference_urls[:6]:
        try:
            b = load_image_bytes(url)
            ref_bytes.append(b)
            logger.info("IMAGE_GEN_REF_LOADED character_id=%s url=%s bytes=%d", character_id, url, len(b))
        except Exception as exc:
            logger.warning("IMAGE_GEN_REF_LOAD_FAILED character_id=%s url=%s error=%r", character_id, url, str(exc))

    # ── Resolve provider ──────────────────────────────────────────
    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError):
        logger.warning(
            "image_generator provider_unavailable option=%s provider=%s character_id=%s",
            effective_option, resolved_provider_name, character_id,
        )
        provider = None

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
    # TOGETHER_DIAG log entries record selected_refs/loaded_refs/provider_refs_sent/
    # provider_response_mode for benchmark diagnostics.
    together_urls_sent: list[str] = []
    together_response_mode: str = "not_applicable"

    if png_bytes is None and reference_urls and provider_supports(provider, Capability.URL_ANCHORS):
        public_urls = [u for u in reference_urls[:6] if u.startswith("https://")]
        local_refs = [u for u in reference_urls[:6] if not u.startswith("https://")]
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
    # failed so a canon generation can fail loudly instead of silently dropping
    # to a ref-less path. None until a ref-bearing attempt raises.
    ref_failure_reason: str | None = None
    if provider is not None and ref_bytes and provider_supports_multi:
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
            logger.info("IMAGE_GEN_MULTI_IMAGE_FAILED character_id=%s fallback=grounded reason=%r",
                        character_id, str(exc)[:200])

    if png_bytes is None and provider is not None and ref_bytes:
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

    # ── S24AD: block the ref-less fallback for canon generations ──────
    # When this is a canon generation (using_canon) with reference images
    # loaded, and a real provider's reference-bearing calls (multi-image AND
    # grounded) have all failed or been REFUSED (e.g. Gemini "google_refused_
    # image" on adult-adjacent prompts), DO NOT silently degrade to text-only /
    # FAL / stub. Those drop every identity reference and return a generic
    # person, not the character (the S24AC2 Summer-bikini failure). Fail loudly
    # so the caller can reword or route to Adult Studio. The ref-less fallbacks
    # below stay intact for genuine non-ref flows (include_character=False, no
    # refs available, or no provider configured → offline/stub path).
    if png_bytes is None and using_canon and ref_bytes and provider is not None:
        refused = bool(ref_failure_reason and "google_refused_image" in ref_failure_reason)
        logger.warning(
            "IMAGE_GEN_CANON_REFUSED_BLOCKED character_id=%s provider=%s model=%s "
            "refused=%s fallback_blocked=true reason=%r",
            character_id, resolved_provider_name,
            getattr(provider, "_model", getattr(provider, "model", "?")),
            refused, (ref_failure_reason or "")[:200],
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Canon provider declined this scene. "
                   "Try Adult Studio or reduce adult/explicit wording.",
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
        and body.include_character
        and not body.is_cover
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

    if png_bytes is not None:
        file_path = save_image(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=character.name,
            sublabel=body.prompt[:80],
            role="generated",
        )
        actual_provider_name = "stub"
        logger.info("IMAGE_GEN_STUB character_id=%s", character_id)

    # ── Cover composition retry (character-inclusive covers only) ──
    # One deterministic retry with an escalated cover prompt, still sourced
    # entirely from canon. Supersedes the first pass on success.
    cover_retry_attempted = False
    cover_retry_succeeded = False
    if body.is_cover and body.include_character and canon is not None and provider is not None and png_bytes is not None:
        cover_retry_attempted = True
        retry_prompt = compile_canon_prompt(
            canon,
            _COVER_RETRY_PROMPT + body.prompt.strip(),
            include_accessories=True,
        )
        cover_retry_png: bytes | None = None
        if ref_bytes and provider_supports_multi:
            try:
                cover_retry_png = provider.generate_with_anchors(prompt=retry_prompt, anchor_images=ref_bytes)
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        if cover_retry_png is None and ref_bytes:
            try:
                cover_retry_png = provider.generate_grounded_image(prompt=retry_prompt, reference_image_bytes=ref_bytes[0])
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        if cover_retry_png is None:
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

    # ── Persist image record — SCENE_ONLY / COVER, never canon ────
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        # Model slug used for generation (populated for FLUX providers; None for others).
        "model": (lambda v: v if isinstance(v, str) else None)(
            getattr(provider, "model_name", None) if provider is not None else None
        ),
        "include_character": body.include_character,
        "character_id": character_id if body.include_character else None,
        "prompt": body.prompt,
        "is_cover": body.is_cover,
        # Identity OS: generated scenes are not canon.
        "scene_only": not body.is_cover,
        # Canon-contract diagnostics (replace legacy strict-identity metadata).
        "canon_used": using_canon,
        "refs_count": len(ref_bytes),
        "compiled_prompt": compiled_prompt[:400],
    }
    if body.include_character:
        metadata["multi_image_used"] = multi_image_used
        metadata["used_ref"] = used_ref
        metadata["cover_retry_attempted"] = cover_retry_attempted
        metadata["cover_retry_succeeded"] = cover_retry_succeeded
        if face_verify_meta:
            metadata.update(face_verify_meta)
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
        user_id=current_user.id,  # B22: stamp for quota tracking
        # Identity OS: generated scenes default to SCENE_ONLY — promotion to
        # face/body canon must be explicit via the canon flow.
        kind=ImageKindEnum.COVER if body.is_cover else ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=actual_provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json=metadata,
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "image_generator_result image_id=%s character_id=%s provider=%s "
        "provider_option=%s include_character=%s canon_used=%s refs=%d",
        img.id, character_id, actual_provider_name, effective_option,
        body.include_character, using_canon, len(ref_bytes),
    )

    return CharacterImageRead.model_validate(img)

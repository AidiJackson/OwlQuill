"""Closed-loop face verification.

Scores a *generated* scene image against a character's locked canon face
reference and reports whether they depict the same person. This is the
measurement half of the consistency gate; the regeneration policy lives at the
call site (``image_generator.generate_image``).

Implementation uses the same OpenAI vision model already used for face
signatures / front-anchor validation — no new dependency, no face-embedding
model to ship. Everything here is best-effort: a missing API key, a parse
error, or any API failure returns ``ok=False`` with a skip reason, and callers
must treat that as "could not verify" (never as "failed verification") so the
gate degrades to a no-op rather than blocking generation.

SECURITY: no image bytes, prompt text, or API responses are logged.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_SKIP: dict[str, Any] = {"ok": False, "match": False, "similarity": 0.0, "skip_reason": ""}

_COMPARE_PROMPT = (
    "You are a strict identity-matching checker for AI-generated character art. "
    "The FIRST image is the canonical reference face. The SECOND image is a newly "
    "generated scene. Decide whether the SECOND image depicts the SAME individual "
    "as the FIRST — same bone structure, face shape, jaw, nose, eye shape, brow, "
    "and overall likeness. Ignore differences in expression, pose, camera angle, "
    "lighting, hairstyle, clothing, makeup, and background — judge identity only. "
    "Return ONLY a valid JSON object, no markdown, exactly: "
    '{"same_person":bool,"similarity":float,"reason":string}. '
    "similarity is 0.0-1.0 (1.0 = unmistakably the same person). "
    "Be conservative: if the facial structure differs, score low."
)


# ── Scorability (measurement only) ────────────────────────────────────
#
# Face similarity is only meaningful when there is enough face to compare.
# A back-facing shot or a distant full-body frame produces a low score for a
# reason that has nothing to do with identity, and scoring those as FAIL
# turns "insufficient evidence" into "wrong character" — which is what
# corrupted the first soak's face numbers.
#
# This is additive and OPT-IN: ``verify_face_match`` keeps its exact prompt
# and return contract by default, so the generation path is untouched. Only
# the measurement harness passes ``assess_visibility=True``.
_VISIBILITY_CLAUSE = (
    ' Additionally report "face_visible": true only if enough of the SECOND '
    "image's face is actually visible to judge identity — a face turned away "
    "from camera, obscured, or too small/blurred to read must be false. "
    'Return {"same_person":bool,"similarity":float,"face_visible":bool,"reason":string}.'
)

# Deterministic pre-check: the router already knows a back-facing scene, so a
# provably face-away prompt is ruled NOT_SCORABLE without spending a call.
def prompt_is_face_away(scene_prompt: str) -> bool:
    """True when the scene prompt itself places the face away from camera."""
    from app.services.scene_router import _BACK_SIGNALS

    return any(s in (scene_prompt or "").lower() for s in _BACK_SIGNALS)


def _b64_data_url(png_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}"


def verify_face_match(
    reference_png: bytes,
    candidate_png: bytes,
    *,
    assess_visibility: bool = False,
) -> dict[str, Any]:
    """Compare a candidate generated image against a reference face.

    Returns ``{ok, match, similarity, skip_reason}``:
      * ok=True with match/similarity when the comparison ran.
      * ok=False with a skip_reason when it could not run (no key / API error /
        parse error) — callers must treat this as "unverified", not "mismatch".
    """
    if not settings.OPENAI_API_KEY:
        return {**_SKIP, "skip_reason": "no_api_key"}
    if not reference_png or not candidate_png:
        return {**_SKIP, "skip_reason": "missing_image"}

    try:
        from openai import OpenAI  # local import keeps module importable without the dep

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text",
                         "text": _COMPARE_PROMPT + (_VISIBILITY_CLAUSE if assess_visibility else "")},
                        {"type": "image_url",
                         "image_url": {"url": _b64_data_url(reference_png), "detail": "low"}},
                        {"type": "image_url",
                         "image_url": {"url": _b64_data_url(candidate_png), "detail": "low"}},
                    ],
                }
            ],
            max_tokens=200,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines[1:] if not l.strip().startswith("```"))
        parsed = json.loads(raw)
        similarity = max(0.0, min(1.0, float(parsed.get("similarity", 0.0))))
        match = bool(parsed.get("same_person", False))
        logger.info("face_verify event=ok match=%s similarity=%.2f", match, similarity)
        verdict = {"ok": True, "match": match, "similarity": similarity, "skip_reason": ""}
        if assess_visibility:
            # Absent key → assume visible, so a model that ignores the clause
            # cannot silently mark everything unscorable.
            verdict["face_visible"] = bool(parsed.get("face_visible", True))
        return verdict
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("face_verify event=parse_error")
        return {**_SKIP, "skip_reason": "parse_error"}
    except Exception:
        logger.warning("face_verify event=api_error")
        return {**_SKIP, "skip_reason": "api_error"}


def passes(verdict: dict[str, Any], threshold: float) -> bool:
    """True when a verdict clears the bar, OR when it could not be evaluated.

    Unverifiable verdicts (ok=False) pass so the gate never blocks generation on
    its own infrastructure failing — it only acts on a *confident* mismatch.
    """
    if not verdict.get("ok"):
        return True
    return bool(verdict.get("match")) and float(verdict.get("similarity", 0.0)) >= threshold

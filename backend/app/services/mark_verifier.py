"""Permanent-mark placement verification (PERMANENT-MARK CANON sprint).

Detects GROSS permanent-mark violations in a generated image against the
canon's mark-location authority: tattoos on regions the canon says are clean
skin (invented neck/hand/face tattoos), and markings printed on top of
clothing. It deliberately does NOT try to judge design fidelity, side
correctness, or subtle placement drift — those are below the reliable
resolution of a vision-LLM check, and generation-time Canon grounding (the
routed reference cards + the compiler's clean-skin/occlusion clauses) remains
the primary defence for them.

Flag-only by design: a violation NEVER rejects or regenerates the image — it
writes a metadata warning so creators and diagnostics can see it. A checker
confident enough to gate output would need far lower false-positive rates
than a vision-LLM offers; a silent-drift detector that occasionally
over-reports is useful, one that discards good generations is not.

Best-effort like face_verifier: missing key / API error / parse error returns
ok=False with a skip_reason and callers treat it as "could not verify".

SECURITY: no image bytes, prompt text, or API responses are logged.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_SKIP: dict[str, Any] = {"ok": False, "violations": [], "skip_reason": ""}

# Region vocabulary shown to the checker — matches the canon group vocabulary
# so verdicts map straight back onto authority regions.
_CHECK_REGIONS = (
    "face", "neck", "torso", "back", "upper_arms", "forearms",
    "hands", "legs", "on_clothing",
)

_CHECK_PROMPT = (
    "You are a strict checker for AI-generated character art. Look at the image "
    "and report which of these body regions visibly show tattoos or permanent "
    "markings on the character: face, neck, torso, back, upper_arms, forearms, "
    "hands, legs. Additionally report on_clothing if any tattoo-like marking "
    "appears printed ON or THROUGH clothing fabric rather than on bare skin. "
    "Only report a region when you are confident; ignore jewellery, clothing "
    "patterns, shadows, and body hair. Return ONLY a valid JSON object, no "
    'markdown, exactly: {"marked_regions": [..], "on_clothing": bool}. '
    "marked_regions values must come from the list above (excluding on_clothing)."
)


def _b64_data_url(png_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}"


def verify_mark_regions(
    candidate_png: bytes,
    allowed_regions: frozenset[str] | set[str],
) -> dict[str, Any]:
    """Check a generated image for marks outside ``allowed_regions``.

    Returns ``{ok, violations, observed, on_clothing, skip_reason}``:
      * ok=True — the check ran; ``violations`` lists regions showing marks
        that the canon says are clean, and ``on_clothing`` reports fabric
        contamination (always a violation regardless of authority).
      * ok=False with skip_reason — could not run; callers must treat this as
        "unverified", never as "violated".
    """
    if not settings.OPENAI_API_KEY:
        return {**_SKIP, "skip_reason": "no_api_key"}
    if not candidate_png:
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
                        {"type": "text", "text": _CHECK_PROMPT},
                        # detail=high, unlike the face check: hand/knuckle and
                        # collar tattoos are small structures that low-detail
                        # tiling demonstrably misses (validated on the Davies
                        # legacy office image, which shows both).
                        {"type": "image_url",
                         "image_url": {"url": _b64_data_url(candidate_png), "detail": "high"}},
                    ],
                }
            ],
            max_tokens=150,
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines[1:] if not l.strip().startswith("```"))
        parsed = json.loads(raw)
        observed = [
            r for r in (parsed.get("marked_regions") or [])
            if isinstance(r, str) and r in _CHECK_REGIONS and r != "on_clothing"
        ]
        on_clothing = bool(parsed.get("on_clothing", False))
        violations = sorted(set(observed) - set(allowed_regions))
        logger.info(
            "mark_verify event=ok observed=%s violations=%s on_clothing=%s",
            observed, violations, on_clothing,
        )
        return {
            "ok": True,
            "observed": observed,
            "violations": violations,
            "on_clothing": on_clothing,
            "skip_reason": "",
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("mark_verify event=parse_error")
        return {**_SKIP, "skip_reason": "parse_error"}
    except Exception:
        logger.warning("mark_verify event=api_error")
        return {**_SKIP, "skip_reason": "api_error"}

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

_SKIP: dict[str, Any] = {
    "ok": False, "observed": [], "uncertain": [], "violations": [],
    "uncertain_violations": [], "on_clothing": False, "skip_reason": "",
}

# Region vocabulary shown to the checker — matches the canon group vocabulary
# so verdicts map straight back onto authority regions.
_CHECK_REGIONS = (
    "face", "neck", "torso", "back", "upper_arms", "forearms",
    "hands", "legs", "on_clothing",
)

# ── Anatomical boundary definitions ───────────────────────────────────
#
# The original prompt named the regions and defined NONE of them, so the
# model applied colloquial boundaries. That produced two reproducible
# misclassifications in the first soak, both at region borders:
#
#   * a sleeve covering the deltoid/shoulder cap was reported as "torso",
#     making a clean chest look like a canon violation;
#   * a sleeve ending at the wrist was reported as "hands", inventing a hand
#     violation on a character with no hand marks.
#
# Every region is now defined by its ANATOMICAL BORDERS, and the two borders
# that actually failed are stated twice — once as an inclusion and once as an
# explicit exclusion — because a boundary the model has to infer is a boundary
# it gets wrong. These are anatomy, not per-character coordinates: nothing here
# refers to any particular character, mark or image.
_REGION_DEFINITIONS: dict[str, str] = {
    "face": "the face and head only — forehead, cheeks, jaw, chin, temples, scalp.",
    "neck": "the neck: throat at the front, nape at the back, between jawline and collarbone. "
            "NOT the shoulders and NOT the upper chest below the collarbone.",
    "torso": "the TRUNK ONLY: chest/pectorals, sternum, abdomen, stomach, ribs, waist, flanks. "
             "The trunk ENDS at the shoulder joint. Ink on the deltoid, shoulder cap or the "
             "rounded top of the arm is NOT torso — that is upper_arms. A sleeve that wraps "
             "over the shoulder does NOT make the torso marked. Report torso ONLY if ink sits "
             "on the chest, abdomen or ribs themselves.",
    "back": "the back of the trunk: shoulder blades, spine, lower back. "
            "NOT the deltoid or the back of the arm.",
    "upper_arms": "shoulder cap/deltoid down to the elbow, including the rounded top of the "
                  "shoulder where a sleeve tattoo commonly begins.",
    "forearms": "elbow down to the WRIST. Ink that stops at or above the wrist crease is "
                "forearm. NOT the hand.",
    "hands": "the hand ITSELF, past the wrist crease: back of the hand (dorsum), palm, "
             "fingers, thumb, knuckles. Ink on the wrist or lower forearm that stops before "
             "the wrist crease is NOT hands — that is forearms. Report hands ONLY if ink is "
             "visibly on the hand or fingers themselves.",
    "legs": "thigh, knee, calf, shin, ankle, foot.",
}

_CHECK_PROMPT = (
    "You are a strict checker for AI-generated character art. Report which body "
    "regions visibly show tattoos or permanent skin markings on the character.\n\n"
    "Use these anatomical definitions exactly — they override any everyday sense "
    "of the words:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in _REGION_DEFINITIONS.items())
    + "\n\nAlso report on_clothing = true if a tattoo-like marking appears printed on, "
    "through or embroidered onto clothing fabric rather than sitting on bare skin.\n\n"
    "Rules:\n"
    "- Judge each region by the anatomical borders above, not by what looks nearby.\n"
    "- If ink crosses a border, assign it to the region the ink actually SITS on; a "
    "region counts as marked only if ink is on that region itself.\n"
    "- Put a region in \"uncertain\" instead of \"marked_regions\" when the ink is at a "
    "border, partly out of frame, or too small/blurred to be sure.\n"
    "- Ignore jewellery, watches, clothing patterns, shadows, muscle definition, "
    "veins and body hair. Skin shading is not ink.\n"
    "- Only report a region as marked when the region is actually VISIBLE (bare) in "
    "the image.\n\n"
    "Then answer these BORDER QUESTIONS separately and literally. They decide "
    "the two boundaries that are most often misjudged, so answer them from the "
    "pixels rather than from your region list:\n"
    "- hand_or_finger_ink: is there ink ON THE HAND ITSELF — back of the hand, "
    "palm, fingers, thumb or knuckles, PAST the wrist crease? A sleeve that "
    "ends at the wrist means false.\n"
    "- chest_or_abdomen_ink: is there ink on the CHEST, STERNUM, ABDOMEN or "
    "RIBS themselves? Ink only on the shoulder cap/deltoid means false.\n"
    "- bare_regions: which regions are visibly BARE SKIN (not covered by "
    "clothing, gloves, wraps or hair) in this image, whether or not they carry "
    "ink?\n\n"
    "Return ONLY a valid JSON object, no markdown, exactly: "
    '{"marked_regions": [..], "uncertain": [..], "bare_regions": [..], '
    '"hand_or_finger_ink": bool, "chest_or_abdomen_ink": bool, '
    '"on_clothing": bool}. '
    "Values in all lists must come from: "
    + ", ".join(r for r in _CHECK_REGIONS if r != "on_clothing") + "."
)

# A region whose membership is decided by a dedicated border question →
# the question that decides it. The free-form list is the loose reading; the
# direct binary is the discriminating one, and it wins. Defining the two
# borders that actually failed keeps this anatomy-general — there is nothing
# character-specific here.
_BORDER_GUARDS: dict[str, str] = {
    "hands": "hand_or_finger_ink",
    "torso": "chest_or_abdomen_ink",
}


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

        def _regions(key: str) -> list[str]:
            return [
                r for r in (parsed.get(key) or [])
                if isinstance(r, str) and r in _CHECK_REGIONS and r != "on_clothing"
            ]

        observed = _regions("marked_regions")
        # Border guards: a region claimed in the loose list but denied by its
        # dedicated border question is demoted to "uncertain" rather than
        # counted. This is what stops a sleeve ending at the wrist reading as
        # hand ink, and a deltoid sleeve reading as chest ink — the two
        # reproducible false positives from the first soak.
        demoted: list[str] = []
        for region, question in _BORDER_GUARDS.items():
            if region in observed and parsed.get(question) is False:
                observed.remove(region)
                demoted.append(region)
        # Border/blurred calls are reported but never counted as violations:
        # an uncertain reading is exactly what produced the false positives
        # this verifier is being corrected for. They surface for manual audit
        # instead of silently inflating the failure rate.
        uncertain = sorted(set(_regions("uncertain") + demoted) - set(observed))
        # Regions visibly bare. A region the image does not show bare cannot
        # testify either way: a boxer with wrapped hands is not a canon
        # violation, and counting it as a missing mark measures the harness,
        # not the generator. Absent key → treat all as bare (never invent
        # coverage that would hide a genuine failure).
        bare = _regions("bare_regions") if "bare_regions" in parsed else list(_CHECK_REGIONS)
        on_clothing = bool(parsed.get("on_clothing", False))
        violations = sorted(set(observed) - set(allowed_regions))
        uncertain_violations = sorted(set(uncertain) - set(allowed_regions))
        logger.info(
            "mark_verify event=ok observed=%s violations=%s uncertain=%s "
            "demoted=%s on_clothing=%s",
            observed, violations, uncertain, demoted, on_clothing,
        )
        return {
            "ok": True,
            "observed": observed,
            "uncertain": uncertain,
            "demoted": demoted,
            "bare_regions": bare,
            "violations": violations,
            "uncertain_violations": uncertain_violations,
            "on_clothing": on_clothing,
            "skip_reason": "",
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("mark_verify event=parse_error")
        return {**_SKIP, "skip_reason": "parse_error"}
    except Exception:
        logger.warning("mark_verify event=api_error")
        return {**_SKIP, "skip_reason": "api_error"}

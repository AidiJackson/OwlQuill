"""Identity pack front-anchor validator (B6).

Uses OpenAI Vision to verify that a generated image is a passport-style
headshot before it ever reaches the user.  Returns structured compliance
fields.

SECURITY: No prompt text, image data, or API keys are written to logs.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Demand strict JSON — no markdown, no explanations.
_VALIDATION_PROMPT = (
    "You are a strict compliance checker for AI-generated identity card images. "
    "Analyse the image and return ONLY a valid JSON object — no markdown, no extra text. "
    "Use exactly this structure:\n"
    '{"is_passport_headshot":bool,"has_hands_or_props":bool,'
    '"is_full_body_or_seated":bool,"background_is_neutral":bool,"confidence":float}\n'
    "Definitions:\n"
    "- is_passport_headshot: true ONLY if head-and-shoulders only (cropped ~mid-chest), "
    "face straight to camera, single person, standard portrait orientation.\n"
    "- has_hands_or_props: true if hands, held objects, weapons, or prominent props are visible.\n"
    "- is_full_body_or_seated: true if full body (head to near-foot) is shown, or subject is "
    "seated/crouching/lying.\n"
    "- background_is_neutral: true if background is plain, solid, simple gradient, or clean "
    "studio backdrop — no busy scenes or outdoor environments.\n"
    "- confidence: 0.0-1.0 reflecting overall certainty.\n"
    "Be strict and conservative; if uncertain err toward non-compliant."
)

_FAIL_TEMPLATE: dict[str, Any] = {
    "ok": False,
    "is_passport_headshot": False,
    "has_hands_or_props": False,
    "is_full_body_or_seated": False,
    "background_is_neutral": False,
    "confidence": 0.0,
    "fail_reason": "",
}


def validate_front_anchor_png(png_bytes: bytes) -> dict[str, Any]:
    """Validate that *png_bytes* is a passport-style headshot.

    Returns a dict:
    {
        "ok": bool,
        "is_passport_headshot": bool,
        "has_hands_or_props": bool,
        "is_full_body_or_seated": bool,
        "background_is_neutral": bool,
        "confidence": float,
        "fail_reason": str,
    }

    When OPENAI_API_KEY is absent the function returns ok=True (skip-through)
    so callers in keyless environments (tests, stub mode) are unaffected.
    No prompt text, image data, or keys are written to logs.
    """
    if not settings.OPENAI_API_KEY:
        # No key configured — let the image pass through silently.
        logger.debug("identity_front_validator skipped reason=no_api_key")
        return {
            "ok": True,
            "is_passport_headshot": True,
            "has_hands_or_props": False,
            "is_full_body_or_seated": False,
            "background_is_neutral": True,
            "confidence": 1.0,
            "fail_reason": "no_api_key_skip",
        }

    try:
        from openai import OpenAI  # local import keeps module importable without key

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        response = client.chat.completions.create(
            model=settings.OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VALIDATION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "low"},
                        },
                    ],
                }
            ],
            max_tokens=256,
            temperature=0,
        )

        raw = response.choices[0].message.content or ""
        cleaned = raw.strip()
        # Strip markdown fences if the model adds them despite instructions
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines[1:] if not line.strip().startswith("```")
            )

        parsed = json.loads(cleaned)

        is_passport = bool(parsed.get("is_passport_headshot", False))
        has_hands = bool(parsed.get("has_hands_or_props", False))
        is_full_body = bool(parsed.get("is_full_body_or_seated", False))
        bg_neutral = bool(parsed.get("background_is_neutral", True))
        confidence = float(parsed.get("confidence", 0.5))

        overall_ok = is_passport and not has_hands and not is_full_body and bg_neutral

        fail_reason = ""
        if not overall_ok:
            reasons: list[str] = []
            if not is_passport:
                reasons.append("not_headshot")
            if has_hands:
                reasons.append("hands_or_props")
            if is_full_body:
                reasons.append("full_body_or_seated")
            if not bg_neutral:
                reasons.append("busy_background")
            fail_reason = "|".join(reasons) if reasons else "unknown"

        return {
            "ok": overall_ok,
            "is_passport_headshot": is_passport,
            "has_hands_or_props": has_hands,
            "is_full_body_or_seated": is_full_body,
            "background_is_neutral": bg_neutral,
            "confidence": confidence,
            "fail_reason": fail_reason,
        }

    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("identity_front_validator event=parse_error")
        return {**_FAIL_TEMPLATE, "fail_reason": "vision_parse_error"}
    except Exception:
        # Catches OpenAIError and any other unexpected failures without leaking details
        logger.warning("identity_front_validator event=api_error")
        return {**_FAIL_TEMPLATE, "fail_reason": "vision_api_error"}

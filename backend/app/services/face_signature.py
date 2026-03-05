"""Face signature extractor using OpenAI Vision.

Derives a compact, stable textual description of immutable facial traits from
a square face-crop image.  The result is stored in identity_anchor_json so
scene generation prompts can inject it as a canonical identity anchor.

SECURITY: Image bytes, base64 data, and API responses are NEVER written to
logs.  Only structured outcome flags and char counts are logged.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Max signature length stored / injected into prompts.
_SIG_MAX_CHARS = 220

# Vision prompt — strict JSON only, no prose, no markdown.
_SIGNATURE_PROMPT = (
    "You are extracting a stable facial identity signature from a square face crop. "
    "Return JSON ONLY — no markdown, no extra text. "
    "Use exactly this structure: {\"signature\": str, \"confidence\": float}\n"
    "signature: <=220 chars. Describe ONLY immutable facial traits: face shape, jaw, "
    "brow shape, eye spacing/shape, nose, lips, cheekbones, facial hair (if present), "
    "distinctive marks. No clothing, no lighting, no mood, no background. No gender "
    "guessing. Start with 'FACE_SIG:'. "
    "Example: \"FACE_SIG: square jaw, high cheekbones, straight thick brows, "
    "deep-set almond eyes (wide-set), medium straight nose, defined cupid's bow, "
    "faint chin cleft, small mole left cheek\"\n"
    "confidence: 0.0-1.0 reflecting certainty about the facial traits."
)

_SKIP_RESULT: dict[str, Any] = {
    "ok": False,
    "signature": "",
    "confidence": 0.0,
    "skip_reason": "no_api_key",
}


def build_face_signature_from_png(png_bytes: bytes) -> dict[str, Any]:
    """Derive a compact face-signature string from a PNG face crop.

    Returns a dict:
    {
        "ok": bool,
        "signature": str,   # ≤220 chars; empty on failure
        "confidence": float,
        "skip_reason": str, # non-empty only when ok=False
    }

    When OPENAI_API_KEY is absent the function returns ok=False immediately
    without raising — callers must never treat a missing signature as fatal.
    No image data, prompt text, or API responses are written to logs.
    """
    if not settings.OPENAI_API_KEY:
        logger.debug("face_signature skipped reason=no_api_key")
        return {**_SKIP_RESULT, "skip_reason": "no_api_key"}

    try:
        from openai import OpenAI  # local import — keeps module importable without key

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        response = client.chat.completions.create(
            model=settings.OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _SIGNATURE_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "low"},
                        },
                    ],
                }
            ],
            max_tokens=300,
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
        signature = str(parsed.get("signature", "")).strip()
        confidence = float(parsed.get("confidence", 0.5))

        # Trim to max allowed
        if len(signature) > _SIG_MAX_CHARS:
            signature = signature[:_SIG_MAX_CHARS]

        if not signature:
            logger.warning("face_signature event=empty_signature")
            return {"ok": False, "signature": "", "confidence": 0.0, "skip_reason": "empty_signature"}

        logger.info(
            "face_signature event=ok sig_chars=%d confidence=%.2f",
            len(signature), confidence,
        )
        return {"ok": True, "signature": signature, "confidence": confidence, "skip_reason": ""}

    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("face_signature event=parse_error")
        return {"ok": False, "signature": "", "confidence": 0.0, "skip_reason": "parse_error"}
    except Exception:
        # Catches OpenAIError and any unexpected failures without leaking details
        logger.warning("face_signature event=api_error")
        return {"ok": False, "signature": "", "confidence": 0.0, "skip_reason": "api_error"}

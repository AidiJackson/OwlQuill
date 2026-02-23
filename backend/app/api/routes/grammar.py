"""Grammar-check endpoint powered by LanguageTool.

Accepts plain text and returns normalised grammar/spelling matches.

Manual test (requires a running server):

    curl -s -X POST http://localhost:8000/api/grammar/check \
      -H "Content-Type: application/json" \
      -d '{"text": "She go to the store yesterday.", "language": "en-US"}' | python3 -m json.tool
"""
import logging

import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.grammar import (
    GrammarCheckRequest,
    GrammarCheckResponse,
    GrammarMatchSchema,
    GrammarReplacementSchema,
    GrammarRuleSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_TEXT_LENGTH = 20_000
_REQUEST_TIMEOUT = 8.0  # seconds


@router.post("/check", response_model=GrammarCheckResponse)
async def grammar_check(request: GrammarCheckRequest) -> GrammarCheckResponse:
    """Check text for grammar and spelling issues via LanguageTool.

    Returns a normalised list of matches with offset, length, message,
    rule metadata, and suggested replacements.
    """
    text = request.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty")

    if len(text) > _MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"text exceeds maximum length of {_MAX_TEXT_LENGTH} characters",
        )

    language = (request.language or "en-US").strip() or "en-US"
    lt_url = settings.LANGUAGETOOL_URL.rstrip("/") + "/check"

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                lt_url,
                data={"text": text, "language": language},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        logger.warning("LanguageTool request timed out (url=%s)", lt_url)
        raise HTTPException(status_code=504, detail="Grammar service timed out")
    except httpx.HTTPStatusError as exc:
        logger.warning("LanguageTool returned %s", exc.response.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"Grammar service returned an error ({exc.response.status_code})",
        )
    except httpx.RequestError as exc:
        logger.warning("LanguageTool connection error: %s", exc)
        raise HTTPException(status_code=502, detail="Grammar service unavailable")

    raw = response.json()

    matches: list[GrammarMatchSchema] = []
    for m in raw.get("matches", []):
        raw_rule = m.get("rule", {})
        raw_cat = raw_rule.get("category", {})
        rule = GrammarRuleSchema(
            id=raw_rule.get("id", ""),
            description=raw_rule.get("description") or None,
            issueType=raw_rule.get("issueType") or None,
            category=raw_cat.get("name") if isinstance(raw_cat, dict) else None,
        )
        replacements = [
            GrammarReplacementSchema(value=r["value"])
            for r in m.get("replacements", [])[:5]  # cap at 5 suggestions
            if r.get("value")
        ]
        matches.append(
            GrammarMatchSchema(
                offset=m.get("offset", 0),
                length=m.get("length", 0),
                message=m.get("message", ""),
                shortMessage=m.get("shortMessage") or None,
                rule=rule,
                replacements=replacements,
            )
        )

    detected_language = raw.get("language", {})
    if isinstance(detected_language, dict):
        language_code = detected_language.get("code", language)
    else:
        language_code = language

    return GrammarCheckResponse(language=language_code, matches=matches)

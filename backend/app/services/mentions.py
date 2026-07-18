"""Mention parsing and resolution service."""
import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.character import Character, VisibilityEnum

_MENTION_RE = re.compile(r"@([A-Za-z0-9_]+)")
_MAX_MENTIONS = 20


def parse_mention_texts(text: str) -> list[str]:
    """Extract unique @mention strings from text (max 20, preserving first-seen order)."""
    seen: set[str] = set()
    result: list[str] = []
    for match in _MENTION_RE.finditer(text):
        mention = f"@{match.group(1)}"
        key = mention.lower()
        if key not in seen:
            seen.add(key)
            result.append(mention)
        if len(result) >= _MAX_MENTIONS:
            break
    return result


def resolve_mentions(mention_texts: list[str], db: Session) -> list[dict[str, Any]]:
    """Resolve a list of @mention strings to character records.

    Sprint 33 (identity-first): mentions resolve to PUBLIC CHARACTERS ONLY.
    Account usernames are private infrastructure — an @mention matching a
    username stays unresolved (no link, and no confirmation that such an
    account exists).

    Returns a list of dicts with keys:
        mention_text, target_type, target_id,
        mentioned_user_id, mentioned_character_id,
        display_name, url
    """
    results: list[dict[str, Any]] = []
    for mention_text in mention_texts:
        handle = mention_text.lstrip("@")

        # Public character only — accounts are never mention targets
        char = (
            db.query(Character)
            .filter(
                func.lower(Character.name) == handle.lower(),
                Character.visibility == VisibilityEnum.PUBLIC,
            )
            .first()
        )
        if char:
            results.append({
                "mention_text": mention_text,
                "target_type": "character",
                "target_id": char.id,
                "mentioned_user_id": None,
                "mentioned_character_id": char.id,
                "display_name": char.name,
                "url": f"/characters/{char.id}",
            })
            continue

        # Unresolved
        results.append({
            "mention_text": mention_text,
            "target_type": "unresolved",
            "target_id": None,
            "mentioned_user_id": None,
            "mentioned_character_id": None,
            "display_name": handle,
            "url": "",
        })

    return results

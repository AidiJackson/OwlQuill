"""Transparent prompt normalisation for character image generation.

Soft-rewrites prompts so they pass image-model moderation without
changing user intent.  Two tiers:

- ``normalize_prompt``  – gentle synonym swap (first attempt).
- ``normalize_prompt_strict`` – aggressive strip of outfit/body words (retry).

A safety prefix is also exported for callers to prepend.
"""

import re
from typing import Tuple

# ── Soft replacements (preserve intent, swap trigger words) ──────────

_SOFT_REPLACEMENTS: Tuple[Tuple[re.Pattern, str], ...] = (
    # attitude / tone
    (re.compile(r"\bsexy\b", re.I), "confident"),
    (re.compile(r"\bsensual\b", re.I), "confident"),
    (re.compile(r"\bprovocative\b", re.I), "bold"),
    (re.compile(r"\berotic\b", re.I), "romantic"),
    (re.compile(r"\bsultry\b", re.I), "intense"),
    # clothing
    (re.compile(r"\btight\b", re.I), "fitted"),
    (re.compile(r"\bskintight\b", re.I), "form-fitting"),
    (re.compile(r"\bstrappy\b", re.I), "sleek"),
    (re.compile(r"\brevealing\b", re.I), "stylish"),
    (re.compile(r"\blingerie\b", re.I), "fashion"),
    (re.compile(r"\bbikini\b", re.I), "swimsuit"),
    (re.compile(r"\bunderwear\b", re.I), "base layer"),
    (re.compile(r"\bsee-through\b", re.I), "lightweight"),
    # body
    (re.compile(r"\bfull lips\b", re.I), "defined lips"),
    (re.compile(r"\bcleavage\b", re.I), "neckline"),
    (re.compile(r"\bbusty\b", re.I), "curvy"),
    # explicit — strip entirely
    (re.compile(r"\bnude\b", re.I), ""),
    (re.compile(r"\btopless\b", re.I), ""),
)

# ── Strict-mode strip list (outfit / body words removed entirely) ────

_STRICT_STRIP: re.Pattern = re.compile(
    r"\b(?:"
    r"dress|skirt|lingerie|bikini|swimsuit|thong|bra|panties|"
    r"cleavage|busty|curvy|neckline|corset|stockings|garter|"
    r"miniskirt|crop top|halter|bodysuit|teddy|negligee|"
    r"fitted|form-fitting|sleek|stylish|fashion|base layer|lightweight"
    r")\b",
    re.I,
)

# ── Public constant — callers prepend this to generation prompts ─────

SAFE_VISUAL_PREFIX = (
    "adult (mid-20s+), fully clothed, non-explicit fashion portrait, non-nude"
)

# ── Helpers ──────────────────────────────────────────────────────────

def _collapse(text: str) -> str:
    """Collapse multiple spaces / stray commas and trim."""
    text = re.sub(r"(\s*,\s*)+", ", ", text)   # dedupe commas
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip().strip(",").strip()


def normalize_prompt(prompt: str) -> str:
    """Soft-normalise a user vibe prompt (first-attempt tier).

    Swaps trigger words for safe synonyms while keeping intent.
    """
    if not prompt:
        return prompt

    result = prompt
    for pattern, repl in _SOFT_REPLACEMENTS:
        result = pattern.sub(repl, result)

    if "adult" not in result.lower():
        result = "adult, mid-20s+, " + result

    return _collapse(result)


def normalize_prompt_strict(prompt: str) -> str:
    """Strict normalisation (retry tier after moderation block).

    Applies soft replacements first, then strips all outfit / body
    descriptor words, keeping only identity essentials (age, hair,
    eyes, skin tone, build, face features).
    """
    if not prompt:
        return prompt

    # apply soft pass first
    result = normalize_prompt(prompt)

    # strip outfit / body words entirely
    result = _STRICT_STRIP.sub("", result)

    return _collapse(result)

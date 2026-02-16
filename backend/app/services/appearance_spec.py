"""Appearance-spec rewrite pipeline for safe character image generation.

Transparently rewrites user vibe prompts into neutral, fashion-focused
appearance specifications that pass image-model moderation.

Public API:
- ``build_appearance_spec(raw_vibe, conservative=False, failsafe=False)``
- ``build_generation_prompt(appearance_spec, traits, shot_desc)``
"""

import hashlib
import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)

# ── Blocked terms (hard reject) ─────────────────────────────────────

_BLOCKED_EXPLICIT: re.Pattern = re.compile(
    r"\b(?:"
    r"nude|naked|topless|nsfw|porn|xxx|hentai|"
    r"see[- ]?through|wet t-?shirt|spread legs|explicit|"
    r"genitals?|vagina|penis|anus|nipples?"
    r")\b",
    re.I,
)

_BLOCKED_MINOR: re.Pattern = re.compile(
    r"\b(?:"
    r"teen(?:age(?:r)?)?|child|kid|minor|underage|"
    r"schoolgirl|schoolboy|loli|shota|"
    r"preteen|pre-teen|infant|toddler|juvenile"
    r")\b",
    re.I,
)

# Also block if user specifies an age under 21
_AGE_PATTERN: re.Pattern = re.compile(
    r"\b(\d{1,2})\s*(?:yr|year|yo|y/?o)s?\s*(?:old)?\b",
    re.I,
)

# ── Soft synonym replacements ────────────────────────────────────────

_SOFT_REPLACEMENTS: Tuple[Tuple[re.Pattern, str], ...] = (
    # attitude / tone
    (re.compile(r"\bsexy\b", re.I), "confident"),
    (re.compile(r"\bhot\b", re.I), "glamorous"),
    (re.compile(r"\bseductive\b", re.I), "stylish"),
    (re.compile(r"\bsensual\b", re.I), "confident"),
    (re.compile(r"\bprovocative\b", re.I), "bold"),
    (re.compile(r"\berotic\b", re.I), "glamorous"),
    (re.compile(r"\bsultry\b", re.I), "intense"),
    # clothing
    (re.compile(r"\btight\b", re.I), "fitted"),
    (re.compile(r"\bskintight\b", re.I), "form-fitting"),
    (re.compile(r"\bstrappy\b", re.I), "sleek"),
    (re.compile(r"\brevealing\b", re.I), "stylish"),
    (re.compile(r"\blingerie\b", re.I), "eveningwear"),
    (re.compile(r"\bbikini\b", re.I), "two-piece swimsuit"),
    (re.compile(r"\bunderwear\b", re.I), "swimwear"),
    (re.compile(r"\bbra\b", re.I), "swimwear top"),
    (re.compile(r"\bpanties\b", re.I), "swimwear"),
    (re.compile(r"\bthong\b", re.I), "swimwear"),
    (re.compile(r"\bsee-through\b", re.I), "lightweight"),
    # body / model cluster
    (re.compile(r"\bmodel[\s-]*thin\b", re.I), "model-like"),
    (re.compile(r"\bthin nose\b", re.I), "slender nose"),
    (re.compile(r"\bfull lips\b", re.I), "defined lips"),
    (re.compile(r"\bcleavage\b", re.I), "neckline"),
    (re.compile(r"\bbusty\b", re.I), "curvy"),
)

# ── Conservative-mode strip list (physical features only) ────────────

_CONSERVATIVE_STRIP: re.Pattern = re.compile(
    r"\b(?:"
    r"dress|skirt|gown|corset|stockings|garter|"
    r"miniskirt|crop top|halter|bodysuit|teddy|negligee|"
    r"eveningwear|swimsuit|swimwear|two-piece|"
    r"fitted|form-fitting|sleek|stylish|fashion|"
    r"lightweight|bold|glamorous|confident|intense|"
    r"curvy|neckline"
    r")\b",
    re.I,
)

# ── Ethnicity-coded parentheticals ───────────────────────────────────

_ETHNICITY_PARENS: re.Pattern = re.compile(
    r"\(\s*(?:white|black|asian|hispanic|latino|latina|"
    r"caucasian|african|indian|middle eastern|european|"
    r"american|british|irish|italian|french|german|"
    r"japanese|chinese|korean|mexican|brazilian|"
    r"mixed race|biracial|multiracial)"
    r"[^)]*\)",
    re.I,
)

# ── Standalone ethnicity phrases (not in parentheses) ────────────────

_ETHNICITY_STANDALONE: re.Pattern = re.compile(
    r"\b(?:white|black|asian|hispanic|latino|latina|caucasian|african|"
    r"european|middle eastern|biracial|multiracial|mixed race)"
    r"\s+"
    r"(?:american|british|irish|italian|french|german|canadian|australian|"
    r"european|person|woman|man|girl|boy|lady|guy|male|female)\b",
    re.I,
)

# ── Height patterns (e.g. 5'9, 5'9", 5 foot 9, 6'2 height) ─────────

_HEIGHT_PATTERN: re.Pattern = re.compile(
    r"\b\d['′]\s*\d{1,2}[\"″]?\s*(?:height|tall|in height)?\b"
    r"|\b\d\s*(?:foot|feet|ft)\s*\d{1,2}\s*(?:inches?|in)?\s*(?:height|tall|in height)?\b",
    re.I,
)

# ── Failsafe-mode: keep only identity-core features ─────────────────

_FAILSAFE_KEEP: re.Pattern = re.compile(
    r"\b(?:"
    # hair descriptors
    r"(?:(?:long|short|medium|curly|straight|wavy|thick|thin)\s+)?"
    r"(?:brunette|blonde|auburn|redhead|black|brown|silver|gray|grey|"
    r"red|platinum|strawberry|golden|dark|light|sandy|chestnut|copper|"
    r"ginger|raven|jet[- ]?black|ash[- ]?blonde|honey)"
    r"(?:\s+hair)?"
    r"|"
    # eye descriptors
    r"(?:hazel|blue|green|brown|amber|gray|grey|dark|light|emerald|"
    r"violet|sapphire|golden|honey|chestnut|olive)"
    r"\s+eyes?"
    r"|"
    # general skin tones
    r"(?:tanned|fair|olive|dark|light|pale|brown|golden|warm|cool|"
    r"sun-kissed|bronze|porcelain|ivory|peach|caramel|ebony|mahogany)"
    r"\s+skin"
    r"|"
    # simple outfits
    r"(?:black|white|red|blue|green|elegant|simple|casual)\s+"
    r"(?:dress|suit|shirt|blouse|jacket|coat|sweater|top|outfit)"
    r"|"
    r"swimwear|two-piece swimsuit|swimsuit"
    r")\b",
    re.I,
)

# ── Safety constants ─────────────────────────────────────────────────

_SAFETY_PREFIX = "adult, fully clothed, non-explicit, fashion portrait, tasteful"
_ADULT_ANCHOR = "adult, mid-20s, "


# ── Helpers ──────────────────────────────────────────────────────────

def _collapse(text: str) -> str:
    """Collapse multiple spaces / stray commas and trim."""
    text = re.sub(r"(\s*,\s*){2,}", ", ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip().strip(",").strip()


def _prompt_hash(text: str) -> str:
    """Short hash for logging (no full user text stored)."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# ── Public API ───────────────────────────────────────────────────────

class PromptBlockedError(ValueError):
    """Raised when a prompt contains terms that cannot be rewritten."""

    def __init__(self, reason: str, friendly_message: str) -> None:
        self.reason = reason
        self.friendly_message = friendly_message
        super().__init__(friendly_message)


def build_appearance_spec(
    raw_vibe: str,
    *,
    conservative: bool = False,
    failsafe: bool = False,
    request_id: str = "",
) -> tuple[str, dict]:
    """Rewrite a raw user vibe string into a safe appearance specification.

    Modes:
        - Default: soft synonym rewrites + ethnicity stripping.
        - conservative=True: additionally strips outfit/body words.
        - failsafe=True: aggressively strips everything except identity
          core (hair, eye colour, skin tone, simple outfit). Always
          returns a short, safe spec. Implies conservative.

    Returns:
        (appearance_spec, meta) where meta contains rewrite diagnostics.

    Raises:
        PromptBlockedError: If the prompt contains explicit or minor content.
    """
    if not raw_vibe or not raw_vibe.strip():
        return "", {"did_rewrite": False, "reasons": [], "original_len": 0, "final_len": 0}

    reasons: list[str] = []
    result = raw_vibe

    # ── Hard blocks ──────────────────────────────────────────────
    if _BLOCKED_EXPLICIT.search(result):
        logger.warning(
            "prompt_blocked request_id=%s reason=explicit hash=%s",
            request_id, _prompt_hash(raw_vibe),
        )
        raise PromptBlockedError(
            reason="explicit_content",
            friendly_message=(
                "Some terms in your description aren't supported for image generation. "
                "Outfits like swimsuits and fitted dresses are fine — "
                "just remove any explicit or nudity-related words."
            ),
        )

    if _BLOCKED_MINOR.search(result):
        logger.warning(
            "prompt_blocked request_id=%s reason=minor hash=%s",
            request_id, _prompt_hash(raw_vibe),
        )
        raise PromptBlockedError(
            reason="minor_content",
            friendly_message=(
                "Character descriptions must be for adults (21+). "
                "Please update the age or remove age-related terms and try again."
            ),
        )

    # Check explicit age < 21
    for match in _AGE_PATTERN.finditer(result):
        age = int(match.group(1))
        if age < 21:
            logger.warning(
                "prompt_blocked request_id=%s reason=underage_age(%d) hash=%s",
                request_id, age, _prompt_hash(raw_vibe),
            )
            raise PromptBlockedError(
                reason="underage_age",
                friendly_message=(
                    "Character descriptions must be for adults (21+). "
                    "Please update the age and try again."
                ),
            )

    # ── Strip ethnicity-coded parentheticals ─────────────────────
    stripped = _ETHNICITY_PARENS.sub("", result)
    if stripped != result:
        reasons.append("ethnicity_parenthetical_removed")
        result = stripped

    # ── Strip standalone ethnicity phrases ────────────────────────
    stripped = _ETHNICITY_STANDALONE.sub("", result)
    if stripped != result:
        reasons.append("ethnicity_standalone_removed")
        result = stripped

    # ── Strip height patterns ────────────────────────────────────
    stripped = _HEIGHT_PATTERN.sub("", result)
    if stripped != result:
        reasons.append("height_removed")
        result = stripped

    # ── Soft synonym replacements ────────────────────────────────
    for pattern, repl in _SOFT_REPLACEMENTS:
        new_result = pattern.sub(repl, result)
        if new_result != result:
            reasons.append(f"rewrite:{pattern.pattern}")
            result = new_result

    # ── Conservative mode: strip outfit/body words entirely ──────
    if conservative or failsafe:
        stripped = _CONSERVATIVE_STRIP.sub("", result)
        if stripped != result:
            reasons.append("conservative_strip")
            result = stripped

    # ── Failsafe mode: keep only identity-core features ──────────
    if failsafe:
        kept = _FAILSAFE_KEEP.findall(result)
        if kept:
            result = ", ".join(kept)
        else:
            # Nothing recognisable — fall back to minimal spec
            result = ""
        reasons.append("failsafe_extract")

    # ── Ensure adult anchor ──────────────────────────────────────
    if "adult" not in result.lower():
        result = _ADULT_ANCHOR + result
        reasons.append("adult_anchor_added")

    result = _collapse(result)

    did_rewrite = result != raw_vibe
    meta = {
        "did_rewrite": did_rewrite,
        "reasons": reasons,
        "original_len": len(raw_vibe),
        "final_len": len(result),
    }

    logger.info(
        "appearance_spec request_id=%s did_rewrite=%s reasons=%s hash=%s",
        request_id, did_rewrite, ",".join(reasons) or "none", _prompt_hash(raw_vibe),
    )

    return result, meta


# ── Style tokens ─────────────────────────────────────────────────────

_STYLE_TOKENS: dict[str, str] = {
    "realistic": "cinematic portrait, realistic",
    "anime": "anime character illustration",
    "cartoon": "stylized cartoon character",
    "illustration": "digital illustration",
    "comic": "comic book style",
    "pixel": "pixel art",
}


def build_generation_prompt(
    appearance_spec: str,
    traits: list[str],
    shot_desc: str,
    *,
    style: str = "realistic",
) -> str:
    """Combine appearance spec, character traits, and shot description.

    Prepends an internal safety prefix and a style token.
    Hard-caps at 250 characters.
    """
    parts: list[str] = []

    # Safety prefix — always first (biases model toward safe output)
    parts.append(_SAFETY_PREFIX)

    # Style token — right after safety prefix
    style_token = _STYLE_TOKENS.get(style, _STYLE_TOKENS["realistic"])
    parts.append(style_token)

    # Character traits (name, species, gender)
    parts.extend(t for t in traits if t)

    # Appearance spec (user vibe, rewritten)
    if appearance_spec:
        parts.append(appearance_spec)

    # Shot framing
    if shot_desc:
        parts.append(shot_desc)

    prompt = ", ".join(parts)
    return prompt[:250]

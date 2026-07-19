"""RP Reply model configuration and quality evaluation for bake-off testing.

This module is INTERNAL — not exposed to normal users.
Used by the RP Reply Generator bake-off system to benchmark prose quality,
anti-godmodding behaviour, and style matching across different OpenRouter models.
"""
import re

# ── model registry ────────────────────────────────────────────────────────────

# Keyed by profile name. Empty string for "default" means "use effective storylab model."
RP_REPLY_MODELS: dict[str, str] = {
    "default":       "",   # resolved at runtime to current _EFFECTIVE_STORYLAB_MODEL
    "mixtral_8x22b": "mistralai/mixtral-8x22b-instruct",
    "mixtral_8x7b":  "mistralai/mixtral-8x7b-instruct",
    "llama_70b":     "meta-llama/llama-3.1-70b-instruct",
    "qwen_72b":      "qwen/qwen-2.5-72b-instruct",
}

# Human-readable labels for the frontend selector
RP_REPLY_MODEL_LABELS: dict[str, str] = {
    "default":       "Default",
    "mixtral_8x22b": "Mixtral 8x22B",
    "mixtral_8x7b":  "Mixtral 8x7B",
    "llama_70b":     "Llama 3.1 70B",
    "qwen_72b":      "Qwen 2.5 72B",
}

_VALID_PROFILES: frozenset[str] = frozenset(RP_REPLY_MODELS.keys())

# ── inferno model routing ─────────────────────────────────────────────────────

# Models known to handle explicit inferno content without refusal.
# Ordered by preference (best first).
INFERNO_ALLOWED_MODELS: tuple[str, ...] = (
    "qwen/qwen-2.5-72b-instruct",
    "mistralai/mixtral-8x22b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
)

# Model slug prefixes known to refuse explicit content at the model level.
# If the effective model matches any of these, inferno must route elsewhere.
_RESTRICTIVE_SLUG_PREFIXES: tuple[str, ...] = (
    "anthropic/",
    "openai/",
    "google/",
    "cohere/",
)


def _is_restrictive(model_slug: str) -> bool:
    """Return True if the model is known to refuse explicit content."""
    slug_lower = model_slug.lower()
    return any(slug_lower.startswith(p) for p in _RESTRICTIVE_SLUG_PREFIXES)


def resolve_rp_model(profile: str | None, default_model: str) -> tuple[str, str]:
    """Return (resolved_profile, model_slug).

    Falls back to "default" for unknown or None profiles.
    The "default" profile uses the current effective storylab model.
    """
    if not profile or profile not in _VALID_PROFILES:
        return "default", default_model
    slug = RP_REPLY_MODELS[profile]
    if not slug:  # "default" entry has empty string placeholder
        return "default", default_model
    return profile, slug


def resolve_inferno_model(
    profile: str | None,
    default_model: str,
    inferno_override: str = "",
) -> tuple[str, str, bool]:
    """Return (resolved_profile, model_slug, was_overridden) for inferno heat.

    Priority:
    1. User-selected profile that is already a permissive model.
    2. STORYLAB_MODEL_INFERNO config override (if set and permissive).
    3. First model in INFERNO_ALLOWED_MODELS.

    was_overridden is True when the original model was replaced.
    """
    # Resolve base profile first
    resolved_profile, base_slug = resolve_rp_model(profile, default_model)

    # If user explicitly chose a permissive model, honour it
    if not _is_restrictive(base_slug) and base_slug:
        return resolved_profile, base_slug, False

    original_slug = base_slug

    # Config-level inferno override
    if inferno_override and inferno_override.strip() and not _is_restrictive(inferno_override):
        return "inferno_override", inferno_override.strip(), True

    # Default to first allowed inferno model
    fallback_slug = INFERNO_ALLOWED_MODELS[0]
    return "inferno_fallback", fallback_slug, original_slug != fallback_slug


# ── intensity ↔ heat mapping ──────────────────────────────────────────────────

_HEAT_RANK: dict[str, int] = {"embers": 0, "flame": 1, "inferno": 2}

_INTENSITY_TO_HEAT: dict[str, str] = {
    "standard": "embers",
    "mature":   "flame",
    "explicit": "inferno",
}


def intensity_to_heat(intensity: str) -> str:
    """Map the intensity field to a minimum heat level.

    standard → embers
    mature   → flame
    explicit → inferno
    """
    return _INTENSITY_TO_HEAT.get(intensity, "embers")


def effective_heat_level(heat_level: str, intensity: str) -> str:
    """Return the higher of heat_level or intensity-mapped heat.

    intensity acts as a floor: if the user set intensity=explicit but
    heat_level=flame (default), inferno wins.
    """
    intensity_heat = intensity_to_heat(intensity)
    if _HEAT_RANK.get(intensity_heat, 0) > _HEAT_RANK.get(heat_level, 1):
        return intensity_heat
    return heat_level


# ── quality evaluator ─────────────────────────────────────────────────────────

def evaluate_rp_reply_quality(reply: str) -> dict[str, float]:
    """Lightweight heuristic quality scores for internal bake-off evaluation.

    All scores are in [0.0, 1.0] where 1.0 is best / safest.

    Scores
    ------
    length_score
        Development quality proxy. Penalises very short replies linearly;
        100+ words = 1.0.
    dialogue_score
        Prose/dialogue balance. Pure prose (no quotes) = 0.5; pure dialogue = 0.4;
        a healthy mix peaks at 1.0.
    repetition_score
        3-gram uniqueness. Heavily repeated phrases score lower.
    godmodding_risk
        Probability the reply narrates the partner character (0.0 = cleanest).
        Higher = more suspicious patterns found.
    format_score
        Checks that || bars are balanced (every opening has a matching close).
        1.0 = no bars or perfectly balanced bars; <1.0 = mismatched delimiters.
    """
    words = reply.split()
    word_count = len(words)

    # ── length_score ──────────────────────────────────────────────────────────
    length_score = min(1.0, word_count / 100.0) if word_count > 0 else 0.0

    # ── dialogue_score ────────────────────────────────────────────────────────
    dialogue_segments = re.findall(r'"[^"]{3,}"', reply)
    d_count = len(dialogue_segments)
    # Estimate prose paragraphs as non-empty newline-separated blocks
    paras = [p.strip() for p in reply.split("\n\n") if p.strip()]
    para_count = max(1, len(paras))
    ratio = d_count / (para_count + d_count) if (para_count + d_count) > 0 else 0.0
    # Sweet spot: 0.2–0.6 dialogue ratio
    if ratio == 0.0:
        dialogue_score = 0.5   # pure prose is fine but unremarkable
    elif ratio < 0.2:
        dialogue_score = 0.7
    elif ratio <= 0.6:
        dialogue_score = 1.0
    elif ratio <= 0.8:
        dialogue_score = 0.7
    else:
        dialogue_score = 0.4   # almost pure dialogue

    # ── repetition_score ─────────────────────────────────────────────────────
    if word_count < 6:
        repetition_score = 1.0
    else:
        lower_words = [w.lower() for w in words]
        trigrams = list(zip(lower_words, lower_words[1:], lower_words[2:]))
        if not trigrams:
            repetition_score = 1.0
        else:
            unique = len(set(trigrams))
            ratio_unique = unique / len(trigrams)
            repetition_score = min(1.0, ratio_unique * 1.1)  # slight boost for near-all-unique

    # ── godmodding_risk ───────────────────────────────────────────────────────
    risk = 0.0

    # Interior state narration — multiple pronoun + interior verb combos
    interior = re.findall(
        r'\b(?:she|he|they)\s+(?:felt|thought|knew|realized|wondered|decided|chose|wanted|needed)\b',
        reply, re.IGNORECASE,
    )
    if len(interior) >= 4:
        risk += 0.4
    elif len(interior) >= 2:
        risk += 0.2

    # Forced physical reactions — partner's body described reacting
    reaction = re.findall(
        r'\b(?:she|he|they)\s+(?:gasped|flinched|trembled|shuddered|stiffened|recoiled|'
        r'stepped back|pulled away|tensed|froze|staggered|startled|whimpered|shrank)\b',
        reply, re.IGNORECASE,
    )
    if len(reaction) >= 3:
        risk += 0.4
    elif len(reaction) >= 1:
        risk += 0.15

    # Consent resolution — partner's agency resolved by the writer
    consent = re.findall(
        r'\b(?:let|allowed|permitted|accepted|welcomed)\s+(?:him|her|them|it)\b',
        reply, re.IGNORECASE,
    )
    if len(consent) >= 2:
        risk += 0.3
    elif len(consent) >= 1:
        risk += 0.1

    godmodding_risk = min(1.0, risk)

    # ── format_score ──────────────────────────────────────────────────────────
    bar_count = reply.count("||")
    if bar_count == 0:
        format_score = 1.0   # plain mode — no bars expected
    elif bar_count % 2 == 0:
        format_score = 1.0   # even number of || = all open/closed
    else:
        format_score = 0.5   # odd number = mismatched delimiter

    return {
        "length_score":    round(length_score, 3),
        "dialogue_score":  round(dialogue_score, 3),
        "repetition_score": round(repetition_score, 3),
        "godmodding_risk": round(godmodding_risk, 3),
        "format_score":    round(format_score, 3),
    }

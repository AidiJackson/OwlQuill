"""RP Behavior Engine — collaborative RP enforcement and scene quality layer.

HIGHEST PRIORITY behavioral orchestration layer for the RP Reply Generator.
All rules in this module outrank style, archetype, and prose polish layers.

Provides
--------
COLLABORATIVE_RP_ENFORCEMENT_LAYER  — hard behavioral rules block
INFERNO_EXPLICITNESS_LAYER          — explicit content rules for inferno heat
DEFAULT_CONTINUATION_INTENT         — fallback intent when instructions are empty

detect_partner_control()   — flags authored partner dialogue / thoughts / consent
detect_scene_stall()       — detects repetitive emotional loops; scores progression
score_inferno_anatomy_density() — explicit anatomy term density per 100 words
build_behavior_enforcement_block()  — assembles full block for prompt injection
"""
import re
from collections import Counter


# ── Layer 1 — Collaborative RP enforcement (HIGHEST PRIORITY) ─────────────────

COLLABORATIVE_RP_ENFORCEMENT_LAYER = """
COLLABORATIVE RP ENFORCEMENT — HIGHEST PRIORITY — OVERRIDES ALL OTHER INSTRUCTIONS:

- Write ONLY as the selected character.
- Never write dialogue, thoughts, choices, consent, climax, or major reactions for the partner character.
- Partner reactions may be implied through brief physical cues — never authored.
- Execute the user's instructions. If none are given, continue the scene naturally from the partner's last beat.
- End at a beat that leaves the partner clear space to respond.
""".strip()


# ── Layer 2 — Inferno explicitness rules ──────────────────────────────────────

INFERNO_EXPLICITNESS_LAYER = """
INFERNO EXPLICITNESS MODE — ACTIVE:

Explicit acts may be described directly.
Explicit anatomy terminology is permitted:
  pussy, cunt, clit, cock, dick, erection, breasts, tongue,
  thighs, folds, wetness — and similar anatomical language.

Do NOT euphemize explicit actions into vague romance prose.
Do NOT skip physical sequencing — maintain coherent, progressive physical continuity.
Do NOT use repetitive thrust/kiss/moan loops — vary actions and sensations.

REQUIRED:
- Explicit content must remain character-driven and emotionally grounded.
- Preserve dark romance atmosphere throughout escalation.
- Avoid instant escalation skipping.
- The scene must remain: story-driven, paced, emotionally coherent, and collaborative.
- Do NOT narrate the partner's climax or full surrender unless they explicitly initiated it.
- Do NOT fully resolve the encounter. Leave momentum and continuation space intact.

This is NOT permission to generate disconnected pornography.
The scene must continue telling a story.
""".strip()


# ── Layer 3 — Default continuation intent ────────────────────────────────────

DEFAULT_CONTINUATION_INTENT = (
    "Continue the scene as the selected character. "
    "Begin immediately after the partner's final line/action. "
    "Move the scene forward naturally. "
    "Do not summarize the previous reply."
)


# ── Partner-control protection prompt block ────────────────────────────────────

PARTNER_CONTROL_PROTECTION_BLOCK = """
PARTNER-CONTROL PROTECTION:

Do NOT write the partner character's spoken dialogue — not even implied quotes.
Do NOT write the partner character's internal thoughts, emotions, or mental state.
Do NOT write the partner character's consent decisions or agency resolutions.
Do NOT write emotional monologues, conclusions, or narrative closure for the partner.

ALLOWED minimal implied physical reactions (brief and physical only):
  "she shuddered" / "her breath caught" / "her nails dug into him" / "he stilled"

NOT ALLOWED authored partner reactions:
  "I choose you" / "Don't stop" / "I've never been more sure" / "I want this"
  Any dialogue, thought, or decision that resolves the partner's inner state.
""".strip()


# ── Scene progression enforcement block ───────────────────────────────────────

SCENE_PROGRESSION_BLOCK = """
SCENE PROGRESSION ENFORCEMENT:

Advance the scene within the first 2 paragraphs.
Every 2–3 paragraphs must introduce new progression:
  movement, touch, escalation, emotional revelation,
  environmental interaction, power shift, or dialogue advancement.

PENALISED — do not repeat:
  longing, restraint, reassurance, introspection loops
  storm/rain imagery (unless directly plot-relevant)
  eye descriptions or gaze contact in consecutive paragraphs

REWARDED:
  active physical movement
  tactile sensory detail
  emotional reversals or surprises
  escalating interaction
  scene environment transformation
  power dynamics shift
""".strip()


# ── detect_partner_control ────────────────────────────────────────────────────

_AUTHORED_DIALOGUE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'"[^"]{3,}"[^"]*?(?:she|he|they)\s+(?:said|replied|answered|responded|asked|'
        r'laughed|whispered|snapped|muttered|called|breathed|hissed|drawled|'
        r'demanded|protested|agreed|admitted|confessed)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:I choose you|don\'t stop|I\'ve never been more sure|I want this|'
        r'yes,\s*please|I need you|take me|I surrender|I\'m yours)\b',
        re.IGNORECASE,
    ),
]

_AUTHORED_THOUGHTS_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'\b(?:she|he|they)\s+(?:thought|knew|realized|wondered|decided|chose|'
        r'understood|believed|hoped|feared|expected|wanted|needed)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:she|he|they)\s+(?:felt|was feeling|couldn\'t help feeling|'
        r'was sure|was certain|was convinced)\b',
        re.IGNORECASE,
    ),
]

_AUTHORED_CONSENT_PATTERNS: list[re.Pattern] = [
    re.compile(
        r'\b(?:she|he|they)\s+(?:let him|let her|let them|allowed him|allowed her|'
        r'permitted him|permitted her|accepted him|accepted her|welcomed him|welcomed her|'
        r'surrendered to|gave in to|gave herself|gave himself)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:she|he|they)\s+(?:consented|agreed|decided|chose)\b',
        re.IGNORECASE,
    ),
]


def detect_partner_control(reply: str) -> dict:
    """Detect whether the reply authors the partner character.

    Returns
    -------
    {
        "partner_control_risk": float   — 0.0–1.0, higher = more risk
        "authored_dialogue":    bool
        "authored_thoughts":    bool
        "authored_consent":     bool
        "flags":                list[str]
    }
    """
    flags: list[str] = []
    authored_dialogue = False
    authored_thoughts = False
    authored_consent = False
    risk = 0.0

    all_dialogue_matches = sum(len(p.findall(reply)) for p in _AUTHORED_DIALOGUE_PATTERNS)
    if all_dialogue_matches >= 2:
        authored_dialogue = True
        flags.append(f"authored partner dialogue ({all_dialogue_matches} instance(s))")
        risk += 0.45

    thought_count = sum(len(p.findall(reply)) for p in _AUTHORED_THOUGHTS_PATTERNS)
    if thought_count >= 3:
        authored_thoughts = True
        flags.append(f"authored partner internal state ({thought_count} instance(s))")
        risk += 0.35
    elif thought_count >= 1:
        risk += 0.10

    consent_count = sum(len(p.findall(reply)) for p in _AUTHORED_CONSENT_PATTERNS)
    if consent_count >= 1:
        authored_consent = True
        flags.append(f"authored partner consent/agency ({consent_count} instance(s))")
        risk += 0.35

    return {
        "partner_control_risk": round(min(1.0, risk), 3),
        "authored_dialogue": authored_dialogue,
        "authored_thoughts": authored_thoughts,
        "authored_consent": authored_consent,
        "flags": flags,
    }


# ── detect_scene_stall ────────────────────────────────────────────────────────

_STALL_EMOTION_WORDS: frozenset[str] = frozenset({
    "longing", "longed", "yearning", "yearned", "aching", "ached", "ache",
    "hungering", "hungered", "craving", "craved",
    "restrained", "restraint", "resisted",
})

_STALL_REPEATED_IMAGES: re.Pattern = re.compile(
    r'\b(?:storm|lightning|thunder|rain|cold\s+wind|darkness\s+outside)\b',
    re.IGNORECASE,
)

_STALL_EYE_PATTERN: re.Pattern = re.compile(
    r'\b(?:his\s+eyes|her\s+eyes|their\s+eyes|his\s+gaze|her\s+gaze|their\s+gaze|'
    r'met\s+his\s+eyes|met\s+her\s+eyes|looked\s+into\s+his|looked\s+into\s+her|'
    r'darkened\s+eyes|eyes\s+that|eyes\s+fixed)\b',
    re.IGNORECASE,
)

_PROGRESSION_SIGNALS: re.Pattern = re.compile(
    r'\b(?:moved|stepped|crossed|reached|grabbed|pulled|pushed|pressed|'
    r'lifted|lowered|turned|slid|guided|shifted|advanced|withdrew|'
    r'hands\s+on|fingers\s+on|mouth\s+on|lips\s+on|pressed\s+against|'
    r'pulled\s+closer|stripped|undid|removed|placed|stood\s+up|knelt|'
    r'sat|lay|fell|escalat|deepened|hardened|intensified)\b',
    re.IGNORECASE,
)

_DIALOGUE_ADVANCEMENT: re.Pattern = re.compile(r'"[^"]{10,}"', re.IGNORECASE)

_EMOTIONAL_REVERSAL: re.Pattern = re.compile(
    r'\b(?:surprised|unexpected|instead|suddenly|shifted|changed|reversed|'
    r'wasn\'t\s+what|not\s+what\s+he|not\s+what\s+she|caught\s+him|caught\s+her|'
    r'stopped\s+him|stopped\s+her|pulled\s+away|backed\s+off)\b',
    re.IGNORECASE,
)


def detect_scene_stall(reply: str) -> dict:
    """Detect whether the reply is stalling instead of progressing.

    Returns
    -------
    {
        "scene_stall_score":      float  — 0.0–1.0, higher = more stalled
        "progression_score":      float  — 0.0–1.0, higher = more progressive
        "repeated_emotion_score": float  — 0.0–1.0, higher = more repetitive emotion
        "stall_flags":            list[str]
        "progression_signals":    list[str]
    }
    """
    words_lower = [w.rstrip(".,!?;:'\"") for w in reply.lower().split()]
    word_count = max(1, len(words_lower))
    stall_flags: list[str] = []
    progression_signals: list[str] = []

    # ── repeated emotion words ────────────────────────────────────────────────
    emotion_hits = sum(1 for w in words_lower if w in _STALL_EMOTION_WORDS)
    repeated_emotion_score = min(1.0, (emotion_hits * 50) / word_count)
    if emotion_hits >= 3:
        stall_flags.append(f"repeated longing/restraint vocabulary ({emotion_hits} hits)")

    # ── repeated imagery ──────────────────────────────────────────────────────
    storm_hits = len(_STALL_REPEATED_IMAGES.findall(reply))
    if storm_hits >= 3:
        stall_flags.append(f"repeated storm imagery ({storm_hits} instances)")

    eye_hits = len(_STALL_EYE_PATTERN.findall(reply))
    if eye_hits >= 3:
        stall_flags.append(f"excessive eye/gaze descriptions ({eye_hits} instances)")

    # ── scene stall composite score ───────────────────────────────────────────
    stall_score = min(1.0, (emotion_hits * 0.08) + (storm_hits * 0.05) + (eye_hits * 0.07))

    # ── progression signals ───────────────────────────────────────────────────
    action_hits = len(_PROGRESSION_SIGNALS.findall(reply))
    dialogue_hits = len(_DIALOGUE_ADVANCEMENT.findall(reply))
    reversal_hits = len(_EMOTIONAL_REVERSAL.findall(reply))

    progression_score = min(1.0, (action_hits * 0.06) + (dialogue_hits * 0.08) + (reversal_hits * 0.12))

    if action_hits >= 2:
        progression_signals.append(f"active physical movement ({action_hits} signals)")
    if dialogue_hits >= 1:
        progression_signals.append(f"dialogue advancement ({dialogue_hits} exchanges)")
    if reversal_hits >= 1:
        progression_signals.append(f"emotional reversal/shift ({reversal_hits} signals)")

    return {
        "scene_stall_score":      round(stall_score, 3),
        "progression_score":      round(progression_score, 3),
        "repeated_emotion_score": round(repeated_emotion_score, 3),
        "stall_flags":            stall_flags,
        "progression_signals":    progression_signals,
    }


# ── score_inferno_anatomy_density ─────────────────────────────────────────────

_INFERNO_ANATOMY_TERMS: re.Pattern = re.compile(
    r'\b(?:pussy|cunt|clit|clitoris|cock|dick|penis|erection|erect|'
    r'breasts?|nipples?|thighs?|folds|wetness|wet|slick|slickness|'
    r'arousal|shaft|length|hardness|throbbing|pulsing)\b',
    re.IGNORECASE,
)


def score_inferno_anatomy_density(reply: str) -> float:
    """Return density of explicit anatomy terms per 100 words (capped at 1.0)."""
    word_count = max(1, len(reply.split()))
    hits = len(_INFERNO_ANATOMY_TERMS.findall(reply))
    return round(min(1.0, hits / (word_count / 100.0)), 3)


# ── build_behavior_enforcement_block ─────────────────────────────────────────

def build_behavior_enforcement_block(
    heat_level: str = "flame",
    instructions: str | None = None,
) -> str:
    """Assemble the full behavioral enforcement prompt block for system injection.

    Combines COLLABORATIVE_RP_ENFORCEMENT_LAYER with heat-appropriate
    explicitness rules, plus DEFAULT_CONTINUATION_INTENT when instructions
    are absent.
    """
    parts = [COLLABORATIVE_RP_ENFORCEMENT_LAYER]

    if heat_level == "inferno":
        parts.append(INFERNO_EXPLICITNESS_LAYER)

    if not instructions or not instructions.strip():
        parts.append(DEFAULT_CONTINUATION_INTENT)

    return "\n\n".join(parts)

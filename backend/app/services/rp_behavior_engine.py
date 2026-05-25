"""RP Behavior Engine — collaborative RP enforcement and scene quality layer.

HIGHEST PRIORITY behavioral orchestration layer for the RP Reply Generator.
All rules in this module outrank style, archetype, and prose polish layers.

Provides
--------
COLLABORATIVE_RP_ENFORCEMENT_LAYER  — hard turn-ownership rules block
TURN_BOUNDARY_FOOTER                — "end where partner can respond" footer, added to every prompt
PARTNER_SILENCE_LAYER               — softened silence rule (no authored dialogue/choices)
SELECTED_CHARACTER_DRIVES_SCENE     — positive directive: SC carries scene, no waiting loop
INFERNO_EXPLICITNESS_LAYER          — explicit content rules for inferno heat
DEFAULT_CONTINUATION_INTENT         — fallback intent when instructions are empty
NO_PARTNER_BRIDGE_INSTRUCTION       — multi-beat addendum: no partner bridge, no stall

detect_partner_control()         — flags authored partner dialogue / thoughts / consent
detect_partner_silence_severe()  — strict single-quoted-line severity check for retry
detect_waiting_loop()            — detects anticipation/stall vocabulary loops
detect_scene_stall()             — detects repetitive emotional loops; scores progression
score_inferno_anatomy_density()  — explicit anatomy term density per 100 words
build_behavior_enforcement_block()   — assembles full block for prompt injection
build_partner_silence_correction()   — retry correction block for silence violations
build_waiting_loop_correction()      — retry correction block for waiting-loop violations
"""
import re
from collections import Counter

from app.services._rp_constants import _SPEECH_VERBS


# ── Layer 1 — Collaborative RP enforcement (HIGHEST PRIORITY) ─────────────────

COLLABORATIVE_RP_ENFORCEMENT_LAYER = """
COLLABORATIVE RP ENFORCEMENT — HIGHEST PRIORITY — OVERRIDES ALL OTHER INSTRUCTIONS:

The partner's turn is complete. Write ONLY the selected character's next turn.

ALLOWED: selected character dialogue, action, thought, sensory perception, environment they cause.
NOT ALLOWED: partner dialogue, partner consent, partner climax, partner decisions, partner inner state.
Do NOT narrate "she wanted", "she knew", "she surrendered", or partner body resolution.
""".strip()


# ── Turn boundary footer (injected into every prompt) ─────────────────────────

TURN_BOUNDARY_FOOTER = (
    "End the reply at a point where the partner can respond. "
    "Do not complete the partner's reaction."
)


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

For intimate and romantic scenes:
  Never write the partner's climax, consent, or release.
  The selected character may pause, speak, act, or react — leave the partner's next move open.

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
Do NOT write the partner character's physical reactions — no shuddering, trembling, flinching, gasping, stiffening, or any involuntary bodily response.
Do NOT author partner reactions through causal framing — no "eliciting a shudder from her", "causing her to gasp", "making him tremble", "drawing a whimper from them".

FORBIDDEN examples (partner's experience authored):
  "she shuddered" / "he trembled" / "her breath caught" / "he stilled" / "she gasped"
  "eliciting a moan from her" / "causing her to shiver" / "making him flinch"
  "I choose you" / "Don't stop" / "I've never been more sure" / "I want this"
  Any reaction, thought, decision, or physical response that resolves the partner's experience.
""".strip()


# ── Partner silence layer ──────────────────────────────────────────────────────

PARTNER_SILENCE_LAYER = """
PARTNER SILENCE:

Do not author new dialogue, choices, consent, climax, or inner thoughts for the partner character.
The partner may remain silent, physically present, or minimally/reactively described only when necessary for continuity.

NOT ALLOWED for the partner:
  quoted speech / "she said" / "he replied" / any emotional choice, decision, or resolution

ALLOWED minimal partner reactions (physical, non-authored):
  breath caught / shifted slightly / did not move away / silence / stillness

The selected character must carry the scene forward.
Do not stop and wait for the partner to respond between beats.
""".strip()


# ── Selected-character drive directive ────────────────────────────────────────

SELECTED_CHARACTER_DRIVES_SCENE = (
    "The selected character must carry the scene forward. "
    "Do not wait repeatedly for the partner to respond. "
    "If the partner stays silent, continue through the selected character's actions, "
    "dialogue, movement, choices, internal conflict, time-skip, or scene transition. "
    "Do not loop anticipation."
)


# ── No-partner-bridge instruction (multi-beat / novella addendum) ──────────────

NO_PARTNER_BRIDGE_INSTRUCTION = (
    "Do not use the partner character to bridge beats, and do not stop and wait. "
    "Bridge beats using the selected character's movement, narration, dialogue, time-skip, or choices."
)


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


# ── detect_partner_silence_severe ────────────────────────────────────────────
#
# Checks for partner-dialogue, speech-verb, and decision violations.
#
# Key design decision: "quote" he/she said matches the SELECTED character's own
# speech when that character is gendered (male "he said", female "she said").
# A single such match is therefore NOT a reliable godmod signal on its own.
#
# We add cross_gender_godmod: True when BOTH "he [...] said" AND "she [...] said"
# appear in the reply — strongly indicating both characters were written.
# The retry trigger in generate_rp_reply uses this flag plus a raised threshold.

# Gender-specific variants for cross-pronoun detection (used by detect_partner_silence_severe)
_SEVERE_HE_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]*?\bhe\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)

_SEVERE_SHE_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]*?\bshe\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)

_SEVERE_SPEECH_VERB_RE = re.compile(
    r'\b(?:she|he|they)\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)

_SEVERE_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]*?(?:she|he|they)\s+(?:' + _SPEECH_VERBS + r')',
    re.IGNORECASE,
)

_SEVERE_DECISION_RE = re.compile(
    r'\b(?:she|he|they)\s+'
    r'(?:decided|chose|consented|permitted|allowed|accepted|surrendered|'
    r'gave in|gave herself|gave himself|let him|let her|welcomed)\b',
    re.IGNORECASE,
)


def detect_partner_silence_severe(reply: str) -> dict:
    """Return a severity assessment for partner-silence violations.

    Uses shared speech-verb vocabulary from _rp_constants alongside local
    pattern logic. Cross-gender and decision thresholds differ intentionally
    from detect_godmod_violations: this function is a diagnostic adapter with
    its own severity semantics (single attributed line counts, lower decision bar).

    Returns
    -------
    {
        "severe":              bool    — True when cross-gender godmod, 2+ attributed lines,
                                         or partner decision/consent detected
        "cross_gender_godmod": bool    — True when BOTH he-attributed AND she-attributed
                                         dialogue appear (strong two-character signal)
        "dialogue_count":      int     — number of attributed quoted lines found
        "speech_verb_count":   int     — number of bare speech-verb attributions
        "decision_count":      int     — number of partner-decision attributions
        "flags":               list[str]
    }
    """
    flags: list[str] = []

    dialogue_matches = _SEVERE_DIALOGUE_RE.findall(reply)
    dialogue_count = len(dialogue_matches)

    # Cross-gender: both masculine AND feminine dialogue attribution present.
    # A reply that says "he said" once is likely just the selected character speaking.
    # A reply with BOTH "he said" and "she said" almost certainly writes two characters.
    has_he = bool(_SEVERE_HE_DIALOGUE_RE.search(reply))
    has_she = bool(_SEVERE_SHE_DIALOGUE_RE.search(reply))
    cross_gender_godmod = has_he and has_she

    speech_verb_matches = _SEVERE_SPEECH_VERB_RE.findall(reply)
    speech_verb_count = len(speech_verb_matches)

    decision_matches = _SEVERE_DECISION_RE.findall(reply)
    decision_count = len(decision_matches)

    severe = False

    if cross_gender_godmod:
        severe = True
        flags.append("cross-gender dialogue: both he-attributed and she-attributed speech")
    elif dialogue_count >= 2:
        # 2+ attributed lines strongly suggests both characters were given dialogue,
        # even when both use the same pronoun (same-gender character pairs).
        severe = True
        flags.append(f"attributed partner dialogue ({dialogue_count} line(s))")
    elif dialogue_count == 1:
        # Single attributed line — could be the selected character's own speech.
        # Record the count but do not set severe; let the caller apply context.
        flags.append("single attributed line — possible selected-character speech")

    # Raised bar for bare speech-verb: require 2+ to avoid false positives when
    # the selected character is gendered ("he said" / "she said" for selected char).
    if speech_verb_count >= 2:
        severe = True
        flags.append(f"partner speech verb ({speech_verb_count} instance(s))")

    if decision_count >= 1:
        severe = True
        flags.append(f"partner decision/consent ({decision_count} instance(s))")

    return {
        "severe": severe,
        "cross_gender_godmod": cross_gender_godmod,
        "dialogue_count": dialogue_count,
        "speech_verb_count": speech_verb_count,
        "decision_count": decision_count,
        "flags": flags,
    }


def build_partner_silence_correction(character_name: str = "") -> str:
    """Build the retry correction block for a partner-silence violation."""
    char_label = character_name or "the selected character"
    return (
        "CORRECTION — READ FIRST — OVERRIDES ALL OTHER INSTRUCTIONS:\n"
        "Your previous generation wrote the partner character's dialogue or decisions.\n"
        f"Rewrite. Remove all partner dialogue and decisions. "
        f"Progress the scene only through {char_label}'s actions, speech, and narration."
    )


# ── detect_waiting_loop ───────────────────────────────────────────────────────

_WAITING_LOOP_PATTERNS: list[re.Pattern] = [
    re.compile(r'\bwaiting\s+for\s+(?:her|him|their|a)\b', re.IGNORECASE),
    re.compile(r'\bsilence\s+stretched\b', re.IGNORECASE),
    re.compile(r'\bmoment\s+stretched\b', re.IGNORECASE),
    re.compile(r'\banticipation\b', re.IGNORECASE),
    re.compile(r'\beyes?\s+(?:(?:were|are|remained|still|grew)\s+)?locked\b', re.IGNORECASE),
    re.compile(r'\b(?:pulse|heart)\s+(?:was\s+|is\s+)?pound(?:ing|ed)\b', re.IGNORECASE),
    re.compile(r'\bnot\s+sure\s+what\s+(?:happens|would\s+happen)\s+next\b', re.IGNORECASE),
    re.compile(r'\bready\s+for\s+whatever\s+comes\s+next\b', re.IGNORECASE),
    re.compile(r'\bshow\s+(?:me|him|her)\s+what\s+you\s+want\b', re.IGNORECASE),
    re.compile(r'\bheld?\s+(?:his|her|their)\s+breath\b', re.IGNORECASE),
    re.compile(r'\btime\s+seem(?:ed|s)?\s+to\s+(?:slow|stop|freeze|stand)\b', re.IGNORECASE),
]


def detect_waiting_loop(reply: str) -> dict:
    """Detect whether the reply is stuck in an anticipation/waiting loop.

    Returns
    -------
    {
        "waiting_loop":  bool    — True when 3+ waiting/anticipation patterns found
        "pattern_count": int     — total matched instances across all patterns
        "flags":         list[str]
    }
    """
    if not reply:
        return {"waiting_loop": False, "pattern_count": 0, "flags": []}

    flags: list[str] = []
    total_count = 0
    for pat in _WAITING_LOOP_PATTERNS:
        matches = pat.findall(reply)
        cnt = len(matches)
        if cnt:
            total_count += cnt
            flags.append(f"{matches[0]!r} ×{cnt}")

    return {
        "waiting_loop": total_count >= 3,
        "pattern_count": total_count,
        "flags": flags,
    }


def build_waiting_loop_correction(character_name: str = "") -> str:
    """Build the retry correction block for a waiting-loop violation."""
    char_label = character_name or "the selected character"
    return (
        "CORRECTION — READ FIRST — OVERRIDES ALL OTHER INSTRUCTIONS:\n"
        "Your previous generation stalled in an anticipation loop. "
        f"Rewrite. Do not stop and wait for the partner. "
        f"Continue through {char_label}'s own actions, dialogue, movement, or scene transition "
        f"while preserving partner agency."
    )


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

    parts.append(TURN_BOUNDARY_FOOTER)

    return "\n\n".join(parts)

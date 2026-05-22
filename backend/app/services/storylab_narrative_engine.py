"""StoryLab Narrative Engine — scene propulsion and loop detection for Create Story / Chapter.

Lightweight, StoryLab-specific. Does NOT import or share code with rp_narrative_engine.py.
Used only inside build_storylab_prompt() and build_chapter_prompt().

Public API
----------
detect_story_repetition(text)          — repeated exchange / dialogue loop detection
detect_story_progression(text)         — scene movement and forward-motion scoring
build_storylab_propulsion_block(controls) — settings-aware prompt instruction block
_STORYLAB_PROPULSION_CORE              — base block constant (for isolation tests)
"""
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.schemas.storylab import StoryLabControls


# ── repetition detection ──────────────────────────────────────────────────────

_DIALOGUE_LINE_PAT = re.compile(r'"([^"]{8,})"')
_SENTENCE_SPLIT_PAT = re.compile(r'(?<=[.!?])\s+')

_REPEATED_WEATHER_PAT = re.compile(
    r'\b(?:storm|thunder|lightning|rain|wind|cold\s+air|darkness\s+outside|'
    r'tempest|downpour|fog|mist|freezing)\b',
    re.IGNORECASE,
)
_REPEATED_ATTRACTION_PAT = re.compile(
    r'\b(?:attraction|chemistry|magnetic|drawn\s+to|want(?:ed|ing)?\s+(?:him|her)|'
    r'couldn\'t\s+(?:deny|ignore|help)\s+(?:himself|herself|the)|'
    r'electric|charged\s+(?:air|moment|silence)|something\s+between\s+them)\b',
    re.IGNORECASE,
)
_REPEATED_TENSION_PAT = re.compile(
    r'\b(?:tension|tense|taut|fraught|dangerous|precarious|on\s+edge)\b',
    re.IGNORECASE,
)
_SETTING_BEAT_PAT = re.compile(
    r'\b(?:the\s+(?:room|air|silence|moment|night|rain)\s+(?:was|felt|seemed|hung))\b',
    re.IGNORECASE,
)


def _normalise(s: str) -> str:
    """Lower-case, strip punctuation for comparison."""
    return re.sub(r'[^\w\s]', '', s.lower()).strip()


def _sentence_windows(text: str, window: int = 5) -> list[str]:
    """Split text into overlapping sentence windows for duplication detection."""
    sents = [s.strip() for s in _SENTENCE_SPLIT_PAT.split(text) if s.strip()]
    if len(sents) < window:
        return [" ".join(sents)]
    return [" ".join(sents[i: i + window]) for i in range(len(sents) - window + 1)]


def detect_story_repetition(text: str) -> dict[str, Any]:
    """Detect repeated exchanges, dialogue loops, and atmospheric repetition.

    Returns
    -------
    {
        repeated_section_detected: bool    — True when structural repetition found
        story_repetition_score: float      — 0.0–1.0 (higher = more repetitive)
        repeated_dialogue_count: int       — same quoted line appearing 2+ times
        repeated_ngram_count: int          — 6-gram phrases repeating 2+ times
        repeated_weather_count: int        — storm/weather imagery count
        repeated_attraction_count: int     — attraction narration count
        repeated_tension_count: int        — tension vocabulary count
        repeated_setting_beat_count: int   — "the room felt..." type repetition
        repeated_phrases: list[str]        — up to 5 example repeated n-grams
    }
    """
    word_count = max(1, len(text.split()))

    # ── repeated dialogue lines ───────────────────────────────────────────────
    dialogue_lines = [_normalise(m.group(1)) for m in _DIALOGUE_LINE_PAT.finditer(text)]
    dialogue_counts = Counter(dialogue_lines)
    repeated_dialogue_count = sum(1 for c in dialogue_counts.values() if c >= 2)

    # ── repeated 6-gram phrases ───────────────────────────────────────────────
    words = text.lower().split()
    ngram_size = 6
    ngrams = [" ".join(words[i: i + ngram_size]) for i in range(len(words) - ngram_size + 1)]
    ngram_counts = Counter(ngrams)
    repeated_ngrams = [ng for ng, cnt in ngram_counts.items() if cnt >= 2]
    repeated_ngram_count = len(repeated_ngrams)

    # ── atmospheric / beat repetition ─────────────────────────────────────────
    repeated_weather_count    = len(_REPEATED_WEATHER_PAT.findall(text))
    repeated_attraction_count = len(_REPEATED_ATTRACTION_PAT.findall(text))
    repeated_tension_count    = len(_REPEATED_TENSION_PAT.findall(text))
    repeated_setting_beat_count = len(_SETTING_BEAT_PAT.findall(text))

    # ── repetition score ──────────────────────────────────────────────────────
    score = min(1.0,
        (repeated_dialogue_count * 0.25)
        + (min(repeated_ngram_count, 10) * 0.04)
        + (max(0, repeated_weather_count - 2) * 0.04)
        + (max(0, repeated_attraction_count - 3) * 0.05)
        + (max(0, repeated_tension_count - 3) * 0.04)
        + (max(0, repeated_setting_beat_count - 2) * 0.06)
    )

    repeated_section_detected = (
        repeated_dialogue_count >= 1
        or repeated_ngram_count >= 3
        or repeated_attraction_count >= 5
        or repeated_tension_count >= 6
        or repeated_weather_count >= 4
    )

    return {
        "repeated_section_detected":   repeated_section_detected,
        "story_repetition_score":      round(score, 3),
        "repeated_dialogue_count":     repeated_dialogue_count,
        "repeated_ngram_count":        repeated_ngram_count,
        "repeated_weather_count":      repeated_weather_count,
        "repeated_attraction_count":   repeated_attraction_count,
        "repeated_tension_count":      repeated_tension_count,
        "repeated_setting_beat_count": repeated_setting_beat_count,
        "repeated_phrases":            repeated_ngrams[:5],
    }


# ── progression detection ─────────────────────────────────────────────────────

_ACTION_PAT = re.compile(
    r'\b(?:moved?|steps?|stepped|crossed?|reached?|grabbed?|pulled?|pushed?|'
    r'stood?\s+up|sat\s+down|turned?|lifted?|leaned?\s+in|walked?|ran?|'
    r'slid|spun|shifted?|advanced?|backed?|pressed?\s+(?:forward|against)|'
    r'kissed?|touched?|embraced?|knelt|fell|rose|climbed?|opened?|shut)\b',
    re.IGNORECASE,
)
_DIALOGUE_EXCHANGE_PAT = re.compile(r'"[^"]{5,}"', re.IGNORECASE)
_SCENE_CHANGE_PAT = re.compile(
    r'\b(?:walked?\s+(?:into|out|to|through|toward)|entered?|left\s+the\s+room|'
    r'crossed?\s+(?:to|into|the)|moved?\s+(?:to|into|through)|led?\s+(?:him|her)|'
    r'followed?\s+(?:him|her)\s+(?:to|into)|stepped?\s+(?:into|out|through)|'
    r'went\s+(?:to|into|through))\b',
    re.IGNORECASE,
)
_REVELATION_PAT = re.compile(
    r'\b(?:told?\s+(?:him|her)|confessed?|admitted?|revealed?|finally\s+said|'
    r'broke?\s+(?:the\s+silence|first)|said\s+it\s+aloud|let\s+(?:him|her)\s+(?:know|see))\b',
    re.IGNORECASE,
)
_ENV_PAT = re.compile(
    r'\b(?:wall|door|window|floor|bed|table|chair|counter|bar|sofa|couch|'
    r'desk|stairs?|hallway|room|corner|glass|bottle|cigarette|rain|fireplace|'
    r'mirror|railing|threshold|pillow|sheets?|car)\b',
    re.IGNORECASE,
)


def detect_story_progression(text: str) -> dict[str, Any]:
    """Measure forward motion and scene evolution.

    Returns
    -------
    {
        story_progression_score: float     — 0.0–1.0 (higher = more progressive)
        action_count: int
        dialogue_exchange_count: int
        scene_change_count: int
        revelation_count: int
        environment_count: int
    }
    """
    word_count = max(1, len(text.split()))
    _per100 = 100.0 / word_count

    action_count          = len(_ACTION_PAT.findall(text))
    dialogue_count        = len(_DIALOGUE_EXCHANGE_PAT.findall(text))
    scene_change_count    = len(_SCENE_CHANGE_PAT.findall(text))
    revelation_count      = len(_REVELATION_PAT.findall(text))
    environment_count     = len(_ENV_PAT.findall(text))

    score = min(1.0,
        (action_count      * _per100 / 8)  * 0.35
        + (dialogue_count  * _per100 / 5)  * 0.25
        + (scene_change_count * _per100 / 2) * 0.2
        + (revelation_count * _per100 / 2)  * 0.1
        + (environment_count * _per100 / 4) * 0.1
    )

    return {
        "story_progression_score": round(score, 3),
        "action_count":            action_count,
        "dialogue_exchange_count": dialogue_count,
        "scene_change_count":      scene_change_count,
        "revelation_count":        revelation_count,
        "environment_count":       environment_count,
    }


# ── propulsion block ──────────────────────────────────────────────────────────

# Core block — always injected (both paths)
_STORYLAB_PROPULSION_CORE = (
    "Advance the chapter through concrete scene beats. "
    "Avoid repeating the same conversation, attraction, weather, or emotional framing. "
    "Each major section should change the situation through action, revelation, conflict, "
    "choice, or movement. Do not loop the same exchange. "
    "Use action chains — move characters through the space. "
    "Let objects and settings have purpose. Give each paragraph a job. "
    "Introduce micro power shifts. End with a hook, decision, reveal, or escalation."
)

_FAST_INTENSE_ADDENDUM = (
    "Fast/intense chapters must contain visible stakes and forward motion: "
    "compress exposition, raise the conflict or pressure every few paragraphs, "
    "and ensure the scene state materially changes before the chapter ends."
)

_SENSUAL_ADDENDUM = (
    "Chemistry should develop through action, proximity, tension, and consequence "
    "— not through repeated attraction narration. "
    "Register desire through what characters notice physically: texture, warmth, breath, "
    "specific detail. Something must shift between characters by the end."
)

_LONG_ADDENDUM = (
    "Long chapters must progress through multiple distinct sections — "
    "do not extend length by repeating the same emotional exchange. "
    "Each section should open a new beat: escalation, complication, revelation, or shift."
)

_LOOP_CORRECTION = (
    "REWRITE REQUIREMENT: the previous draft repeated the same dialogue or emotional exchange. "
    "Advance through new action, conflict, revelation, or movement. "
    "Do not restate what has already been established."
)


def build_storylab_propulsion_block(controls: "StoryLabControls") -> str:
    """Build a settings-aware narrative propulsion block for StoryLab prompts.

    Always includes the core advancement directive. Adds control-specific
    addenda for fast/intense/sensual/long settings.

    Args:
        controls: The user's StoryLabControls for this generation.

    Returns:
        A short string (typically 2-4 sentences) for injection into the prompt.
        Never more than ~600 characters under normal conditions.
    """
    # Lazy import to avoid circular at module load time
    from app.schemas.storylab import Boundary, Direction, Length, Pacing, ToneIntensity

    parts = [_STORYLAB_PROPULSION_CORE]

    is_fast    = controls.pacing    == Pacing.fast
    is_intense = controls.tone_intensity == ToneIntensity.intense
    is_sensual = (
        controls.boundary in (Boundary.sensual, Boundary.fade_to_black)
        or controls.direction in (Direction.sensual_scene, Direction.intimate_scene, Direction.romantic_moment)
    )
    is_long    = controls.length == Length.long

    if is_fast or is_intense:
        parts.append(_FAST_INTENSE_ADDENDUM)

    if is_sensual:
        parts.append(_SENSUAL_ADDENDUM)

    if is_long:
        parts.append(_LONG_ADDENDUM)

    return "\n".join(parts)


def build_storylab_loop_correction_block() -> str:
    """Return a correction block for post-generation loop-detected retries."""
    return _LOOP_CORRECTION

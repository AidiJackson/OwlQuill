"""RP Narrative Engine — narrative propulsion and anti-loop orchestration.

Detects emotional looping, atmospheric repetition, stalled tension, floating dialogue,
and recursive attraction narration. Generates lightweight dynamic instruction blocks
to push scenes forward without over-orchestrating prose.

Public API
----------
detect_scene_mechanics(text)          — full mechanics analysis dict
detect_scene_progression_events(text) — extract specific progression events
detect_paragraph_monotony(text)       — paragraph purpose monotony analysis
determine_scene_forward_pressure(mechanics, events) — what guidance to inject
build_narrative_propulsion_block(partner_reply, canon_summary) — prompt block
"""
import re
from collections import Counter
from typing import Any


# ── detection patterns ────────────────────────────────────────────────────────

_MOVEMENT_PAT = re.compile(
    r'\b(?:moved?|steps?|stepped|crossed?|reaches?|reached|walked?|'
    r'stood\s+up|sat\s+down|knelt|leaned?|turned?|shifted?|repositioned?|'
    r'drifted?|backed?|advanced?|approached?|withdrew?|slid|slipped|spun|'
    r'pressed?\s+(?:forward|back|against)|circled?|paced?)\b',
    re.IGNORECASE,
)

_INTERACTION_PAT = re.compile(
    r'\b(?:touched?|grabbed?|pulled?|pushed?|pressed?|held?|gripped?|'
    r'kissed?|embraced?|caught?|guided?|dragged?|lifted?|lowered?|'
    r'hands?\s+on|fingers?\s+on|mouth\s+on|lips?\s+on|pressed?\s+against|'
    r'pulled?\s+closer|pinned?|trapped?|cornered?|reached?\s+for)\b',
    re.IGNORECASE,
)

_PROGRESSION_PAT = re.compile(
    r'\b(?:moved?|steps?|stepped|crossed?|reaches?|reached|grabbed?|'
    r'pulled?|pushed?|pressed?|lifted?|lowered?|turned?|slid|guided?|'
    r'shifted?|advanced?|withdrew?|stripped?|undid|removed?|placed?|'
    r'stood\s+up|knelt|sat|lay|fell|escalat\w*|deepened?|hardened?|'
    r'intensified?|kissed?|touched?|gripped?|leaned?\s+in|backed?\s+(?:him|her|away)|'
    r'pulled?\s+(?:him|her|them)\s+(?:in|close|toward|against))\b',
    re.IGNORECASE,
)

_ENVIRONMENT_PAT = re.compile(
    r'\b(?:wall|door|doorway|window|floor|ceiling|bed|table|chair|couch|'
    r'sofa|bar|counter|desk|stairs?|hallway|corridor|room|corner|'
    r'pool\s+cue|glass|bottle|cigarette|rain|darkness|light|shadow|'
    r'fireplace|mirror|shelf|curtain|balcony|railing|frame|threshold|'
    r'pillow|sheets?|mattress?|railing|banister|fence|hedge|car\s+seat|'
    r'dashboard|kitchen|bathroom|bedroom|living\s+room)\b',
    re.IGNORECASE,
)

_TENSION_PAT = re.compile(
    r'\b(?:tension|danger|dangerous|taut|tense|edge|dangerously|'
    r'charged|electric|volatile|precarious|fraught|on\s+edge|'
    r'dangerous\s+territory|dangerous\s+game)\b',
    re.IGNORECASE,
)

_ATTRACTION_PAT = re.compile(
    r'\b(?:attracted?|attraction|drawn\s+to|pull\s+toward|magnetic|'
    r'chemistry|heat\s+between|want(?:ed|ing)?\s+(?:him|her)|'
    r'couldn\'t\s+(?:help|deny|ignore)\s+(?:himself|herself|the)|'
    r'desire\s+for\s+(?:him|her)|feel(?:ing)?\s+the\s+pull)\b',
    re.IGNORECASE,
)

_HEARTBEAT_PAT = re.compile(
    r'\b(?:heartbeat|heart\s+beat|pulse\s+(?:raced?|quickened?|hammered?|'
    r'skipped?|stuttered?|pound\w*)|heart\s+(?:raced?|hammered?|quickened?|'
    r'pounded?|thudded?|stuttered?|skipped?))\b',
    re.IGNORECASE,
)

_STORM_PAT = re.compile(
    r'\b(?:storm|lightning|thunder|rain|cold\s+wind|darkness\s+outside|'
    r'tempest|gale|downpour|pouring\s+rain|pelting\s+rain)\b',
    re.IGNORECASE,
)

_EYE_PAT = re.compile(
    r'\b(?:his\s+eyes|her\s+eyes|their\s+eyes|his\s+gaze|her\s+gaze|'
    r'their\s+gaze|met\s+his\s+eyes|met\s+her\s+eyes|looked?\s+into\s+his|'
    r'looked?\s+into\s+her|darkened?\s+eyes|eyes\s+that|eyes\s+fixed|'
    r'burning\s+eyes|eyes\s+burn\w*|gaze\s+burn\w*|held?\s+(?:his|her)\s+gaze)\b',
    re.IGNORECASE,
)

_INTROSPECTION_PAT = re.compile(
    r'\b(?:felt|thought|knew|realized|wondered|decided|chose|wanted|needed|'
    r'longed|yearned|ached?|craved?|remembered?|recalled?|imagined?|'
    r'told\s+(?:herself|himself)|couldn\'t\s+(?:help|stop|ignore|deny|shake)|'
    r'part\s+of\s+(?:her|him)\s+(?:wanted|knew|wished)|something\s+in\s+(?:her|him))\b',
    re.IGNORECASE,
)

_DIALOGUE_PAT = re.compile(r'"[^"]{5,}"')

# Progression event patterns
_ESCALATION_PAT = re.compile(
    r'\b(?:kissed?|stripped?|undid|undressed?|unbutton\w*|'
    r'removed?\s+(?:her|his|the)\s+\w+|pressed?\s+against|'
    r'pulled?\s+(?:him|her|them)\s+(?:in|close|against|toward)|'
    r'trapped?|pinned?|cornered?|hands?\s+on\s+(?:her|his)|'
    r'fingers?\s+(?:found?|wrapped?|pressed?|traced?)|mouth\s+on|'
    r'lips?\s+on|touched?\s+(?:his|her)\s+\w+)\b',
    re.IGNORECASE,
)

_POWER_SHIFT_PAT = re.compile(
    r'\b(?:turned?\s+the\s+table|caught\s+(?:him|her)\s+off|'
    r'surprised?|unexpected\w*|reversed?|'
    r'backed?\s+(?:him|her)\s+(?:up|against|into)|cornered?|trapped?|'
    r'pulled?\s+away|pushed?\s+(?:him|her)\s+(?:away|back)|challenged?|'
    r'refused?|resisted?\s+(?:him|her)|stopped?\s+(?:him|her)|'
    r'turned?\s+(?:away|around)|stepped?\s+(?:back|away)\s+from)\b',
    re.IGNORECASE,
)

_SCENE_TRANSITION_PAT = re.compile(
    r'\b(?:walked?\s+(?:to|into|out|through|toward)|'
    r'moved?\s+(?:to|into|through|toward|away)|'
    r'led?\s+(?:him|her)\s+(?:to|into|through)|followed?\s+(?:him|her)|'
    r'crossed?\s+(?:to|the|into)|entered?|exited?|'
    r'stepped?\s+(?:into|out|through)|left\s+the\s+room)\b',
    re.IGNORECASE,
)

_REVELATION_PAT = re.compile(
    r'\b(?:told?\s+(?:him|her)|confessed?|admitted?|revealed?|'
    r'finally\s+said|said\s+it|let\s+(?:him|her)\s+(?:know|see)|'
    r'showed?\s+(?:him|her)|broke?\s+(?:the\s+silence|first|down)|'
    r'spoke\s+(?:the\s+truth|it\s+aloud))\b',
    re.IGNORECASE,
)


# ── paragraph purpose classification ─────────────────────────────────────────

def _classify_paragraph(para: str) -> str:
    """Classify a paragraph as action, dialogue, introspection, description, or mixed."""
    has_dialogue = bool(_DIALOGUE_PAT.search(para))
    action_hits = len(_PROGRESSION_PAT.findall(para))
    intro_hits = len(_INTROSPECTION_PAT.findall(para))
    env_hits = len(_ENVIRONMENT_PAT.findall(para))

    if has_dialogue and action_hits == 0 and intro_hits == 0:
        return "dialogue"
    if action_hits >= 2 and intro_hits <= 1:
        return "action"
    if intro_hits >= 2 and action_hits == 0:
        return "introspection"
    if env_hits >= 2 and action_hits == 0 and intro_hits <= 1 and not has_dialogue:
        return "description"
    return "mixed"


# ── public API ────────────────────────────────────────────────────────────────

def detect_scene_mechanics(text: str) -> dict[str, Any]:
    """Analyze text and return narrative mechanics metrics.

    Returns
    -------
    {
        progression_density: float      — action events per 100 words, 0-1
        interaction_density: float      — direct contact events per 100 words, 0-1
        movement_density: float         — positional change events per 100 words, 0-1
        environment_usage_density: float— environment object references per 100 words, 0-1
        dialogue_ratio: float           — fraction of text that is quoted dialogue, 0-1
        introspection_ratio: float      — introspective phrase density per 100 words, 0-1
        repeated_tension_count: int     — raw count of tension/danger vocabulary
        repeated_attraction_count: int  — raw count of attraction narration
        repeated_heartbeat_count: int   — raw count of heartbeat/pulse references
        repeated_storm_count: int       — raw count of storm/weather imagery
        repeated_eye_count: int         — raw count of eye/gaze descriptions
        floating_scene_risk: float      — high dialogue+low movement, 0-1
        static_scene_risk: float        — low progression overall, 0-1
        recursive_emotion_risk: float   — looped emotion without progression, 0-1
    }
    """
    word_count = max(1, len(text.split()))

    movement_hits     = len(_MOVEMENT_PAT.findall(text))
    interaction_hits  = len(_INTERACTION_PAT.findall(text))
    progression_hits  = len(_PROGRESSION_PAT.findall(text))
    environment_hits  = len(_ENVIRONMENT_PAT.findall(text))
    introspection_hits= len(_INTROSPECTION_PAT.findall(text))
    tension_hits      = len(_TENSION_PAT.findall(text))
    attraction_hits   = len(_ATTRACTION_PAT.findall(text))
    heartbeat_hits    = len(_HEARTBEAT_PAT.findall(text))
    storm_hits        = len(_STORM_PAT.findall(text))
    eye_hits          = len(_EYE_PAT.findall(text))

    # Per-100-word densities (normalised to 0–1)
    _per100 = 100.0 / word_count
    progression_density        = round(min(1.0, progression_hits  * _per100 / 10), 3)
    interaction_density        = round(min(1.0, interaction_hits   * _per100 / 8),  3)
    movement_density           = round(min(1.0, movement_hits      * _per100 / 8),  3)
    environment_usage_density  = round(min(1.0, environment_hits   * _per100 / 5),  3)
    introspection_ratio        = round(min(1.0, introspection_hits * _per100 / 12), 3)

    # Dialogue ratio: fraction of total characters inside quotes
    dialogue_chars = sum(len(m.group()) for m in _DIALOGUE_PAT.finditer(text))
    dialogue_ratio = round(min(1.0, dialogue_chars / max(1, len(text))), 3)

    # Risk composites
    floating_scene_risk = round(min(1.0, max(0.0,
        (dialogue_ratio * 0.3 + introspection_ratio * 0.3)
        - (movement_density * 0.4)
        - (environment_usage_density * 0.3)
    )), 3)

    static_scene_risk = round(min(1.0, max(0.0,
        1.0 - (progression_density * 0.5 + movement_density * 0.3 + interaction_density * 0.2)
    )), 3)

    recursive_emotion_risk = round(min(1.0, max(0.0,
        (introspection_ratio * 0.3
         + min(1.0, tension_hits / 4.0) * 0.25
         + min(1.0, attraction_hits / 3.0) * 0.25)
        - (progression_density * 0.3)
    )), 3)

    return {
        "progression_density":        progression_density,
        "interaction_density":        interaction_density,
        "movement_density":           movement_density,
        "environment_usage_density":  environment_usage_density,
        "dialogue_ratio":             dialogue_ratio,
        "introspection_ratio":        introspection_ratio,
        "repeated_tension_count":     tension_hits,
        "repeated_attraction_count":  attraction_hits,
        "repeated_heartbeat_count":   heartbeat_hits,
        "repeated_storm_count":       storm_hits,
        "repeated_eye_count":         eye_hits,
        "floating_scene_risk":        floating_scene_risk,
        "static_scene_risk":          static_scene_risk,
        "recursive_emotion_risk":     recursive_emotion_risk,
    }


def detect_scene_progression_events(text: str) -> dict[str, Any]:
    """Extract scene progression events from text.

    Returns
    -------
    {
        progression_event_count: int
        escalation_detected: bool
        power_shift_detected: bool
        scene_transition_detected: bool
        environment_transition_detected: bool
        events: list[str]
    }
    """
    escalation_hits  = len(_ESCALATION_PAT.findall(text))
    power_shift_hits = len(_POWER_SHIFT_PAT.findall(text))
    transition_hits  = len(_SCENE_TRANSITION_PAT.findall(text))
    revelation_hits  = len(_REVELATION_PAT.findall(text))

    events: list[str] = []
    if escalation_hits >= 1:
        events.append(f"physical_escalation ({escalation_hits})")
    if power_shift_hits >= 1:
        events.append(f"power_shift ({power_shift_hits})")
    if transition_hits >= 1:
        events.append(f"scene_transition ({transition_hits})")
    if revelation_hits >= 1:
        events.append(f"emotional_revelation ({revelation_hits})")

    return {
        "progression_event_count":     escalation_hits + power_shift_hits + transition_hits + revelation_hits,
        "escalation_detected":         escalation_hits >= 1,
        "power_shift_detected":        power_shift_hits >= 1,
        "scene_transition_detected":   transition_hits >= 1,
        "environment_transition_detected": transition_hits >= 1,
        "events":                      events,
    }


def detect_paragraph_monotony(text: str) -> dict[str, Any]:
    """Detect paragraph purpose monotony — consecutive same-type paragraphs.

    Returns
    -------
    {
        paragraph_count: int
        monotony_score: float       — 0 = fully varied, 1 = all same type
        dominant_type: str          — most common paragraph purpose
        max_consecutive_same_type: int
        type_sequence: list[str]
    }
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return {
            "paragraph_count":           len(paragraphs),
            "monotony_score":            0.0,
            "dominant_type":             "unknown",
            "max_consecutive_same_type": 0,
            "type_sequence":             [],
        }

    purposes = [_classify_paragraph(p) for p in paragraphs]

    max_run = 1
    current_run = 1
    for i in range(1, len(purposes)):
        if purposes[i] == purposes[i - 1] and purposes[i] != "mixed":
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1

    dominant_type = Counter(purposes).most_common(1)[0][0]
    monotony_score = round(min(1.0, (max_run - 1) / max(1, len(paragraphs) - 1)), 3)

    return {
        "paragraph_count":           len(paragraphs),
        "monotony_score":            monotony_score,
        "dominant_type":             dominant_type,
        "max_consecutive_same_type": max_run,
        "type_sequence":             purposes,
    }


def determine_scene_forward_pressure(
    mechanics: dict[str, Any],
    events: dict[str, Any],
) -> str:
    """Return a short instruction string (0–3 sentences) based on detected scene state.

    Empty string when no specific pressure is needed.
    """
    parts: list[str] = []

    if mechanics["recursive_emotion_risk"] > 0.5:
        parts.append(
            "The emotional groundwork is laid — move the scene forward rather than restating it."
        )
    if mechanics["floating_scene_risk"] > 0.5:
        parts.append(
            "Root the scene in physical space: reposition characters, use the environment, interact with objects."
        )
    if mechanics["repeated_attraction_count"] >= 3:
        parts.append(
            "Attraction and chemistry are established — escalate the interaction rather than describing them again."
        )
    if mechanics["repeated_tension_count"] >= 4:
        parts.append(
            "Tension has been named repeatedly — resolve it, escalate it, or shift the dynamic instead."
        )
    if mechanics["static_scene_risk"] > 0.6:
        parts.append(
            "Push the scene to materially change: a decision, a touch, a revelation, or a repositioning."
        )
    if not events["escalation_detected"] and not events["scene_transition_detected"]:
        if mechanics["progression_density"] < 0.2:
            parts.append(
                "No significant scene events yet — introduce a physical or emotional escalation."
            )
    if mechanics["repeated_heartbeat_count"] >= 3:
        parts.append("Heartbeat/pulse has been used repeatedly — find a fresh physical response.")
    if mechanics["repeated_eye_count"] >= 4:
        parts.append("Eye and gaze descriptions are overused — vary the sensory focus.")

    # Cap at 3 to stay lightweight
    return " ".join(parts[:3])


def build_narrative_propulsion_block(
    partner_reply: str,
    canon_summary: str = "",
) -> str:
    """Generate a lightweight narrative propulsion instruction block.

    Analyzes the partner reply (and optional prior context) to determine dynamic
    guidance. The block is intentionally SHORT — 4 core rules plus up to 3 sentences
    of scene-specific pressure.

    IMPORTANT: This block is for RP Reply generation only. It must not appear
    in StoryLab chapter prompts (see test_storylab_create_story_isolation.py).
    """
    combined = (canon_summary + "\n" + partner_reply).strip()
    mechanics = detect_scene_mechanics(combined)
    events    = detect_scene_progression_events(combined)
    pressure  = determine_scene_forward_pressure(mechanics, events)

    core = (
        "- Advance the interaction each paragraph — do not re-describe attraction, chemistry, "
        "or tension that is already established.\n"
        "- Every 2–4 paragraphs should materially change scene state: "
        "a movement, touch, spoken line, revelation, or power shift.\n"
        "- Vary paragraph purpose: alternate action, dialogue, movement, observation, escalation.\n"
        "- Use physical environment — place characters in space, interact with objects and geography."
    )

    if pressure:
        return core + "\n" + pressure
    return core

"""RP Scene Beat Engine — scene-aware progression orchestration layer.

Understands what emotional and physical beats have already occurred in a scene,
detects regression/repetition, and generates targeted next-beat guidance.

This is NOT a censorship layer.
Explicitness remains fully permitted in Inferno mode.
The goal is better collaborative pacing and elimination of repetitive loops.

Provides
--------
detect_scene_beats(text)             — structured dict of completed emotional/physical beats
detect_repeated_beats(reply, prior)  — repetition detection between reply and prior text
determine_next_scene_goal(stage)     — next natural beat + list of forbidden regressions
build_scene_progression_block(...)   — dynamic high-priority prompt block for injection
detect_scene_regression(reply, prior)— regression flags: looping, confession repeat, etc.
"""
import re


# ── Scene stage sequence ──────────────────────────────────────────────────────

SCENE_STAGES: list[str] = [
    "tension",
    "confession",
    "first_touch",
    "kissing",
    "heavy_makeout",
    "undressing",
    "oral",
    "intercourse",
    "aftercare",
]

# Next beat map: current stage → natural next beat
_NEXT_BEAT_MAP: dict[str, str] = {
    "tension":      "confession",
    "confession":   "first_touch",
    "first_touch":  "kissing",
    "kissing":      "heavy_makeout",
    "heavy_makeout":"undressing",
    "undressing":   "oral",
    "oral":         "intercourse",
    "intercourse":  "emotional escalation",
    "aftercare":    "vulnerability",
}

# Forbidden regressions per stage — beats already completed that should not restart
_FORBIDDEN_REGRESSIONS: dict[str, list[str]] = {
    "tension":      [],
    "confession":   ["repeated danger warnings", "repeated 'you should fear me' speeches"],
    "first_touch":  ["repeated emotional confessions", "repeated danger warnings"],
    "kissing":      ["repeated emotional confessions", "returning to pure tension without physical progression"],
    "heavy_makeout":["returning to first_touch", "repeated protection speeches"],
    "undressing":   ["returning to kissing without escalation", "repeated possession dialogue"],
    "oral":         ["returning to undressing loop", "repeated possessive monologue"],
    "intercourse":  ["returning to oral without reason", "repeated emotional confessions mid-act"],
    "aftercare":    ["returning to intercourse", "restarting emotional confessions"],
}


# ── 1. detect_scene_beats ─────────────────────────────────────────────────────

# Beat detection patterns — heuristic, not exhaustive
_BEAT_PATTERNS: dict[str, list[re.Pattern]] = {
    "confession_complete": [
        re.compile(
            r'\b(?:I(?:\'ve)?\s+(?:wanted|needed|loved|felt)|'
            r'truth\s+is|I\s+(?:admit|confess|can\'t\s+deny|can\'t\s+pretend)|'
            r'I\'ve\s+(?:always|never\s+stopped)|can\'t\s+stop\s+(?:thinking|wanting)|'
            r'admitted|confessed|told\s+(?:her|him|them)\s+(?:the\s+truth|everything))\b',
            re.IGNORECASE,
        ),
    ],
    "trust_established": [
        re.compile(
            r'\b(?:I\s+trust\s+you|trusted\s+(?:him|her|them)|safe\s+with\s+(?:him|her|them)|'
            r'wouldn\'t\s+hurt|won\'t\s+hurt|(?:he|she|they)\s+(?:is|was)\s+safe|'
            r'could\s+(?:trust|believe)\s+(?:him|her|them))\b',
            re.IGNORECASE,
        ),
    ],
    "first_kiss_complete": [
        re.compile(
            r'\b(?:kissed|lips\s+(?:met|pressed|found|brushed)|first\s+kiss|'
            r'mouth\s+(?:on|against|found)|pressed\s+(?:his|her|their)\s+lips)\b',
            re.IGNORECASE,
        ),
    ],
    "physical_escalation_started": [
        re.compile(
            r'\b(?:pulled\s+(?:him|her|them)\s+closer|hands\s+(?:slid|moved|traveled)|'
            r'pressed\s+(?:against|into|her|him|them)|grind|hip[s]?\s+against|'
            r'undress|shirt\s+(?:off|removed)|bare\s+(?:skin|chest|shoulder)|'
            r'stripped|unbutton|zipper|clasp)\b',
            re.IGNORECASE,
        ),
    ],
    "explicit_contact_started": [
        re.compile(
            r'\b(?:cock|clit|pussy|erection|throbbing|wetness|slick|'
            r'inside\s+(?:her|him|them)|between\s+(?:her|his|their)\s+legs|'
            r'spread|thrust|penetrat|oral|went\s+down\s+on)\b',
            re.IGNORECASE,
        ),
    ],
    "dominance_dynamic_present": [
        re.compile(
            r'\b(?:mine|you\'re\s+mine|belong\s+to\s+me|possession|possessive|'
            r'commanded|ordered|pinned|held\s+(?:her|him|them)\s+(?:down|still|against)|'
            r'dominant|submit|submission|on\s+(?:her|his|their)\s+knees)\b',
            re.IGNORECASE,
        ),
    ],
    "emotional_resistance_present": [
        re.compile(
            r'\b(?:shouldn\'t|can\'t\s+do\s+this|wrong|mistake|should\s+stop|'
            r'pushed\s+(?:him|her|them)\s+away|step\s+back|pulled\s+away|'
            r'hesitat|resist|this\s+(?:is|was)\s+(?:wrong|a\s+mistake))\b',
            re.IGNORECASE,
        ),
    ],
    "protective_language_present": [
        re.compile(
            r'\b(?:keep\s+(?:you|her|him)\s+safe|protect\s+(?:you|her|him)|'
            r'I\s+won\'t\s+(?:let|allow)|nothing\s+will\s+happen|'
            r'keep\s+(?:her|him|them)\s+from|shield|guard)\b',
            re.IGNORECASE,
        ),
    ],
    "possessive_language_present": [
        re.compile(
            r'\b(?:mine|you\'re\s+mine|she\'s\s+mine|he\'s\s+mine|'
            r'belongs\s+to\s+(?:me|him|her)|claim|claimed|marking|'
            r'mine\s+to\s+(?:protect|have|keep|touch))\b',
            re.IGNORECASE,
        ),
    ],
}

# Scene stage detection — ordered most advanced to least
_STAGE_DETECTION: list[tuple[str, list[re.Pattern]]] = [
    ("aftercare", [re.compile(
        r'\b(?:afterglow|lay\s+together|curled\s+(?:against|together)|'
        r'pulse\s+slowed|breathing\s+steadied|in\s+the\s+quiet\s+after|'
        r'came\s+down|skin\s+still\s+warm)\b',
        re.IGNORECASE,
    )]),
    ("intercourse", [re.compile(
        r'\b(?:inside\s+(?:her|him|them)|thrust(?:ed|ing)?|penetrat|'
        r'rode|riding|hips\s+(?:moving|rocking|snapping)|'
        r'(?:cock|length|shaft)\s+(?:inside|deep|buried))\b',
        re.IGNORECASE,
    )]),
    ("oral", [re.compile(
        r'\b(?:went\s+down\s+on|mouth\s+on\s+(?:her|his|their)|'
        r'tongue\s+(?:between|against|on)\s+(?:her|his|their)|'
        r'oral|on\s+(?:her|his|their)\s+knees\s+before|'
        r'lick(?:ed|ing)|suck(?:ed|ing))\b',
        re.IGNORECASE,
    )]),
    ("undressing", [re.compile(
        r'\b(?:undress|stripped|shirt\s+(?:off|gone|removed)|'
        r'bare\s+(?:chest|skin|stomach|shoulder[s]?)|'
        r'unbutton|unhook|clasp\s+(?:undone|open)|zipper|'
        r'naked|nude|without\s+(?:a\s+shirt|clothes|anything\s+on))\b',
        re.IGNORECASE,
    )]),
    ("heavy_makeout", [re.compile(
        r'\b(?:grind(?:ed|ing)?|hip[s]?\s+against|pressed\s+(?:her|him|them)\s+against|'
        r'thigh\s+between|hands\s+(?:slid|moved|traveled|roamed)|'
        r'deepened\s+(?:the\s+kiss|it)|pulled\s+closer|body\s+against)\b',
        re.IGNORECASE,
    )]),
    ("kissing", [re.compile(
        r'\b(?:kiss(?:ed|ing)?|lips\s+(?:met|pressed|found|brushed|parted)|'
        r'mouth\s+(?:on|against|found|covered)|'
        r'pressed\s+(?:his|her|their)\s+lips|breath\s+(?:mixing|on\s+(?:her|his|their)\s+lips))\b',
        re.IGNORECASE,
    )]),
    ("first_touch", [re.compile(
        r'\b(?:touch(?:ed)?|reached\s+for|hand\s+on|fingers\s+(?:brushed|grazed|traced)|'
        r'closed\s+the\s+distance|inches\s+away|close\s+enough\s+to\s+(?:feel|touch))\b',
        re.IGNORECASE,
    )]),
    ("confession", [re.compile(
        r'\b(?:I\s+(?:want|need|love|feel|admit|confess)|'
        r'truth\s+is|can\'t\s+(?:deny|pretend|hide)|'
        r'admitted|confessed|told\s+(?:her|him|them))\b',
        re.IGNORECASE,
    )]),
]


def detect_scene_beats(text: str) -> dict:
    """Detect which narrative and physical beats are present in text.

    Scans the combined scene context (prior_text + partner_reply) to build
    a structured picture of what has already happened. Uses heuristic keyword
    patterns — not perfect, but sufficient to prevent obvious regression.

    Returns
    -------
    {
        "confession_complete": bool,
        "trust_established": bool,
        "first_kiss_complete": bool,
        "physical_escalation_started": bool,
        "explicit_contact_started": bool,
        "dominance_dynamic_present": bool,
        "emotional_resistance_present": bool,
        "protective_language_present": bool,
        "possessive_language_present": bool,
        "scene_stage": str  — most advanced stage detected
    }
    """
    results: dict[str, bool] = {}

    for beat_key, patterns in _BEAT_PATTERNS.items():
        results[beat_key] = any(p.search(text) for p in patterns)

    # ── scene stage ───────────────────────────────────────────────────────────
    scene_stage = "tension"
    for stage, patterns in _STAGE_DETECTION:
        if any(p.search(text) for p in patterns):
            scene_stage = stage
            break

    return {**results, "scene_stage": scene_stage}


# ── 2. detect_repeated_beats ──────────────────────────────────────────────────

_CLICHE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("danger_warning", re.compile(
        r'\b(?:I\'m\s+(?:dangerous|not\s+(?:safe|good)\s+for\s+you)|'
        r'you\s+should\s+(?:fear|run\s+from|be\s+afraid\s+of)\s+me|'
        r'I\'m\s+a\s+(?:monster|danger|threat)|'
        r'stay\s+away\s+from\s+me|I\'ll\s+only\s+hurt\s+you)\b',
        re.IGNORECASE,
    )),
    ("trust_speech", re.compile(
        r'\b(?:I\s+(?:would\s+never|won\'t)\s+hurt\s+you|'
        r'you\s+can\s+trust\s+me|I\s+(?:promise|swear)\s+(?:I\s+won\'t|to\s+keep)|'
        r'safe\s+with\s+me|you\'re\s+safe\s+(?:here|with\s+me))\b',
        re.IGNORECASE,
    )),
    ("emotional_hesitation", re.compile(
        r'\b(?:we\s+shouldn\'t|this\s+(?:is\s+)?(?:wrong|a\s+mistake)|'
        r'(?:I\s+)?can\'t\s+do\s+this|this\s+(?:can\'t|shouldn\'t)\s+happen|'
        r'we\s+can\'t\s+(?:keep\s+doing\s+this|do\s+this))\b',
        re.IGNORECASE,
    )),
    ("storm_narration", re.compile(
        r'\b(?:the\s+storm|lightning\s+(?:split|flashed|cracked)|thunder\s+(?:rolled|rumbled)|'
        r'rain\s+(?:against|on)\s+the\s+(?:window|glass|roof)|'
        r'the\s+rain\s+(?:fell|hammered|drummed))\b',
        re.IGNORECASE,
    )),
    ("eye_color_narration", re.compile(
        r'\b(?:(?:his|her|their)\s+(?:dark|green|blue|brown|grey|gray|amber|gold|silver|black|hazel|violet)\s+eyes|'
        r'(?:dark|green|blue|brown|grey|gray|amber|gold|silver|black)\s+(?:irises?|pupils?)|'
        r'eyes\s+(?:the\s+color|like\s+(?:the\s+sea|emeralds?|steel)))\b',
        re.IGNORECASE,
    )),
    ("possession_line", re.compile(
        r'\b(?:(?:you\'re|she\'s|he\'s)\s+mine|'
        r'belong[s]?\s+to\s+me|'
        r'mine\s+(?:to\s+(?:take|keep|have|protect|touch)|and\s+only\s+mine)|'
        r'I\s+(?:own|claimed?)\s+(?:you|her|him))\b',
        re.IGNORECASE,
    )),
    ("protection_speech", re.compile(
        r'\b(?:I\'ll\s+(?:keep|protect)\s+(?:you|her|him)\s+safe|'
        r'nothing\s+(?:will|can)\s+(?:touch|hurt)\s+(?:you|her|him)|'
        r'I\s+(?:protect|keep)\s+what\'s\s+mine|'
        r'over\s+my\s+(?:dead\s+)?body)\b',
        re.IGNORECASE,
    )),
    ("breathing_narration", re.compile(
        r'\b(?:(?:her|his|their)\s+breath\s+(?:caught|hitched|quickened|came\s+in\s+short)|'
        r'breathless(?:ly)?|the\s+sound\s+of\s+(?:her|his)\s+breathing|'
        r'breathing\s+(?:hard|fast|heavily|unevenly))\b',
        re.IGNORECASE,
    )),
]


def detect_repeated_beats(reply: str, prior_text: str) -> dict:
    """Detect which clichéd or repetitive beat patterns appear in the reply.

    When prior_text is non-empty: flags patterns present in BOTH reply AND prior_text
    (cross-turn repetition detection).

    When prior_text is empty: falls back to within-reply detection — flags patterns
    that appear 2+ times inside the reply itself, catching single-turn repetition.

    Returns
    -------
    {
        "repeated_beats":   list[str]  — names of beat categories repeated
        "repetition_score": float      — 0.0–1.0, higher = more repeated
    }
    """
    repeated_beats: list[str] = []
    cross_turn_mode = bool(prior_text and prior_text.strip())

    for beat_name, pattern in _CLICHE_PATTERNS:
        if cross_turn_mode:
            in_prior = bool(pattern.search(prior_text))
            in_reply = bool(pattern.search(reply))
            if in_prior and in_reply:
                repeated_beats.append(beat_name)
        else:
            # Fallback: 2+ hits within the reply alone = within-turn repetition
            reply_hits = len(pattern.findall(reply))
            if reply_hits >= 2:
                repeated_beats.append(beat_name)

    repetition_score = round(min(1.0, len(repeated_beats) / max(1, len(_CLICHE_PATTERNS))), 3)

    return {
        "repeated_beats": repeated_beats,
        "repetition_score": repetition_score,
    }


# ── 3. determine_next_scene_goal ──────────────────────────────────────────────

def determine_next_scene_goal(scene_stage: str) -> dict:
    """Return the recommended next beat for the current scene stage.

    Returns
    -------
    {
        "next_goal":              str        — natural next story beat
        "forbidden_regressions":  list[str]  — completed beats not to restart
    }
    """
    next_goal = _NEXT_BEAT_MAP.get(scene_stage, "deepen current stage")
    forbidden = _FORBIDDEN_REGRESSIONS.get(scene_stage, [])
    return {
        "next_goal": next_goal,
        "forbidden_regressions": forbidden,
    }


# ── 4. build_scene_progression_block ─────────────────────────────────────────

def build_scene_progression_block(
    scene_stage: str,
    beats: dict,
    next_goal: str,
    repeated_beats: list[str],
    heat_level: str = "flame",
) -> str:
    """Build a dynamic, high-priority scene progression prompt block.

    Tailored to what has already happened and what should happen next.
    Injected VERY HIGH in prompt priority, before behavior enforcement.
    """
    lines: list[str] = [
        "SCENE BEAT ENGINE — HIGH PRIORITY:",
        f"Current scene stage: {scene_stage}",
        f"Recommended next beat: {next_goal}",
        "",
        "SCENE RULES:",
        "- Do NOT restart already completed emotional beats.",
        "- Do NOT repeat emotional confessions unless meaningfully escalated.",
        "- Do NOT repeatedly narrate storm/eyes/breathing without scene advancement.",
        "- EVERY 1–2 paragraphs must introduce NEW progression.",
        "- Scene momentum must move FORWARD, not cycle back.",
        "- Avoid repetitive possessive dialogue ('you're mine' etc).",
        "- Avoid repetitive protective speeches.",
        "- Avoid generic romance filler — continue the interaction already in progress.",
        "- Physical escalation must follow believable sequencing.",
    ]

    if heat_level == "inferno":
        lines.append("- Explicit acts are permitted and encouraged — do not euphemize.")

    lines += [
        "- NEVER force the partner character to orgasm, speak, consent, climax, or emotionally react.",
        "- The partner character is collaborative space — their agency is theirs alone.",
    ]

    # Completed beats — do not regress
    completed: list[str] = []
    if beats.get("confession_complete"):
        completed.append("emotional confession")
    if beats.get("first_kiss_complete"):
        completed.append("first kiss")
    if beats.get("physical_escalation_started"):
        completed.append("physical escalation begun")
    if beats.get("explicit_contact_started"):
        completed.append("explicit contact begun")
    if beats.get("trust_established"):
        completed.append("trust established")

    if completed:
        lines.append("")
        lines.append(f"Already completed — do not regress to: {', '.join(completed)}.")

    # Repeated beats warning
    if repeated_beats:
        lines.append("")
        lines.append(
            "DETECTED REPETITION — avoid repeating these in this reply: "
            + ", ".join(rb.replace("_", " ") for rb in repeated_beats)
            + "."
        )

    # Forbidden regressions for this stage
    forbidden = _FORBIDDEN_REGRESSIONS.get(scene_stage, [])
    if forbidden:
        lines.append("")
        lines.append("Forbidden regressions at this stage: " + "; ".join(forbidden) + ".")

    return "\n".join(lines)


# ── 5. detect_scene_regression ────────────────────────────────────────────────

_LOOP_PATTERNS: dict[str, re.Pattern] = {
    "emotional_looping": re.compile(
        r'\b(?:ached|longed|yearned|hungered|craved)\b',
        re.IGNORECASE,
    ),
    "repeated_confession": re.compile(
        r'\b(?:I\s+(?:love|want|need)\s+(?:you|her|him)|'
        r'I(?:\'ve)?\s+(?:always|never\s+stopped)\s+(?:wanting|loving|needing))\b',
        re.IGNORECASE,
    ),
    "repetitive_possessiveness": re.compile(
        r'\b(?:(?:you\'re|she\'s|he\'s)\s+mine|belong[s]?\s+to\s+me|claimed?)\b',
        re.IGNORECASE,
    ),
    "atmospheric_stalling": re.compile(
        r'\b(?:the\s+storm|lightning|thunder|the\s+rain|the\s+darkness|'
        r'the\s+cold|the\s+silence\s+(?:between|that)\b)\b',
        re.IGNORECASE,
    ),
}

# Minimum threshold per loop category before flagging
_LOOP_THRESHOLDS: dict[str, int] = {
    "emotional_looping":          3,
    "repeated_confession":        2,
    "repetitive_possessiveness":  2,
    "atmospheric_stalling":       3,
}


def detect_scene_regression(reply: str, prior_text: str) -> dict:
    """Detect regression/looping patterns in the reply relative to prior text.

    Returns
    -------
    {
        "emotional_looping":          bool
        "repeated_confession":        bool
        "repetitive_possessiveness":  bool
        "atmospheric_stalling":       bool
        "progression_failure":        bool  — True if reply fails to advance
        "regression_flags":           list[str]
    }
    """
    flags: list[str] = []
    results: dict[str, bool] = {}

    for flag_name, pattern in _LOOP_PATTERNS.items():
        threshold = _LOOP_THRESHOLDS[flag_name]
        reply_hits = len(pattern.findall(reply))
        prior_hits = len(pattern.findall(prior_text))
        triggered = reply_hits >= threshold or (reply_hits >= 1 and prior_hits >= threshold)
        results[flag_name] = triggered
        if triggered:
            flags.append(flag_name)

    # progression_failure: low action/dialogue/reversal signals with meaningful stall score.
    # Threshold raised from 0.05 → 0.20 to catch genuinely stalled replies (not just stub output).
    from app.services.rp_behavior_engine import detect_scene_stall
    stall = detect_scene_stall(reply)
    progression_failure = stall["progression_score"] < 0.20 and stall["scene_stall_score"] > 0.3

    results["progression_failure"] = progression_failure
    if progression_failure:
        flags.append("progression_failure")

    results["regression_flags"] = flags
    return results

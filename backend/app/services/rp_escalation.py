"""RP Reply escalation engine — unified 9-stage canonical scene system.

Provides:
  RP_HEAT_PROFILES          — heat profile definitions (embers / flame / inferno)
  get_heat_prompt_block()   — returns the prose instruction block for a heat level
  CANONICAL_STAGES          — the single authoritative stage list used everywhere
  compute_scene_stage()     — maps text to a canonical stage name
  detect_scene_resolution() — checks whether the reply has resolved the scene
  score_collaborative_continuation() — 0–1 float; 1.0 = maximum continuation space
  get_pacing_warnings()     — non-blocking diagnostic warnings

Philosophy
----------
This is NOT censorship — it is pacing / orchestration.
We support dark romance, mature intimacy, emotional obsession, and possessive dynamics.
What we protect is: agency, pacing, turn structure, and the partner's space to write back.

Stage system (canonical, 9 stages — ordered from least to most advanced):
  tension → confession → first_touch → kissing → heavy_makeout →
  undressing → oral → intercourse → aftercare
"""
import re

# ── canonical stage system ─────────────────────────────────────────────────────

CANONICAL_STAGES: tuple[str, ...] = (
    "tension",
    "confession",
    "first_touch",
    "kissing",
    "heavy_makeout",
    "undressing",
    "oral",
    "intercourse",
    "aftercare",
)

_STAGE_RANK: dict[str, int] = {s: i for i, s in enumerate(CANONICAL_STAGES)}

# ── heat profiles ─────────────────────────────────────────────────────────────

RP_HEAT_PROFILES: dict[str, dict] = {
    "embers": {
        "label": "Embers",
        "allow_explicit_anatomy": False,
        "allow_explicit_acts": False,
        "max_stage": "kissing",
        "prompt_block": (
            "HEAT — EMBERS: slow burn, controlled longing.\n"
            "- Write restraint, not release. The power is in what is withheld.\n"
            "- Longing, charged proximity, deliberate touches, and possessive tension are your tools.\n"
            "- Kisses, if they appear, are weighted with restraint — not an ending, a beginning.\n"
            "- Do NOT write explicit anatomy. Do NOT write explicit sexual acts.\n"
            "- Emotional pressure and unspoken desire carry more charge than explicit action.\n"
            "- The scene should feel like held breath — the reader should feel the heat, not see it burn."
        ),
    },
    "flame": {
        "label": "Flame",
        "allow_explicit_anatomy": False,
        "allow_explicit_acts": False,
        "max_stage": "undressing",
        "prompt_block": (
            "HEAT — FLAME: mature intimacy, escalating but unresolved.\n"
            "- Heavier physicality is permitted: stronger touching, partial undressing, "
            "grinding, sensual body detail, heightened possessiveness.\n"
            "- Some mature vocabulary is allowed. Sensation and implication over clinical description.\n"
            "- Escalation is allowed, but the encounter must remain unresolved. "
            "Do NOT write orgasm completion. Do NOT fully close the encounter.\n"
            "- Preserve pacing and collaborative turn space — the scene is mid-motion, not finished.\n"
            "- The partner must still have something meaningful to respond to."
        ),
    },
    "inferno": {
        "label": "Inferno",
        "allow_explicit_anatomy": True,
        "allow_explicit_acts": True,
        "max_stage": "intercourse",
        "prompt_block": (
            "HEAT — INFERNO: explicit erotic prose.\n"
            "- Explicit body terminology, explicit sexual escalation, and graphic detail are permitted.\n"
            "- Write with literary intention — heat should emerge from character and tension, "
            "not mechanical description.\n"
            "STILL REQUIRED:\n"
            "- Do NOT narrate the partner character's climax or full surrender unless they explicitly "
            "initiated it in their last reply.\n"
            "- Do NOT fully resolve the encounter. Leave momentum and continuation space intact.\n"
            "- Do NOT override the partner character's agency entirely — their consent and choices "
            "remain their own.\n"
            "- The scene must continue, not conclude."
        ),
    },
}

_VALID_HEAT_LEVELS: frozenset[str] = frozenset(RP_HEAT_PROFILES.keys())


def get_heat_prompt_block(heat_level: str) -> str:
    """Return the prose instruction block for the given heat level.

    Falls back to 'flame' for unknown values.
    """
    profile = RP_HEAT_PROFILES.get(heat_level, RP_HEAT_PROFILES["flame"])
    return profile["prompt_block"]


# ── scene stage detection (unified 9-stage system) ─────────────────────────────

# Ordered from most-advanced to least; first match wins.
_STAGE_PATTERNS: list[tuple[str, list[str]]] = [
    ("aftercare", [
        r'\b(?:afterglow|lay together|curled together|pulse slowed|breathing steadied|'
        r'exhausted silence|they lay|wrapped around each other|came down from|'
        r'skin still warm|breath finally settling|heartbeat slow|in the quiet after|'
        r'lay tangled|held (?:her|him|them) after)\b',
    ]),
    ("intercourse", [
        r'\b(?:thrust(?:ed|ing)?|penetrat|inside (?:her|him|them)|'
        r'spread her|spread his|between (?:her|his|their) legs|'
        r'drove (?:into|deeper)|hips (?:rolling|snapping|moving|against)|'
        r'cock|pussy|clit|filling (?:her|him|them)|took (?:her|him|them)\b)\b',
    ]),
    ("oral", [
        r'\b(?:mouth on (?:her|him|them)|lips around|knelt between|'
        r'tongue (?:against|along|over|inside)|went down on|'
        r'face between|pressed (?:his|her|their) mouth (?:lower|down|between))\b',
    ]),
    ("undressing", [
        r'\b(?:undress|unbutton(?:ed|ing)?|shirt off|took (?:his|her|their) shirt|'
        r'bare(?:d| skin| shoulder| chest| stomach| back| thigh)|'
        r'grind(?:ed|ing)?|hip(?:s)? against|thigh(?:s)? between|'
        r'hands slipped|hands moved lower|slid (?:his|her|their) hands?|'
        r'stripped|removed (?:his|her|their)|zipper|clasp|hook|'
        r'pulled (?:the shirt|the dress|her dress|his shirt) (?:off|up|open))\b',
    ]),
    ("heavy_makeout", [
        r'\b(?:pressed (?:him|her|them) against|pulled (?:him|her|them) closer|'
        r'bodies pressed|hands on (?:his|her|their) (?:waist|hips|chest|back)|'
        r'deepened the kiss|teeth|bit|nipped|'
        r'breathless|gasping|panting|breath coming faster|'
        r'fingers in (?:his|her|their) hair|'
        r'pressed (?:hard|closer|tight) against)\b',
    ]),
    ("kissing", [
        r'\b(?:kiss(?:ed|ing)?|lips (?:met|pressed|brushed|grazed|parted|touched)|'
        r'mouth (?:on|against|found)|pressed (?:his|her|their) lips|'
        r'noses? (?:almost|nearly|just) touching|'
        r'forehead against|leaned in|breath on)\b',
    ]),
    ("first_touch", [
        r'\b(?:hand(?:s)? on (?:his|her|their)|touched|reached for|'
        r'fingers (?:grazed|brushed|traced|found)|'
        r'held (?:his|her|their) (?:hand|wrist|arm|face)|embrace[d]?|'
        r'close enough to|cheek against|pulled (?:him|her|them) in|'
        r'caught (?:his|her|their) wrist|drew (?:him|her|them) close)\b',
    ]),
    ("confession", [
        r'\b(?:told (?:him|her|them) (?:the truth|everything|what she|what he|how she|how he)|'
        r'admitted|confessed|said it (?:aloud|out loud)|couldn\'t lie|'
        r'finally said|said (?:his|her|their) name|I (?:love|need|want) you|'
        r'I\'ve (?:wanted|needed)|been wanting to)\b',
    ]),
]


def compute_scene_stage(reply_text: str) -> str:
    """Return the most advanced canonical scene stage detected in the reply.

    Uses the unified 9-stage system:
    tension → confession → first_touch → kissing → heavy_makeout →
    undressing → oral → intercourse → aftercare
    """
    text_lower = reply_text.lower()
    for stage, patterns in _STAGE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return stage
    return "tension"


# ── resolution detection ──────────────────────────────────────────────────────

_RESOLUTION_PATTERNS: list[tuple[str, str]] = [
    (
        r'\b(?:came\b|climaxed|fell apart|cried out in|shattered|shook apart|'
        r'exploded|broke apart|came undone|came together|came hard|'
        r'body gave way|lost control completely)\b',
        "orgasm completion detected",
    ),
    (
        r'\b(?:finally together|finally his\b|finally hers\b|finally theirs\b|'
        r'everything was (?:right|perfect|as it should)|all was finally)\b',
        "emotional closure language",
    ),
    (
        r'\b(?:everything faded|world dissolved|nothing else mattered|'
        r'scene (?:complete|over|done)|they were complete|it was over|'
        r'all was done|had what (?:he|she|they) (?:wanted|needed))\b',
        "scene dissolution language",
    ),
    (
        r'\b(?:lay (?:there|together|tangled)|lay in the afterglow|'
        r'caught (?:his|her|their) breath|breathing slowed|pulse (?:settled|quieted|calmed)|'
        r'heartbeat (?:slowing|steadied|calmed)|in the quiet after)\b',
        "post-act recovery framing",
    ),
    (
        r'\b(?:the end|and that was it|and so it (?:was|ended)|nothing more to say|'
        r'there was nothing left)\b',
        "explicit scene closure",
    ),
]


def detect_scene_resolution(reply_text: str) -> dict:
    """Detect whether the reply has resolved the scene.

    Returns:
        {"resolved": bool, "reasons": list[str]}
    """
    reasons: list[str] = []
    for pattern, reason in _RESOLUTION_PATTERNS:
        if re.search(pattern, reply_text, re.IGNORECASE):
            reasons.append(reason)

    if compute_scene_stage(reply_text) == "aftercare":
        reasons.append("aftercare stage detected")

    return {"resolved": len(reasons) > 0, "reasons": reasons}


# ── collaborative continuation score ─────────────────────────────────────────

# Signals that increase continuation space (good)
_CONTINUATION_POSITIVE: list[str] = [
    r'\b(?:waited|watching|watching him|watching her|watching them)\b',
    r'\b(?:didn\'t (?:know|move|speak|answer)|couldn\'t (?:find|say|speak))\b',
    r'\b(?:something (?:shifted|tightened|caught|stirred)|a beat of silence|'
    r'the silence (?:stretched|held|settled|sat))\b',
    r'"[^"]{3,}[.?…—]"',                   # dialogue that ends open
    r'\b(?:he (?:waited|paused|stilled)|she (?:waited|paused|stilled)|'
    r'they (?:waited|paused|stilled))\b',
    r'\b(?:left (?:it|that|the question|the moment) there|let it sit|'
    r'let that land)\b',
    r'\?["\s]|[—…]["\s]',                  # trailing question or em-dash in speech
    r'\b(?:nothing (?:yet|followed|came)|hadn\'t (?:said|moved|decided))\b',
]

# Signals that reduce continuation space (bad)
_CONTINUATION_NEGATIVE: list[str] = [
    r'\b(?:climaxed|orgasm|fell apart|shattered|came\b|cried out)\b',
    r'\b(?:finally together|everything (?:was|felt) right|complete|it was over)\b',
    r'\b(?:lay together|caught (?:his|her|their) breath|breathed slowly|'
    r'pulse (?:settled|calmed))\b',
    r'\b(?:all was (?:resolved|over|done|finished)|nothing left to say)\b',
]


def score_collaborative_continuation(reply_text: str) -> float:
    """Return a 0–1 score for how much continuation space the reply preserves.

    1.0 = maximum open space (ideal collaborative turn)
    0.0 = scene fully resolved (poor for collaborative RP)
    """
    score = 0.60  # neutral baseline

    for pattern in _CONTINUATION_POSITIVE:
        if re.search(pattern, reply_text, re.IGNORECASE):
            score += 0.06

    for pattern in _CONTINUATION_NEGATIVE:
        if re.search(pattern, reply_text, re.IGNORECASE):
            score -= 0.15

    return round(max(0.0, min(1.0, score)), 3)


# ── pacing warnings (unified stage names) ─────────────────────────────────────

# Maximum stage permitted per heat level
_HEAT_MAX_STAGE: dict[str, str] = {
    "embers":  "kissing",
    "flame":   "undressing",
    "inferno": "intercourse",
}


def get_pacing_warnings(
    reply_text: str,
    heat_level: str,
    continuation_score: float,
    resolution: dict,
) -> list[str]:
    """Return non-blocking pacing/escalation warnings for internal diagnostics.

    These are surface-level signals for internal testing — not user-facing errors.
    Uses canonical 9-stage names throughout.
    """
    warnings: list[str] = []
    stage = compute_scene_stage(reply_text)
    stage_rank = _STAGE_RANK.get(stage, 0)
    max_stage = _HEAT_MAX_STAGE.get(heat_level, "intercourse")
    max_rank = _STAGE_RANK.get(max_stage, 6)

    if resolution["resolved"]:
        warnings.append("Reply may fully resolve the scene.")

    if continuation_score < 0.35:
        warnings.append("Very low continuation space — partner may have little to respond to.")

    if stage_rank > max_rank:
        warnings.append(
            f"Heat level '{heat_level}' (max stage: {max_stage}) but scene detected "
            f"at stage '{stage}' — content may exceed intended heat ceiling."
        )

    return warnings

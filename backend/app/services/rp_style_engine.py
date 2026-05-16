"""RP Style Engine — literary quality preservation layer for dark romance prose.

This is NOT a censorship layer.
This is a literary quality preservation layer.

Phases
------
1  DARK_ROMANCE_PROSE_LAYER       — core cinematic prose instruction block
2  ESCALATION_STORY_LAYER         — earned escalation pacing block
3  RP_STYLE_ARCHETYPES            — five named prose archetypes with distinct guidance
4  detect_generic_cadence()       — heuristic repetition / generic-cadence detector
5  maintain_scene_continuity()    — scene environment / tension extractor
"""
import re
from collections import Counter

# ── Phase 1 — dark romance prose layer ───────────────────────────────────────

DARK_ROMANCE_PROSE_LAYER = """
Maintain cinematic literary prose throughout the reply.

The scene should feel emotionally dangerous, obsessive, atmospheric, and character-driven.

Preserve:
- emotional tension
- morally grey attraction
- restraint struggling against desire
- sensory immersion
- environmental continuity
- character-specific obsession
- psychological intensity

Do not allow the prose to collapse into repetitive or generic cadence.

Even during high-intensity scenes:
- maintain atmosphere
- maintain narrative rhythm
- maintain emotional layering
- maintain cinematic pacing

Characters should feel emotionally and psychologically present in every action.

Body language, eye contact, breathing, hesitation, restraint, fixation, possessiveness,
vulnerability, and emotional contradiction should remain important throughout the scene.

The surrounding environment must remain present:
- storm
- rain
- ruined architecture
- blood
- heat
- breath
- sound
- movement

The scene should continue telling a story rather than becoming disconnected action sequences.

Avoid repetitive sentence structures and repetitive phrasing.

Preserve the unique emotional identity of the characters.
""".strip()

# ── Phase 2 — escalation story layer ─────────────────────────────────────────

ESCALATION_STORY_LAYER = """
Escalation should feel earned and progressive.

Do not jump rapidly between emotional and physical stages.

Maintain narrative transitions between:
- tension
- touch
- intimacy
- vulnerability
- obsession
- loss of restraint

Actions should deepen the emotional stakes of the scene.

The reply should preserve collaborative continuation space and unresolved emotional momentum.
""".strip()

# ── Phase 3 — style archetypes ────────────────────────────────────────────────

RP_STYLE_ARCHETYPES: frozenset[str] = frozenset({
    "cinematic_dark_romance",
    "gothic_obsession",
    "slow_burn_tension",
    "dangerous_devotion",
    "primal_restraint",
})

DEFAULT_ARCHETYPE = "cinematic_dark_romance"

_ARCHETYPE_CONFIGS: dict[str, dict] = {
    "cinematic_dark_romance": {
        "label": "Cinematic Dark Romance",
        "prompt_block": (
            "STYLE — CINEMATIC DARK ROMANCE:\n"
            "Pacing: wide-screen, deliberate. Each beat carries visual weight — "
            "write as though a camera is watching, slow-zooming on hands, mouths, "
            "the space between bodies.\n"
            "Cadence: alternating long atmospheric paragraphs with short, weighted sentences. "
            "Let silences land.\n"
            "Emotional weighting: subtext over statement. "
            "Desire and danger share the same breath — what is not said matters more than what is.\n"
            "Atmosphere: the scene is a character. Light, weather, architecture, "
            "and temperature inform every exchange."
        ),
    },
    "gothic_obsession": {
        "label": "Gothic Obsession",
        "prompt_block": (
            "STYLE — GOTHIC OBSESSION:\n"
            "Pacing: slow and claustrophobic. Time is distorted by fixation — "
            "moments stretch, small details become enormous.\n"
            "Cadence: dense, layered sentences. "
            "Shadows and architecture appear in almost every paragraph. "
            "The scene is haunted by what came before.\n"
            "Emotional weighting: obsession is not romantic — it is consuming, unsettling, "
            "and desperately sincere. The character cannot stop watching, noticing, wanting.\n"
            "Atmosphere: darkness, stone, candlelight, echo, dust, the smell of old wood and rain. "
            "The setting presses in."
        ),
    },
    "slow_burn_tension": {
        "label": "Slow Burn Tension",
        "prompt_block": (
            "STYLE — SLOW BURN TENSION:\n"
            "Pacing: withholding. Escalation is deferred — "
            "every approach is almost, every touch is withdrawn or interrupted.\n"
            "Cadence: short, controlled sentences during proximity. "
            "Sentence rhythm tightens when characters are close. Breath appears on the page.\n"
            "Emotional weighting: want is the whole scene. "
            "Nothing is given away. The charge lives in what is almost done.\n"
            "Atmosphere: charged silence. The gap between bodies. "
            "Sound drops out. Small physical details — fingers near a collarbone, "
            "a held breath — carry everything."
        ),
    },
    "dangerous_devotion": {
        "label": "Dangerous Devotion",
        "prompt_block": (
            "STYLE — DANGEROUS DEVOTION:\n"
            "Pacing: urgent but controlled. "
            "There is intensity beneath every line — but the character chooses their moments.\n"
            "Cadence: possessive, direct. Short declarative statements carry weight. "
            "The character's devotion is not soft — it has edges.\n"
            "Emotional weighting: love that is also a threat, a promise, a warning. "
            "The character would cross any line. They have not decided yet whether that is beautiful or monstrous.\n"
            "Atmosphere: heat, proximity, the physical presence of the object of devotion. "
            "Protection and possession are indistinguishable."
        ),
    },
    "primal_restraint": {
        "label": "Primal Restraint",
        "prompt_block": (
            "STYLE — PRIMAL RESTRAINT:\n"
            "Pacing: coiled. Every action is the character holding something back. "
            "Movement is deliberate because loss of control is close.\n"
            "Cadence: physical and visceral. "
            "The body is the instrument — jaw, hands, pulse, breath, heat. "
            "Sentences feel muscular, controlled, on the edge.\n"
            "Emotional weighting: the struggle is the story. "
            "The character wants something raw and is fighting it. "
            "Every beat is the gap between want and action.\n"
            "Atmosphere: animal heat beneath civilised surface. "
            "Sound and sensation. The smell of skin, the warmth of breath, "
            "the tension in a held muscle."
        ),
    },
}


def get_archetype_config(archetype: str) -> dict:
    """Return config for the given archetype, defaulting to cinematic_dark_romance."""
    return _ARCHETYPE_CONFIGS.get(archetype, _ARCHETYPE_CONFIGS[DEFAULT_ARCHETYPE])


def get_archetype_prompt_block(archetype: str) -> str:
    """Return the prose instruction block for the given archetype."""
    return get_archetype_config(archetype)["prompt_block"]


def build_style_layer(archetype: str = DEFAULT_ARCHETYPE) -> str:
    """Return the combined prose + escalation + archetype layer for prompt injection."""
    return "\n\n".join([
        DARK_ROMANCE_PROSE_LAYER,
        ESCALATION_STORY_LAYER,
        get_archetype_prompt_block(archetype),
    ])


# ── Phase 4 — repetition detection ───────────────────────────────────────────

# Sentence openers to flag as over-generic when repeated
_GENERIC_OPENERS = re.compile(
    r'^(?:he|she|they|it)\s+(?:moved|turned|stepped|walked|looked|reached|pulled|pushed|crossed)',
    re.IGNORECASE,
)

# Emotion words whose repetition signals emotional flattening
_EMOTION_WORDS: frozenset[str] = frozenset({
    "ache", "ached", "aching",
    "burn", "burned", "burning",
    "yearn", "yearned", "yearning",
    "hunger", "hungered", "hungering",
    "want", "wanted", "wanting",
    "need", "needed", "needing",
    "long", "longed", "longing",
    "desire", "desired", "desiring",
    "trembled", "trembling", "shiver", "shivered",
    "breathless", "breathlessly",
})

# High-frequency action verbs whose repetition signals mechanical narration
_ACTION_VERBS: frozenset[str] = frozenset({
    "moved", "turned", "stepped", "walked", "crossed",
    "pulled", "pushed", "reached", "grabbed", "took",
    "pressed", "placed", "put", "set",
    "looked", "glanced", "stared", "watched",
})


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on .!? boundaries."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def detect_generic_cadence(reply_text: str) -> dict:
    """Detect repetitive or generic prose patterns in a reply.

    Returns
    -------
    {
        "warnings":                  list[str],
        "generic_cadence_risk":      bool,
        "prose_repetition_detected": bool,
        "emotional_flattening_risk": bool,
    }
    """
    warnings: list[str] = []
    generic_cadence_risk = False
    prose_repetition_detected = False
    emotional_flattening_risk = False

    sentences = _split_sentences(reply_text)
    words_lower = [w.lower().strip(".,!?\"'—;:") for w in reply_text.split()]

    # ── repetitive sentence openings ─────────────────────────────────────────
    openers: list[str] = []
    generic_opener_count = 0
    for sentence in sentences:
        first_words = " ".join(sentence.split()[:3]).lower()
        openers.append(first_words)
        if _GENERIC_OPENERS.match(sentence):
            generic_opener_count += 1

    opener_counts = Counter(openers)
    repeated_openers = [(o, c) for o, c in opener_counts.items() if c >= 3]
    if repeated_openers:
        prose_repetition_detected = True
        top = repeated_openers[0]
        warnings.append(
            f"prose repetition detected: sentence opening '{top[0]}' appears {top[1]} times"
        )

    if generic_opener_count >= 4:
        generic_cadence_risk = True
        warnings.append(
            f"generic cadence risk: {generic_opener_count} sentences open with "
            "generic he/she/they + action-verb pattern"
        )

    # ── repetitive emotional phrasing ─────────────────────────────────────────
    emotion_counts = Counter(w for w in words_lower if w in _EMOTION_WORDS)
    heavy_repeats = [(w, c) for w, c in emotion_counts.items() if c >= 3]
    if heavy_repeats:
        emotional_flattening_risk = True
        top_e = sorted(heavy_repeats, key=lambda x: -x[1])[0]
        warnings.append(
            f"emotional flattening risk: '{top_e[0]}' repeated {top_e[1]} times — "
            "vary emotional vocabulary"
        )

    # ── repetitive action loops ───────────────────────────────────────────────
    action_counts = Counter(w for w in words_lower if w in _ACTION_VERBS)
    heavy_actions = [(w, c) for w, c in action_counts.items() if c >= 3]
    if heavy_actions:
        prose_repetition_detected = True
        top_a = sorted(heavy_actions, key=lambda x: -x[1])[0]
        warnings.append(
            f"prose repetition detected: action verb '{top_a[0]}' repeated {top_a[1]} times"
        )

    # ── excessive mechanical narration ────────────────────────────────────────
    # Flag replies where >60% of sentences are short (≤6 words) with no atmosphere
    short_mechanical = sum(
        1 for s in sentences
        if len(s.split()) <= 6 and not re.search(
            r'\b(?:breath|shadow|light|dark|heat|cold|sound|silence|smell|air|rain|storm)\b',
            s, re.IGNORECASE,
        )
    )
    if sentences and (short_mechanical / len(sentences)) > 0.6:
        generic_cadence_risk = True
        warnings.append(
            "generic cadence risk: majority of sentences are short mechanical narration "
            "with no atmospheric content"
        )

    # ── 3-gram repetition (prose-level) ──────────────────────────────────────
    if len(words_lower) >= 9:
        trigrams = list(zip(words_lower, words_lower[1:], words_lower[2:]))
        trigram_counts = Counter(trigrams)
        repeated_trigrams = [(t, c) for t, c in trigram_counts.items() if c >= 2]
        if len(repeated_trigrams) >= 3:
            prose_repetition_detected = True
            warnings.append(
                f"prose repetition detected: {len(repeated_trigrams)} repeated 3-word phrases — "
                "prose cadence is becoming circular"
            )

    return {
        "warnings": warnings,
        "generic_cadence_risk": generic_cadence_risk,
        "prose_repetition_detected": prose_repetition_detected,
        "emotional_flattening_risk": emotional_flattening_risk,
    }


# ── Phase 5 — scene continuity preservation ──────────────────────────────────

# Environmental pattern groups
_ENV_PATTERNS: dict[str, re.Pattern] = {
    "weather": re.compile(
        r'\b(?:rain|raining|storm|lightning|thunder|wind|snow|hail|downpour|fog|mist|drizzle|cold|heat|humid)\b',
        re.IGNORECASE,
    ),
    "architecture": re.compile(
        r'\b(?:wall|walls|window|windows|door|doorway|floor|ceiling|roof|stone|wood|glass|arch|column|ruin|ruins|room|hallway|corridor|stairs)\b',
        re.IGNORECASE,
    ),
    "light": re.compile(
        r'\b(?:candle|candlelight|flame|shadow|shadows|dark|darkness|light|moonlight|firelight|lantern|torch|dim|glow|flicker)\b',
        re.IGNORECASE,
    ),
    "sound": re.compile(
        r'\b(?:silence|quiet|sound|noise|creak|tap|drip|crash|rumble|echo|whisper|breath|breathing|heartbeat|pulse)\b',
        re.IGNORECASE,
    ),
    "sensation": re.compile(
        r'\b(?:blood|heat|cold|smoke|ash|dust|salt|skin|sweat|tears|breath)\b',
        re.IGNORECASE,
    ),
}

# Physical positioning references
_POSITION_PATTERNS = re.compile(
    r'\b(?:doorway|threshold|corner|against the wall|against him|against her|against them|'
    r'beside|between|across from|facing|leaning|standing|sitting|kneeling|lying|pressed|'
    r'close|near|inches|distance|reach|step)\b',
    re.IGNORECASE,
)

# Tension state markers
_TENSION_MARKERS: list[tuple[str, re.Pattern]] = [
    ("coiled", re.compile(
        r'\b(?:waiting|watching|still|frozen|paused|hadn\'t moved|held|silence|held breath)\b',
        re.IGNORECASE,
    )),
    ("charged", re.compile(
        r'\b(?:touched|hand|fingers|close enough|inches|breath on|pulse|heartbeat|trembl)\b',
        re.IGNORECASE,
    )),
    ("breaking", re.compile(
        r'\b(?:kissed|pulled|grabbed|pressed lips|mouth on|fell into|couldn\'t stop)\b',
        re.IGNORECASE,
    )),
]


def maintain_scene_continuity(
    partner_reply: str,
    prior_context: str | None = None,
) -> dict:
    """Extract scene continuity signals from the partner reply and optional prior context.

    Returns
    -------
    {
        "environment":           list[str]  — detected environmental categories present
        "environment_terms":     list[str]  — specific terms found
        "tension_state":         str        — "coiled" | "charged" | "breaking" | "neutral"
        "physical_positioning":  list[str]  — spatial reference terms found
        "continuity_prompt":     str        — instruction block for prompt injection
        "floating_scene_risk":   bool       — True if context has env but partner reply lost it
    }
    """
    search_text = partner_reply
    if prior_context:
        search_text = prior_context + "\n" + partner_reply

    # ── environment ──────────────────────────────────────────────────────────
    present_categories: list[str] = []
    all_terms: list[str] = []
    for category, pattern in _ENV_PATTERNS.items():
        matches = pattern.findall(search_text)
        if matches:
            present_categories.append(category)
            all_terms.extend(set(m.lower() for m in matches))

    # ── physical positioning ──────────────────────────────────────────────────
    position_matches = _POSITION_PATTERNS.findall(partner_reply)
    positioning = list(set(m.lower() for m in position_matches))

    # ── tension state ─────────────────────────────────────────────────────────
    tension_state = "neutral"
    for state, pattern in _TENSION_MARKERS:
        if pattern.search(partner_reply):
            tension_state = state
            break

    # ── floating scene risk ───────────────────────────────────────────────────
    floating_scene_risk = False
    if prior_context and present_categories:
        prior_env_hits = sum(
            1 for _, p in _ENV_PATTERNS.items() if p.search(prior_context)
        )
        partner_env_hits = sum(
            1 for _, p in _ENV_PATTERNS.items() if p.search(partner_reply)
        )
        if prior_env_hits >= 2 and partner_env_hits == 0:
            floating_scene_risk = True

    # ── continuity prompt ─────────────────────────────────────────────────────
    continuity_lines: list[str] = []

    if present_categories:
        term_sample = ", ".join(all_terms[:8])
        continuity_lines.append(
            f"SCENE CONTINUITY: The scene contains {', '.join(present_categories)} elements "
            f"({term_sample}). Keep these environmental elements present and active in your reply — "
            "do not let the scene become a void of action without atmosphere."
        )

    if positioning:
        pos_sample = ", ".join(positioning[:6])
        continuity_lines.append(
            f"The physical space includes: {pos_sample}. "
            "Maintain spatial awareness — characters should remain anchored in the scene."
        )

    if tension_state != "neutral":
        continuity_lines.append(
            f"Tension state entering your reply: {tension_state}. "
            "Write YOUR CHARACTER's response from within this emotional register — "
            "do not reset the scene, and do not continue from the partner's point of view."
        )

    if floating_scene_risk:
        continuity_lines.append(
            "WARNING: the prior scene had strong environmental presence that the partner's reply "
            "did not carry forward. Reintroduce environmental grounding in your reply."
        )

    continuity_prompt = "\n".join(continuity_lines) if continuity_lines else ""

    return {
        "environment": present_categories,
        "environment_terms": all_terms,
        "tension_state": tension_state,
        "physical_positioning": positioning,
        "continuity_prompt": continuity_prompt,
        "floating_scene_risk": floating_scene_risk,
    }


# ── RP-specific AI cadence detector ──────────────────────────────────────────

# Breath/shiver/gaze loop vocabulary — common AI prose tells
_RP_BREATH_GAZE: re.Pattern = re.compile(
    r'\b(?:breath(?:ed|less|lessly|ing|es?|caught|hitched|quickened|came\s+in\s+short|'
    r'against|on|mixing)?|shiver(?:ed|ing|s)?|shudder(?:ed|ing|s)?|'
    r'(?:his|her|their)\s+(?:eyes?|gaze)\s+(?:met|found|darkened|fixed|locked|dropped|lifted)|'
    r'eyes?\s+(?:the\s+color|like|that\s+held|that\s+caught)|'
    r'gaz(?:e|ed|ing)\s+(?:at|into|down|up))\b',
    re.IGNORECASE,
)

# Possessive/protective speech loop
_RP_POSSESSION_LOOP: re.Pattern = re.compile(
    r'\b(?:you\'re\s+mine|she\'s\s+mine|he\'s\s+mine|belong[s]?\s+to\s+me|'
    r'mine\s+to\s+(?:take|keep|have|protect|touch)|I\s+(?:own|claim(?:ed)?)\s+(?:you|her|him)|'
    r'I\'ll\s+(?:keep|protect)\s+(?:you|her|him)\s+safe|'
    r'nothing\s+(?:will|can)\s+(?:touch|hurt)\s+(?:you|her|him))\b',
    re.IGNORECASE,
)

# Paragraph-rhythm check — detect opening-word patterns across paragraphs
_PARA_SPLIT = re.compile(r'\n\n+')


def _paragraph_opening_words(text: str) -> list[str]:
    """Return the first 1–2 words of each non-empty paragraph."""
    openers: list[str] = []
    for para in _PARA_SPLIT.split(text):
        para = para.strip()
        if not para:
            continue
        words = para.split()
        if words:
            openers.append(" ".join(w.lower() for w in words[:2]))
    return openers


def detect_ai_cadence(reply_text: str) -> dict:
    """RP-specific AI cadence detector — extends detect_generic_cadence with RP tells.

    Checks for:
    1. All generic cadence issues (repetitive openers, emotion loops, action verb loops)
    2. Breath/shiver/gaze loop density
    3. Possessive/protective speech repetition
    4. Repetitive paragraph-opening rhythm

    Returns
    -------
    {
        "warnings":              list[str]
        "ai_cadence_risk":       bool
        "breath_gaze_density":   float  — 0.0–1.0
        "possession_loop_risk":  bool
        "rhythm_monotone_risk":  bool
    }
    """
    from app.services.rp_style_engine import detect_generic_cadence

    base = detect_generic_cadence(reply_text)
    warnings = list(base["warnings"])
    ai_cadence_risk = base["generic_cadence_risk"] or base["prose_repetition_detected"]

    word_count = max(1, len(reply_text.split()))

    # ── breath/shiver/gaze density ────────────────────────────────────────────
    breath_gaze_hits = len(_RP_BREATH_GAZE.findall(reply_text))
    breath_gaze_density = round(min(1.0, breath_gaze_hits / (word_count / 100.0)), 3)
    if breath_gaze_hits >= 5:
        ai_cadence_risk = True
        warnings.append(
            f"AI cadence: breath/shiver/gaze loop ({breath_gaze_hits} hits) — "
            "vary sensory vocabulary, add tactile and environmental diversity."
        )

    # ── possession/protection speech loop ─────────────────────────────────────
    possession_hits = len(_RP_POSSESSION_LOOP.findall(reply_text))
    possession_loop_risk = possession_hits >= 2
    if possession_loop_risk:
        ai_cadence_risk = True
        warnings.append(
            f"AI cadence: possessive/protective speech repeated {possession_hits}× — "
            "vary power dynamic expression, advance the scene rather than restating."
        )

    # ── paragraph opening rhythm monotony ─────────────────────────────────────
    para_openers = _paragraph_opening_words(reply_text)
    rhythm_monotone_risk = False
    if len(para_openers) >= 3:
        opener_counts = Counter(para_openers)
        repeated = [(o, c) for o, c in opener_counts.items() if c >= 2]
        if repeated:
            rhythm_monotone_risk = True
            top = repeated[0]
            warnings.append(
                f"AI cadence: paragraph opening '{top[0]}' appears {top[1]}× — "
                "vary paragraph rhythm and structure."
            )
        # Also flag if >60% of paragraphs start with same subject pronoun
        pronoun_openers = sum(
            1 for o in para_openers
            if o.split()[0] in ("he", "she", "they", "it", "the")
        )
        if len(para_openers) > 0 and pronoun_openers / len(para_openers) > 0.6:
            rhythm_monotone_risk = True
            ai_cadence_risk = True
            warnings.append(
                "AI cadence: majority of paragraphs open with same pronoun/article — "
                "vary paragraph entry points."
            )

    return {
        "warnings":             warnings,
        "ai_cadence_risk":      ai_cadence_risk,
        "breath_gaze_density":  breath_gaze_density,
        "possession_loop_risk": possession_loop_risk,
        "rhythm_monotone_risk": rhythm_monotone_risk,
    }


# ── POV validator ─────────────────────────────────────────────────────────────

# Strip roleplay bars from the opening of a text block
_BAR_STRIP_RE = re.compile(r'^(?:\|\|)+\s*')

# Third-person narrative pronouns that could indicate the partner's POV
_THIRD_PERSON_PRONOUNS = ("she", "he", "they")


def _strip_bars(text: str) -> str:
    """Remove leading || roleplay bar markers."""
    return _BAR_STRIP_RE.sub("", text.strip())


def detect_wrong_pov(
    reply_text: str,
    character_name: str,
    partner_reply: str,
) -> dict:
    """Detect if the generated reply is written from the partner character's POV.

    Uses NAME ANCHORING as the primary signal — pronoun-only matching is skipped
    when character names are available or when both characters use the same pronoun,
    to prevent false-positive retries (e.g. female/female, male/male pairings).

    Strategy:
    1. Infer the partner's character name from the opening of their reply.
    2. If the generated reply starts with THAT NAME → wrong POV (reliable).
    3. Pronoun check is only applied when:
       a. A partner character name could NOT be inferred, AND
       b. The selected character's name is known (so we can verify pronoun differs).
       In all other cases, skip pronoun check to avoid false positives.

    Returns
    -------
    {
        "wrong_pov":       bool   — True if POV mismatch detected
        "reason":          str    — human-readable explanation
        "partner_pronoun": str    — inferred partner pronoun (may be empty)
        "partner_char":    str    — inferred partner character name (may be empty)
    }
    """
    clean_reply = _strip_bars(reply_text)
    clean_partner = _strip_bars(partner_reply)

    wrong_pov = False
    reason = ""

    # ── Infer partner character name ──────────────────────────────────────────
    partner_char = ""
    name_match = re.match(r'^([A-Z][a-z]{2,})\b', clean_partner)
    if name_match:
        candidate = name_match.group(1)
        _NON_NAMES = frozenset({
            "The", "A", "An", "It", "This", "That", "There",
            "Then", "But", "And", "Her", "His", "Their", "She",
            "He", "They", "We", "You", "Rain", "Dark", "Cold",
            "Light", "Heat", "Wind", "Storm", "Silence",
        })
        if candidate not in _NON_NAMES:
            partner_char = candidate

    selected_first = character_name.split()[0] if character_name else ""
    # Clear partner_char if it matches the selected character's name
    if partner_char and selected_first and partner_char.lower() == selected_first.lower():
        partner_char = ""

    # ── Check generated reply opening ─────────────────────────────────────────
    reply_head = clean_reply[:80]

    # Signal 1: reply starts with partner character's name (most reliable)
    if partner_char and re.match(rf'{re.escape(partner_char)}\b', reply_head, re.IGNORECASE):
        wrong_pov = True
        reason = (
            f"Reply opens with '{partner_char}' — the partner character's name "
            "appears to be the narrative subject"
        )

    # Signal 2: pronoun check — ONLY when no name anchor exists and selected char name is known
    partner_pronoun = ""
    if not wrong_pov and not partner_char and character_name:
        partner_head = clean_partner[:200].lower()
        for pronoun in _THIRD_PERSON_PRONOUNS:
            if re.search(rf'(?:^|[.!?]\s+){pronoun}\b', partner_head):
                partner_pronoun = pronoun
                break
        # Only fire if pronoun is unambiguous: selected char name implies a different pronoun
        # (we skip pronoun check when we can't establish pronoun differs between characters)
        selected_lower = selected_first.lower() if selected_first else ""
        # Heuristic: if selected character name starts with a male name indicator we skip
        # This is inherently imperfect — prefer name check over pronoun check
        # Safe rule: only use pronoun if partner reply starts with pronoun AND we have a char name
        if partner_pronoun and character_name:
            reply_head_lower = reply_head.lower()
            if re.match(rf'{partner_pronoun}\b', reply_head_lower):
                # Additional safety: skip if selected char name is unknown (no anchor)
                # or the reply pronoun could belong to OUR character too
                # We flag only if partner reply unambiguously uses that pronoun as their subject
                # AND the reply's opening pronoun differs from what our character would use
                wrong_pov = True
                reason = (
                    f"Reply opens with '{partner_pronoun}' — matches inferred partner pronoun"
                )

    return {
        "wrong_pov": wrong_pov,
        "reason": reason,
        "partner_pronoun": partner_pronoun,
        "partner_char": partner_char,
    }

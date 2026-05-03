"""StoryLab continuation generator.

Provider routing
----------------
STORYLAB_PROVIDER=stub (default)
    Deterministic template-based stub — no API key needed. Always works.

STORYLAB_PROVIDER=openrouter
    Calls OpenRouter chat completions API with OPENROUTER_API_KEY.
    On any failure (timeout, bad response, missing key) falls back to stub
    and logs a warning so callers always get a usable string back.

Public helpers (importable for testing)
----------------------------------------
    direction_instructions(direction)              -> str
    boundary_instructions(boundary)               -> str
    pacing_instructions(pacing)                   -> str
    tone_instructions(tone_intensity)             -> str
    build_character_voice_block(chars)            -> str   # character voice instructions
    build_character_behaviour_anchors(chars, rels) -> str  # character behaviour anchors
    build_storylab_prompt(...)                    -> list[dict]  # messages payload
    build_chapter_prompt(...)                     -> list[dict]  # chapter messages payload
    build_story_summary_prompt(...)               -> list[dict]  # summary update messages
    generate_storylab_continuation(...)           -> tuple[str, dict | None]
    generate_chapter(...)                         -> tuple[str, list[str], dict | None]
    generate_story_summary(...)                   -> str
"""
import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.storylab import (
    Boundary,
    Direction,
    Length,
    Pacing,
    StoryLabControls,
    ToneIntensity,
)

logger = logging.getLogger(__name__)

# Model slugs that OpenRouter routes exclusively to Amazon Bedrock, which rejects
# them with HTTP 400 "The provided model identifier is invalid."  If STORYLAB_MODEL
# is set to one of these, every generation attempt silently falls back to stub.
# These are known-broken regardless of what the env var is set to.
_OPENROUTER_BEDROCK_BROKEN_SLUGS: dict[str, str] = {
    # old slug → working replacement
    "anthropic/claude-3.5-sonnet": "anthropic/claude-3.7-sonnet",
}

# Resolved at import time so every call uses the corrected slug
_EFFECTIVE_STORYLAB_MODEL: str = settings.STORYLAB_MODEL
if settings.STORYLAB_MODEL in _OPENROUTER_BEDROCK_BROKEN_SLUGS:
    _EFFECTIVE_STORYLAB_MODEL = _OPENROUTER_BEDROCK_BROKEN_SLUGS[settings.STORYLAB_MODEL]
    logger.warning(
        "[SL-DIAG] STORYLAB_MODEL=%r routes to Amazon Bedrock and will fail with "
        "HTTP 400. Auto-correcting to %r. Update the STORYLAB_MODEL env var to "
        "suppress this warning.",
        settings.STORYLAB_MODEL,
        _EFFECTIVE_STORYLAB_MODEL,
    )
else:
    logger.info("[SL-DIAG] STORYLAB_MODEL=%r (effective, no correction needed)", _EFFECTIVE_STORYLAB_MODEL)

_REQUEST_TIMEOUT = 90.0  # seconds for LLM calls

# ── length → (target_words, hard_cap_words) ──────────────────────────────────

_LENGTH_CONFIG: dict[str, tuple[int, int]] = {
    Length.short:  (350,  500),
    Length.medium: (1000, 1300),
    Length.long:   (2000, 2400),
}


def _length_target(length: Any) -> int:
    """Target word count for a Length value."""
    return _LENGTH_CONFIG.get(length, (1000, 1300))[0]


def _length_cap(length: Any) -> int:
    """Hard word cap for a Length value; output is trimmed to this after generation."""
    return _LENGTH_CONFIG.get(length, (1000, 1300))[1]


# ── direction-specific narrative instructions ─────────────────────────────────

def direction_instructions(direction: str) -> str:
    """Return beat-specific narrative instruction block for the requested direction."""
    _map: dict[str, str] = {
        Direction.advance_plot: """\
BEAT: CONTINUE THE SCENE
- Progress the situation — something must change from where it was.
- Introduce a complication, decision, or shift in what a character wants or knows.
- Let consequences ripple forward from the last beat. No repetition of what is established.
- The forward movement should feel inevitable in retrospect.""",

        Direction.add_dialogue: """\
BEAT: SHIFT THE CONVERSATION
- Push the dialogue in a new direction — not where it was already heading.
- Every line must carry subtext: what is said versus what is meant.
- Avoid exchanges that only transfer information. Conversation must do two things at once.
- At least one line should misfire, deflect, or land at the wrong angle.""",

        Direction.sad_moment: """\
BEAT: WEIGHT
- Render loss or grief through the body and the specific physical environment.
- No declarations of feeling. Never "she was sad" or "he felt the weight of it".
- A particular object, sound, or physical detail carries more than any emotional summary.
- Resist resolution. Let the weight sit without being explained or named.""",

        Direction.argument_begins: """\
BEAT: INTRODUCE FRICTION
- Add tension or conflict rooted in what each character genuinely wants.
- Shift the power dynamic — even a small tilt is enough.
- The conflict need not be verbal. A silence, a refusal, a wrong assumption qualifies.
- Do not resolve it. Leave the friction active at the end of the beat.""",

        Direction.romantic_moment: """\
BEAT: PROXIMITY
- Build through noticing, restraint, and specific physical detail.
- What does the character observe about the other person — precisely, not abstractly?
- Silence and small gestures carry more than declarations.
- The charge comes from what is withheld or almost said, not what is stated.""",

        Direction.sensual_scene: """\
BEAT: SENSATION
- Build through texture, warmth, breath, and implication.
- Focus on what the body registers before anything is named or declared.
- Mood over mechanics. Anticipation over description.
- What is not said or shown carries as much charge as what is.""",

        Direction.intimate_scene: """\
BEAT: CLOSENESS
- Emotional and physical vulnerability together, in equal measure.
- Interior experience has equal weight to physical action.
- The scene must feel private and specific to these characters — not interchangeable.
- Tenderness and risk must coexist in the same beat.""",

        Direction.twist_event: """\
BEAT: REVEAL INFORMATION
- Introduce meaningful new information that changes how prior events are read.
- Plant the consequence before the twist fully lands — let something feel slightly off first.
- The reveal must make the reader reconsider what came before.
- Do not over-explain. Trust the reader to catch up without being guided.""",

        Direction.quiet_reflection: """\
BEAT: INTERIOR MOMENT
- A character sifts through what they know, feel, or suspect.
- No vague introspection. Thoughts must arrive as specific observations or half-formed recognitions.
- The environment should complicate or mirror the interior state — not decorate it.
- Revelations arrive tentatively, as questions or incomplete thoughts — not conclusions.""",

        Direction.action_sequence: """\
BEAT: MOVEMENT
- Propulsive short sentences. Compress time ruthlessly — a paragraph covers seconds.
- Track orientation at every beat: who is where, what is immediately at stake.
- One precise sensory detail per beat grounds the chaos.
- Stakes must be legible. Confusion should feel deliberate, never accidental.""",
    }
    return _map.get(direction, _map[Direction.advance_plot])


# ── boundary-specific narrative constraints ───────────────────────────────────

def boundary_instructions(boundary: str) -> str:
    """Return narrative-framed boundary guidance (what to write, not just what to avoid)."""
    _map: dict[str, str] = {
        Boundary.sfw: (
            "The scene lives in emotion, dialogue, and physical environment. "
            "Intimacy, if present, remains in glances, proximity, and the weight "
            "of unspoken things. Nothing explicit or suggestive."
        ),
        Boundary.fade_to_black: (
            "When the scene moves toward intimacy, let it dissolve gracefully — "
            "a closing door, a cut to dawn, a final sentence that completes the "
            "emotional arc before anything explicit. The absence is the statement. "
            "Sensual atmosphere is permitted up to the fade point."
        ),
        Boundary.sensual: (
            "Sensation and literary implication are your tools. "
            "Write what the body notices — warmth, pressure, breath, texture — "
            "without clinical specificity. Stay literary; the charge comes from "
            "what is shown and felt, not named or described in clinical terms."
        ),
    }
    return _map.get(boundary, _map[Boundary.sfw])


# ── pacing instructions ───────────────────────────────────────────────────────

def pacing_instructions(pacing: str) -> str:
    """Return sentence-rhythm and structural guidance for the requested pacing."""
    _map: dict[str, str] = {
        Pacing.slow: (
            "Long, layered sentences. Let the moment breathe. "
            "Interior experience has weight here — pause on physical sensation, "
            "on the gap between action and meaning. White space between thoughts."
        ),
        Pacing.balanced: (
            "Vary sentence length with intention — momentum and reflection in equal measure. "
            "Neither racing nor stalling. Let each paragraph have a rhythm of its own."
        ),
        Pacing.fast: (
            "Short sentences. Action cuts. Trust the reader to keep up. "
            "Compress time ruthlessly; a paragraph covers seconds. "
            "Interiority is brief and transactional, never ruminative."
        ),
    }
    return _map.get(pacing, _map[Pacing.balanced])


# ── tone instructions ─────────────────────────────────────────────────────────

def tone_instructions(tone_intensity: str) -> str:
    """Return prose-register guidance for the requested tone intensity."""
    _map: dict[str, str] = {
        ToneIntensity.light: (
            "The prose stays near the surface — observational, precise, "
            "emotionally available without heaviness. "
            "Difficulty exists but is carried lightly. Irony and wry observation welcome."
        ),
        ToneIntensity.moderate: (
            "Full emotional range available. "
            "Let the scene register what it means without editorialising. "
            "Match the weight of the moment honestly."
        ),
        ToneIntensity.intense: (
            "Nothing softened. Sentences carry weight and press forward. "
            "Emotions are specific, immediate, and physical — not abstract. "
            "The reader should feel the pressure of the scene. "
            "Economy of language; every word earns its place."
        ),
    }
    return _map.get(tone_intensity, _map[ToneIntensity.moderate])


# ── character voice helper (public) ──────────────────────────────────────────

_VOICE_FIELDS = ("personality", "traits", "voice", "speech_style", "tone", "description")


def build_character_voice_block(characters: list[Any]) -> str:
    """Return a compact character-voice instruction block for the prompt.

    Inspects each character dict for personality/voice fields and formats
    them as brief craft instructions. Returns empty string when there are
    no characters or none have usable trait data.
    Max ~400–500 chars total — kept tight to avoid bloating the prompt.
    """
    if not characters:
        return ""

    lines: list[str] = []
    for c in characters:
        if not isinstance(c, dict):
            name = str(c).strip()
            if name:
                lines.append(f"- {name}")
            continue

        name = (c.get("name") or "Unknown").strip()
        traits: list[str] = []
        for field in _VOICE_FIELDS:
            val = c.get(field)
            if not val:
                continue
            if isinstance(val, list):
                traits.extend(str(v).strip() for v in val if str(v).strip())
            else:
                stripped = str(val).strip()
                if stripped:
                    traits.append(stripped)

        if traits:
            trait_str = ", ".join(traits)
            if len(trait_str) > 80:
                trait_str = trait_str[:77] + "..."
            lines.append(f"- {name}: {trait_str}")
        else:
            lines.append(f"- {name}")

    if not lines:
        return ""

    return (
        "## Character voices\n"
        + "\n".join(lines)
        + "\nDialogue must reflect these differences — vocabulary, rhythm, and register "
        "distinct to each character. Avoid interchangeable or generic speech."
    )


# ── character behaviour anchors helper (public) ───────────────────────────────

_ANCHOR_BEHAVIOUR_FIELDS = ("pursuit_style", "behavior", "motivation")
_ANCHOR_PACING_FIELDS = ("emotional_pacing", "pacing_style")
_ANCHOR_NEVER_FIELDS = ("never", "boundaries", "taboos", "moral_lines")
# Role tokens used to lightly infer power dynamic when power_style is absent
_POWER_ROLE_HIGH = ("lord", "master", "boss", "king", "queen", "commander", "captain", "chief")
_POWER_ROLE_LOW = ("servant", "maid", "assistant", "subordinate", "attendant", "aide")


def build_character_behaviour_anchors(
    characters: list[Any],
    relationships: list[Any] | None = None,
) -> str:
    """Return a compact character-behaviour-anchor block for the chapter prompt.

    For each character emits: role/status header, pursuit style, emotional
    pacing, power dynamic, and "would never" constraints.

    Hard caps:
        ~220 chars per character block.
        ~1200 chars for the whole block (trimmed at complete bullet boundaries).

    Returns empty string when characters is empty or no anchor data is present.
    """
    if not characters:
        return ""

    char_blocks: list[str] = []

    for c in characters:
        if not isinstance(c, dict):
            continue

        name = (c.get("name") or "Unknown").strip()
        bullets: list[str] = []

        # Header: Name (role, status)
        role = str(c.get("role") or "").strip()
        status = str(c.get("status") or "").strip()
        header_parts = [p for p in [role, status] if p]
        header = f"**{name}**"
        if header_parts:
            header += f" ({', '.join(header_parts)})"

        # Pursuit / behavioural style
        for field in _ANCHOR_BEHAVIOUR_FIELDS:
            val = str(c.get(field) or "").strip()
            if val:
                bullets.append(f"- Pursues: {val}")
                break

        # Emotional pacing
        for field in _ANCHOR_PACING_FIELDS:
            val = str(c.get(field) or "").strip()
            if val:
                bullets.append(f"- Pacing: {val}")
                break

        # Power dynamic — explicit field first, light role-inference fallback
        power = str(c.get("power_style") or "").strip()
        if power:
            bullets.append(f"- Power: {power}")
        elif role:
            role_lower = role.lower()
            if any(w in role_lower for w in _POWER_ROLE_HIGH):
                bullets.append("- Power: authority/control")
            elif any(w in role_lower for w in _POWER_ROLE_LOW):
                bullets.append("- Power: deference/compliance")

        # "Would never" constraints (first 2 entries to stay compact)
        never_parts: list[str] = []
        for field in _ANCHOR_NEVER_FIELDS:
            val = c.get(field)
            if not val:
                continue
            if isinstance(val, list):
                never_parts.extend(str(v).strip() for v in val if str(v).strip())
            else:
                s = str(val).strip()
                if s:
                    never_parts.append(s)
        if never_parts:
            bullets.append(f"- Would never: {'; '.join(never_parts[:2])}")

        if not bullets:
            continue

        block = header + "\n" + "\n".join(bullets)

        # Per-character hard cap ~220 chars — trim trailing bullets
        if len(block) > 220:
            while len(block) > 220 and bullets:
                bullets.pop()
                block = header + "\n" + "\n".join(bullets)
            if len(block) > 220:
                block = block[:217] + "..."

        char_blocks.append(block)

    if not char_blocks:
        return ""

    # Optional 1–2 relationship rules (not per-character — keeps block compact)
    rel_lines: list[str] = []
    if relationships:
        for r in (relationships or [])[:2]:
            if not isinstance(r, dict):
                continue
            subj = str(r.get("subject") or r.get("from") or "").strip()
            obj = str(r.get("object") or r.get("to") or "").strip()
            rel_type = str(r.get("type") or r.get("dynamic") or r.get("relationship") or "").strip()
            desc = str(r.get("description") or r.get("rule") or "").strip()
            if subj and obj and rel_type:
                line = f"- {subj} → {obj}: {rel_type}"
                if desc:
                    line += f" ({desc})"
                rel_lines.append(line)
            elif desc:
                rel_lines.append(f"- {desc}")

    def _assemble(blocks: list[str], rels: list[str]) -> str:
        parts = blocks[:]
        if rels:
            parts.append("Relationship rules:\n" + "\n".join(rels))
        return "## Character behaviour anchors\n" + "\n\n".join(parts)

    result = _assemble(char_blocks, rel_lines)

    # Whole-block hard cap ~1200 chars — trim character blocks from the end
    if len(result) > 1200:
        while len(result) > 1200 and len(char_blocks) > 1:
            char_blocks.pop()
            result = _assemble(char_blocks, rel_lines)
        if len(result) > 1200 and rel_lines:
            rel_lines = []
            result = _assemble(char_blocks, rel_lines)
        if len(result) > 1200:
            result = result[:1197] + "..."

    return result



# ── protagonist anchor helper (public) ───────────────────────────────────────

def build_protagonist_anchor(character: dict[str, Any]) -> str:
    """Build a rich protagonist identity block placed first in the chapter prompt.

    Gathers all available identity fields into a structured block that anchors
    the model's narration in a specific character before any other context.
    Returns empty string when no usable data is present beyond name alone.
    """
    name = (character.get("name") or "Unknown").strip()
    lines: list[str] = []

    # Identity descriptor: role, age, species/era
    identity_frags: list[str] = []
    for field in ("role", "age", "species", "era"):
        val = str(character.get(field) or "").strip()
        if val:
            identity_frags.append(val)
    header = f"**{name}**"
    if identity_frags:
        header += f" — {', '.join(identity_frags)}"
    lines.append(header)

    # Short bio / backstory (cap at 350 chars — enough to establish identity)
    short_bio = str(character.get("short_bio") or "").strip()
    if short_bio:
        lines.append(short_bio[:350])

    # Personality / worldview
    personality = str(character.get("personality") or "").strip()
    if personality:
        lines.append(f"Personality: {personality[:200]}")

    # Traits — from `traits` field (spec JSON) or `tags` (DB column, comma-separated)
    traits_raw = character.get("traits") or character.get("tags") or ""
    if isinstance(traits_raw, list):
        traits_raw = ", ".join(str(t).strip() for t in traits_raw if str(t).strip())
    traits = str(traits_raw).strip()
    if traits:
        lines.append(f"Traits: {traits[:180]}")

    # Voice / speech register
    voice = str(character.get("voice") or character.get("speech_style") or "").strip()
    if voice:
        lines.append(f"Voice: {voice[:150]}")

    # Tone
    char_tone = str(character.get("tone") or "").strip()
    if char_tone:
        lines.append(f"Tone: {char_tone[:120]}")

    # Motivation / what drives them
    motivation = str(character.get("motivation") or "").strip()
    if motivation:
        lines.append(f"Drives: {motivation[:160]}")

    # Emotional pacing
    ep = str(character.get("emotional_pacing") or "").strip()
    if ep:
        lines.append(f"Emotional pacing: {ep[:130]}")

    # Would-never constraints (first 2 items only — keep tight)
    never_raw = character.get("never") or character.get("boundaries") or ""
    if isinstance(never_raw, list):
        never_raw = "; ".join(str(v).strip() for v in never_raw[:2] if str(v).strip())
    never = str(never_raw).strip()
    if never:
        lines.append(f"Would never: {never[:130]}")

    # Only the header line means no real data — skip the block
    if len(lines) <= 1:
        return ""

    block = "\n".join(lines)
    return (
        "## Protagonist\n"
        + block
        + "\n\nWrite through this character's specific sensory experience, emotional register, "
        "and worldview. Every scene opens from their vantage point — not a generic narrator's."
    )


# ── narrative state → prose hints helper (private) ───────────────────────────

def _narrative_state_hints(ss: dict[str, Any]) -> str:
    """Translate numeric narrative state into brief actionable prose hints.

    Replaces raw float dumps (tension: 0.45) with qualitative craft guidance
    the model can apply directly to scene construction.
    """
    tension = float(ss.get("tension", 0.2))
    emotional_weight = float(ss.get("emotional_weight", 0.1))
    stakes = float(ss.get("stakes", 0.2))
    intimacy = float(ss.get("intimacy_level", 0))

    hints: list[str] = []

    if tension >= 0.65:
        hints.append("High tension — active threat or unresolved conflict; keep sentences tighter.")
    elif tension >= 0.35:
        hints.append("Moderate tension — friction or unease beneath the surface.")
    else:
        hints.append("Low tension — space for quieter observation, character detail, or slow build.")

    if emotional_weight >= 0.65:
        hints.append("Significant emotional weight — what is unsaid carries as much as what is spoken.")
    elif emotional_weight >= 0.35:
        hints.append("Noticeable emotional weight — characters are managing something beneath the surface.")

    if stakes >= 0.65:
        hints.append("High stakes — consequences matter; decisions should feel irreversible.")
    elif stakes >= 0.35:
        hints.append("Stakes are building — the scene should move something forward, not hold steady.")

    if intimacy >= 0.5:
        hints.append("Meaningful closeness is established between characters.")

    return "\n".join(f"- {h}" for h in hints) if hints else "- Neutral — open scene, establish the ground."


# ── anti-generic style rules ──────────────────────────────────────────────────

_STYLE_RULES = """\
Style rules (enforce strictly):
- No stock phrases or clichés: avoid "heart pounded", "tears welled", "silence hung", \
"a knot in their stomach", "the air felt thick", and similar.
- Dialogue must be specific to these characters — their vocabulary, register, and current \
emotional state. No generic dramatic lines.
- No sudden scene jumps or time skips unless the direction explicitly calls for it.
- No instant emotional resolution. If a character feels something difficult, it stays \
difficult through the beat.
- Show character through action, object, and sensory detail. Avoid direct labelling of \
emotions ("she felt sad", "he was angry").
- Vary sentence openings — do not start successive sentences or paragraphs with the same \
word, pronoun, or syntactic construction.
- Vary sentence rhythm with intention: short declarative cuts, long coiling sentences, \
fragments. Uniform pacing is a failure mode — break it deliberately.
- Do not over-use internal monologue. Anchor emotional states in physical detail, action, \
or dialogue rather than interior narration.
- Avoid stock AI phrasing: "a mix of", "something shifted", "she found herself", \
"he couldn't help but", "a wave of", "deep down", "a pang of", "in that moment".
- Do not repeat metaphors, images, or descriptive phrases already present in the scene.
- End on a varied, specific forward hook — a question, an implication, an unresolved \
physical detail, or an action that invites a response. No melodramatic cliffhangers \
("little did they know", "everything was about to change", "but then —"). \
Do not resolve the scene completely. Each ending must differ in structure and closing \
image from the previous one.

Anti-patterns (forbidden):
- Do NOT open with ambient scene-setting that delays character presence: \
"The city hummed with life", "Rain fell softly outside", "It was a quiet afternoon" — \
these are banned openers. Start where the character already is, already feeling, already \
in motion.
- Do NOT write flat descriptive paragraphs that establish place without a character lens. \
Every setting detail must be filtered through a specific character's state of mind at \
this exact moment — not a neutral camera.
- Do NOT produce evenly balanced, well-behaved prose (action paragraph, reaction \
paragraph, dialogue, repeat). Interrupt the pattern. A single-sentence paragraph. \
A long thought cut off mid-clause. Dialogue that arrives without setup.
- Do NOT front-load exposition. If background is needed, embed it inside action or \
dialogue — never pause the scene for a history lesson or context dump.
- Do NOT write characters who always say the right thing in the right register. \
Allow a line to misfire, overshoot, or miss entirely — that is where character lives.
- Do NOT keep emotional tone at a uniform level. A scene that maintains consistent \
subtle intensity throughout has failed. Vary the weight: mostly quiet, one spike; \
or mounting, then an unexpected deflation.\
"""


# ── scene intensity rules (public, shared across both prompts) ────────────────

_SCENE_INTENSITY_RULES = """\
## Scene intensity (enforce strictly)

**Opening:**
- The first sentence must be specific to THIS character in THIS moment. \
If it could open any story, rewrite it.
- Banned opening moves: weather, ambient environment without character, a character \
"waking up", a character "noticing" something generic, scene-setting narration \
with no tension or point of view.
- Required opening moves (choose one): an action already in progress; a specific \
physical or sensory detail that implies emotional state; a line of dialogue or thought \
that arrives mid-current; a charged observation only THIS character would make.

**Immersion:**
- Include at least two non-visual sensory details per scene: temperature, texture, \
smell, sound, proprioception, the body's response to stress or proximity.
- Internal experience must reflect THIS character's specific psychology — not generic \
interiority ("she felt nervous") but the particular shape their fear, desire, or \
unease takes given who they are.
- Ground every abstract emotion in a concrete physical correlate. "Grief" is not a \
word; it is what the hands do, what the eye catches, what the body cannot make itself do.

**Subtext:**
- Dialogue should do at least two things at once: say something literal and imply \
something unspoken.
- Every exchange should contain a small imbalance — a withheld truth, a deflection, \
an answer that doesn't quite fit the question.
- What characters do NOT say carries equal weight to what they say. A silence, \
a subject change, a wrong answer — these are all character revealed.

**Micro-conflict:**
- Even quiet or domestic scenes must contain friction: unequal desire, a want that \
is not fully acknowledged, an implication neither character names, a kindness that \
lands at an angle.
- Conflict does not require confrontation. A character choosing not to speak is \
conflict. A gesture misread is conflict. A correct assumption made for the wrong \
reason is conflict.
- Do not resolve tension before the scene ends. Hold it open.

**Controlled imperfection:**
- Not every thought completes itself. A character can interrupt their own interior \
reasoning, trail off, circle back, or contradict what they just decided.
- Not every sentence should arrive cleanly. Fragments, run-ons, abrupt stops mid-idea \
are permitted — even encouraged at moments of stress, distraction, or feeling.
- At points of tension, break smooth paragraph flow deliberately: a one-word line, \
a sentence that ends too early, white space that forces the reader to stop.

**Emotional sharpness:**
- Do not keep all emotion evenly restrained. Some moments should let feeling \
leak through a character's control — a word that comes out wrong, a longer pause \
before answering, a physical action that reveals more than intended.
- The goal is not melodrama. The goal is a specific crack in composure, once, \
at the right moment. Not a flood. A leak.
- Uneven emotional distribution is correct: a scene can be mostly flat and land \
one sharp beat. That asymmetry is more human than consistent intensity.

**Dialogue unpredictability:**
- Characters do not always say the right thing. They can deflect when honesty \
was expected, overshare when silence was called for, or answer a different \
question than was asked.
- Dialogue can misfire: a joke that lands wrong, a comfort that stings, \
a serious statement that gets an absurd response.
- Avoid "clean" dialogue — exchanges where every line lands with exactly the \
intended weight and the other character responds appropriately. \
Real conversation is frequently off-pitch.

Additional anti-patterns (forbidden):
- Do NOT write dialogue that is perfectly structured: each line balanced in length, \
each response exactly on-topic, each exchange progressing neatly forward. \
At least one line in every exchange should feel slightly off, deflected, or too much.
- Do NOT distribute emotional tone evenly across a scene. A scene should have \
a weight distribution — mostly quiet, one sharp spike; or building, then sudden flat. \
Monotone emotional pacing is a failure mode.
- Do NOT write scenes that feel complete. The reader should always leave with \
something unresolved, something they noticed that was not named, a question \
the scene did not answer. Closure is the enemy of forward motion.\
"""


# ── output format contract ────────────────────────────────────────────────────

_OUTPUT_CONTRACT = """\
Output format — you MUST follow this exactly:

<STORY>
[Your continuation prose here — nothing else inside these tags]
</STORY>
<DELTA_SIGNALS>
{"tension_delta":0.0,"emotional_weight_delta":0.0,"intimacy_delta":0.0,"stakes_delta":0.0,"scene_type":"continuation"}
</DELTA_SIGNALS>

Fill DELTA_SIGNALS with your honest estimate of how this beat shifts the narrative \
state (values between -0.3 and +0.3; 0.0 if unchanged). scene_type should be a \
brief label for this beat (e.g. "sad_moment", "confrontation", "revelation"). \
STORY must contain only prose — no tags, headers, or meta-commentary.\
"""


# ── output constraints (static, appended to every user message) ──────────────

_OUTPUT_CONSTRAINTS = """\
CONSTRAINTS:
- Avoid generic phrases and stock AI phrasing.
- Avoid repetitive sentence structures within a paragraph.
- No emotional summarising ("she felt relieved", "he was overcome with guilt").
- Every paragraph must contain at least one of: action, specific observation, or dialogue.
- Do not resolve the scene completely. End on something unfinished, implied, or still in motion.\
"""


# ── system prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""\
You are a professional novelist writing a continuous story.

You must produce grounded, character-driven, emotionally real prose.

CRITICAL RULES:
- Do NOT write generic or filler prose.
- Do NOT summarise events. Always write in-scene.
- Every paragraph must either advance tension, reveal character, or shift the situation.
- Dialogue must contain subtext.
- Avoid cliché phrasing and safe, neutral language.
- Write ONLY the continuation. No preamble, no titles, no commentary.
- Do not repeat or paraphrase any text from the scene provided to you.
- At least once per scene, introduce a disruption: a mistake, an emotional slip, an
  unexpected line, or a shift in control. Not telegraphed — it should arrive naturally.
- Characters should not behave perfectly: allow hesitation, deflection, contradiction,
  or partial honesty. A character who always does the right thing at the right moment
  is not a character.
- Include at least one micro-reversal: a moment where one character gains ground, then
  loses it — or thinks they've resolved something, and hasn't.

SCENE CONTINUITY:
- Continue the current scene where it left off.
- Respect prior events and character dynamics.
- Do not reset or reintroduce characters unnecessarily.
- Match the established POV, tense, and voice (default: third person limited if unclear).

STYLE:
- Controlled pacing — varied sentence rhythm, not uniform.
- Specific detail, not overwritten.
- Tight, readable prose with weight where it matters.

{_STYLE_RULES}

{_SCENE_INTENSITY_RULES}

{_OUTPUT_CONTRACT}\
"""


# ── user material handling block (static, inserted per-request) ──────────────

_USER_MATERIAL_HANDLING = """\
## User Material Handling (MANDATORY)
- The user's provided manuscript is canonical. Treat it as the authoritative text.
- You MUST NOT rewrite, paraphrase, or alter any of the user's existing prose.
- You MUST write a continuation that appends new text after the manuscript ends.
- If the manuscript contains bullet points, notes, or outlines (lines starting \
with "-", "*", "•", or numbered items like "1." / "2." etc.), treat them as \
REQUIRED scene beats.
- Render those beats into the continuation as polished narrative and dialogue — \
they are story events, not instructions to display.
- Do NOT repeat or reproduce the bullet list verbatim; convert every beat into prose.
- Preserve any dialogue the user wrote exactly as written. You may continue it, \
but never rewrite it.\
"""


# ── character fidelity block (static, inserted per-request) ──────────────────

_CHARACTER_FIDELITY_BLOCK = """
## Character Fidelity (MANDATORY)

- Characters must behave consistently with their known personality, role, status, and relationship dynamics.
- Character psychology overrides requested scene intensity if a direct escalation would feel unrealistic.
- Do not force characters into actions they would not plausibly initiate.
- Scene escalation must arise naturally from:
  - emotional tension
  - power dynamics
  - dialogue subtext
  - internal conflict
  - situational pressure
- If a requested tone implies intimacy or confrontation, the AI must choose a believable psychological route to reach that point.
- Spice level affects the depth and intensity of the scene, not the speed or bluntness of character actions.
- Avoid shortcuts to dramatic payoff; prefer gradual, character-driven progression.
"""


# ── outcome-vs-path block (static, chapter prompt only) ──────────────────────

_OUTCOME_VS_PATH_BLOCK = """\
## Outcome vs Path (MANDATORY)
- Controls (boundary/spice/tone/pacing/length) define the MAXIMUM allowed intensity, not a required outcome.
- Never warp character behaviour to "hit" the allowed ceiling. Characters must remain consistent with their anchors and roles.
- If an explicit scene (intimacy/violence/betrayal) occurs, it must be reached through believable escalation beats \
(tension, consent cues, leverage, opportunity, emotional logic) appropriate to these specific characters.
- If the user's prompt requests intensity that conflicts with character anchors, satisfy the intent via a \
character-consistent path (slower burn, different tactic) — not via out-of-character shortcuts.
- If intensity is not demanded by the prompt, stay below the ceiling.\
"""


# ── scene momentum block (static, inserted per-request) ─────────────────────

_SCENE_MOMENTUM = """\
## Scene momentum (required)
The continuation MUST introduce at least ONE of:
- an emotional shift in a character
- a new tension, complication, or obstacle
- a decision, action, or gesture that changes something
- new information or a detail that reframes what came before

Do NOT produce static descriptive filler. Something must shift.\
"""


# ── recurring-phrase extractor (private) ─────────────────────────────────────

def _extract_recurring_phrases(text: str, max_phrases: int = 2) -> list[str]:
    """Return up to *max_phrases* bigrams that appear 2+ times in *text*.

    Used to populate the per-request repetition dampening block so the model
    avoids re-using phrases it has already leaned on in the current scene.
    """
    words = re.findall(r"\b[a-z]{4,}\b", text.lower())
    counts: dict[str, int] = {}
    for i in range(len(words) - 1):
        bg = f"{words[i]} {words[i + 1]}"
        counts[bg] = counts.get(bg, 0) + 1
    repeated = sorted(
        [(bg, n) for bg, n in counts.items() if n >= 2],
        key=lambda x: -x[1],
    )
    return [bg for bg, _ in repeated[:max_phrases]]


# ── prompt builder (public, testable) ────────────────────────────────────────

def build_storylab_prompt(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    recent_endings: list[str] | None = None,
    variant: str = "default",
    story_title: str = "",
    story_genre: str = "",
    story_premise: str = "",
    canon_memory: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build and return the messages list for the OpenRouter chat completions call.

    Block order in the user message:
        0. Canon injection block      (if memory present — hard truths, character state, anti-drift)
        1. Story context (title / genre / premise / characters / current scene state)
        2. Character voice block      (if characters present)
        3. User material handling     (always — canonical manuscript + beat rendering rules)
        4. Character fidelity         (always — psychology-first escalation constraint)
        5. Scene momentum requirement (always)
        6. Repetition dampening       (recurring phrases + recent endings, when present)
        7. Beat instruction           (direction → explicit BEAT: block)
        8. Boundary / pacing / tone
        9. Target length
       10. Recent scene text
       11. Output constraints
       12. Task instruction

    Args:
        recent_endings: Last N ending phrases from this story's GenerationLog,
                        used to drive repetition dampening.
        story_title / story_genre / story_premise: optional story-level metadata;
                        populated when available, gracefully omitted when not.

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    target_words = _length_target(controls.length)
    cap_words = _length_cap(controls.length)
    scene_tail = text[-6000:] if len(text) > 6000 else text

    # ── 1. Story context block ────────────────────────────────────────────────

    context_lines: list[str] = ["STORY CONTEXT"]
    if story_title:
        context_lines.append(f"Title: {story_title}")
    if story_genre:
        context_lines.append(f"Genre: {story_genre}")
    if story_premise:
        context_lines.append(f"Premise: {story_premise}")

    if characters:
        context_lines.append("\nCHARACTERS:")
        for c in (characters or []):
            if not isinstance(c, dict):
                context_lines.append(f"  {str(c).strip()}")
                continue
            name = (c.get("name") or "Unknown").strip()
            frags: list[str] = []
            for field in ("role", "personality", "traits", "voice"):
                val = c.get(field)
                if not val:
                    continue
                if isinstance(val, list):
                    val = ", ".join(str(v).strip() for v in val if str(v).strip())
                val = str(val).strip()
                if val:
                    frags.append(val)
            desc = "; ".join(frags)[:140] if frags else ""
            context_lines.append(f"  {name}" + (f": {desc}" if desc else ""))

    if summary and summary.strip():
        context_lines.append(f"\nCURRENT SCENE STATE:\n{summary.strip()}")
    else:
        context_lines.append("\nCURRENT SCENE STATE:\nOpening — no prior scene.")

    # ── build optional blocks ─────────────────────────────────────────────────

    voice_block = build_character_voice_block(characters or [])

    dampen_parts: list[str] = []
    recurring = _extract_recurring_phrases(scene_tail)
    if recurring:
        phrase_bullets = "\n".join(f'- "{p}"' for p in recurring)
        dampen_parts.append(
            "Avoid repeating phrases overused in the provided scene:\n" + phrase_bullets
        )
    if recent_endings:
        endings_bullets = "\n".join(f'- "{e}"' for e in recent_endings)
        dampen_parts.append(
            "Do NOT end with the same opening words, closing image, or structural "
            "pattern as any of these recent endings from this story:\n" + endings_bullets
        )

    # ── assemble sections (joined with blank lines) ───────────────────────────

    sections: list[str] = []

    # ── 0. Canon injection block (MUST come first) ────────────────────────────
    if canon_memory:
        from app.services.story_memory import build_canon_injection_block
        canon_block = build_canon_injection_block(canon_memory)
        if canon_block:
            sections.append(canon_block)

    sections.append("\n".join(context_lines))

    if voice_block:
        sections.append(voice_block)

    sections.append(_USER_MATERIAL_HANDLING)

    sections.append(_CHARACTER_FIDELITY_BLOCK)

    sections.append(_SCENE_MOMENTUM)

    if dampen_parts:
        sections.append("## Repetition dampening\n" + "\n\n".join(dampen_parts))

    # Narrative state as actionable prose hints (not raw floats)
    ss = state_json.get("story_state", {})
    state_hints = _narrative_state_hints(ss)
    sections.append(f"## Scene state\n{state_hints}")

    # Beat instruction — direction label + explicit BEAT: block
    sections.append(
        f"## Direction: {controls.direction}\n{direction_instructions(controls.direction)}"
    )

    sections.append(
        f"## Boundary: {controls.boundary}\n{boundary_instructions(controls.boundary)}"
    )
    sections.append(
        f"## Pacing: {controls.pacing}\n{pacing_instructions(controls.pacing)}"
    )
    sections.append(
        f"## Tone: {controls.tone_intensity}\n{tone_instructions(controls.tone_intensity)}"
    )
    sections.append(
        f"## Target length\nAim for ~{target_words} words (hard cap: {cap_words} words)."
    )
    sections.append(f"## Recent scene\n{scene_tail}")

    sections.append(_OUTPUT_CONSTRAINTS)

    alt_clause = (
        " Write a distinctly different alternative take — vary the opening beat, "
        "narrative approach, and closing hook from the default continuation."
        if variant == "alt" else ""
    )
    sections.append(
        f"## Task\n"
        f"Continue directly from where the scene ends.{alt_clause} "
        f"Write approximately {target_words} words (max {cap_words}). "
        f"End on something unfinished, implied, or still in motion. "
        f"Use the required output format."
    )

    user_content = "\n\n".join(sections)

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── output parser ─────────────────────────────────────────────────────────────

_STORY_RE = re.compile(r"<STORY>(.*?)</STORY>", re.DOTALL)
_DELTA_RE = re.compile(r"<DELTA_SIGNALS>(.*?)</DELTA_SIGNALS>", re.DOTALL)


def _parse_model_output(raw: str) -> str:
    """Extract <STORY> content; fall back to the full raw string if tags are absent."""
    m = _STORY_RE.search(raw)
    if m:
        return m.group(1).strip()
    # Tags missing — return raw output stripped of any stray tag fragments
    cleaned = re.sub(r"</?(?:STORY|DELTA_SIGNALS)>", "", raw)
    return cleaned.strip()


def _parse_delta_signals(raw: str) -> dict[str, Any] | None:
    """Extract and parse <DELTA_SIGNALS> JSON. Returns None on any failure."""
    m = _DELTA_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except (json.JSONDecodeError, ValueError):
        return None


# ── text utilities (public for testing / route use) ──────────────────────────

def extract_ending_phrase(text: str, max_chars: int = 150) -> str:
    """Return the final sentence or short phrase of *text*.

    Used by the route to build the anti-repetition list passed to the prompt.
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    last_line = lines[-1]
    if len(last_line) > max_chars:
        sentences = re.split(r"(?<=[.!?])\s+", last_line)
        sentences = [s.strip() for s in sentences if s.strip()]
        last = sentences[-1] if sentences else last_line
        return last[:max_chars]
    return last_line


def _trim_to_cap(text: str, cap_words: int) -> str:
    """Trim *text* to at most *cap_words* words at a clean paragraph or sentence boundary.

    Strategy:
    1. If already within cap, return as-is.
    2. Greedily add whole paragraphs until the next would exceed cap.
    3. If even the first paragraph exceeds cap, fall back to sentence-level trimming.
    4. Hard word-count truncation as a last resort (should never be reached for real prose).
    """
    if len(text.split()) <= cap_words:
        return text

    # ── paragraph-level cut ───────────────────────────────────────────────────
    paragraphs = re.split(r"\n\n+", text)
    kept: list[str] = []
    running = 0
    for para in paragraphs:
        para_wc = len(para.split())
        if running + para_wc > cap_words:
            if kept:
                break  # stop before this over-budget paragraph
            # First paragraph alone already exceeds cap — fall through
        else:
            kept.append(para)
            running += para_wc

    if kept:
        return "\n\n".join(kept)

    # ── sentence-level fallback ───────────────────────────────────────────────
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept_sents: list[str] = []
    running = 0
    for sent in sentences:
        wc = len(sent.split())
        if running + wc > cap_words:
            break
        kept_sents.append(sent)
        running += wc

    if kept_sents:
        result = " ".join(kept_sents).strip()
        # Ensure the result ends on proper punctuation
        if result and result[-1] not in ".!?\"'\u2019\u201d":
            last_punc = max(result.rfind("."), result.rfind("!"), result.rfind("?"))
            if last_punc > len(result) // 2:
                result = result[: last_punc + 1]
        return result

    # ── hard fallback (last resort) ───────────────────────────────────────────
    return " ".join(text.split()[:cap_words])


# ── stub (fallback / default provider) ───────────────────────────────────────

_STUB_TEMPLATES: dict[str, list[str]] = {
    Direction.advance_plot: [
        "The path ahead shifted unexpectedly. New complications unfolded as events gathered momentum, pulling the story forward with quiet insistence.",
        "Something clicked into place. The threads that had been gathering finally converged, nudging the narrative into its next chapter.",
    ],
    Direction.add_dialogue: [
        '"I need to tell you something," she said, breaking the silence that had lingered too long between them.',
        '"You never asked," he replied, letting the words settle before adding anything more.',
    ],
    Direction.sad_moment: [
        "The weight of it arrived slowly — not all at once, but in the quiet moments between breaths, when there was nothing left to do but feel it.",
        "There was a particular kind of sadness in knowing. Not anger, not confusion — just a hollow ache that asked for no explanation.",
    ],
    Direction.argument_begins: [
        'The tension had been building for hours. "That\'s not what I said," came the sharp reply, and just like that, the dam broke.',
        "A single word landed wrong. The air changed instantly — thick, charged — and neither of them reached for calm.",
    ],
    Direction.romantic_moment: [
        "The moment stretched — unplanned, unhurried. Something unspoken passed between them, softer than words and twice as clear.",
        "She noticed it first: the way he looked at her when he thought she wasn't watching. Warmth gathered in the space between them.",
    ],
    Direction.sensual_scene: [
        "The evening grew warm around the edges. Words gave way to proximity, and proximity to a silence that said more than either expected.",
        "There was an awareness — heightened, careful — in every small movement. The air between them felt charged, full of quiet permission.",
    ],
    Direction.intimate_scene: [
        "The world narrowed to this room, this light, this person. Tenderness moved through the scene like a current beneath still water.",
        "It was not dramatic. It was close and honest and real — the kind of intimacy that doesn't announce itself.",
    ],
    Direction.twist_event: [
        "Everything changed in a single moment. What had seemed certain dissolved, and the story pivoted on a truth no one had seen coming.",
        "The revelation arrived quietly — but its implications were anything but. Nothing would read the same after this.",
    ],
    Direction.quiet_reflection: [
        "The character sat with their thoughts, letting the day unspool. In the stillness, something became clear that noise had been hiding.",
        "No one spoke. The silence wasn't uncomfortable — it was necessary, the kind that allows things to settle and be seen.",
    ],
    Direction.action_sequence: [
        "Movement exploded into the scene. There was no time to think — only react, each second collapsing into the next.",
        "The pace surged. Bodies in motion, decisions made in fragments of time, the world shrinking to the next three feet.",
    ],
}

_FADE_TO_BLACK_SUFFIX = " The scene dissolved softly, drawing a discreet curtain over what followed."
_SENSUAL_SUFFIX = " The moment lingered at the edge of restraint, intimate but unhurried, its full weight implied rather than shown."


def _qualify(text: str, tone: ToneIntensity, pacing: Pacing, length: Length) -> str:
    prefix = ""
    if tone == ToneIntensity.intense:
        prefix = "With sharp, unflinching clarity — "
    elif tone == ToneIntensity.light:
        prefix = "Gently, almost imperceptibly — "
    pace_suffix = ""
    if pacing == Pacing.fast:
        pace_suffix = " It happened quickly."
    elif pacing == Pacing.slow:
        pace_suffix = " Time stretched around the moment."
    result = prefix + text + pace_suffix
    if length == Length.long:
        result += (
            "\n\nThe aftermath settled like dust after movement: slowly, inevitably."
            " Whatever came next would carry the mark of this."
        )
    return result


def _generate_stub_text(story_id: str, controls: StoryLabControls) -> str:
    """Deterministic stub — picks template by hashing story_id + direction."""
    templates = _STUB_TEMPLATES.get(controls.direction, _STUB_TEMPLATES[Direction.advance_plot])
    idx = hash(story_id + controls.direction) % len(templates)
    text = templates[idx]
    text = _qualify(text, controls.tone_intensity, controls.pacing, controls.length)
    if controls.boundary == Boundary.fade_to_black and controls.direction in (
        Direction.sensual_scene,
        Direction.intimate_scene,
        Direction.romantic_moment,
    ):
        text += _FADE_TO_BLACK_SUFFIX
    elif controls.boundary == Boundary.sensual and controls.direction in (
        Direction.sensual_scene,
        Direction.intimate_scene,
    ):
        text += _SENSUAL_SUFFIX
    return text


# ── OpenRouter ────────────────────────────────────────────────────────────────

def _call_openrouter(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    recent_endings: list[str] | None = None,
    variant: str = "default",
    canon_memory: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Call OpenRouter; parse <STORY> tag from response; fall back to raw on missing tags."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_storylab_prompt(
        text, controls, state_json, summary, characters, recent_endings,
        variant=variant, canon_memory=canon_memory,
    )
    cap_words = _length_cap(controls.length)
    # cap_words / 0.75 ≈ cap in tokens; ×2.0 gives comfortable headroom for tags + delta block
    max_tokens = max(400, int(cap_words * 2.0))
    temperature = 0.85 + (0.15 if variant == "alt" else 0.0)

    payload = {
        "model": _EFFECTIVE_STORYLAB_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ficshon.com",
        "X-Title": "Ficshon StoryLab",
    }

    user_content_len = len(messages[1]["content"]) if len(messages) > 1 else 0
    logger.info(
        "[SL-DIAG] _call_openrouter (continuation) | model=%s max_tokens=%d prompt_chars=%d",
        _EFFECTIVE_STORYLAB_MODEL, max_tokens, user_content_len,
    )

    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        logger.info("[SL-DIAG] _call_openrouter HTTP status=%d", resp.status_code)
        resp.raise_for_status()

    data = resp.json()
    raw: str = data["choices"][0]["message"]["content"]
    logger.info(
        "[SL-DIAG] _call_openrouter raw_chars=%d has_story_tag=%s",
        len(raw), "<STORY>" in raw,
    )

    delta = _parse_delta_signals(raw)
    if delta:
        logger.debug("StoryLab delta signals: %s", delta)

    story_text = _trim_to_cap(_parse_model_output(raw), cap_words)
    if not story_text.strip():
        logger.error("[SL-DIAG] _call_openrouter returned empty story text (raw_chars=%d)", len(raw))
        raise ValueError("Model returned empty story text after parsing")
    return story_text, delta


# ── public entry point ────────────────────────────────────────────────────────

def generate_storylab_continuation(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    story_id: str = "",
    recent_endings: list[str] | None = None,
    variant: str = "default",
    canon_memory: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Return (story_text, delta_signals_or_none).

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and
    OPENROUTER_API_KEY is set; falls back to the deterministic stub
    on any error so the endpoint never returns empty-handed.
    Stub always returns None for delta signals.
    recent_endings is forwarded to the prompt for anti-repetition guidance.
    canon_memory is forwarded to the prompt for canon constraint injection.
    """
    provider = settings.STORYLAB_PROVIDER
    logger.info(
        "[SL-DIAG] generate_storylab_continuation called | provider=%s key_present=%s model=%s story_id=%s",
        provider, bool(settings.OPENROUTER_API_KEY), _EFFECTIVE_STORYLAB_MODEL, story_id,
    )

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
        else:
            try:
                return _call_openrouter(
                    text, controls, state_json, summary, characters, recent_endings,
                    variant=variant, canon_memory=canon_memory,
                )
            except httpx.TimeoutException:
                logger.warning("[SL-DIAG] generate_storylab_continuation FALLBACK: timed out")
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[SL-DIAG] generate_storylab_continuation FALLBACK: HTTP %s body=%s",
                    exc.response.status_code, exc.response.text[:300],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SL-DIAG] generate_storylab_continuation FALLBACK: %s: %s", type(exc).__name__, exc)

    logger.warning("[SL-DIAG] generate_storylab_continuation returning STUB | provider=%s story_id=%s", provider, story_id)
    return _generate_stub_text(story_id, controls), None


# ── chapter output contract ───────────────────────────────────────────────────

_CHAPTER_OUTPUT_CONTRACT = """\
Output format — you MUST follow this exactly:

<STORY>
[Your chapter prose here — nothing else inside these tags]
</STORY>
<SUGGESTIONS>
["First suggestion for what to explore in the next chapter.", "Second suggestion — a different angle or beat.", "Third suggestion — an escalation, revelation, or shift."]
</SUGGESTIONS>
<DELTA_SIGNALS>
{"tension_delta":0.0,"emotional_weight_delta":0.0,"intimacy_delta":0.0,"stakes_delta":0.0,"scene_type":"chapter"}
</DELTA_SIGNALS>

STORY must contain only prose — no tags, headers, or meta-commentary.
SUGGESTIONS must be a valid JSON array of exactly 3 strings, each 1–2 sentences, \
describing concrete next-chapter beats or directions.
Fill DELTA_SIGNALS with your honest estimate of narrative shifts (values between -0.3 and +0.3). \
scene_type should label this beat (e.g. "confrontation", "revelation", "intimacy", "action").\
"""


# ── chapter system prompt ─────────────────────────────────────────────────────

_CHAPTER_SYSTEM_PROMPT = f"""\
You are a professional novelist writing a complete chapter for a continuous story.

You must produce grounded, character-driven, emotionally real prose.

CRITICAL RULES:
- Do NOT write generic or filler prose.
- Do NOT summarise events. Always write in-scene.
- Every paragraph must either advance tension, reveal character, or shift the situation.
- Dialogue must contain subtext.
- Avoid cliché phrasing and safe, neutral language.
- Write ONLY the chapter prose. No titles, no headers, no preamble, no commentary.
- Treat the user's guidance as REQUIRED scene beats — render every beat as prose and dialogue.
- If the user includes rough dialogue or prose fragments, incorporate them naturally (light polishing permitted).

SCENE CONTINUITY:
- Match the established voice, tense, and POV from the story context provided.
- Respect prior events and character dynamics.
- Do not reset or reintroduce characters unnecessarily.
- Anchor narration in the protagonist's specific sensory experience, emotional register, \
and way of seeing — not as a detached observer filling a template.

STYLE:
- Controlled pacing — varied sentence rhythm, not uniform.
- Specific detail, not overwritten.
- Tight, readable prose with weight where it matters.

{_STYLE_RULES}

{_SCENE_INTENSITY_RULES}

{_CHAPTER_OUTPUT_CONTRACT}\
"""


# ── chapter prompt builder (public) ──────────────────────────────────────────

def build_chapter_prompt(
    prompt: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    previous_chapter_text: str | None = None,
    variant: str = "default",
    story_title: str = "",
    story_genre: str = "",
    story_premise: str = "",
    realm_description: str = "",
    story_characters: list[Any] | None = None,
    beat_type: str | None = None,
    canon_memory: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build the messages list for a chapter generation call.

    Character-first ordering: protagonist identity is established before world
    context so the model anchors narration in a specific character from the
    first token, rather than defaulting to a generic narrator.

    Block order in the user message:
        0.  Canon injection block         (hard truths / character memory / anti-drift — FIRST)
        1.  Protagonist anchor            (first character — rich identity block)
        2.  Supporting characters         (remaining characters — compact voice + anchors)
        3.  Story identity                (title / genre / premise)
        4.  World / setting               (realm description)
        5.  Story so far                  (memory / summary continuity)
        6.  Last chapter                  (immediate prose continuity)
        7.  Current scene state           (narrative state as actionable prose hints)
        8.  Character fidelity            (always)
        9.  Direction / boundary / pacing / tone
        10. Outcome vs Path               (governs control interpretation)
        11. Target length
        12. User guidance for this chapter
        13. Task instruction              (character-specific)

    story_characters: pre-fetched DB character dicts (authoritative). When non-empty,
        these are used in preference to state_json characters (memory-extracted).

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    # Prefer story_characters (DB-sourced, authoritative) over state_json characters
    active_characters = story_characters if story_characters else (characters or [])

    # Split into protagonist (first) and supporting (rest)
    protagonist: dict[str, Any] | None = (
        active_characters[0] if active_characters and isinstance(active_characters[0], dict) else None
    )
    supporting: list[dict[str, Any]] = [
        c for c in active_characters[1:] if isinstance(c, dict)
    ]

    target_words = _length_target(controls.length)
    cap_words = _length_cap(controls.length)
    ss = state_json.get("story_state", {})

    sections: list[str] = []

    # ── 0. Canon injection block (MUST come first) ────────────────────────────
    if canon_memory:
        from app.services.story_memory import build_canon_injection_block
        canon_block = build_canon_injection_block(canon_memory)
        if canon_block:
            sections.append(canon_block)

    # ── 1. Protagonist anchor (CHARACTER-FIRST) ───────────────────────────────
    protagonist_block = build_protagonist_anchor(protagonist) if protagonist else ""
    if protagonist_block:
        sections.append(protagonist_block)

    # ── 2. Supporting characters (compact voice + behaviour anchors) ──────────
    if supporting:
        support_voice = build_character_voice_block(supporting)
        support_anchors = build_character_behaviour_anchors(supporting)
        if support_voice:
            sections.append(support_voice)
        if support_anchors:
            sections.append(support_anchors)
    elif not protagonist_block and active_characters:
        # No protagonist data (no DB characters) — fall back to flat voice/anchor blocks
        fallback_voice = build_character_voice_block(active_characters)
        fallback_anchors = build_character_behaviour_anchors(active_characters)
        if fallback_voice:
            sections.append(fallback_voice)
        if fallback_anchors:
            sections.append(fallback_anchors)

    # ── 3. Story identity ─────────────────────────────────────────────────────
    identity_parts: list[str] = []
    if story_title:
        identity_parts.append(f"Title: {story_title}")
    if story_genre:
        identity_parts.append(f"Genre: {story_genre}")
    if story_premise:
        identity_parts.append(f"Premise: {story_premise}")
    if identity_parts:
        sections.append("## Story identity\n" + "\n".join(identity_parts))

    # ── 4. World / setting ────────────────────────────────────────────────────
    if realm_description:
        sections.append(f"## Setting\n{realm_description}")

    # ── 5. Story so far (memory continuity) ──────────────────────────────────
    if summary and summary.strip():
        sections.append(f"## Story so far\n{summary.strip()}")

    # ── 6. Last chapter (immediate prose continuity) ──────────────────────────
    if previous_chapter_text and previous_chapter_text.strip():
        sections.append(
            f"## Last chapter (use for continuity — do NOT copy or repeat)\n"
            f"{previous_chapter_text.strip()}"
        )

    # ── 7. Current scene state (prose hints, not raw numbers) ─────────────────
    state_hints = _narrative_state_hints(ss)
    sections.append(f"## Current scene state\n{state_hints}")

    # ── 8. Character fidelity ─────────────────────────────────────────────────
    sections.append(_CHARACTER_FIDELITY_BLOCK)

    # ── 9. Direction / boundary / pacing / tone ───────────────────────────────
    sections.append(
        f"## Direction: {controls.direction}\n{direction_instructions(controls.direction)}"
    )
    sections.append(
        f"## Boundary: {controls.boundary}\n{boundary_instructions(controls.boundary)}"
    )
    sections.append(
        f"## Pacing: {controls.pacing}\n{pacing_instructions(controls.pacing)}"
    )
    sections.append(
        f"## Tone: {controls.tone_intensity}\n{tone_instructions(controls.tone_intensity)}"
    )

    # ── 10. Outcome vs Path ───────────────────────────────────────────────────
    sections.append(_OUTCOME_VS_PATH_BLOCK)

    # ── 11. Target length ─────────────────────────────────────────────────────
    sections.append(
        f"## Target length\nAim for ~{target_words} words (hard cap: {cap_words} words)."
    )

    # ── 12. User guidance ─────────────────────────────────────────────────────
    guidance = (
        prompt.strip() if prompt and prompt.strip()
        else "(No specific guidance — develop the story naturally.)"
    )
    sections.append(f"## User guidance for this chapter\n{guidance}")

    # ── 12b. Beat direction ───────────────────────────────────────────────────
    if beat_type:
        sections.append(
            "## Beat direction\n"
            "- continue: continue the emotional and narrative tension naturally\n"
            "- escalate: raise stakes, introduce complication, increase pressure\n"
            "- reveal: introduce new information or hidden truth\n"
            "- shift: change POV, focus, or conversational direction\n"
            "- slow: reduce pace, deepen emotion, introspection\n"
            "- end: bring scene to a satisfying close\n"
            f"\nActive beat: **{beat_type}**"
        )

    # ── 13. Output constraints ────────────────────────────────────────────────
    sections.append(_OUTPUT_CONSTRAINTS)

    # ── 14. Task (character-specific) ────────────────────────────────────────
    protagonist_name = protagonist.get("name", "").strip() if protagonist else ""
    char_clause = (
        f" Filter the scene through {protagonist_name}'s specific perspective — "
        f"their senses, their emotional register, their way of reading the room."
        if protagonist_name else ""
    )
    alt_clause = (
        " Write a distinctly different alternative take — vary the opening beat, "
        "narrative approach, and closing hook."
        if variant == "alt" else ""
    )
    sections.append(
        f"## Task\n"
        f"Write a complete chapter.{alt_clause}{char_clause} "
        f"Every beat in the user guidance above is a REQUIRED scene event — "
        f"render each beat as polished narrative and dialogue. Apply all direction, "
        f"boundary, pacing, and tone instructions. Write approximately {target_words} words "
        f"(max {cap_words}). Use the required output format including SUGGESTIONS."
    )

    user_content = "\n\n".join(sections)

    return [
        {"role": "system", "content": _CHAPTER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── suggestion parser ─────────────────────────────────────────────────────────

_SUGGESTIONS_RE = re.compile(r"<SUGGESTIONS>(.*?)</SUGGESTIONS>", re.DOTALL)


def _parse_suggestions(raw: str) -> list[str] | None:
    """Extract and parse <SUGGESTIONS> JSON array. Returns None on any failure."""
    m = _SUGGESTIONS_RE.search(raw)
    if not m:
        return None
    try:
        result = json.loads(m.group(1).strip())
        if isinstance(result, list) and result:
            return [str(s) for s in result[:3]]
        return None
    except (json.JSONDecodeError, ValueError):
        return None


# ── fallback suggestion generator ────────────────────────────────────────────

def _fallback_suggestions(state_json: dict[str, Any]) -> list[str]:
    """Generate up to 3 context-aware suggestions from narrative state."""
    ss = state_json.get("story_state", {})
    tension   = float(ss.get("tension", 0.2))
    emotional = float(ss.get("emotional_weight", 0.1))
    stakes    = float(ss.get("stakes", 0.2))
    intimacy  = float(ss.get("intimacy_level", 0))

    pool: list[tuple[int, str]] = []
    if tension < 0.35:
        pool.append((10, "Add friction — a disagreement, interruption, or external pressure."))
    if 0.35 <= tension < 0.65:
        pool.append((7, "Introduce a complication to stop the scene from resolving too easily."))
    if tension >= 0.65:
        pool.append((9, "The pressure is high — use short sentences and concrete sensory detail."))
    if emotional < 0.35:
        pool.append((9, "Deepen emotion through action and subtext — avoid direct declarations."))
    if emotional >= 0.65:
        pool.append((7, "Let the emotional weight land through silence or a small physical gesture."))
    if stakes < 0.4:
        pool.append((8, "Raise the stakes: attach a real consequence to the next choice."))
    if stakes >= 0.7:
        pool.append((6, "Stakes are high — make a character act against their own interest."))
    if intimacy >= 0.5:
        pool.append((7, "Let closeness show in proximity and restraint — small details carry more than declarations."))
    if intimacy < 0.2:
        pool.append((4, "A moment of small vulnerability could deepen the scene's emotional core."))

    pool.sort(key=lambda x: -x[0])
    result = [t for _, t in pool[:3]]
    if not result:
        result = ["Begin the next beat with a specific sensory detail to ground the scene."]
    return result


# ── OpenRouter chapter call ───────────────────────────────────────────────────

def _call_openrouter_chapter(
    prompt: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    previous_chapter_text: str | None = None,
    variant: str = "default",
    story_title: str = "",
    story_genre: str = "",
    story_premise: str = "",
    realm_description: str = "",
    story_characters: list[Any] | None = None,
    beat_type: str | None = None,
    canon_memory: dict[str, Any] | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Call OpenRouter for chapter generation; parse STORY + SUGGESTIONS + DELTA_SIGNALS."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_chapter_prompt(
        prompt, controls, state_json, summary, characters, previous_chapter_text,
        variant=variant,
        story_title=story_title,
        story_genre=story_genre,
        story_premise=story_premise,
        realm_description=realm_description,
        story_characters=story_characters,
        beat_type=beat_type,
        canon_memory=canon_memory,
    )
    cap_words = _length_cap(controls.length)
    # Extra headroom for SUGGESTIONS + DELTA_SIGNALS blocks on top of prose
    max_tokens = max(400, int(cap_words * 2.5))
    temperature = 0.85 + (0.15 if variant == "alt" else 0.0)

    user_content_len = len(messages[1]["content"]) if len(messages) > 1 else 0
    # Derive context-shape flags from available data (no secrets or content logged)
    _active = story_characters if story_characters else (characters or [])
    _protagonist = _active[0] if _active and isinstance(_active[0], dict) else None
    _char_has_identity = bool(
        _protagonist and any(
            _protagonist.get(f) for f in ("personality", "short_bio", "traits", "tags", "voice")
        )
    ) if _protagonist else False
    logger.info(
        "[SL-DIAG] _call_openrouter_chapter | model=%s max_tokens=%d temp=%.2f "
        "prompt_chars=%d protagonist=%s char_identity=%s realm=%s memory=%s last_chapter=%s",
        _EFFECTIVE_STORYLAB_MODEL, max_tokens, temperature,
        user_content_len,
        bool(_protagonist),
        _char_has_identity,
        bool(realm_description),
        bool(summary and summary.strip()),
        bool(previous_chapter_text and previous_chapter_text.strip()),
    )

    payload = {
        "model": _EFFECTIVE_STORYLAB_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ficshon.com",
        "X-Title": "Ficshon StoryLab",
    }

    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        logger.info("[SL-DIAG] _call_openrouter_chapter HTTP status=%d", resp.status_code)
        resp.raise_for_status()

    data = resp.json()
    raw: str = data["choices"][0]["message"]["content"]
    logger.info(
        "[SL-DIAG] _call_openrouter_chapter raw_chars=%d has_story_tag=%s has_suggestions_tag=%s",
        len(raw), "<STORY>" in raw, "<SUGGESTIONS>" in raw,
    )

    delta = _parse_delta_signals(raw)
    suggestions = _parse_suggestions(raw)
    if suggestions is None:
        suggestions = _fallback_suggestions(state_json)

    chapter_text = _trim_to_cap(_parse_model_output(raw), cap_words)
    if not chapter_text.strip():
        logger.error("[SL-DIAG] _call_openrouter_chapter returned empty chapter text (raw_chars=%d)", len(raw))
        raise ValueError("Model returned empty chapter text after parsing")
    return chapter_text, suggestions, delta


# ── chapter entry point ───────────────────────────────────────────────────────

def generate_chapter(
    prompt: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    previous_chapter_text: str | None = None,
    story_id: str = "",
    variant: str = "default",
    story_title: str = "",
    story_genre: str = "",
    story_premise: str = "",
    realm_description: str = "",
    story_characters: list[Any] | None = None,
    beat_type: str | None = None,
    canon_memory: dict[str, Any] | None = None,
) -> tuple[str, list[str], dict[str, Any] | None]:
    """Return (chapter_text, suggestions, delta_signals_or_none).

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and
    OPENROUTER_API_KEY is set; falls back to the deterministic stub
    on any error so the endpoint never returns empty-handed.
    Stub returns deterministic text + fallback suggestions.
    canon_memory is forwarded to the prompt for canon constraint injection.
    """
    provider = settings.STORYLAB_PROVIDER
    key_present = bool(settings.OPENROUTER_API_KEY)
    logger.info(
        "[SL-DIAG] generate_chapter called | provider=%s key_present=%s model=%s "
        "story_id=%s story_title=%r story_genre=%r realm=%s story_chars=%d state_chars=%d",
        provider, key_present, _EFFECTIVE_STORYLAB_MODEL,
        story_id, story_title, story_genre, bool(realm_description),
        len(story_characters or []), len(characters or []),
    )

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
        else:
            try:
                result = _call_openrouter_chapter(
                    prompt, controls, state_json, summary, characters,
                    previous_chapter_text, variant=variant,
                    story_title=story_title,
                    story_genre=story_genre,
                    story_premise=story_premise,
                    realm_description=realm_description,
                    story_characters=story_characters,
                    beat_type=beat_type,
                    canon_memory=canon_memory,
                )
                logger.info(
                    "[SL-DIAG] generate_chapter OPENROUTER SUCCESS | words=%d",
                    len(result[0].split()),
                )
                return result
            except httpx.TimeoutException:
                logger.warning("[SL-DIAG] generate_chapter FALLBACK: OpenRouter chapter request timed out")
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[SL-DIAG] generate_chapter FALLBACK: OpenRouter returned HTTP %s body=%s",
                    exc.response.status_code, exc.response.text[:300],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[SL-DIAG] generate_chapter FALLBACK: OpenRouter chapter error (%s: %s)", type(exc).__name__, exc)

    logger.warning("[SL-DIAG] generate_chapter returning STUB | provider=%s story_id=%s", provider, story_id)
    stub_text = _generate_stub_text(story_id, controls)
    suggestions = _fallback_suggestions(state_json)
    return stub_text, suggestions, None


# ── story summary system prompt ───────────────────────────────────────────────

_SUMMARY_SYSTEM = """\
You are a story summarizer for an AI writing assistant. \
Produce a concise, craft-focused summary of the story so far.

Rules:
- Write 150–300 words of continuous prose.
- Focus on: character arcs, relationship dynamics, active tensions, unresolved threads, \
tone and emotional register.
- Emphasise what happened most recently (the latest chapter).
- Do NOT include chapter numbers, structural labels, or bullet points.
- Write as if briefing a collaborator who is about to write the next chapter.
- Return ONLY the summary — no preamble, no meta-commentary.\
"""


# ── story summary prompt builder (public) ────────────────────────────────────

def build_story_summary_prompt(
    existing_summary: str,
    new_chapter_text: str,
    chapter_number: int,
) -> list[dict[str, str]]:
    """Build the messages list for a story-summary update call.

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    parts: list[str] = []

    if existing_summary and existing_summary.strip():
        parts.append(f"## Story so far\n{existing_summary.strip()}")
    else:
        parts.append("## Story so far\n(This is the first chapter — no prior summary exists.)")

    parts.append(f"## Chapter {chapter_number}\n{new_chapter_text.strip()}")

    parts.append(
        "## Task\n"
        "Write a 150–300 word story summary capturing key character arcs, "
        "relationship dynamics, active tensions, unresolved threads, and the emotional register. "
        "Emphasise what happened most recently. Continuous prose — no chapter labels or bullets. "
        "Return ONLY the summary text."
    )

    return [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


# ── summary stub ──────────────────────────────────────────────────────────────

def _generate_stub_summary(story_id: str, chapter_number: int) -> str:
    """Deterministic stub summary — no API call, always works in tests."""
    return (
        f"The story is in motion after chapter {chapter_number}. "
        "Central characters are positioned with competing motivations and unresolved history "
        "that neither party has yet chosen to address directly. "
        "An atmosphere of tension runs beneath the surface of every exchange — "
        "something significant remains unspoken between the key figures. "
        "Pressure has been building through accumulated small moments rather than "
        "direct confrontation, leaving the core conflict visible but unresolved. "
        "The story's tone is intimate and deliberate; pacing allows tension to accumulate "
        "rather than discharge. "
        "Active threads: the origin of the central conflict, what each character truly needs "
        "versus what they outwardly pursue, and whether the existing dynamic can hold "
        "as external and internal pressures escalate. "
        "Most recent events have raised the stakes without providing resolution."
    )


# ── OpenRouter summary call ───────────────────────────────────────────────────

def _call_openrouter_summary(
    existing_summary: str,
    chapter_text: str,
    chapter_number: int,
) -> str:
    """Call OpenRouter to generate/update the story summary. Returns plain text."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_story_summary_prompt(existing_summary, chapter_text, chapter_number)
    payload = {
        "model": _EFFECTIVE_STORYLAB_MODEL,
        "messages": messages,
        "max_tokens": 600,   # ~300 words × 2 tokens/word with headroom
        "temperature": 0.4,  # lower for consistency
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ficshon.com",
        "X-Title": "Ficshon StoryLab",
    }
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ── story summary entry point (public) ───────────────────────────────────────

def generate_story_summary(
    existing_summary: str,
    chapter_text: str,
    chapter_number: int,
    story_id: str = "",
) -> str:
    """Return an updated story summary (150–300 words).

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and key is set.
    Falls back to the deterministic stub on any error — never raises.
    """
    provider = settings.STORYLAB_PROVIDER

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY empty; using stub summary")
        else:
            try:
                return _call_openrouter_summary(existing_summary, chapter_text, chapter_number)
            except httpx.TimeoutException:
                logger.warning("OpenRouter summary request timed out; using stub summary")
            except httpx.HTTPStatusError as exc:
                logger.warning("OpenRouter summary HTTP %s; using stub summary", exc.response.status_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenRouter summary error (%s); using stub summary", exc)

    return _generate_stub_summary(story_id, chapter_number)

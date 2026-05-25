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
    _CINEMATIC_PROSE_LAYER                        -> str   # cinematic prose layer block (testable)
"""
import json
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.storylab import (
    Boundary,
    Direction,
    Length,
    Pacing,
    RPReplyFormatting,
    RPReplyIntensity,
    RPReplyPerspective,
    RPReplyResponseLength,
    RPReplyStyleMatch,
    StoryLabControls,
    ToneIntensity,
)
from app.services.rp_behavior_engine import (
    build_behavior_enforcement_block,
    build_partner_silence_correction,
    build_waiting_loop_correction,
    detect_partner_control,
    detect_partner_silence_severe,
    detect_scene_stall,
    detect_waiting_loop,
    score_inferno_anatomy_density,
    NO_PARTNER_BRIDGE_INSTRUCTION,
    PARTNER_CONTROL_PROTECTION_BLOCK,
    PARTNER_SILENCE_LAYER,
    SCENE_PROGRESSION_BLOCK,
    SELECTED_CHARACTER_DRIVES_SCENE,
    TURN_BOUNDARY_FOOTER,
)
from app.services.godmod_validator import detect_godmod_violations
from app.services.rp_scene_engine import (
    detect_scene_beats,
    detect_repeated_beats,
    determine_next_scene_goal,
    build_scene_progression_block,
    detect_scene_regression,
)
from app.services.rp_escalation import get_heat_prompt_block
from app.services.rp_models import (
    effective_heat_level,
    resolve_inferno_model,
    resolve_rp_model,
)
from app.services.rp_beat_planner import (
    beat_completion_mode,
    build_beat_execution_block,
    detect_multi_beat_instruction,
    extract_requested_beats,
)
from app.services.rp_spatial_engine import detect_spatial_state, build_spatial_continuity_block
from app.services.rp_narrative_engine import build_narrative_propulsion_block
from app.services.storylab_narrative_engine import (
    build_storylab_propulsion_block,
    build_storylab_loop_correction_block,
    detect_story_repetition,
    detect_story_progression,
)
from app.services.rp_style_engine import (
    DEFAULT_ARCHETYPE,
    DARK_ROMANCE_PROSE_LAYER,
    ESCALATION_STORY_LAYER,
    detect_ai_cadence,
    detect_wrong_pov,
    get_archetype_prompt_block,
    maintain_scene_continuity,
)

logger = logging.getLogger(__name__)

# Fallback model used when STORYLAB_MODEL is empty or not configured.
# qwen/qwen-2.5-72b-instruct is a confirmed working non-Bedrock OpenRouter route,
# already present in the RP model registry (rp_models.py).
_STORYLAB_FALLBACK_MODEL: str = "qwen/qwen-2.5-72b-instruct"

# Resolved at import time. No slug rewriting is applied — if a configured model slug
# returns errors (404 / 400), update STORYLAB_MODEL in .env to a valid slug instead.
_EFFECTIVE_STORYLAB_MODEL: str = settings.STORYLAB_MODEL.strip() or _STORYLAB_FALLBACK_MODEL
if not settings.STORYLAB_MODEL.strip():
    logger.warning(
        "[SL-DIAG] STORYLAB_MODEL is empty or unset; using fallback model %r. "
        "Set STORYLAB_MODEL in .env to suppress this warning.",
        _EFFECTIVE_STORYLAB_MODEL,
    )
else:
    logger.info("[SL-DIAG] STORYLAB_MODEL=%r (effective)", _EFFECTIVE_STORYLAB_MODEL)

_REQUEST_TIMEOUT = 90.0  # seconds for LLM calls

# ── length → (target_words, hard_cap_words) ──────────────────────────────────
#
# Targets are what we ask the model for; caps are the trim ceiling applied
# to the raw response.  Minimums for live-provider output that trigger a retry
# are stored separately in _STUB_MIN_WORDS (same keys, lower values).
#
# short  → 500  words target   /  600  words cap   (quick beat, ~1 scene beat)
# medium → 900  words target   /  1100 words cap   (single chapter scene)
# long   → 1500 words target   /  2000 words cap   (full chapter, multiple beats)

_LENGTH_CONFIG: dict[str, tuple[int, int]] = {
    Length.short:  (500,  600),
    Length.medium: (900,  1100),
    Length.long:   (1500, 2000),
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


# ── cinematic prose layer (static, inserted in both prompt builders) ─────────

_CINEMATIC_PROSE_LAYER = """\
## CINEMATIC PROSE LAYER

These instructions govern scene physicality and texture. Apply them throughout,
not only at peak moments.

**Physical space and movement**
- Every scene occupies a specific physical location. Establish it through the
  character's sensory contact: what they hear, feel underfoot, smell, or catch
  at the edge of vision. Filter every setting detail through the character's
  current emotional state — not a neutral camera.
- Track where characters are in the space and how they move through it.
  Proximity, distance, and the act of crossing a room carry meaning.
  At least one movement through the environment belongs in every sustained scene.
- Include one environmental detail per scene that is specific to THIS place —
  not generic atmosphere.

**Body language and micro-reactions**
- Show character state through physical specifics: where their hands are, how
  they hold themselves, what their body does that their words contradict.
- Micro-reactions matter: the pause before answering, a glance toward the exit,
  a hand that starts to reach and stops. These reveal more than interior narration.
- Let two characters' bodies relate — mirroring, withdrawing, occupying more
  space, failing to fully turn toward each other.

**Scene texture (required in every major beat)**
Every significant beat must include at least one of:
- a character gesture or deliberate physical action
- spatial movement (someone crosses the room, steps back, turns away)
- a non-visual sensory cue (sound, temperature, texture, smell)
- an environmental detail that shifts or reflects the emotional register
- an internal physical response to emotional state — shown through the body,
  not named

**Relationship and tension expression**
When attraction, rivalry, fear, loyalty, suspicion, or any charged dynamic is
present, express it through:
- proximity and the management of distance between characters
- what one character notices specifically about the other
- pauses and what is withheld rather than said
- tactical word choice — what is offered, deflected, redirected
- body language that contradicts the surface tone
Do NOT name or explain the dynamic. Let behaviour make it legible.

**Dialogue with competing motives**
Characters speak from a position — something they want, protect, test, or
conceal. Their words reflect that even when the surface subject is mundane.
Allow characters to avoid direct answers, answer a different question, or
reveal something while appearing to conceal it.
Let a line misfire occasionally: a question that sounds like an accusation,
a comfort that lands as a challenge.

**Restraint (MANDATORY)**
- Richness is not length. Do not inflate with stacked sensory inventories,
  repetitive internal monologue, or circling introspection.
- Do not push every scene toward romance or sexuality. Stay in the register
  the scene actually calls for.
- Do not manufacture drama by contradicting established facts.

**Canon priority (ABSOLUTE)**
Canon and memory constraints outrank cinematic style at all times.
Never add atmosphere, drama, or emotional texture by contradicting protected
facts, established character behaviour, or world rules in memory.
If cinematic instinct conflicts with canon, canon wins — always.\
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
    propulsion_correction: str = "",
) -> list[dict[str, str]]:
    """Build and return the messages list for the OpenRouter chat completions call.

    Block order in the user message:
        0.  Canon injection block      (if memory present — hard truths, character state, anti-drift)
        1.  Story context (title / genre / premise / characters / current scene state)
        2.  Character voice block      (if characters present)
        3.  User material handling     (always — canonical manuscript + beat rendering rules)
        4.  Character fidelity         (always — psychology-first escalation constraint)
        5.  Scene momentum requirement (always)
        5b. Narrative propulsion       (always — anti-loop, settings-aware scene momentum)
        6.  Repetition dampening       (recurring phrases + recent endings, when present)
        7.  Scene state hints          (narrative state as actionable prose guidance)
        8.  Cinematic prose layer      (physical space, body language, texture, restraint)
        9.  Beat instruction           (direction → explicit BEAT: block)
       10.  Boundary / pacing / tone
       11.  Target length
       12.  Recent scene text
       13.  Output constraints
       13b. Loop correction            (only on retry — override for detected repetition loops)
       14.  Task instruction

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

    sections.append(
        "## Narrative propulsion\n" + build_storylab_propulsion_block(controls)
    )

    if dampen_parts:
        sections.append("## Repetition dampening\n" + "\n\n".join(dampen_parts))

    # Narrative state as actionable prose hints (not raw floats)
    ss = state_json.get("story_state", {})
    state_hints = _narrative_state_hints(ss)
    sections.append(f"## Scene state\n{state_hints}")

    sections.append(_CINEMATIC_PROSE_LAYER)

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
    _cont_length_note = ""
    if controls.length == Length.long:
        _cont_length_note = (
            " Do NOT stop before 1,500 words. "
            "Continue through multiple beats until you reach the target."
        )
    elif controls.length == Length.medium:
        _cont_length_note = " Write at least 900 words — cover the full scene beat."
    sections.append(
        f"## Target length — MANDATORY\n"
        f"**{target_words} words minimum** (hard cap: {cap_words} words).{_cont_length_note}"
    )
    sections.append(f"## Recent scene\n{scene_tail}")

    sections.append(_OUTPUT_CONSTRAINTS)

    if propulsion_correction:
        sections.append("## Loop correction (MANDATORY)\n" + propulsion_correction)

    alt_clause = (
        " Write a distinctly different alternative take — vary the opening beat, "
        "narrative approach, and closing hook from the default continuation."
        if variant == "alt" else ""
    )
    sections.append(
        f"## Task\n"
        f"Continue directly from where the scene ends.{alt_clause} "
        f"**Write at least {target_words} words.** Do not stop early. "
        f"If the scene feels complete, continue into the next beat or escalate. "
        f"Hard cap: {cap_words} words. End on something unfinished or still in motion. "
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


# ── minimum word counts per length setting ───────────────────────────────────
# These are the LIVE provider output minimums.  If the model returns fewer
# words than this, generate_* will retry once.  Stub templates are allowed to
# be shorter for short length (they're deliberate compact placeholders).

_STUB_MIN_WORDS: dict[str, int] = {
    Length.short:  500,
    Length.medium: 900,
    Length.long:   1500,
}


def _minimum_words(length: Any) -> int:
    """Minimum acceptable word count for a given Length value."""
    return _STUB_MIN_WORDS.get(length, 350)


# ── rich multi-paragraph stub templates (one per direction, 700–800 words) ───
#
# Used for Length.medium and Length.long. Trimmed to target word count at
# paragraph boundaries for medium; used at full length for long.
# All templates are open-ended narrative — no scene-resolution cadence.

_STUB_RICH_TEMPLATES: dict[str, str] = {
    Direction.advance_plot: """\
The elevator did not come. She pressed the button twice, then stood back and looked at the display — stuck on 3, the same as it had been for the last four minutes — and took the stairs instead.

Three floors up, on the landing between seven and eight, she passed Marcus coming down. He had his coat on and his bag in his hand and the expression of a man who had been found before he was ready to be.

"I was coming to you," he said.

"You were leaving." She kept moving. He turned and followed.

The stairwell was narrow, the walls close enough that she could hear him behind her and feel the cold coming off his coat. She stopped on the step that put them level.

"The papers were filed this morning," he said. "I couldn't stop it."

"You didn't try to stop it." She watched his face. "I saw the wire transfer, Marcus. You routed everything through a holding account I've never heard of. That's not someone who couldn't stop something. That's someone who helped."

He looked at the wall behind her. When he looked back he was done with the shape he'd been giving to things.

"There were details you didn't need," he said.

"That's not true anymore."

He shifted the bag. She could see him deciding — could see the exact moment when he stopped managing it and made the choice she'd been waiting three weeks for him to make.

"The account has two names on it," he said. "Mine and someone else's. The other name is why all of this started."

"Whose name?"

"If I tell you, you're inside it."

"Marcus." She kept her voice flat. "I have been inside it since before I understood what it was. The only difference now is whether I know."

He looked at the bag. He looked at her. He looked at the door above them and the one below as if calculating, one last time, whether there was a version of this in which he simply walked through one of them and the problem dissolved.

There wasn't. She could see him understand that.

"Come back upstairs," he said. "I'll show you the documentation."

She moved past him. She was already at the door when she realized she'd expected him to follow. He hadn't moved.

She waited.

Down in the lobby, something electrical clunked back on — the lights, the elevator hum, the building resuming its general competent noise. His face in the new light looked tired in a specific way, the way people looked when they'd been carrying something in secret for so long that the secret had changed shape.

Not everything, she understood. That was something.

She held the door. He came through it.

The corridor on seven smelled of old carpet and a diffuser someone had plugged in near the service entrance, doing its best against the building's general indifference. She noticed it now because she was paying attention to everything at once, which was the way her mind worked when the stakes were real: observation as control.

The apartment door was locked. She had the key. She let them both in.

The table by the window had folders on it she hadn't put there — three of them, organized, in an order that suggested he'd been through this before. The realization moved through her without surprise, which was itself a kind of information.

"Sit down," she said.

He sat. She opened the first folder.

The document inside was twelve pages, legal formatting, and in the third paragraph she found the name he hadn't said on the stairs. She read it twice. She kept her face neutral.

Outside the window, the city was doing what it always did. She thought about all the times she'd sat at this table with a cup of coffee and looked at that same view and understood nothing of what was actually happening.

She turned the page.

The second document had a different header. She read the date first. Then the signatory. Then, slowly, the first paragraph, which was brief and used plain language and was the most unambiguous thing she had read in weeks.

Outside, the city. The hum of it through the window. Traffic two floors below, the particular frequency of a Tuesday afternoon, meaning nothing, continuing regardless.\
""",

    Direction.add_dialogue: """\
"You said you'd call," she said.

She hadn't planned to lead with it. She'd planned to be pleasant, to pour herself a glass of water and sit in the chair by the window and let him explain himself on his own terms. That had lasted approximately four seconds.

Daniel set his keys on the counter. He didn't look at her directly — looked at the counter, at the keys, at the middle distance between the kitchen and the hall. "Something came up."

"Something always comes up."

"That's not fair."

"Which part isn't?" She sat down. She didn't want to stand over him and she didn't want to stand anywhere in particular so she sat. "The part where you said you'd call, or the part where you didn't?"

He came into the main room. He stood near the couch but didn't sit. The lamp was on the low setting and the light made everything look approximate, which was probably not what either of them needed right now. "Can we not do this tonight? I just got in."

"You've been getting in for three weeks and we don't do this on any of those nights either. When are we doing it?"

He looked at her. Not through her or around her — at her, which was something. "I don't know what you want from me."

"I want the answer to the thing I asked you."

"Which thing." Not a question. He knew which thing.

She didn't repeat it. She'd asked it once, in this room, on the night that had started all the others — the night the whole texture of things had changed without any single moment she could point to. She'd asked once. She wasn't going to make a habit of it.

He ran a hand through his hair. He sat down on the arm of the couch, which was the posture of someone who hadn't committed to staying but hadn't left either. She noticed that. She had started noticing a lot of things.

"I don't have a good answer," he said.

"A bad answer would do."

Something crossed his face — not amusement exactly, but the ghost of it, from before, from when things between them were easier. "You'd take a bad answer."

"I'd take an honest one."

He was quiet for a long moment. Long enough that she thought about getting up, going to the kitchen, putting the kettle on — doing anything that wasn't sitting here in the approximate lamplight watching him find a way not to tell her things. Then he said:

"I was with Rosen."

She hadn't expected that name. "David Rosen."

"Yes."

"You haven't spoken to David Rosen in four years." She said it as a fact because it was a fact. She had been there when Daniel had made that decision. She had driven him home after.

"I know."

"Why?"

He looked at his hands. He looked at the window. He looked at her. "Because he called and told me something that I can't repeat to you yet, and because I owed him enough to go and hear it, and because after I heard it I needed time to figure out whether it was true."

"Is it?"

He didn't answer immediately. She watched the muscles in his jaw tighten and release.

"I think it is," he said.

She held very still. Outside a car passed, its lights sweeping through the window and across the ceiling and gone. "Then you're going to have to tell me."

"I know I am."

"Daniel."

"I know." He looked up. His eyes in the lamplight were doing the thing they did when he was past the pretending and into the actual situation. "But not tonight. I need one more day."

She sat with that. She looked at the window. She looked at him.

"One day," she said.

"That's all I'm asking."

She didn't say yes. She didn't say no. She stood up and went to the kitchen and put the kettle on, and the sound of it filled the apartment, and neither of them spoke for a while.

She heard him sit down at the table. The scrape of the chair. Then silence in the way there was always silence after the kettle — the particular absence of noise that filled a room when both people were still and no longer performing the act of not talking.

She poured two cups. She brought them to the table. She set one in front of him without asking if he wanted it, because asking felt like the wrong kind of careful right now.

He wrapped his hands around the cup. He didn't drink.

She sat.

Outside, the night was doing its routine indifferent thing — windows lit in the building opposite, one going dark as she watched, a life transitioning between one room and another with no knowledge of this kitchen or what was sitting in it. She found that thought steadying. She usually did.\
""",

    Direction.sad_moment: """\
The cardboard box was still in the hall where she'd put it six weeks ago, when she'd been sure she was ready. She wasn't ready. She hadn't opened it since.

She walked past it to the kitchen and filled the kettle without thinking. The familiar weight of it, the specific sound of the water — she had done this every morning for eleven years and she had done it every morning for the five months since, and the two kinds of morning were nothing alike. The object was the same. The weight was different.

She stood at the counter while the kettle heated. The window above the sink looked out onto the narrow strip of garden, which was doing what gardens did in November: going grey, going still, making its preparations in the dark. He had planted the climbing rose on the left side of the fence the first summer they were here. It was bare now, just the canes, and she had a note from him somewhere — a note on actual paper, which was the kind of person he had been — that said what month to prune it and how far back.

She had not pruned it. She didn't know if she would.

The kettle clicked off. She made tea in the way she always had, which was the way he had taught her, which was the way his mother had taught him. She held the mug in both hands and sat at the table.

The box in the hall.

There were things inside it she needed to deal with — practical things, documents, the watch his brother had asked about. She'd told his brother she'd call. She hadn't called. This too had become one of the things she was going to do on a day that kept not arriving.

She wasn't broken. She understood that now in a way she hadn't in the first weeks, when she'd expected to feel broken and had felt instead something quieter and harder to name: not the collapse she'd feared but a steady grey muffling, as if everything were happening at a slight remove. The grief was real but it moved through her like weather rather than wounding her cleanly, and she couldn't decide if that was better or worse.

She drank her tea. A bird landed on the fence post above the rose canes, sat there for a moment considering something, and then was gone.

She thought about the note with the pruning instructions. She thought about where she'd put it — one of the kitchen drawers, she was almost certain, the one on the left, the drawer that had always been his drawer, the one she still opened and closed gently as if not to disturb it.

She finished the tea. She washed the mug.

In the hall, passing the box, she stopped.

Her hand rested on the cardboard flap. She didn't open it. She stood there for a long moment, her hand on the box, feeling the specific weight of what was inside and what was not, what remained and what was only memory.

Then she went and got her coat. She had to be somewhere. The box would still be there when she got back.

It was going to be there for a while.

She came back in the evening and did not look at it. She made herself a proper dinner — not cereal, not toast — something that required the use of three different pans and some amount of effort, because effort was one of the things she could still control, and she was keeping a list, in her head, of things she could still control.

She ate at the table. She washed the dishes.

The box was still there when she turned off the kitchen light. Still there in the dimness when she passed it on the way upstairs. Still there, was the operative fact. It was not going anywhere. Neither was she.

She stopped at the foot of the stairs and looked at it for a moment — just looked, without intent, the way you look at something you've decided to accept — and then she went up to bed.

Tomorrow. Or the day after. It would wait.\
""",

    Direction.argument_begins: """\
She said his name three times before he looked up.

"I heard you," he said.

"Then why—"

"Because I was thinking." He closed the laptop. He'd been closed off since dinner, since before dinner, since the afternoon when she'd made the mistake of telling him what she'd found out, and she could track it backwards now, the moment when his expression had changed and become this — careful, contained, exactly the distance he deployed when he didn't want to be in a conversation.

"You've been thinking since four o'clock," she said. "What are you thinking about?"

"I don't want to do this right now."

"You keep saying that."

"Because I keep meaning it." He stood up. He went to the window. The familiar move — she'd catalogued it without intending to, the places he went when he wanted to feel in control of a room. Window, desk, the walk to the kitchen and back. She used to find it endearing.

"Tell me you weren't there," she said.

He turned. His face in the lamp-light was flat in a particular way. "I'm not going to tell you that."

"Because you were there."

"Because I'm not going to play this game where you ask me things you already know the answer to and I'm supposed to deny them until you push hard enough and then we can pretend I told you voluntarily." He came back to the centre of the room. "I was there. Yes. Is that what you need to hear?"

"I need to know why."

"You know why."

"I know the version you gave me. I want the actual version."

He looked at her. He'd done this before — this particular stillness, this measuring of what she could be told versus what she would accept — and she'd always trusted it. She had believed, right up until this afternoon, that the version he gave her and the actual version were the same thing. She was still deciding what to do with knowing they weren't.

"The actual version," he said, "is more complicated than you're going to want it to be."

"That's not your decision."

"It used to be."

That landed wrong. She could feel it land wrong, feel the flash of something at the back of her jaw. "Don't do that."

"I'm not doing anything."

"You're making this about trust and it's not about trust, it's about the fact that you were somewhere you told me you wouldn't be, for reasons you haven't explained, and now you're standing there deciding how much of the truth I'm equipped for." She kept her voice level. She was good at keeping her voice level. "Don't decide what I'm equipped for."

He said nothing. The room held the silence.

She picked up her phone from the table, not because she needed it but because she needed something to hold. "I'm going to ask you one more time," she said. "Then I'm going to stop asking."

He looked at her hands. He looked at her face. Something in his expression shifted — not softening exactly, more like a calculation reaching its conclusion.

"Sit down," he said.

"Tell me first."

A long pause. The refrigerator hummed in the kitchen. Outside, rain had begun on the window, the particular pattering of a light rain, unhurried.

"Her name was Cassidy," he said. "She worked for Brennan. And she called me three weeks before the election because she had something she needed someone to know."

He watched her face.

"That's the actual version," he said. "The beginning of it."

She sat. Not because he'd told her to. Because her legs had made the decision before the rest of her was ready.

She set her phone face-down on the table and looked at him. His expression now was the one she'd almost forgotten — the one that came out when he'd stopped managing what he showed her and was simply present instead, open to whatever was about to happen. She hadn't seen it in months. She'd wondered if she would again.

"Tell me the rest," she said.

He did. It took a while. The rain continued outside, unhurried, indifferent, falling on the street and the parked cars and the narrow garden wall beyond the window, and she sat at the table and listened, and the room held everything it was asked to hold.\
""",

    Direction.romantic_moment: """\
The table they'd been given was too small, which put them closer together than either had planned.

She noticed it when she sat down — the narrowness of the thing, their menus nearly touching — and she saw him notice it too, the slight adjustment he made, the way he moved his water glass to give her room. A small courtesy. She'd catalogued a number of small courtesies this evening without intending to.

"You were saying," he said.

She'd been saying something about the project, about the deadline, about the thing her manager had said yesterday that had made the whole team laugh in the particular helpless way of people who'd already moved past being surprised. She couldn't reconstruct it exactly now.

"It doesn't matter," she said.

He smiled. Not the social smile, the one she'd learned to read as polite attention. The other one. "Then tell me something that does."

She picked up her glass. The restaurant noise moved around them — other tables, other evenings — and she thought about how she'd almost cancelled. She thought about the three different messages she'd drafted and deleted on the way here, the excuses she'd considered. She'd come anyway. She wasn't entirely sure why.

"I don't know what we're doing," she said.

"What do you think we're doing?"

"I think we're having dinner."

"Specifically."

She looked at him. He was watching her with the particular attention he gave to things he was genuinely interested in, which she'd learned over the past weeks was not the same as the attention he gave to things he was politely engaged in. The difference was subtle. She'd learned to read it.

"I think," she said carefully, "that this is the fourth time we've had dinner in three weeks and we've never talked about what that means."

"Does it have to mean something?"

"I don't know."

He turned his glass in a slow circle. "What would it mean if it did?"

She considered that. The question wasn't leading anywhere she didn't see — she could see exactly where it was leading, had been able to see it for approximately two and a half of the three weeks — but seeing the path clearly was different from deciding to walk it, and she hadn't decided yet.

"Something I haven't named," she said.

He nodded. Not like he was satisfied, more like he was filing it. "Okay."

"That's it? Okay?"

"You don't have to name it tonight."

She looked at him. He was looking at the table now, not at her, and she watched the angle of his jaw in the light from the candle and thought about the way that first dinner had gone, how she'd sat across from him at a table three times this size with other people around them and how she'd still somehow been aware of him at every moment, the specific quality of his attention like a frequency she was tuned to without choosing.

She picked up her fork. She put it down again.

"What if I want to," she said.

He looked up.

"Name it," she said. "What if I want to."

The candle did something between them, the light shifting in whatever draft moved through the restaurant. He reached across the narrow table and moved her water glass half an inch, the same small courtesy as before, except this time his hand stayed near hers on the table afterward, not touching, close enough that she could have moved and made it contact.

She didn't move.

He didn't move.

"Take your time," he said. "I'm not going anywhere."

She looked at his hand, still near hers on the table. Not touching. The space between them the exact width of a decision she hadn't made yet.

"That's the problem," she said. Her voice came out quieter than she intended. More honest. "I don't need more time. I think I've had too much of it already."

He didn't fill the space. That was the thing about him she'd noticed first, at the beginning — the way he didn't rush to fill a silence. Other people filled silences. He let them exist and waited to see what came next.

What came next was her hand moving the last half-inch.

The restaurant noise continued around them, other people's evenings, other tables, other conversations where other people were saying easier things. She was not looking at any of it. She was looking at him, and he was looking at her, and the candle between them held its small steady flame against whatever current moved through the room.\
""",

    Direction.sensual_scene: """\
The night had gone warm in the way autumn sometimes did — one last insistence before the cold settled in — and she'd left the window cracked when she'd gone to answer the door.

He came in past her, bringing the outdoor air with him, and she watched him take in the room — the lamp on the sideboard, the two glasses she'd already poured, the particular way she'd arranged things without quite acknowledging she'd arranged them.

"You've been here a while," he said.

"A little while."

He set his jacket over the chair. She watched him do it, the unhurried way he moved through a space, the particular ease of a man who was comfortable wherever he was. She'd found that quality disarming when she first understood it. She still found it disarming.

She picked up one of the glasses and held it out. He crossed the room to take it. Their fingers touched on the stem. Neither of them moved away immediately.

"You're nervous," he said.

"I'm not."

The corner of his mouth. "All right."

She set her own glass down on the sideboard. She turned to look at the window, the crack letting in the warm night smell of the street below — leaves, rain somewhere in the distance, the vague sweetness of something she couldn't identify. She felt him behind her, not close enough to touch, close enough to feel.

"You've been thinking about this," he said. Not a question.

"Haven't you?"

"Yes." Simple, unhesitant. "But I wanted to hear you say it."

She turned. He was watching her with an expression she'd catalogued carefully over the past months — the look that meant he was paying full attention, that whatever happened next had his complete consideration. She'd learned it was the look he wore when something actually mattered to him.

"Say what, exactly," she said.

"Whatever you came here to say."

She looked at him. The lamplight between them was soft, the kind of light that didn't demand anything, that let a room hold ambiguity without resolving it. She'd chosen it deliberately, she realized. She'd been choosing things deliberately all evening.

"I've been thinking about the last time," she said. "And the time before that."

"And?"

"And I don't want to keep thinking about them." She held his gaze. "I want to stop thinking and do something about it."

He was still for a moment. Then he reached out and touched her face — one hand, the back of his fingers along her jaw, the lightest possible contact. Not taking anything. Asking.

She put her hand over his.

The window let in the warm night. The lamp held its soft position. Outside, the city went on doing whatever the city did, and in this room, for this specific interval of time, the rest of it was very far away.

The lamp held its position. The window stayed cracked. The warm night smell of the street came and went in small variations — something chemical, then clean air, then leaves again, then something she couldn't name — and she paid attention to each of them in sequence the way her mind sometimes worked when her body was already committed and her thinking had run slightly ahead of the event.

She didn't reach for her glass again. Neither did he.

What he did instead was cross the room to where she was standing, slowly enough that she had time to decide what happened next, and stand close enough that the question was clear.

She had already decided. She'd decided three weeks ago and talked herself out of it and decided again and waited for a moment that felt like this — unhurried, warm, no urgency beyond the simple fact of finally being somewhere she wanted to be.

"I'm not nervous," she said.

"I know," he said. "You'd have left already if you were."

She laughed — quiet, surprised by itself, the kind of laugh that only came when something was precisely accurate and also slightly unfair. She could feel the tension in her own shoulders releasing as it did, the particular unclenching of a position she'd been holding for weeks, possibly longer.

"That's a very confident thing to say," she told him.

"It's a very accurate thing to say."

She had nothing to argue with in that. She stood in her own apartment with the warm night coming through the cracked window and the lamp at its low setting and nothing she needed to do tomorrow that couldn't wait, and she was exactly where she'd decided to be.

"All right," she said. It was not an all right that meant fine, or acceptable, or I suppose. It was an all right that meant: yes. This. Here. Now.

He understood the difference. She'd been fairly sure he would.\
""",

    Direction.intimate_scene: """\
She woke at four and lay still for a moment, oriented by the particular darkness, the way the light from the street press through the curtain on the left side only. His arm was across her, his breathing slow and even, and she lay inside that and tried to understand what she was feeling.

Not happiness exactly. Something more complicated and more honest than happiness.

She turned carefully, slowly enough not to wake him, until she was facing the room. She could see the shape of his jacket on the chair. His shoes on the floor, the way he'd left them — not placed, exactly, more let go, the shoes of a person who'd arrived and stopped thinking about shoes. She had arranged nothing last night. She hadn't planned anything. That, too, felt like information.

"You're awake," he said. She hadn't heard him shift.

"For a little while."

A pause. His hand found her shoulder blade. Not possessively — just present, the warmth of a hand at rest. "What time is it?"

"Early. Go back to sleep."

"You're not sleeping."

"I will."

He was quiet. She lay in the not-quite-dark and listened to him breathe and thought about the conversation they'd had last month, the one where she'd told him she wasn't ready for anything and he'd said he understood and she'd believed him, and had also believed herself. The way things were actually true until they weren't.

"You're thinking about something," he said.

"I'm always thinking about something."

"Something specific."

She turned again, back to face him. In the grey light of four a.m. he looked different — less maintained than in daylight, more actual, the face of a person rather than the presentation of one. She'd seen him in daylight more times than she could count. She hadn't seen this version nearly as much.

"I was thinking about how I told you I wasn't ready," she said.

"And?"

"And it was true when I said it."

He didn't fill the space. He'd always been good at that — at not filling the space when she was in the middle of something.

"I think I got ready somewhere in between," she said.

He reached up and pushed her hair back from her face. The gesture was simple and unhesitant, the gesture of someone who'd stopped asking permission for small things, which was not the same as taking anything for granted — more like they'd arrived somewhere, together, without having planned the route.

"I know," he said.

"You know?"

"I could tell. About three weeks ago." He kept his hand in her hair, not moving, just there. "I was waiting for you to figure it out."

She looked at him. Outside, the city made its four-a.m. noises — distant, sparse, the particular texture of a city that hadn't quite gone to sleep and hadn't quite woken up. The curtain moved slightly in a draft she couldn't feel from where she lay.

She put her hand over his. She kept it there.

"That's—" she started.

"I know," he said. "I know it is."

She closed her eyes. His hand in her hair, warm and still. The room around them held.

She opened them again after a while. The curtain moved. The grey light was beginning to shift — not dawn exactly, not yet, but the hour before dawn when the dark starts to thin at its edges and you can see the shapes of things without the details.

"Go back to sleep," she said again.

"Are you?"

"In a minute."

He pulled her closer without another word, and she let herself be pulled, and she lay in the half-dark with his arm across her and thought: here. This is the thing. Not the version she'd expected or planned or sometimes given up on expecting — just this, specific and unrepeatable, the particular weight of an arm across her back and the sound of someone breathing beside her at four in the morning as the city began to wake outside the window.

She had been right when she told him she wasn't ready. She had been right when she stopped saying it.

She lay still and let the room settle around them. The curtain moved again. The grey outside the window continued its slow reddening toward morning, unhurried, doing what mornings did regardless of what happened in rooms.

She thought about the conversation she'd had with herself, the night three weeks ago when she'd almost called him and then put the phone down and stood in her kitchen for twenty minutes doing nothing, just standing there with the certainty of something growing louder than she'd been managing to ignore.

She hadn't called.

She'd texted.

*Are you awake.*

And he'd answered in twelve seconds, which was the only evidence she'd needed that he'd been waiting for exactly that kind of message at exactly that kind of hour.

She didn't say any of this out loud. She just lay there beside him as the morning came in at the edges of the curtain, and thought about how few things felt this uncomplicated, and decided that was reason enough to let it be what it was.\
""",

    Direction.twist_event: """\
She found the letter in a box she'd been told not to open.

She'd been told once, very clearly, by someone she trusted absolutely. The box had sat on the high shelf in the study for eleven years and she had kept her word in the exact spirit it had been given — not looked inside, not wondered aloud, not asked for an explanation. She had understood it was not her information to have.

She opened it now because the person who'd told her not to was no longer alive to hold the boundary, and because there was a question she'd been sitting with for three weeks that had no answer anywhere else she'd looked.

The letter was at the bottom, under the photographs she'd expected and one she hadn't. The unexpected photograph showed two people she recognized and one she didn't. They were at a table, outdoors, in a city she identified immediately as not the city her father had told her he was in that particular autumn.

She looked at the unknown face. She turned the photograph over. Written in pencil, in her father's handwriting, a name she recognized and a date four months before she was born.

She sat down on the floor of the study.

She held the letter without opening it. She thought about the name. She thought about the timeline. She thought about the story she'd been told, which was a good story, which had always felt complete, which had never left a gap she needed to ask about.

She opened the letter.

It was three pages, dated from the same autumn as the photograph. Her father's handwriting, younger than she knew it, not yet containing the slight tremor she'd noticed in his last years. He'd written it to someone he called by a name that meant nothing to her — and then, in the second paragraph, had referred to that person by a different name. A name she knew.

Her uncle. Her father's younger brother. Her uncle who had died before she was two and whom she'd known only as a story, a series of photographs, a habit her father had of going quiet at particular moments.

She read the second page.

She set it face-down on the floor of the study and sat with her back against the shelving and looked at the room. The room looked back at her, indifferent, as rooms were. Nothing in it had changed. The chair, the desk, the lamp, the boxes on the high shelf and the one open now at her feet.

All of it the same.

Her understanding of all of it entirely different.

She picked the page back up. She made herself read it again. She was the kind of person who needed to read a thing more than once when the first reading was too large to take in, and she knew that about herself, and she gave herself that, sitting on the floor of her dead father's study with a letter she had waited eleven years not to read.

On the third page, at the very end, a single line that had no context she could assign it yet.

*She should have been told. I'm sorry I am not the one to tell her.*

She closed her eyes. She breathed.

She opened them and looked at the photograph again.

Three people at a table. Outdoors, somewhere warm. Her father young in a way she'd never seen him — twenty-five, perhaps, his face still loose with it. The unknown person beside him, half-turned away, caught mid-sentence. And to the left: the face she recognized from decades of photographs, from a single grave marker she'd stood at twice in her life and once in her childhood without understanding what it meant.

Her uncle.

She turned the photograph over. Read the name and the date again. Put it face-up on the floor and sat with it.

There would be a point, she understood, at which she would have to decide what to do with this. Whether to find the person with the unknown face, if they were still alive. Whether to call her mother and ask the question she now had the beginning of an answer to. Whether to go looking for more boxes, more shelves, more sealed envelopes from a life that had been arranged very carefully around a space she'd never thought to ask about.

She was not at that point yet. She was at the earlier point, the one where you hold a fact and wait for it to stop being too large to think about clearly.

She held it.\
""",

    Direction.quiet_reflection: """\
The bench had been there longer than she had. She knew this from the plaque on the arm, which gave a date thirty years earlier and a name she'd never asked about. She sat here often. She'd never read the full inscription until today.

The park in October was doing what October parks did — letting go of things, making a show of it. She didn't mind. She'd always found autumn more honest than spring, which made promises, whereas autumn simply said: here is what is ending, watch it go, that's all.

She had a coffee in her hand, cold now. She didn't drink it. She sat with it and watched a dog cross the path thirty feet away and the dog's person walking behind and not hurrying, and she thought about her sister.

She'd been thinking about her sister for three weeks. Before that she'd barely thought about her for a year, which was not because she didn't care but because caring and thinking were not the same thing and she had learned, at some point in her forties, to put certain caring on a shelf and visit it selectively. It was a skill. She'd been proud of it. She was less proud of it now.

The thing her sister had said, on the phone, the night of the conversation she hadn't wanted to have. She'd replayed it many times and she was still not sure whether it was a true thing said in anger or an angry thing that happened to be true, and the difference mattered to her more than she expected.

*You've always been able to leave. It never cost you anything.*

She'd argued back. Of course she had. She'd cited the years and the miles and the effort she'd made, and she'd been right to cite them — the effort had been real, the distance had been real. She had not manufactured the years or the miles.

But.

She turned the coffee cup in her hands. A leaf came down from the oak to her left and settled on the path near her feet, not spinning, just landing, the way things landed when there was no wind to perform for.

The distance had been her choice. That was what she hadn't argued back.

She wasn't sure when she'd made the choice. That was the harder thing. It hadn't felt like a choice while she was making it. It had felt like logistics, like work schedules, like the ordinary accumulation of decisions that were individually reasonable and collectively amounted to something she hadn't examined.

She put the coffee on the bench beside her. She sat with her hands in her lap.

The park went on. A child came past on a bicycle, listing slightly, correcting, going. The bench's cold plaque against the back of her shoulder. Thirty years of people sitting here and probably not reading the name and not feeling anything in particular, just sitting, just breathing, just needing somewhere to be that wasn't inside the particular walls of their own life for a moment.

She could call her sister. She could call her right now, from this bench, with the cold coffee and the October park and whatever truth was going to arrive when she stopped managing its approach.

She picked up her phone.

She put it down again.

She sat a little longer.

When she finally did call, she'd been sitting on the bench for forty minutes. The coffee was cold in her hand. The dog and its person had long since passed. The park around her had shifted from morning to mid-morning in the way that parks did — school-run children replaced by older walkers with better shoes, the light settling into something flatter, less dramatic.

Her sister answered on the third ring.

"Hey," her sister said. Not guarded, not warm — just there. Which was something.

"Hey," she said back. She looked at the park. She thought about what she'd rehearsed on the bench, the careful framing, the even tone. She said none of it. Instead she said:

"I've been thinking about what you said."

A pause. The sound of her sister's apartment — a window, something ordinary. "Which part."

"The part about leaving. The part about it not costing me anything."

Another pause. Longer.

"It cost something," she said. "I just didn't let you see it."

Her sister said nothing. She said nothing back. But she was still there on the line, and so was her sister, and that, for now, was enough to go on with.\
""",

    Direction.action_sequence: """\
She heard the door at the end of the hall and broke into a run.

Three strides and she was at the corner, one hand braced on the wall as she took the turn — felt her shoulder catch the plaster and used the impact to push off harder. The hall ahead was empty, the exit sign at the far end green and unhelpful. She ran toward it.

Behind her, footsteps. Not running yet. Controlled. The sound of someone who did not need to run because they'd already run the calculations and liked what they found.

She hit the stairwell door with both hands and took the stairs going down, her hand on the rail for the corners, counting — two, one, ground. The lobby door was locked but she had the key she'd taken from the office when she still had time to think about taking things. She was at the outer door in seconds.

Outside the air was cold. She didn't stop.

The street was lit by shop fronts and passing traffic and she moved with the pedestrians, not against them, not pushing — moving with the flow, which was what you did when you didn't want to be the shape someone was looking for. She turned at the first intersection without slowing. She turned again at the second.

She stopped in the doorway of a pharmacy and looked back the way she'd come.

Nothing that matched. Nothing moving against the crowd. That was something, but not enough.

She pulled out her phone. One contact: Marcus. She'd had two days to memorize the number and she had memorized the number, because two days ago she had understood this might happen and she had made her preparations accordingly. The call connected on the second ring.

"I'm out," she said. "South side of the building, about two blocks. They were close."

"How close?"

"Close enough."

His end of the line was quiet for a moment in the specific way of someone in motion. "Green line. Fifteen minutes. Take the back streets."

"I know which route."

"Then take it faster than you think you need to." A pause. "You have the drive?"

She touched the inside pocket of her jacket. The shape was there. "I have it."

"Then stop talking to me and move."

She put the phone in her pocket. She looked at the street. She looked at the people moving through it — ordinary traffic, the ordinary evening, no one looking at her specifically, though she'd learned that not looking at someone specifically was its own kind of attention.

She stepped back into the flow.

The pharmacy doorway was behind her. The station was ahead. She did not run. She walked at the pace of someone with somewhere to go, which was true, which made it easier.

Behind her, half a block back, a man in a dark coat turned the same corner she had turned.

She didn't look back again. She counted her steps instead. She counted the seconds between intersections. She counted the distance to the entrance and she was still counting when she went down the stairs and into the noise and the ordinary electric smell of the city underground.

The platform was crowded in the way that made sense at this hour — people going somewhere, all of them visible to each other, none of them paying specific attention. She stood near the wall, facing the tracks, and waited.

Her phone buzzed. She took it out: Marcus, one message. *On the platform. Green line, westbound. Look for the woman in the red coat.*

She did not look around. Looking around was exactly what she should not do. She put her phone back and let her eyes stay forward and watched the tunnel mouth at the far end of the platform for the approaching glow of the train.

The man in the dark coat had not followed her down. That was something. Either he'd lost her on the street, or he'd decided not to. She couldn't tell which, and the difference mattered, and she filed it for after — for the part of the evening where there was somewhere safe to sit down and think clearly.

The train arrived. She got on.\
""",
}


_FADE_TO_BLACK_SUFFIX = " The scene dissolved softly, drawing a discreet curtain over what followed."
_SENSUAL_SUFFIX = " The moment lingered at the edge of restraint, intimate but unhurried, its full weight implied rather than shown."

# Compact fallback templates for Length.short (120–200 words target)
_STUB_SHORT_TEMPLATES: dict[str, list[str]] = {
    Direction.advance_plot: [
        "The path ahead shifted without warning. She'd been so certain of the direction — had rehearsed it, practically, the steps and their order — and then the ground changed beneath her and the certainty was gone. She stood in the hall of the thing she'd intended and looked at the wreckage of the plan and thought: all right, then. Start from this.",
        "Something moved that had been fixed. Not loudly — there was no crash, no announcement — just the particular sound of a hinge finally giving way, of a weight that had been held in one position for a long time suddenly free to go somewhere else. The story moved with it.",
    ],
    Direction.add_dialogue: [
        '"I need to tell you something," she said, and the way she said it — the particular flatness of it, the lack of preamble — told him everything about how long she\'d been holding it.',
        '"You never asked," he replied. Not an accusation. A statement of fact, delivered carefully, which was somehow worse. The silence after it had weight.',
    ],
    Direction.sad_moment: [
        "The weight arrived not all at once but in layers, the way winter came — first the light changing, then the cold, then the particular quality of the silence that meant something had stopped. She sat with it. She did not name it. Some things were larger than their names.",
        "There was a kind of sadness that didn't ask for anything. Not comfort, not explanation. Just acknowledgment. Just: yes, this is real, and it is heavy, and it is yours to carry now. She carried it.",
    ],
    Direction.argument_begins: [
        'A single word landed wrong. She felt it before she understood it — the change in the room\'s temperature, the way his face tightened. "That\'s not what I said," she told him, and heard in her own voice the beginning of something she\'d been trying not to start.',
        "The tension had been building since the morning, or maybe longer. It broke on a small thing, as these things always did — not the real thing, never the real thing, but the word that rhymed with it.",
    ],
    Direction.romantic_moment: [
        "Something shifted in the space between them — nothing named, nothing announced, just the particular awareness of another person standing too close to be entirely accidental. She noticed it first. She said nothing about it.",
        "She noticed it in the way he looked at her when he thought she wasn't paying attention — the unguarded version, the one he hadn't arranged. She filed it away. She wasn't sure yet what she was going to do with it.",
    ],
    Direction.sensual_scene: [
        "The evening had gone warm. She stood at the window with her glass in her hand and was aware of him across the room in the particular way that meant she'd been aware of him for some time without having chosen to be.",
        "There was a quality to the silence that said more than either of them had. She was good at reading silences. This one said: here, and now, and if you choose.",
    ],
    Direction.intimate_scene: [
        "The world narrowed to this room, to this light, to the specific warmth of someone else nearby. Not dramatic. Not arranged. Just the honest fact of it, which was, she had come to understand, rarer than people said it was.",
        "It was close and quiet and real — the kind of closeness that didn't announce itself or perform, that simply happened between people who'd stopped pretending they didn't want it.",
    ],
    Direction.twist_event: [
        "She read the message twice. The words were simple; the implication was not. She stood in the kitchen with her phone in her hand and felt the ground shift in the way it shifted when something had been true for a long time and you'd only just realized it.",
        "The revelation arrived without drama. A single fact, stated plainly, in an ordinary context. She turned it over. She looked at everything she'd understood to be fixed, and saw it wasn't.",
    ],
    Direction.quiet_reflection: [
        "She sat with what she knew and what she didn't, which was a kind of sorting. Not productive, exactly — the categories didn't resolve into anything — but necessary, the way breathing was necessary, in that it had to happen regardless.",
        "The quiet wasn't empty. It contained something: the sound of her own thinking, the specific texture of a question she'd been avoiding. She let it be there. She didn't answer it yet.",
    ],
    Direction.action_sequence: [
        "She moved fast and kept moving. Three turns, one straight sprint across the open square. She didn't stop to look back. Looking back was for people who had time, and she'd run the math on the time she had, and this was not it.",
        "No time to plan. Only to react. She was through the first door and into the stairwell before the decision had finished forming, running on the part of her brain that didn't need to deliberate.",
    ],
}


def _qualify(text: str, tone: ToneIntensity, pacing: Pacing, length: Length) -> str:
    prefix = ""
    if tone == ToneIntensity.intense:
        prefix = "With sharp, unflinching clarity — "
    elif tone == ToneIntensity.light:
        prefix = "Gently, almost imperceptibly — "
    pace_suffix = ""
    if pacing == Pacing.fast:
        pace_suffix = " She kept moving."
    elif pacing == Pacing.slow:
        pace_suffix = " Time moved differently here."
    return prefix + text + pace_suffix


def _stub_trim_to_words(text: str, target_words: int) -> str:
    """Return text trimmed to approximately target_words at a paragraph boundary.

    Unlike _trim_to_cap (which enforces an upper bound), this targets
    a minimum — it stops adding paragraphs once we reach target_words.
    If the full text is shorter than target_words, it is returned as-is.
    """
    words = text.split()
    if len(words) <= target_words:
        return text
    paragraphs = re.split(r"\n\n+", text)
    kept: list[str] = []
    running = 0
    for para in paragraphs:
        wc = len(para.split())
        kept.append(para)
        running += wc
        if running >= target_words:
            break
    return "\n\n".join(kept)


def _generate_stub_text(story_id: str, controls: StoryLabControls) -> str:
    """Generate stub text appropriate for the requested length and direction.

    Length.long / Length.medium: rich multi-paragraph templates (700+ / 350+ words).
    Length.short: compact single-paragraph templates (~150 words).
    """
    direction = controls.direction
    length = controls.length

    if length in (Length.medium, Length.long):
        rich = _STUB_RICH_TEMPLATES.get(direction, _STUB_RICH_TEMPLATES[Direction.advance_plot])
        target = _length_target(length)
        # For medium, trim rich template to target; for long, use fully
        text = _stub_trim_to_words(rich, target) if length == Length.medium else rich
    else:
        short_templates = _STUB_SHORT_TEMPLATES.get(direction, _STUB_SHORT_TEMPLATES[Direction.advance_plot])
        idx = hash(story_id + direction) % len(short_templates)
        text = short_templates[idx]

    text = _qualify(text, controls.tone_intensity, controls.pacing, length)

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
    propulsion_correction: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Call OpenRouter; parse <STORY> tag from response; fall back to raw on missing tags."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_storylab_prompt(
        text, controls, state_json, summary, characters, recent_endings,
        variant=variant, canon_memory=canon_memory,
        propulsion_correction=propulsion_correction,
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

    _t0 = time.time()
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        _generation_ms = int((time.time() - _t0) * 1000)
        logger.info("[SL-DIAG] _call_openrouter HTTP status=%d generation_ms=%d", resp.status_code, _generation_ms)
        resp.raise_for_status()

    data = resp.json()
    raw: str = data["choices"][0]["message"]["content"]
    _choice = data["choices"][0]
    _finish_reason = _choice.get("finish_reason") or _choice.get("stop_reason", "unknown")
    _usage = data.get("usage") or {}
    logger.info(
        "[SL-DIAG] _call_openrouter raw_chars=%d has_story_tag=%s finish_reason=%s "
        "prompt_tokens=%s completion_tokens=%s generation_ms=%d",
        len(raw), "<STORY>" in raw, _finish_reason,
        _usage.get("prompt_tokens", "?"), _usage.get("completion_tokens", "?"),
        _generation_ms,
    )

    delta = _parse_delta_signals(raw)
    if delta:
        logger.debug("StoryLab delta signals: %s", delta)

    story_text = _trim_to_cap(_parse_model_output(raw), cap_words)
    if not story_text.strip():
        logger.error("[SL-DIAG] _call_openrouter returned empty story text (raw_chars=%d)", len(raw))
        raise ValueError("Model returned empty story text after parsing")
    logger.info(
        "[SL-DIAG] _call_openrouter COMPLETE | generation_mode=openrouter "
        "max_tokens=%d output_word_count=%d finish_reason=%s generation_ms=%d",
        max_tokens, len(story_text.split()), _finish_reason, _generation_ms,
    )
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
    key_present = bool(settings.OPENROUTER_API_KEY)
    cap_words = _length_cap(controls.length)
    request_max_tokens = max(400, int(cap_words * 2.0))
    logger.info(
        "[SL-DIAG] generate_storylab_continuation called | provider=%s key_present=%s model=%s "
        "story_id=%s length=%s pacing=%s intensity=%s request_max_tokens=%d",
        provider, key_present, _EFFECTIVE_STORYLAB_MODEL, story_id,
        controls.length, controls.pacing, controls.tone_intensity, request_max_tokens,
    )

    fallback_reason: str = ""

    if provider == "openrouter":
        if not key_present:
            fallback_reason = "no_api_key"
            logger.warning("[SL-DIAG] STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
        else:
            try:
                result_text, delta = _call_openrouter(
                    text, controls, state_json, summary, characters, recent_endings,
                    variant=variant, canon_memory=canon_memory,
                )
                word_count = len(result_text.split())
                min_words = _minimum_words(controls.length)
                if word_count < min_words:
                    logger.warning(
                        "[SL-DIAG] generate_storylab_continuation SHORT | words=%d min=%d length=%s; retrying",
                        word_count, min_words, controls.length,
                    )
                    try:
                        result_text, delta = _call_openrouter(
                            text, controls, state_json, summary, characters, recent_endings,
                            variant=variant, canon_memory=canon_memory,
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning("[SL-DIAG] generate_storylab_continuation retry failed: %s", retry_exc)
                # ── loop detection (post-generation) ─────────────────────────
                _rep = detect_story_repetition(result_text)
                _story_propulsion_retry = False
                if _rep["repeated_section_detected"]:
                    _story_propulsion_retry = True
                    logger.warning(
                        "[SL-DIAG] generate_storylab_continuation LOOP_DETECTED | "
                        "story_repetition_score=%.3f repeated_dialogue=%d repeated_ngrams=%d; retrying",
                        _rep["story_repetition_score"],
                        _rep["repeated_dialogue_count"],
                        _rep["repeated_ngram_count"],
                    )
                    try:
                        result_text, delta = _call_openrouter(
                            text, controls, state_json, summary, characters, recent_endings,
                            variant=variant, canon_memory=canon_memory,
                            propulsion_correction=build_storylab_loop_correction_block(),
                        )
                        _rep = detect_story_repetition(result_text)
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning("[SL-DIAG] generate_storylab_continuation loop retry failed: %s", retry_exc)
                _prog = detect_story_progression(result_text)
                logger.info(
                    "[SL-DIAG] generate_storylab_continuation DIAG | "
                    "story_repetition_score=%.3f repeated_section_detected=%s "
                    "story_progression_score=%.3f story_propulsion_retry=%s",
                    _rep["story_repetition_score"],
                    _rep["repeated_section_detected"],
                    _prog["story_progression_score"],
                    _story_propulsion_retry,
                )
                logger.info(
                    "[SL-DIAG] generate_storylab_continuation COMPLETE | using_stub=false "
                    "response_word_count=%d response_char_count=%d length=%s",
                    len(result_text.split()), len(result_text), controls.length,
                )
                return result_text, delta
            except httpx.TimeoutException:
                fallback_reason = "timeout"
                logger.warning(
                    "[SL-DIAG] generate_storylab_continuation FALLBACK | fallback_reason=%s "
                    "exception_type=TimeoutException exception_message=request timed out",
                    fallback_reason,
                )
            except httpx.HTTPStatusError as exc:
                fallback_reason = f"http_{exc.response.status_code}"
                logger.warning(
                    "[SL-DIAG] generate_storylab_continuation FALLBACK | fallback_reason=%s "
                    "exception_type=HTTPStatusError exception_message=%s",
                    fallback_reason, exc.response.text[:300],
                )
            except Exception as exc:  # noqa: BLE001
                fallback_reason = "exception"
                logger.warning(
                    "[SL-DIAG] generate_storylab_continuation FALLBACK | fallback_reason=%s "
                    "exception_type=%s exception_message=%s",
                    fallback_reason, type(exc).__name__, str(exc)[:300],
                )
    else:
        fallback_reason = "stub_provider"

    stub_text = _generate_stub_text(story_id, controls)
    if settings.is_dev_mode():
        stub_text = f"[DEV-STUB-FALLBACK] {stub_text}"
    logger.warning(
        "[SL-DIAG] generate_storylab_continuation STUB | using_stub=true fallback_reason=%s "
        "provider=%s story_id=%s length=%s pacing=%s intensity=%s "
        "request_max_tokens=%d response_word_count=%d response_char_count=%d",
        fallback_reason, provider, story_id,
        controls.length, controls.pacing, controls.tone_intensity,
        request_max_tokens, len(stub_text.split()), len(stub_text),
    )
    return stub_text, None


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
    propulsion_correction: str = "",
) -> list[dict[str, str]]:
    """Build the messages list for a chapter generation call.

    Character-first ordering: protagonist identity is established before world
    context so the model anchors narration in a specific character from the
    first token, rather than defaulting to a generic narrator.

    Block order in the user message:
        0.   Canon injection block         (hard truths / character memory / anti-drift — FIRST)
        1.   Protagonist anchor            (first character — rich identity block)
        2.   Supporting characters         (remaining characters — compact voice + anchors)
        3.   Story identity                (title / genre / premise)
        4.   World / setting               (realm description)
        5.   Story so far                  (memory / summary continuity)
        6.   Last chapter                  (immediate prose continuity)
        7.   Current scene state           (narrative state as actionable prose hints)
        8.   Character fidelity            (always)
        8b.  Cinematic prose layer         (physical space, body language, texture, restraint)
        9.   Direction / boundary / pacing / tone
        10.  Outcome vs Path               (governs control interpretation)
        11.  Target length
        11b. Narrative contract            (settings-driven — only for intense/fast/sensual)
        11c. Narrative propulsion          (always — anti-loop, settings-aware scene momentum)
        12.  User guidance for this chapter
        12b. Beat direction                (structured beat label, when provided)
        12c. Loop correction               (only on retry — override for detected repetition loops)
        13.  Output constraints
        14.  Task instruction              (character-specific)

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

    # ── 8b. Cinematic prose layer ─────────────────────────────────────────────
    sections.append(_CINEMATIC_PROSE_LAYER)

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

    # ── 11. Target length (mandatory, with enforcement for long) ─────────────
    _length_label = controls.length
    _length_enforcement = ""
    if controls.length == Length.long:
        _length_enforcement = (
            "\nDo NOT stop after 500–700 words. "
            "A 'long' chapter MUST reach at least 1,500 words. "
            "Continue writing through multiple scene beats, dialogue exchanges, "
            "and action/reaction cycles until you reach the target. "
            "If the scene feels complete at 700 words, escalate — introduce a complication, "
            "shift the power dynamic, or move to the next beat."
        )
    elif controls.length == Length.medium:
        _length_enforcement = (
            "\nDo NOT stop before 900 words. A 'medium' chapter covers a full scene beat. "
            "If the scene resolves early, continue into the aftermath or next beat."
        )
    elif controls.length == Length.short:
        _length_enforcement = (
            "\nTarget 500 words — a focused single beat. "
            "Deliver complete, polished prose, not a fragment."
        )

    sections.append(
        f"## Target length — MANDATORY\n"
        f"Target: **{target_words} words** (absolute minimum for this length setting). "
        f"Hard cap: {cap_words} words.{_length_enforcement}"
    )

    # ── 11b. Intensity/pacing narrative contract ──────────────────────────────
    _narrative_contract_parts: list[str] = []
    if controls.tone_intensity == ToneIntensity.intense:
        _narrative_contract_parts.append(
            "INTENSE tone contract: Every scene beat carries pressure. "
            "Stakes are real. Consequences are visible. Characters operate under "
            "emotional or situational stress. At least one line of dialogue must "
            "land at an unexpected angle. The scene must not feel safe."
        )
    if controls.pacing == Pacing.fast:
        _narrative_contract_parts.append(
            "FAST pacing contract: Compress interiority ruthlessly. "
            "Prioritize action, forward movement, and consequence over reflection. "
            "Short declarative sentences. A paragraph covers seconds. "
            "Characters must DO things — move, speak, decide, clash. "
            "No lingering on a single emotional register for more than 2 paragraphs."
        )
    if controls.boundary in (Boundary.sensual, Boundary.fade_to_black) or controls.direction in (
        Direction.sensual_scene, Direction.intimate_scene, Direction.romantic_moment
    ):
        _narrative_contract_parts.append(
            "SENSUAL/INTIMATE contract: Chemistry and proximity drive the scene. "
            "Register attraction through what characters notice physically — "
            "texture, warmth, breath, specific detail — not abstract description. "
            "The story must still progress: emotional risk must be at stake. "
            "Something must shift between characters by the end."
        )
    if _narrative_contract_parts:
        sections.append("## Narrative contract (MANDATORY — settings-driven)\n" + "\n\n".join(_narrative_contract_parts))

    # ── 11c. Narrative propulsion (anti-loop, settings-aware scene momentum) ──
    sections.append(
        "## Narrative propulsion\n" + build_storylab_propulsion_block(controls)
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

    # ── 12c. Loop correction (only on retry) ─────────────────────────────────
    if propulsion_correction:
        sections.append("## Loop correction (MANDATORY)\n" + propulsion_correction)

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
        f"boundary, pacing, and tone instructions. "
        f"**You must write at least {target_words} words.** "
        f"Do not stop early. If the scene feels complete, escalate or continue into "
        f"the next beat until you reach {target_words} words. Hard cap: {cap_words} words. "
        f"Use the required output format including SUGGESTIONS."
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
    propulsion_correction: str = "",
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
        propulsion_correction=propulsion_correction,
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

    _t0 = time.time()
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        _generation_ms = int((time.time() - _t0) * 1000)
        logger.info("[SL-DIAG] _call_openrouter_chapter HTTP status=%d generation_ms=%d", resp.status_code, _generation_ms)
        resp.raise_for_status()

    data = resp.json()
    raw: str = data["choices"][0]["message"]["content"]
    _choice = data["choices"][0]
    _finish_reason = _choice.get("finish_reason") or _choice.get("stop_reason", "unknown")
    _usage = data.get("usage") or {}
    logger.info(
        "[SL-DIAG] _call_openrouter_chapter raw_chars=%d has_story_tag=%s has_suggestions_tag=%s "
        "finish_reason=%s prompt_tokens=%s completion_tokens=%s generation_ms=%d",
        len(raw), "<STORY>" in raw, "<SUGGESTIONS>" in raw, _finish_reason,
        _usage.get("prompt_tokens", "?"), _usage.get("completion_tokens", "?"),
        _generation_ms,
    )

    delta = _parse_delta_signals(raw)
    suggestions = _parse_suggestions(raw)
    if suggestions is None:
        suggestions = _fallback_suggestions(state_json)

    chapter_text = _trim_to_cap(_parse_model_output(raw), cap_words)
    if not chapter_text.strip():
        logger.error("[SL-DIAG] _call_openrouter_chapter returned empty chapter text (raw_chars=%d)", len(raw))
        raise ValueError("Model returned empty chapter text after parsing")
    logger.info(
        "[SL-DIAG] _call_openrouter_chapter COMPLETE | generation_mode=openrouter "
        "max_tokens=%d output_word_count=%d finish_reason=%s generation_ms=%d",
        max_tokens, len(chapter_text.split()), _finish_reason, _generation_ms,
    )
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
    cap_words = _length_cap(controls.length)
    request_max_tokens = max(400, int(cap_words * 2.5))
    logger.info(
        "[SL-DIAG] generate_chapter called | provider=%s key_present=%s model=%s "
        "story_id=%s story_title=%r story_genre=%r realm=%s story_chars=%d state_chars=%d "
        "length=%s pacing=%s intensity=%s request_max_tokens=%d",
        provider, key_present, _EFFECTIVE_STORYLAB_MODEL,
        story_id, story_title, story_genre, bool(realm_description),
        len(story_characters or []), len(characters or []),
        controls.length, controls.pacing, controls.tone_intensity, request_max_tokens,
    )

    fallback_reason: str = ""

    if provider == "openrouter":
        if not key_present:
            fallback_reason = "no_api_key"
            logger.warning("[SL-DIAG] STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
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
                chapter_text, suggestions, delta = result
                word_count = len(chapter_text.split())
                min_words = _minimum_words(controls.length)
                if word_count < min_words:
                    logger.warning(
                        "[SL-DIAG] generate_chapter SHORT | words=%d min=%d length=%s; retrying",
                        word_count, min_words, controls.length,
                    )
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
                        chapter_text, suggestions, delta = result
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning("[SL-DIAG] generate_chapter retry failed: %s", retry_exc)
                # ── loop detection (post-generation, after length retry) ──────
                _rep = detect_story_repetition(chapter_text)
                _story_propulsion_retry = False
                if _rep["repeated_section_detected"]:
                    _story_propulsion_retry = True
                    logger.warning(
                        "[SL-DIAG] generate_chapter LOOP_DETECTED | "
                        "story_repetition_score=%.3f repeated_dialogue=%d repeated_ngrams=%d; retrying",
                        _rep["story_repetition_score"],
                        _rep["repeated_dialogue_count"],
                        _rep["repeated_ngram_count"],
                    )
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
                            propulsion_correction=build_storylab_loop_correction_block(),
                        )
                        chapter_text, suggestions, delta = result
                        _rep = detect_story_repetition(chapter_text)
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning("[SL-DIAG] generate_chapter loop retry failed: %s", retry_exc)
                _prog = detect_story_progression(chapter_text)
                logger.info(
                    "[SL-DIAG] generate_chapter DIAG | "
                    "story_repetition_score=%.3f repeated_section_detected=%s "
                    "story_progression_score=%.3f story_propulsion_retry=%s",
                    _rep["story_repetition_score"],
                    _rep["repeated_section_detected"],
                    _prog["story_progression_score"],
                    _story_propulsion_retry,
                )
                logger.info(
                    "[SL-DIAG] generate_chapter COMPLETE | using_stub=false "
                    "response_word_count=%d response_char_count=%d length=%s",
                    len(chapter_text.split()), len(chapter_text), controls.length,
                )
                return chapter_text, suggestions, delta
            except httpx.TimeoutException:
                fallback_reason = "timeout"
                logger.warning(
                    "[SL-DIAG] generate_chapter FALLBACK | fallback_reason=%s "
                    "exception_type=TimeoutException exception_message=request timed out",
                    fallback_reason,
                )
            except httpx.HTTPStatusError as exc:
                fallback_reason = f"http_{exc.response.status_code}"
                logger.warning(
                    "[SL-DIAG] generate_chapter FALLBACK | fallback_reason=%s "
                    "exception_type=HTTPStatusError exception_message=%s",
                    fallback_reason, exc.response.text[:300],
                )
            except Exception as exc:  # noqa: BLE001
                fallback_reason = "exception"
                logger.warning(
                    "[SL-DIAG] generate_chapter FALLBACK | fallback_reason=%s "
                    "exception_type=%s exception_message=%s",
                    fallback_reason, type(exc).__name__, str(exc)[:300],
                )
    else:
        fallback_reason = "stub_provider"

    stub_text = _generate_stub_text(story_id, controls)
    if settings.is_dev_mode():
        stub_text = f"[DEV-STUB-FALLBACK] {stub_text}"
    suggestions = _fallback_suggestions(state_json)
    logger.warning(
        "[SL-DIAG] generate_chapter STUB | using_stub=true fallback_reason=%s "
        "provider=%s story_id=%s length=%s pacing=%s intensity=%s "
        "request_max_tokens=%d response_word_count=%d response_char_count=%d",
        fallback_reason, provider, story_id,
        controls.length, controls.pacing, controls.tone_intensity,
        request_max_tokens, len(stub_text.split()), len(stub_text),
    )
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


# ── RP Reply Generator ────────────────────────────────────────────────────────

_RP_REPLY_SYSTEM = """\
You are a collaborative roleplay writing assistant. Your sole job is to write one character's response.

ABSOLUTE RULES — these override everything else:
1. Write ONLY the user's character. Never write dialogue, actions, thoughts, physical reactions, or emotional states for any other character.
2. Do NOT godmod. You may not decide what the partner character feels, thinks, says, does, reacts to, or consents to — in any way, even by implication.
3. Do NOT narrate the partner character's body language, internal state, or response.
4. Do NOT resolve the scene from both sides. End at a point where the partner has clear space to respond.
5. Match the emotional momentum of the partner's reply. Respond to what just happened — do not ignore it.
6. Leave the door open. The last beat must invite a response, not close one.

OUTPUT: Return the reply text inside <REPLY>...</REPLY> tags. Nothing else — no preamble, no author notes.\
"""

# ── length profiles ────────────────────────────────────────────────────────────
#
# Each profile carries:
#   word_target   — target prose word count injected into the prompt
#   max_tokens    — hard token cap sent to the model
#   label         — human-readable descriptor for the prompt
#
# short    1–2 beats, immediate reply
# match    mirrors partner reply scope
# long     several beats, strong progression
# novella  full narrative sequence; may include scene transitions / time-skips

_RP_LENGTH_PROFILES: dict[str, dict[str, object]] = {
    RPReplyResponseLength.short: {
        "word_target": 100,
        "max_tokens":  450,    # ~3x word target — enough to finish a clean beat without overrun
        "label":       "short (immediate reply, 1–2 beats)",
    },
    RPReplyResponseLength.match: {
        "word_target": None,   # computed dynamically from partner word count
        "max_tokens":  None,   # computed dynamically
        "label":       "match",
    },
    RPReplyResponseLength.long: {
        "word_target": 350,
        "max_tokens":  1100,   # ~3x word target — tighter than before to enforce length
        "label":       "long (several beats, rich prose)",
    },
    RPReplyResponseLength.novella: {
        "word_target": 700,
        "max_tokens":  2200,   # ~3x word target
        "label":       "novella-length (full narrative sequence, scene transitions allowed)",
    },
}

_MATCH_MAX_TOKENS_CAP = 1600   # safety ceiling for match mode (was 2000)


def _rp_length_profile(response_length: str, partner_word_count: int) -> dict[str, object]:
    """Return a resolved profile dict with numeric word_target and max_tokens."""
    base = _RP_LENGTH_PROFILES.get(response_length, _RP_LENGTH_PROFILES[RPReplyResponseLength.match])
    if response_length == RPReplyResponseLength.match:
        wt = max(60, partner_word_count)
        mt = min(_MATCH_MAX_TOKENS_CAP, max(400, int(wt * 2.2)))
        return {"word_target": wt, "max_tokens": mt, "label": f"match (~{wt} words)"}
    return dict(base)


def _rp_reply_word_target(response_length: str, partner_word_count: int) -> int:
    return int(_rp_length_profile(response_length, partner_word_count)["word_target"])


def _rp_reply_max_tokens(response_length: str, partner_word_count: int) -> int:
    return int(_rp_length_profile(response_length, partner_word_count)["max_tokens"])


# ── length instruction text ────────────────────────────────────────────────────

_NOVELLA_BEAT_HINT = (
    "Complete the major requested beats. "
    "Do not spend more than one third of the reply on the opening exchange. "
    "Write through multiple beats entirely from your character's perspective. "
    "Transition between beats using your character's movement, narration, internal reflection, or a time-skip — "
    "never by writing the partner's dialogue, reaction, or decision."
)


def _rp_length_instruction(response_length: str, partner_word_count: int) -> str:
    profile = _rp_length_profile(response_length, partner_word_count)
    wt = int(profile["word_target"])
    label = profile["label"]
    if response_length == RPReplyResponseLength.match:
        return (
            f"Response length: approximately {wt} words — roughly matching the partner reply's length. "
            "Do not pad. Stop when your character's response is complete."
        )
    if response_length == RPReplyResponseLength.short:
        return (
            f"Response length: {label} — write approximately {wt} words. "
            "Cover ONE beat only. Stop as soon as your character's immediate action and/or line of dialogue is delivered. "
            "Do not extend into a second exchange."
        )
    if response_length == RPReplyResponseLength.long:
        return (
            f"Response length: {label} — write approximately {wt} words. "
            "Cover several beats with meaningful progression. "
            "Stop when you have delivered all beats — do not over-extend."
        )
    if response_length == RPReplyResponseLength.novella:
        return (
            f"Response length: {label} — approximately {wt} words. "
            f"{_NOVELLA_BEAT_HINT}"
        )
    return f"Response length: {label} — approximately {wt} words."


# ── style match instruction ────────────────────────────────────────────────────

def _rp_style_instruction(style_match: str) -> str:
    if style_match == RPReplyStyleMatch.off:
        return "Style: write naturally in your character's voice. Do not mirror the partner's style."
    if style_match == RPReplyStyleMatch.soft:
        return (
            "Style match (soft): roughly mirror the partner's paragraph structure and energy, "
            "without copying their phrasing or vocabulary."
        )
    # strong
    return (
        "Style match (strong): closely mirror the partner reply's paragraph count, sentence length patterns, "
        "prose density, and formatting choices. Do not copy their phrases — mirror the rhythm and shape, "
        "not the words."
    )


# ── perspective instruction ────────────────────────────────────────────────────

def _rp_perspective_instruction(perspective: str, character_name: str) -> str:
    if perspective == RPReplyPerspective.first_person:
        return 'Perspective: first person ("I", "me", "my"). Write entirely as "I".'
    name_note = f' ("{character_name}")' if character_name else ""
    return (
        f"Perspective: third person limited{name_note}. "
        "Stay tightly inside your character's viewpoint — their observations, sensations, and thoughts only. "
        'Do NOT use "I", "me", "my", or "myself" in narrative prose. '
        "First-person pronouns may only appear inside quoted dialogue."
    )


# ── first-person narration detector ───────────────────────────────────────────

_QUOTED_SPAN_RE = re.compile(r'"[^"]*"')
_FIRST_PERSON_NARRATION_RE = re.compile(r'\b(I|me|my|myself)\b', re.IGNORECASE)


def detect_first_person_narration(text: str) -> dict:
    """Return {"has_violation": bool, "excerpt": str}.

    Strips all double-quoted spans (dialogue) from *text*, then checks the
    remaining narration prose for first-person pronouns (I / me / my / myself).
    Quoted dialogue is explicitly allowed — '"I want you to look at me," Leonardo said'
    will not trigger a violation.
    """
    stripped = _QUOTED_SPAN_RE.sub("", text)
    m = _FIRST_PERSON_NARRATION_RE.search(stripped)
    if not m:
        return {"has_violation": False, "excerpt": ""}
    start = max(0, m.start() - 30)
    end = min(len(stripped), m.end() + 30)
    excerpt = stripped[start:end].strip()
    return {"has_violation": True, "excerpt": excerpt}


# ── formatting instruction ─────────────────────────────────────────────────────

def _rp_formatting_instruction(formatting: str) -> str:
    if formatting == RPReplyFormatting.roleplay_bars:
        return (
            "Formatting: roleplay bars. Wrap every narrative paragraph in || delimiters. "
            "Dialogue sits outside the bars. Example:\n"
            '||He stepped closer, jaw tight against whatever he was holding back.||\n\n'
            '"You already knew," he said quietly.\n\n'
            '||He did not look away.||'
        )
    return "Formatting: plain prose. No || delimiters."


# ── layered prompt composition ────────────────────────────────────────────────

def build_rp_prompt_layers(
    partner_reply: str,
    response_length: str,
    style_match: str,
    perspective: str,
    formatting: str,
    heat_level: str = "flame",
    instructions: str | None = None,
    character_context: str | None = None,
    canon_summary: str | None = None,
    character_name: str = "",
    style_archetype: str = DEFAULT_ARCHETYPE,
) -> dict[str, str]:
    """Return a named dict of prompt layers for RP reply generation.

    Priority order per spec (1 = highest):
        1. identity lock              — role_lock (POV anchor)
        2. partner control protection — partner_control
        3. scene progression engine   — scene_engine (dynamic beat-aware block)
        4. behavior enforcement       — behavior_enforcement (HIGHEST in system)
        5. heat layer                 — heat
        6. archetype                  — prose style archetype guidance
        7. cinematic prose polish     — prose_polish (LOWEST style)
        —  identity                   — character context (system)
        —  etiquette                  — anti-godmodding (system)
        —  style                      — perspective + formatting + style_match
        —  continuity                 — environmental continuity (conditional)
        —  pacing                     — length target
        —  scene_state                — story context + partner reply + instructions
        —  continuation               — task instruction (final directive)

    prose_style is retained as an alias for prose_polish + archetype combined
    for backward-compatibility with existing tests.
    """
    partner_word_count = len(partner_reply.split())

    # ── scene beat analysis (drives scene_engine layer) ───────────────────────
    combined_context = (canon_summary or "") + "\n" + partner_reply
    _beats = detect_scene_beats(combined_context)
    _scene_stage = _beats["scene_stage"]
    _goal = determine_next_scene_goal(_scene_stage)
    _next_goal = _goal["next_goal"]
    # Use combined_context as prior_text so beat detection works even without canon_summary
    _rep = detect_repeated_beats(partner_reply, canon_summary or "")
    _repeated_beats = _rep["repeated_beats"]

    # ── spatial continuity engine ─────────────────────────────────────────────
    _spatial = detect_spatial_state(combined_context)
    _spatial_block = build_spatial_continuity_block(_spatial)

    # ── scene engine layer: beat-aware block + static progression rules merged ─
    # Static SCENE_PROGRESSION_BLOCK is folded into the dynamic block (not separate layer)
    _dynamic_progression = build_scene_progression_block(
        scene_stage=_scene_stage,
        beats=_beats,
        next_goal=_next_goal,
        repeated_beats=_repeated_beats,
        heat_level=heat_level,
    )
    scene_engine_parts = ["## Scene Beat Engine\n" + _dynamic_progression]
    if _spatial_block:
        scene_engine_parts.append("## Spatial Continuity\n" + _spatial_block)
    scene_engine = "\n\n".join(scene_engine_parts)

    # ── behavior_enforcement (system-level, HIGHEST PRIORITY) ─────────────────
    behavior_enforcement = (
        "## RP BEHAVIORAL ENFORCEMENT\n"
        + build_behavior_enforcement_block(heat_level=heat_level, instructions=instructions)
    )

    # ── identity ─────────────────────────────────────────────────────────────
    identity_parts = [
        "You are a collaborative roleplay writing assistant. "
        "Your sole job is to write one character's response.\n\n"
        "OUTPUT: Return the reply text inside <REPLY>...</REPLY> tags. "
        "Nothing else — no preamble, no author notes."
    ]
    if character_context and character_context.strip():
        identity_parts.append(f"## Your Character\n{character_context.strip()}")
    identity = "\n\n".join(identity_parts)

    # ── role lock (POV lock) ─────────────────────────────────────────────────
    if character_name:
        role_lock = (
            "## ROLE LOCK — POV LOCK\n"
            f"You are writing ONLY as {character_name}.\n"
            "The partner reply is READ-ONLY context — it is NOT your voice.\n"
            f"Do NOT continue from the partner character's perspective.\n"
            "Do NOT start your reply with the partner character's pronoun or name.\n"
            f"Every sentence belongs to {character_name}: "
            f"their actions, their voice, their body, their interiority."
        )
    else:
        role_lock = (
            "## ROLE LOCK — POV LOCK\n"
            "You are writing ONLY as the selected character.\n"
            "The partner reply is READ-ONLY context — it is NOT your voice.\n"
            "Do NOT continue from the partner character's perspective.\n"
            "Do NOT start with the partner character's pronoun or name.\n"
            "Write only what the selected character does, says, thinks, and feels."
        )

    # ── partner silence (zero-dialogue rule) ─────────────────────────────────
    # Injected after role_lock and before partner_control so it sits at the
    # highest user-message priority after the POV anchor.
    partner_silence = "## Partner Silence\n" + PARTNER_SILENCE_LAYER

    # ── partner-control protection ────────────────────────────────────────────
    # Partner control layer: focused entirely on anti-godmodding rules.
    # The output format tag is in identity; repetition here is intentional (different priority layer).
    partner_control = "## Partner-Control Protection\n" + PARTNER_CONTROL_PROTECTION_BLOCK

    # ── selected-character drive (anti-stall positive directive) ──────────────
    partner_drive = "## Scene Drive\n" + SELECTED_CHARACTER_DRIVES_SCENE

    # ── narrative propulsion (anti-loop, movement pressure) ──────────────────
    # Injected AFTER partner_control / partner_drive and BEFORE heat/style layers.
    # Analyzes partner reply + canon context to generate scene-specific forward pressure.
    _propulsion_block = build_narrative_propulsion_block(partner_reply, canon_summary or "")
    narrative_propulsion = "## Narrative Propulsion\n" + _propulsion_block

    # ── heat ──────────────────────────────────────────────────────────────────
    heat = f"## {get_heat_prompt_block(heat_level)}"

    # ── style (formatting/perspective/style_match) ─────────────────────────────
    style_lines = [
        _rp_perspective_instruction(perspective, character_name),
        _rp_style_instruction(style_match),
        _rp_formatting_instruction(formatting),
    ]
    style = "## Style\n" + "\n".join(f"- {l}" for l in style_lines)

    # ── scene continuity (environmental) ─────────────────────────────────────
    continuity_data = maintain_scene_continuity(partner_reply, prior_context=canon_summary)
    continuity = (
        f"## Scene Continuity\n{continuity_data['continuity_prompt']}"
        if continuity_data["continuity_prompt"]
        else ""
    )

    # ── pacing ────────────────────────────────────────────────────────────────
    pacing = f"## Pacing\n- {_rp_length_instruction(response_length, partner_word_count)}"

    # ── beat planner (multi-beat instruction sequencing) ──────────────────────
    _multi_beat = detect_multi_beat_instruction(instructions or "")
    _req_beats = extract_requested_beats(instructions or "") if _multi_beat else []
    _beat_block_base = build_beat_execution_block(_req_beats)
    # Always append no-partner-bridge for long/novella (multi-exchange responses are the
    # highest-risk window for the model to start authoring the partner character).
    # For shorter lengths the continuation block already handles it.
    _needs_bridge_guard = (
        _beat_block_base
        or response_length in (RPReplyResponseLength.long, RPReplyResponseLength.novella)
    )
    if _beat_block_base:
        _beat_block = _beat_block_base + "\n" + NO_PARTNER_BRIDGE_INSTRUCTION
    elif _needs_bridge_guard:
        _beat_block = NO_PARTNER_BRIDGE_INSTRUCTION
    else:
        _beat_block = ""

    # ── scene state (context + instructions + beat block + partner reply) ─────
    # Beat execution block is injected between instructions and partner reply
    # so the model reads the sequencing directive before encountering the partner text.
    scene_parts: list[str] = []
    if canon_summary and canon_summary.strip():
        scene_parts.append(f"## Story Context\n{canon_summary.strip()}")
    if instructions and instructions.strip():
        scene_parts.append(f"## Your Instructions\n{instructions.strip()}")
        if _beat_block:
            scene_parts.append(_beat_block)
    elif _beat_block:
        # No explicit instructions but bridge guard is needed (long/novella length)
        scene_parts.append(_beat_block)
    scene_parts.append(
        f"## Partner's Reply — their turn is complete; do not continue writing for them\n"
        f"{partner_reply.strip()}"
    )
    scene_state = "\n\n".join(scene_parts)

    # ── archetype (style archetype) ───────────────────────────────────────────
    archetype = "## Style Archetype\n" + get_archetype_prompt_block(style_archetype)

    # ── prose polish (cinematic prose — LOWEST style priority) ────────────────
    # At inferno heat, ESCALATION_STORY_LAYER ("Do not jump rapidly between stages") is
    # omitted — it would throttle explicit escalation that's already been cleared.
    if heat_level == "inferno":
        prose_polish = "## Prose Polish\n" + DARK_ROMANCE_PROSE_LAYER
    else:
        prose_polish = "## Prose Polish\n" + DARK_ROMANCE_PROSE_LAYER + "\n\n" + ESCALATION_STORY_LAYER

    # prose_style alias: retained for backward-compatibility with existing tests
    from app.services.rp_style_engine import build_style_layer
    prose_style = "## Prose Style\n" + build_style_layer(style_archetype)

    # ── continuation (final task directive — always last) ─────────────────────
    char_clause = f" Write as {character_name}." if character_name else ""
    char_label = character_name or "your character"
    anti_godmod_reminder = (
        f"WRITE ONLY {char_label.upper()}'S RESPONSE. "
        "The partner's turn is over — do not give the partner new dialogue, actions, consent, climax, "
        "reactions, thoughts, or decisions. Every sentence must belong to your character."
    )
    continuation = (
        f"## Task — Your Turn\n"
        f"The partner's turn is complete. Write only {char_label}'s next turn.{char_clause} "
        f"Apply all behavioral, heat, and pacing instructions above.\n"
        f"{anti_godmod_reminder}\n"
        f"{TURN_BOUNDARY_FOOTER}\n"
        f"Return the reply inside <REPLY>...</REPLY> tags."
    )

    layers: dict[str, str] = {
        "identity": identity,
        "behavior_enforcement": behavior_enforcement,
        "role_lock": role_lock,
        "partner_silence": partner_silence,
        "partner_control": partner_control,
        "partner_drive": partner_drive,
        "narrative_propulsion": narrative_propulsion,
        "scene_engine": scene_engine,
        "heat": heat,
        "style": style,
        "prose_style": prose_style,
        "archetype": archetype,
        "prose_polish": prose_polish,
        "pacing": pacing,
        "scene_state": scene_state,
        "continuation": continuation,
        # Expose beat metadata for caller diagnostics
        "_scene_stage": _scene_stage,
        "_next_goal": _next_goal,
        "_repetition_score": str(_rep["repetition_score"]),
        "_repeated_beats": ", ".join(_repeated_beats) if _repeated_beats else "",
        # Beat planner diagnostics
        "_multi_beat_detected": "true" if _multi_beat else "false",
        "_requested_beats": ",".join(_req_beats),
    }
    if continuity:
        layers["continuity"] = continuity
    return layers


# ── prompt builder (public) ───────────────────────────────────────────────────

def build_rp_reply_prompt(
    partner_reply: str,
    response_length: str,
    style_match: str,
    perspective: str,
    formatting: str,
    intensity: str,
    instructions: str | None = None,
    character_context: str | None = None,
    canon_summary: str | None = None,
    character_name: str = "",
    heat_level: str = "flame",
    style_archetype: str = DEFAULT_ARCHETYPE,
) -> list[dict[str, str]]:
    """Build the messages payload for an RP reply generation call.

    Uses layered prompt composition via build_rp_prompt_layers().
    heat_level (embers/flame/inferno) drives content guidance; intensity is kept
    for API compat but heat_level takes precedence for the heat block.
    style_archetype selects the prose style layer from rp_style_engine.

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    layers = build_rp_prompt_layers(
        partner_reply=partner_reply,
        response_length=response_length,
        style_match=style_match,
        perspective=perspective,
        formatting=formatting,
        heat_level=heat_level,
        instructions=instructions,
        character_context=character_context,
        canon_summary=canon_summary,
        character_name=character_name,
        style_archetype=style_archetype,
    )

    # System: identity (includes output format) + behavioral enforcement (highest priority)
    # etiquette is removed as a separate block — behavior_enforcement fully covers it.
    system_content = (
        layers["identity"]
        + "\n\n"
        + layers["behavior_enforcement"]
    )

    # User message priority order:
    #   1. role_lock             — POV anchor (highest user-message priority)
    #   2. partner_silence       — no authored dialogue/choices for partner
    #   3. partner_control       — anti-godmodding rules
    #   4. partner_drive         — selected character carries scene, no waiting loop
    #   5. narrative_propulsion  — anti-loop, movement/escalation pressure
    #   6. heat                  — content level rules
    #   7. style                 — formatting/perspective/style_match
    #   8. pacing                — length target
    #   9. scene_state           — context + instructions + partner reply
    #  10. continuation          — task directive (always last)
    user_sections = [
        layers["role_lock"],
        layers["partner_silence"],
        layers["partner_control"],
        layers["partner_drive"],
        layers["narrative_propulsion"],
        layers["heat"],
        layers["style"],
        layers["pacing"],
        layers["scene_state"],
        layers["continuation"],
    ]
    user_content = "\n\n".join(user_sections)

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ── retry correction block ────────────────────────────────────────────────────

def build_retry_correction_block(character_name: str = "") -> str:
    """Build a partner-control correction for a generation retry.

    Injected at the TOP of the system message, before all other instructions.
    Only called when authored_dialogue or authored_consent is detected.
    """
    char_label = character_name or "the selected character"
    return (
        "CORRECTION — READ FIRST — OVERRIDES ALL OTHER INSTRUCTIONS:\n"
        "Your previous generation wrote the partner character.\n"
        f"Rewrite the reply. Write only as {char_label}. "
        "Do not author the partner's dialogue, thoughts, choices, climax, or major reactions."
    )


# ── output parser ──────────────────────────────────────────────────────────────

_RP_REPLY_TAG_RE = re.compile(r"<REPLY>(.*?)</REPLY>", re.DOTALL)


def _parse_rp_reply_output(raw: str) -> str:
    m = _RP_REPLY_TAG_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


# ── anti-godmodding output guard ───────────────────────────────────────────────

def _check_rp_reply_output(reply: str) -> list[str]:
    """Return warning strings for quality issues NOT already covered by the godmod validator.

    The godmod validator (detect_godmod_violations) handles physical reactions,
    consent/agency, climax, and attributed dialogue with retry support. This
    function covers the remaining cases the godmod validator does not:

      1. Empty / too short  — always returned early, no other checks run
      2. Multiple dialogue attribution (≥3 blocks) — broad structural signal;
         godmod validator catches ≥2 attributed lines but this check fires on a
         higher count to catch prose with very dense multi-character dialogue
         that may pass the godmod retry at lower counts
      3. Dense interior-state narration (≥4 instances) — godmod validator uses
         a different inner-state verb set and fires at ≥2; this check uses a
         broader verb list and fires only at ≥4 to avoid false positives, giving
         a user-facing nudge when the validator's threshold wasn't crossed
    """
    warnings: list[str] = []
    words = reply.split()

    if len(words) < 20:
        warnings.append("Generated reply is very short — consider regenerating.")
        return warnings

    # 1. Multiple dialogue attribution patterns suggest both characters speaking
    attributions = re.findall(
        r'"[^"]{3,}"[^"]*?(?:said|replied|answered|responded|asked|laughed|'
        r'whispered|snapped|muttered|called|breathed|hissed|drawled)\b',
        reply, re.IGNORECASE,
    )
    if len(attributions) >= 3:
        warnings.append(
            "Reply may include dialogue from more than one character — review before sending."
        )

    # 2. Dense third-person interior-state narration likely means partner POV was written
    interior = re.findall(
        r'\b(?:she|he|they)\s+(?:felt|thought|knew|realized|wondered|decided|'
        r'chose|wanted|needed|understood|believed|hoped|feared|expected)\b',
        reply, re.IGNORECASE,
    )
    if len(interior) >= 4:
        warnings.append(
            "Reply may be narrating another character's internal state — "
            "ensure you are only writing your own character."
        )

    return warnings


# ── stub ───────────────────────────────────────────────────────────────────────

_RP_REPLY_STUBS = [
    (
        "He let the silence absorb what she'd said, the words settling into him slowly, "
        "the way cold water settles into stone. There was something in what she wasn't saying "
        "that pulled harder than the words themselves.\n\n"
        '"I heard you," he said at last. His voice was quieter than he intended. '
        "He did not look away from the window, but his focus had long since left it."
    ),
    (
        "She did not move immediately. Let the weight of it land — because it deserved that, "
        "at least. A breath. Another.\n\n"
        "When she finally turned, her expression had resolved into something careful and "
        "deliberately still. The kind of still that took effort.\n\n"
        '"That\'s one way to put it," she said.'
    ),
    (
        "Something shifted in his chest that he hadn't been expecting. Not surprise, exactly — "
        "more like recognition. The kind that arrives a beat too late to do anything useful with.\n\n"
        "He crossed to the table. Poured water he didn't need. Set the glass down without drinking.\n\n"
        '"You\'re asking me to choose." It wasn\'t a question.'
    ),
]


def _rp_reply_stub(partner_reply: str, formatting: str, perspective: str) -> str:
    idx = hash(partner_reply[:60]) % len(_RP_REPLY_STUBS)
    text = _RP_REPLY_STUBS[idx]

    if perspective == RPReplyPerspective.first_person:
        text = (
            text.replace("He let the silence", "I let the silence")
            .replace("his chest", "my chest")
            .replace("he'd", "I'd")
            .replace("He did not", "I did not")
            .replace("his focus", "my focus")
            .replace("She did not", "I did not")
            .replace("she'd", "I'd")
            .replace("her expression", "my expression")
            .replace("she said", "I said")
            .replace("He crossed", "I crossed")
            .replace("he didn't", "I didn't")
        )

    if formatting == RPReplyFormatting.roleplay_bars:
        parts = []
        for para in text.split("\n\n"):
            para = para.strip()
            if para.startswith('"'):
                parts.append(para)
            else:
                parts.append(f"||{para}||")
        text = "\n\n".join(parts)

    return text


# ── OpenRouter caller ──────────────────────────────────────────────────────────

def _call_openrouter_rp_reply(
    partner_reply: str,
    response_length: str,
    style_match: str,
    perspective: str,
    formatting: str,
    intensity: str,
    model_slug: str,
    instructions: str | None = None,
    character_context: str | None = None,
    canon_summary: str | None = None,
    character_name: str = "",
    heat_level: str = "flame",
    style_archetype: str = DEFAULT_ARCHETYPE,
    pov_correction: str | None = None,
) -> tuple[str, int, int]:
    """Call OpenRouter for RP reply generation; return (reply, generation_time_ms, max_tokens_used).

    pov_correction: when provided (on a retry after wrong-POV detection), this string
    is prepended to the system message at the highest priority position.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_rp_reply_prompt(
        partner_reply=partner_reply,
        response_length=response_length,
        style_match=style_match,
        perspective=perspective,
        formatting=formatting,
        intensity=intensity,
        instructions=instructions,
        character_context=character_context,
        canon_summary=canon_summary,
        character_name=character_name,
        heat_level=heat_level,
        style_archetype=style_archetype,
    )
    # On retry: inject correction at the very top of the system message so it
    # has maximum weight over every other instruction.
    if pov_correction:
        messages[0]["content"] = pov_correction + "\n\n" + messages[0]["content"]
    partner_words = len(partner_reply.split())
    # Use the length profile's explicit max_tokens rather than computing from word target
    max_tokens = _rp_reply_max_tokens(response_length, partner_words)

    payload = {
        "model": model_slug,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.88,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ficshon.com",
        "X-Title": "Ficshon StoryLab",
    }

    user_content_len = len(messages[1]["content"]) if len(messages) > 1 else 0
    logger.info(
        "[SL-DIAG] _call_openrouter_rp_reply | model=%s max_tokens=%d prompt_chars=%d partner_words=%d",
        model_slug, max_tokens, user_content_len, partner_words,
    )

    t_start = time.monotonic()
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
        logger.info("[SL-DIAG] _call_openrouter_rp_reply HTTP status=%d", resp.status_code)
        resp.raise_for_status()
    generation_time_ms = int((time.monotonic() - t_start) * 1000)

    data = resp.json()
    raw: str = data["choices"][0]["message"]["content"]
    logger.info(
        "[SL-DIAG] _call_openrouter_rp_reply raw_chars=%d has_reply_tag=%s time_ms=%d",
        len(raw), "<REPLY>" in raw, generation_time_ms,
    )

    reply = _parse_rp_reply_output(raw)
    if not reply:
        raise ValueError("Model returned empty RP reply after parsing")
    return reply, generation_time_ms, max_tokens


# ── public entry point ────────────────────────────────────────────────────────

def generate_rp_reply(
    partner_reply: str,
    response_length: str = RPReplyResponseLength.match,
    style_match: str = RPReplyStyleMatch.soft,
    perspective: str = RPReplyPerspective.third_person_limited,
    formatting: str = RPReplyFormatting.plain,
    intensity: str = RPReplyIntensity.standard,
    instructions: str | None = None,
    character_context: str | None = None,
    canon_summary: str | None = None,
    character_name: str = "",
    model_profile: str = "default",
    heat_level: str = "flame",
    style_archetype: str = DEFAULT_ARCHETYPE,
    partner_character_name: str = "",
) -> tuple[str, str, int, list[str], int, dict]:
    """Return (reply, model_used, generation_time_ms, pov_warnings, max_tokens_used, godmod_meta).

    godmod_meta = {"detected": bool, "severity": str, "warnings": list[str]}

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and
    OPENROUTER_API_KEY is set; falls back to the deterministic stub
    on any error so the endpoint never returns empty-handed.

    Heat routing:
    - intensity acts as a floor for heat_level (explicit → inferno, mature → flame, standard → embers)
    - inferno heat auto-routes to a permissive model, never Claude
    model_profile selects from RP_REPLY_MODELS; inferno may override.
    style_archetype selects prose style from rp_style_engine.

    Quality retries: after first generation, if serious issues are detected
    (progression failure, partner control, repetition, regression) a single
    correction-injected retry is attempted.

    POV validation: if the generated reply starts from the partner character's
    POV, retries once with a POV correction injected at system-message priority.
    """
    provider = settings.STORYLAB_PROVIDER

    # ── intensity → heat floor ─────────────────────────────────────────────────
    heat_level = effective_heat_level(heat_level, intensity)

    # ── model routing ──────────────────────────────────────────────────────────
    inferno_model_override = False
    original_model = ""
    if heat_level == "inferno":
        resolved_profile, model_slug, inferno_model_override = resolve_inferno_model(
            model_profile, _EFFECTIVE_STORYLAB_MODEL,
            inferno_override=settings.STORYLAB_MODEL_INFERNO,
        )
        original_model = _EFFECTIVE_STORYLAB_MODEL
        if inferno_model_override:
            logger.info(
                "[SL-DIAG] inferno_model_override=True original_model=%s resolved_model=%s",
                original_model, model_slug,
            )
    else:
        resolved_profile, model_slug = resolve_rp_model(model_profile, _EFFECTIVE_STORYLAB_MODEL)

    logger.info(
        "[SL-DIAG] generate_rp_reply | provider=%s key_present=%s profile=%s model=%s "
        "length=%s style=%s formatting=%s intensity=%s heat=%s archetype=%s "
        "inferno_override=%s",
        provider, bool(settings.OPENROUTER_API_KEY), resolved_profile, model_slug,
        response_length, style_match, formatting, intensity, heat_level, style_archetype,
        inferno_model_override,
    )

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub for RP reply")
        else:
            t_start = time.monotonic()
            try:
                reply, generation_time_ms, max_tokens_used = _call_openrouter_rp_reply(
                    partner_reply=partner_reply,
                    response_length=response_length,
                    style_match=style_match,
                    perspective=perspective,
                    formatting=formatting,
                    intensity=intensity,
                    model_slug=model_slug,
                    instructions=instructions,
                    character_context=character_context,
                    canon_summary=canon_summary,
                    character_name=character_name,
                    heat_level=heat_level,
                    style_archetype=style_archetype,
                )

                # ── quality diagnostics ───────────────────────────────────────
                _pc = detect_partner_control(reply)
                _ss = detect_scene_stall(reply)
                _anatomy = score_inferno_anatomy_density(reply) if heat_level == "inferno" else 0.0
                combined_ctx = (canon_summary or "") + "\n" + partner_reply
                _reg = detect_scene_regression(reply, combined_ctx)
                _rep_post = detect_repeated_beats(reply, combined_ctx)
                _cadence = detect_ai_cadence(reply)

                logger.info(
                    "[SL-DIAG] rp_reply_generation | profile=%s model=%s "
                    "reply_words=%d time_ms=%d heat=%s | "
                    "partner_control_risk=%.3f scene_stall_score=%.3f "
                    "progression_score=%.3f inferno_anatomy_density=%.3f "
                    "repeated_emotion_score=%.3f ai_cadence_risk=%s",
                    resolved_profile, model_slug,
                    len(reply.split()), generation_time_ms, heat_level,
                    _pc["partner_control_risk"], _ss["scene_stall_score"],
                    _ss["progression_score"], _anatomy,
                    _ss["repeated_emotion_score"], _cadence["ai_cadence_risk"],
                )

                # ── partner-silence retry ──────────────────────────────────────
                # Retry triggers when:
                #   (a) cross_gender_godmod: BOTH "he ... said" AND "she ... said"
                #       are present — strong evidence both characters were written;
                #   (b) dialogue_count >= 2: two attributed lines even at same gender,
                #       likely one for selected char and one for partner;
                #   (c) decision_count >= 1: partner agency/consent authored.
                #
                # dialogue_count == 1 alone is NOT enough to trigger because a single
                # '"quote," he said' / '"quote," she said' is almost always the
                # selected character's own attributed speech — not godmodding.
                retry_triggered = False
                pov_warnings: list[str] = []

                _silence = detect_partner_silence_severe(reply)
                _cross_gender = _silence.get("cross_gender_godmod", False)
                if _cross_gender or _silence["dialogue_count"] >= 2 or _silence["decision_count"] >= 1:
                    retry_triggered = True
                    correction = build_partner_silence_correction(character_name)
                    logger.info(
                        "[SL-DIAG] partner_silence_retry triggered | flags=%s | model=%s",
                        _silence["flags"], model_slug,
                    )
                    try:
                        retry_reply, retry_ms, _ = _call_openrouter_rp_reply(
                            partner_reply=partner_reply,
                            response_length=response_length,
                            style_match=style_match,
                            perspective=perspective,
                            formatting=formatting,
                            intensity=intensity,
                            model_slug=model_slug,
                            instructions=instructions,
                            character_context=character_context,
                            canon_summary=canon_summary,
                            character_name=character_name,
                            heat_level=heat_level,
                            style_archetype=style_archetype,
                            pov_correction=correction,
                        )
                        generation_time_ms += retry_ms
                        reply = retry_reply
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning(
                            "[SL-DIAG] partner_control_retry failed: %s — using original reply",
                            retry_exc,
                        )

                # ── waiting-loop retry ────────────────────────────────────────
                # Only fires when silence retry was not triggered (one retry max per generation).
                if not retry_triggered:
                    _waiting = detect_waiting_loop(reply)
                    if _waiting["waiting_loop"]:
                        retry_triggered = True
                        correction = build_waiting_loop_correction(character_name)
                        logger.info(
                            "[SL-DIAG] waiting_loop_retry triggered | count=%d flags=%s | model=%s",
                            _waiting["pattern_count"], _waiting["flags"], model_slug,
                        )
                        try:
                            retry_reply, retry_ms, _ = _call_openrouter_rp_reply(
                                partner_reply=partner_reply,
                                response_length=response_length,
                                style_match=style_match,
                                perspective=perspective,
                                formatting=formatting,
                                intensity=intensity,
                                model_slug=model_slug,
                                instructions=instructions,
                                character_context=character_context,
                                canon_summary=canon_summary,
                                character_name=character_name,
                                heat_level=heat_level,
                                style_archetype=style_archetype,
                                pov_correction=correction,
                            )
                            generation_time_ms += retry_ms
                            reply = retry_reply
                        except Exception as retry_exc:  # noqa: BLE001
                            logger.warning(
                                "[SL-DIAG] waiting_loop_retry failed: %s — using original reply",
                                retry_exc,
                            )

                # ── POV validation ────────────────────────────────────────────
                # Skip POV retry if any other retry was already triggered (one retry max)
                if not retry_triggered:
                    pov_result = detect_wrong_pov(reply, character_name, partner_reply)
                    if pov_result["wrong_pov"]:
                        logger.warning(
                            "[SL-DIAG] wrong POV detected | char=%s reason=%s — retrying",
                            character_name or "(none)", pov_result["reason"],
                        )
                        char_label = character_name or "the selected character"
                        pov_correction = (
                            f"CRITICAL CORRECTION — READ FIRST:\n"
                            f"Your previous output continued from the partner character's perspective. "
                            f"This is incorrect.\n"
                            f"You MUST rewrite ONLY from {char_label}'s perspective.\n"
                            f"Do NOT open with the partner character's pronoun or name.\n"
                            f"The partner reply is context for you to respond TO, not a voice to continue."
                        )
                        try:
                            retry_reply, retry_ms, _ = _call_openrouter_rp_reply(
                                partner_reply=partner_reply,
                                response_length=response_length,
                                style_match=style_match,
                                perspective=perspective,
                                formatting=formatting,
                                intensity=intensity,
                                model_slug=model_slug,
                                instructions=instructions,
                                character_context=character_context,
                                canon_summary=canon_summary,
                                character_name=character_name,
                                heat_level=heat_level,
                                style_archetype=style_archetype,
                                pov_correction=pov_correction,
                            )
                            generation_time_ms += retry_ms
                            retry_pov = detect_wrong_pov(retry_reply, character_name, partner_reply)
                            if retry_pov["wrong_pov"]:
                                pov_warnings.append(
                                    f"POV warning: reply may still be written from the partner's "
                                    f"perspective after retry. ({retry_pov['reason']})"
                                )
                            reply = retry_reply
                        except Exception as retry_exc:  # noqa: BLE001
                            logger.warning(
                                "[SL-DIAG] POV retry failed: %s — using original reply",
                                retry_exc,
                            )
                            pov_warnings.append(
                                f"POV warning: wrong-POV detected but retry failed. "
                                f"({pov_result['reason']})"
                            )

                # ── perspective (first-person narration) retry ────────────────
                # Only fires when no other retry was already triggered (one retry max).
                # Quoted dialogue is exempt — only bare narration prose is checked.
                if not retry_triggered and perspective == RPReplyPerspective.third_person_limited:
                    _fp = detect_first_person_narration(reply)
                    if _fp["has_violation"]:
                        retry_triggered = True
                        char_label = character_name or "the selected character"
                        perspective_correction = (
                            "CRITICAL CORRECTION — READ FIRST:\n"
                            'Your previous output used first-person narration ("I", "me", "my") '
                            "outside of quoted dialogue. This violates the third-person limited perspective.\n"
                            f"Rewrite the reply as {char_label} using ONLY third-person narration. "
                            '"I" / "me" / "my" / "myself" may appear ONLY inside quoted speech.\n'
                            'Every narrative sentence must use "he", "she", "they", or the character\'s name.'
                        )
                        logger.info(
                            "[SL-DIAG] perspective_retry triggered | excerpt=%r | model=%s",
                            _fp["excerpt"], model_slug,
                        )
                        try:
                            retry_reply, retry_ms, _ = _call_openrouter_rp_reply(
                                partner_reply=partner_reply,
                                response_length=response_length,
                                style_match=style_match,
                                perspective=perspective,
                                formatting=formatting,
                                intensity=intensity,
                                model_slug=model_slug,
                                instructions=instructions,
                                character_context=character_context,
                                canon_summary=canon_summary,
                                character_name=character_name,
                                heat_level=heat_level,
                                style_archetype=style_archetype,
                                pov_correction=perspective_correction,
                            )
                            generation_time_ms += retry_ms
                            reply = retry_reply
                        except Exception as retry_exc:  # noqa: BLE001
                            logger.warning(
                                "[SL-DIAG] perspective_retry failed: %s — using original reply",
                                retry_exc,
                            )

                # ── Godmod output gate ────────────────────────────────────────
                # Run after all other retries. Godmod gate has its own boolean
                # so it fires even when a prior retry (partner_silence,
                # waiting_loop, POV) already set retry_triggered = True.
                godmod_meta: dict = {"detected": False, "severity": "none", "warnings": []}
                godmod_retry_triggered = False
                _godmod = detect_godmod_violations(
                    reply,
                    selected_character_name=character_name or None,
                    partner_character_name=partner_character_name or None,
                )
                if _godmod["severity"] == "hard" and not godmod_retry_triggered:
                    godmod_retry_triggered = True
                    char_label = character_name or "the selected character"
                    godmod_correction = (
                        "CRITICAL CORRECTION — READ FIRST — OVERRIDES ALL OTHER INSTRUCTIONS:\n"
                        f"Your previous output wrote the partner character's dialogue, decisions, "
                        f"inner thoughts, or major actions. This is godmodding — it is not allowed.\n"
                        f"Rewrite the reply as {char_label} ONLY.\n"
                        "Remove ALL of the following from the partner character:\n"
                        "  - spoken dialogue or quoted speech\n"
                        "  - consent, permission, or decisions\n"
                        "  - inner thoughts, feelings, or emotional conclusions\n"
                        "  - climax or orgasm\n"
                        "  - any major action that moves the scene forward\n"
                        f"Continue only through {char_label}'s own actions, speech, and narration."
                    )
                    logger.info(
                        "[SL-DIAG] godmod_output_gate retry | severity=%s violations=%s | model=%s",
                        _godmod["severity"],
                        [v["type"] for v in _godmod["violations"]],
                        model_slug,
                    )
                    try:
                        retry_reply, retry_ms, _ = _call_openrouter_rp_reply(
                            partner_reply=partner_reply,
                            response_length=response_length,
                            style_match=style_match,
                            perspective=perspective,
                            formatting=formatting,
                            intensity=intensity,
                            model_slug=model_slug,
                            instructions=instructions,
                            character_context=character_context,
                            canon_summary=canon_summary,
                            character_name=character_name,
                            heat_level=heat_level,
                            style_archetype=style_archetype,
                            pov_correction=godmod_correction,
                        )
                        generation_time_ms += retry_ms
                        reply = retry_reply
                        # Re-validate after retry
                        _godmod = detect_godmod_violations(
                            reply,
                            selected_character_name=character_name or None,
                            partner_character_name=partner_character_name or None,
                        )
                    except Exception as retry_exc:  # noqa: BLE001
                        logger.warning(
                            "[SL-DIAG] godmod_output_gate retry failed: %s — using pre-retry reply",
                            retry_exc,
                        )

                godmod_meta = {
                    "detected": _godmod["severity"] == "hard",
                    "severity": _godmod["severity"],
                    "warnings": [v["excerpt"] for v in _godmod["violations"] if v["type"] != "ambiguous_attribution"],
                }
                if godmod_meta["detected"]:
                    logger.warning(
                        "[SL-DIAG] godmod_output_gate HARD_VIOLATION_IN_FINAL_OUTPUT | "
                        "violations=%s | model=%s",
                        [v["type"] for v in _godmod["violations"]],
                        model_slug,
                    )

                return reply, model_slug, generation_time_ms, pov_warnings, max_tokens_used, godmod_meta

            except httpx.TimeoutException:
                logger.warning(
                    "[SL-DIAG] generate_rp_reply FALLBACK: timed out | profile=%s model=%s time_ms=%d",
                    resolved_profile, model_slug,
                    int((time.monotonic() - t_start) * 1000),
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[SL-DIAG] generate_rp_reply FALLBACK: HTTP %s | profile=%s model=%s body=%s",
                    exc.response.status_code, resolved_profile, model_slug,
                    exc.response.text[:300],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[SL-DIAG] generate_rp_reply FALLBACK: %s: %s | profile=%s model=%s",
                    type(exc).__name__, exc, resolved_profile, model_slug,
                )

    logger.warning(
        "[SL-DIAG] generate_rp_reply returning STUB | provider=%s profile=%s",
        provider, resolved_profile,
    )
    stub = _rp_reply_stub(partner_reply, formatting, perspective)
    partner_words = len(partner_reply.split())
    stub_max_tokens = _rp_reply_max_tokens(response_length, partner_words)
    return stub, "stub", 0, [], stub_max_tokens, {"detected": False, "severity": "none", "warnings": []}

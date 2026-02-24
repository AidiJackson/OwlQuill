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
    direction_instructions(direction)     -> str
    boundary_instructions(boundary)       -> str
    pacing_instructions(pacing)           -> str
    tone_instructions(tone_intensity)     -> str
    build_storylab_prompt(...)            -> list[dict]  # messages payload
    generate_storylab_continuation(...)   -> tuple[str, dict | None]
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

_REQUEST_TIMEOUT = 25.0  # seconds for LLM calls

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
    """Return craft-focused narrative guidance for the requested direction."""
    _map: dict[str, str] = {
        Direction.advance_plot: (
            "Introduce a complication, revelation, or decision that shifts what is possible. "
            "Let consequences ripple forward from the last beat rather than introducing "
            "something entirely new. The forward movement should feel inevitable in retrospect."
        ),
        Direction.add_dialogue: (
            "Let characters speak in their own distinct voices — what they say should "
            "reveal what they want, fear, or are hiding from each other. "
            "Ground every line in a specific want. Avoid dialogue that exists only to "
            "exchange information; let subtext carry half the meaning."
        ),
        Direction.sad_moment: (
            "Render grief or loss through the body and the physical environment — "
            "not through declarations of feeling. Avoid the word 'sad'. "
            "Resist premature resolution; let the weight sit. "
            "Specific detail (a particular object, a sound, the quality of light) "
            "carries more emotional force than general statements."
        ),
        Direction.argument_begins: (
            "Root the conflict in something each character genuinely wants or believes. "
            "Avoid clichéd argument starters. Not every grievance is stated directly — "
            "let subtext, deflection, and misdirection do work. "
            "The argument should reveal character, not just advance a dispute."
        ),
        Direction.romantic_moment: (
            "Lean into proximity, noticing, and restraint. "
            "Describe what the character observes about the other person — specific, "
            "sensory detail rather than abstract attraction. "
            "The moment should feel earned by what preceded it. "
            "Silence and small gestures carry more weight than declarations."
        ),
        Direction.sensual_scene: (
            "Build through sensation and implication. "
            "Focus on textures, warmth, breath, and the small precise gestures "
            "that register before anything is named. Mood over mechanics. "
            "The charge comes from anticipation and from what is noticed, not described."
        ),
        Direction.intimate_scene: (
            "Write emotional and physical closeness together — vulnerability as carefully "
            "as anything physical. The scene should feel private and specific to these "
            "characters, not generic. Interior experience has equal weight to action."
        ),
        Direction.twist_event: (
            "Plant the consequences before the twist lands fully — let something feel "
            "slightly wrong in the sentence before the reveal. "
            "The surprise should make the reader reconsider what came before. "
            "Resist the urge to over-explain; trust the reader to catch up."
        ),
        Direction.quiet_reflection: (
            "Interior space: a character sifts through what they know, feel, or suspect. "
            "Revelations should arrive tentatively, not declaratively — "
            "as questions or half-formed recognitions, not conclusions. "
            "The environment should mirror or complicate the interior state."
        ),
        Direction.action_sequence: (
            "Propulsive short sentences. Compress time ruthlessly. "
            "Track orientation — who is where relative to whom, what is at stake "
            "at every beat. Use sensory specifics to ground the chaos. "
            "Stakes must be legible; confusion should feel deliberate, not accidental."
        ),
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
- End on a varied, specific forward hook — a question, an implication, an unresolved \
physical detail, or an action that invites a response. No melodramatic cliffhangers \
("little did they know", "everything was about to change", "but then —"). \
Do not resolve the scene completely. Each ending must differ in structure and closing \
image from the previous one.\
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


# ── system prompt (stable, cache-friendly) ────────────────────────────────────

_SYSTEM_PROMPT = f"""\
You are StoryLab, Ficshon's narrative continuation engine. You continue stories \
with the voice, tense, and POV already established — never explaining, never \
summarising, never breaking the fourth wall.

Core rules:
- Write ONLY the continuation. No preamble, no titles, no commentary.
- Do not repeat or paraphrase any text from the scene provided to you.
- Match the established POV (default: third person limited if unclear).
- Honour boundary and direction instructions exactly.

{_STYLE_RULES}

{_OUTPUT_CONTRACT}\
"""


# ── prompt builder (public, testable) ────────────────────────────────────────

def build_storylab_prompt(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    recent_endings: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build and return the messages list for the OpenRouter chat completions call.

    Args:
        recent_endings: Last N ending phrases from this story's GenerationLog,
                        used to drive anti-repetition instructions.

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    ss = state_json.get("story_state", {})

    def _fmt(v: object) -> str:
        return f"{v:.2f}" if isinstance(v, float) else str(v)

    state_lines = "\n".join(
        f"  {k}: {_fmt(v)}" for k, v in ss.items() if k != "scene_type"
    ) or "  (default)"

    char_names = (
        ", ".join(
            c.get("name", "Unknown") if isinstance(c, dict) else str(c)
            for c in (characters or [])
        )
        or "None specified"
    )

    target_words = _length_target(controls.length)
    cap_words = _length_cap(controls.length)
    scene_tail = text[-6000:] if len(text) > 6000 else text

    endings_block = ""
    if recent_endings:
        bullets = "\n".join(f'- "{e}"' for e in recent_endings)
        endings_block = (
            "\n\n## Endings to avoid\n"
            "Do NOT end your continuation with the same opening words, closing image, "
            "or structural pattern as any of these recent endings from this story:\n"
            f"{bullets}"
        )

    user_content = f"""\
## Story context
Summary: {summary or "No summary yet."}
Characters: {char_names}

## Narrative state
{state_lines}

## Direction: {controls.direction}
{direction_instructions(controls.direction)}

## Boundary: {controls.boundary}
{boundary_instructions(controls.boundary)}

## Pacing: {controls.pacing}
{pacing_instructions(controls.pacing)}

## Tone: {controls.tone_intensity}
{tone_instructions(controls.tone_intensity)}

## Target length
Aim for ~{target_words} words (hard cap: {cap_words} words).

## Recent scene
{scene_tail}

## Task
Continue directly from where the scene ends. Apply all direction, boundary, pacing, \
and tone instructions above. Write approximately {target_words} words (max {cap_words}). \
End on a natural pause with a distinct forward hook. Use the required output format.\
{endings_block}"""

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
) -> tuple[str, dict[str, Any] | None]:
    """Call OpenRouter; parse <STORY> tag from response; fall back to raw on missing tags."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = build_storylab_prompt(
        text, controls, state_json, summary, characters, recent_endings
    )
    cap_words = _length_cap(controls.length)
    # cap_words / 0.75 ≈ cap in tokens; ×2.0 gives comfortable headroom for tags + delta block
    max_tokens = max(400, int(cap_words * 2.0))

    payload = {
        "model": settings.STORYLAB_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.85,
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
    raw: str = data["choices"][0]["message"]["content"]

    delta = _parse_delta_signals(raw)
    if delta:
        logger.debug("StoryLab delta signals: %s", delta)

    story_text = _trim_to_cap(_parse_model_output(raw), cap_words)
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
) -> tuple[str, dict[str, Any] | None]:
    """Return (story_text, delta_signals_or_none).

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and
    OPENROUTER_API_KEY is set; falls back to the deterministic stub
    on any error so the endpoint never returns empty-handed.
    Stub always returns None for delta signals.
    recent_endings is forwarded to the prompt for anti-repetition guidance.
    """
    provider = settings.STORYLAB_PROVIDER

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
        else:
            try:
                return _call_openrouter(
                    text, controls, state_json, summary, characters, recent_endings
                )
            except httpx.TimeoutException:
                logger.warning("OpenRouter request timed out; falling back to stub")
            except httpx.HTTPStatusError as exc:
                logger.warning("OpenRouter returned HTTP %s; falling back to stub", exc.response.status_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenRouter error (%s); falling back to stub", exc)

    return _generate_stub_text(story_id, controls), None

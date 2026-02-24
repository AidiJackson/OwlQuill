"""StoryLab continuation generator.

Provider routing
----------------
STORYLAB_PROVIDER=stub (default)
    Deterministic template-based stub — no API key needed. Always works.

STORYLAB_PROVIDER=openrouter
    Calls OpenRouter chat completions API with OPENROUTER_API_KEY.
    On any failure (timeout, bad response, missing key) falls back to stub
    and logs a warning so callers always get a usable string back.
"""
import logging
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

# ── length → approximate word targets ────────────────────────────────────────

_LENGTH_WORDS = {
    Length.short: 75,
    Length.medium: 150,
    Length.long: 250,
}

# ── boundary instruction phrases ──────────────────────────────────────────────

_BOUNDARY_INSTRUCTION = {
    Boundary.sfw: "Keep content suitable for all audiences. No explicit, intimate, or suggestive content.",
    Boundary.fade_to_black: (
        "Fade to black for any intimate or sensual content — imply but never describe explicitly. "
        "The scene should dissolve gracefully before anything explicit occurs."
    ),
    Boundary.sensual: (
        "Sensual and suggestive content is permitted. Remain literary and non-graphic; "
        "prioritise mood, touch, and implication over explicit description."
    ),
}

# ── stub templates keyed by Direction ────────────────────────────────────────

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
    """Expand stub text based on tone/pacing/length controls."""
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

_SYSTEM_PROMPT = (
    "You are StoryLab, Ficshon's narrative continuation engine. "
    "Your role is to generate immersive, character-aware story continuations that "
    "respect the writer's creative voice and the current narrative state.\n\n"
    "Rules:\n"
    "- Output ONLY the continuation prose. No preamble, no commentary, no titles.\n"
    "- Do not quote or repeat the scene text that was given to you.\n"
    "- Write in the POV and tense established by the scene. Default to third person if unclear.\n"
    "- Honour the boundary instruction exactly."
)


def _build_prompt(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
) -> str:
    ss = state_json.get("story_state", {})

    def _fmt(v: object) -> str:
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    state_lines = "\n".join(
        f"  - {k}: {_fmt(v)}"
        for k, v in ss.items()
        if k not in ("scene_type",)
    )

    char_names = ", ".join(
        c.get("name", "Unknown") if isinstance(c, dict) else str(c)
        for c in (characters or [])
    ) or "None specified"

    target_words = _LENGTH_WORDS.get(controls.length, 150)
    boundary_instr = _BOUNDARY_INSTRUCTION.get(controls.boundary, "SFW content only.")

    # Tail the scene text to keep the prompt focused
    scene_tail = text[-6000:] if len(text) > 6000 else text

    return (
        f"## Story context\n"
        f"Summary: {summary or 'No summary yet.'}\n"
        f"Characters: {char_names}\n\n"
        f"Current narrative state:\n{state_lines or '  (default)'}\n\n"
        f"## Generation controls\n"
        f"Direction: {controls.direction}\n"
        f"Tone intensity: {controls.tone_intensity}\n"
        f"Pacing: {controls.pacing}\n"
        f"Target length: ~{target_words} words\n"
        f"Boundary: {controls.boundary} — {boundary_instr}\n\n"
        f"## Recent scene\n"
        f"{scene_tail}\n\n"
        f"## Task\n"
        f"Continue the scene naturally from where it ends. "
        f"Direction: {controls.direction}. "
        f"Tone intensity: {controls.tone_intensity}. "
        f"Pacing: {controls.pacing}. "
        f"Write approximately {target_words} words. "
        f"Boundary rule: {boundary_instr} "
        f"Output ONLY the continuation prose."
    )


def _call_openrouter(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
) -> str:
    """Call OpenRouter chat completions; returns the assistant message content."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    prompt = _build_prompt(text, controls, state_json, summary, characters)
    target_words = _LENGTH_WORDS.get(controls.length, 150)
    # Allow ~1.5x headroom over word target; words ≈ 0.75 tokens on average
    max_tokens = max(256, int(target_words * 2.0))

    payload = {
        "model": settings.STORYLAB_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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
    content: str = data["choices"][0]["message"]["content"]
    return content.strip()


# ── public entry point ────────────────────────────────────────────────────────

def generate_storylab_continuation(
    text: str,
    controls: StoryLabControls,
    state_json: dict[str, Any],
    summary: str,
    characters: list[Any],
    story_id: str = "",
) -> str:
    """Return a story continuation string.

    Routes to OpenRouter when STORYLAB_PROVIDER=openrouter and
    OPENROUTER_API_KEY is set; falls back to the deterministic stub
    on any error so the endpoint never returns empty-handed.
    """
    provider = settings.STORYLAB_PROVIDER

    if provider == "openrouter":
        if not settings.OPENROUTER_API_KEY:
            logger.warning("STORYLAB_PROVIDER=openrouter but OPENROUTER_API_KEY is empty; using stub")
        else:
            try:
                return _call_openrouter(text, controls, state_json, summary, characters)
            except httpx.TimeoutException:
                logger.warning("OpenRouter request timed out; falling back to stub")
            except httpx.HTTPStatusError as exc:
                logger.warning("OpenRouter returned HTTP %s; falling back to stub", exc.response.status_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenRouter error (%s); falling back to stub", exc)

    return _generate_stub_text(story_id, controls)

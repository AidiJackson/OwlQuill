"""Service layer for RP Story Thread generation and context building."""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character import Character as CharacterModel
from app.models.rp_story import RPStoryThread, RPStoryTurn
from app.services.storylab_generator import generate_rp_reply

logger = logging.getLogger(__name__)

# Maximum turns to include verbatim before summarisation kicks in
_RECENT_TURNS_WINDOW = 8


def _auto_title(partner_starter: str) -> str:
    """Derive a short thread title from the first line of the partner starter."""
    first_line = partner_starter.split("\n")[0].strip().strip("|").strip()
    if len(first_line) > 80:
        first_line = first_line[:77] + "…"
    return first_line or "RP Story"


def _format_turn_for_context(turn: RPStoryTurn, char_name: str, partner_label: str) -> str:
    label = char_name if turn.author_type == "selected_character" else (partner_label or "Partner")
    return f"[{label}]: {turn.content}"


def build_thread_context(
    thread: RPStoryThread,
    turns: list[RPStoryTurn],
    char_name: str,
) -> tuple[str, str]:
    """Return (partner_reply, canon_summary) for generate_rp_reply().

    partner_reply — the most recent partner turn's content.
    canon_summary — formatted history of earlier turns + optional summary_memory.
    """
    partner_label = thread.partner_label or "Partner"

    # Identify the last partner turn as the immediate prompt
    partner_turns = [t for t in turns if t.author_type == "partner"]
    if not partner_turns:
        return "", ""
    latest_partner_turn = partner_turns[-1]
    partner_reply = latest_partner_turn.content

    # Build canon from everything except the last partner turn
    history_turns = [t for t in turns if t.id != latest_partner_turn.id]
    # Take at most _RECENT_TURNS_WINDOW turns from history
    if len(history_turns) > _RECENT_TURNS_WINDOW:
        history_turns = history_turns[-_RECENT_TURNS_WINDOW:]

    parts: list[str] = []
    if thread.summary_memory:
        parts.append(f"[Story so far]: {thread.summary_memory}")

    for turn in history_turns:
        parts.append(_format_turn_for_context(turn, char_name, partner_label))

    canon_summary = "\n\n".join(parts) if parts else ""
    return partner_reply, canon_summary


def generate_thread_reply(
    db: Session,
    thread: RPStoryThread,
    *,
    instructions: Optional[str] = None,
    response_length: str = "match",
    style_match: str = "soft",
    perspective: str = "third_person_limited",
    formatting: str = "plain",
    intensity: str = "standard",
    heat_level: str = "flame",
    style_archetype: Optional[str] = None,
    model_profile: str = "default",
) -> dict:
    """Generate the selected character's next reply for a thread.

    Returns a dict with reply text and diagnostics. Does NOT save to DB.
    """
    turns = (
        db.query(RPStoryTurn)
        .filter(RPStoryTurn.thread_id == thread.id)
        .order_by(RPStoryTurn.turn_index)
        .all()
    )

    if not any(t.author_type == "partner" for t in turns):
        raise ValueError("No partner turn found in thread — nothing to reply to.")

    # Resolve character context
    char_name = ""
    character_context = None
    if thread.selected_character_id:
        char = db.query(CharacterModel).filter(CharacterModel.id == thread.selected_character_id).first()
        if char:
            char_name = char.name or ""
            parts = []
            if char.name:
                parts.append(f"Name: {char.name}")
            if char.short_bio:
                parts.append(f"Bio: {char.short_bio}")
            elif char.long_bio:
                parts.append(f"Bio: {char.long_bio[:500]}")
            if char.role:
                parts.append(f"Role: {char.role}")
            character_context = "\n".join(parts) if parts else None

    partner_reply, canon_summary = build_thread_context(thread, turns, char_name)

    # Build thread-context header for instructions
    thread_header_parts = [
        f"RP Story Thread: {thread.title}",
    ]
    if thread.partner_label:
        thread_header_parts.append(f"Partner: {thread.partner_label}")
    if thread.partner_pov != "unknown":
        thread_header_parts.append(f"Partner POV: {thread.partner_pov} person")
    thread_header_parts.append(
        "The partner's turn is complete. Write only the selected character's next turn."
    )
    thread_header = "\n".join(thread_header_parts)
    combined_instructions = thread_header
    if instructions:
        combined_instructions += f"\n\nAdditional guidance: {instructions}"

    reply, model_used, generation_time_ms, pov_warnings, max_tokens_used, godmod_meta = generate_rp_reply(
        partner_reply=partner_reply,
        response_length=response_length,
        style_match=style_match,
        perspective=perspective,
        formatting=formatting,
        intensity=intensity,
        instructions=combined_instructions,
        character_context=character_context,
        canon_summary=canon_summary or None,
        character_name=char_name,
        model_profile=model_profile or "default",
        heat_level=heat_level,
        style_archetype=style_archetype or "cinematic_dark_romance",
        partner_character_name=thread.partner_label or "",
    )

    return {
        "reply": reply,
        "model_used": model_used,
        "generation_time_ms": generation_time_ms,
        "godmod_detected": godmod_meta.get("detected", False),
        "godmod_severity": godmod_meta.get("severity", "none"),
        "godmod_warnings": godmod_meta.get("warnings", []),
        "warnings": pov_warnings,
        "continuation_score": 0.0,
        "pacing_warnings": [],
        "style_warnings": [],
    }


def append_lightweight_summary(thread: RPStoryThread, turn: RPStoryTurn, char_name: str) -> None:
    """Append a one-line summary entry for a saved selected_character turn.

    Lightweight V1 — no LLM call, just a breadcrumb log.
    """
    partner_label = thread.partner_label or "Partner"
    entry = f"Turn {turn.turn_index}: {char_name or 'Character'} responded to {partner_label}."
    if thread.summary_memory:
        thread.summary_memory = thread.summary_memory + "\n" + entry
    else:
        thread.summary_memory = entry

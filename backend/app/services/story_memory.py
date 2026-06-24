"""Story Canon/Memory Engine v3 — canon tracking, injection, and inference enforcement for StoryLab.

Tracks hard canon facts, character states, relationships, open threads and
world rules across chapters. Injects structured memory into generation prompts
to prevent character drift, canon forgetting, and mechanic replacement.

Public API
----------
    EMPTY_CANON_MEMORY              -> dict template (do not mutate)
    seed_memory_from_story_creation(...)  -> dict
    build_canon_injection_block(memory)   -> str
    extract_and_merge_memory(...)         -> dict
    check_for_contradictions(text, memory) -> list[str]
"""

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── canonical empty schema ────────────────────────────────────────────────────

EMPTY_CANON_MEMORY: dict[str, Any] = {
    "canon": {
        "hard_truths": [],
        "world_rules": [],
        "forbidden_contradictions": [],
        "forbidden_inferences": [],
    },
    "characters": {},
    "relationships": [],
    "open_threads": [],
    "recent_events": [],
}


# ── memory seeding ────────────────────────────────────────────────────────────

def seed_memory_from_story_creation(
    title: str = "",
    genre: str = "",
    premise: str = "",
    characters: list[dict[str, Any]] | None = None,
    opening_prompt: str = "",
) -> dict[str, Any]:
    """Initialise canon memory from story creation inputs.

    Establishes initial hard truths and character identities so that the first
    chapter prompt already carries structured canon constraints.
    """
    memory = _deep_copy_empty()

    if premise and premise.strip():
        memory["canon"]["hard_truths"].append(f"Story premise: {premise.strip()}")

    for char in (characters or []):
        if not isinstance(char, dict):
            continue
        name = (char.get("name") or "").strip()
        if not name:
            continue

        entry: dict[str, list[str]] = {
            "identity": [],
            "current_status": ["alive"],
            "abilities_or_traits": [],
            "goals": [],
            "growth": [],
            "secrets": [],
        }

        # Identity facts
        for field, label in (
            ("role", "Role"),
            ("species", "Species"),
            ("personality", "Personality"),
            ("short_bio", "Bio"),
        ):
            val = char.get(field)
            if isinstance(val, str) and val.strip():
                entry["identity"].append(f"{label}: {val.strip()}")

        # Traits / abilities
        traits_raw = char.get("traits") or char.get("tags") or []
        if isinstance(traits_raw, str):
            traits_raw = [t.strip() for t in traits_raw.split(",") if t.strip()]
        if isinstance(traits_raw, list):
            entry["abilities_or_traits"] = [str(t).strip() for t in traits_raw[:6] if str(t).strip()]

        # Goals
        goals_raw = char.get("goals") or []
        if isinstance(goals_raw, str):
            goals_raw = [goals_raw.strip()]
        if isinstance(goals_raw, list):
            entry["goals"] = [str(g).strip() for g in goals_raw[:3] if str(g).strip()]

        memory["characters"][name] = entry
        memory["canon"]["hard_truths"].append(f"{name} is alive at story start.")
        if f"Do not kill or erase {name} unless the current user prompt explicitly instructs it." \
                not in memory["canon"]["forbidden_contradictions"]:
            memory["canon"]["forbidden_contradictions"].append(
                f"Do not kill or erase {name} unless the current user prompt explicitly instructs it."
            )
        # Explicit death-phrase forbidden list — uses shared helper for deduplication
        _auto_append_alive_forbidden(memory, name)
        # Disappearance / fake-death inference protection
        _auto_append_alive_inferences(memory, name)

    logger.info(
        "[STORY-MEMORY] Seeded from story creation | title=%r genre=%r "
        "hard_truths=%d characters=%d",
        title, genre,
        len(memory["canon"]["hard_truths"]),
        len(memory["characters"]),
    )
    return memory


# ── canon injection block ────────────────────────────────────────────────────

def build_canon_injection_block(memory: dict[str, Any]) -> str:
    """Build the STORY CANON block that is prepended to every generation prompt.

    Returns an empty string if memory is effectively empty so callers can
    skip the block without adding whitespace.
    """
    if not memory or not isinstance(memory, dict):
        return ""

    canon = memory.get("canon", {})
    hard_truths = canon.get("hard_truths", [])
    world_rules = canon.get("world_rules", [])
    forbidden = canon.get("forbidden_contradictions", [])
    forbidden_inferences = canon.get("forbidden_inferences", [])
    characters_mem = memory.get("characters", {})
    relationships = memory.get("relationships", [])
    open_threads = memory.get("open_threads", [])

    has_content = any([hard_truths, world_rules, forbidden, forbidden_inferences, characters_mem, relationships, open_threads])
    if not has_content:
        return ""

    sep = "═" * 55
    lines: list[str] = [
        sep,
        "STORY CANON — DO NOT CONTRADICT ANYTHING IN THIS BLOCK",
        sep,
        "Hard canon is absolute. Do not contradict it, reinterpret it, kill living "
        "characters, resurrect dead ones, or change parentage unless the user's current "
        "prompt explicitly instructs the change.",
    ]

    if hard_truths:
        lines.append("")
        lines.append("STORY CANON — MUST NOT CONTRADICT:")
        for t in hard_truths:
            lines.append(f"  • {t}")

    if world_rules:
        lines.append("")
        lines.append("WORLD / LORE RULES — MUST PRESERVE:")
        for r in world_rules:
            lines.append(f"  • {r}")

    if characters_mem and isinstance(characters_mem, dict):
        lines.append("")
        lines.append("CHARACTER MEMORY — MUST PRESERVE:")
        for char_name, char_data in characters_mem.items():
            if not isinstance(char_data, dict):
                continue
            lines.append(f"  [{char_name}]")
            field_labels = {
                "identity": "Identity",
                "current_status": "Current status",
                "abilities_or_traits": "Abilities/traits",
                "goals": "Goals",
                "growth": "Growth",
                "secrets": "Secrets",
            }
            for field, label in field_labels.items():
                vals = char_data.get(field, [])
                if not isinstance(vals, list):
                    continue
                items_str = "; ".join(str(v) for v in vals[:4] if str(v).strip())
                if items_str:
                    lines.append(f"    {label}: {items_str}")

    if relationships:
        lines.append("")
        lines.append("RELATIONSHIP STATE — MUST RESPECT:")
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            a = rel.get("a", "")
            b = rel.get("b", "")
            if not a or not b:
                continue
            parts: list[str] = []
            for field in ("status", "tension", "recent_change"):
                val = rel.get(field, "")
                if val:
                    parts.append(f"{field.replace('_', ' ')}: {val}")
            rel_str = f"  {a} ↔ {b}"
            if parts:
                rel_str += ": " + "; ".join(parts)
            lines.append(rel_str)

    if open_threads:
        lines.append("")
        lines.append("OPEN THREADS — CONTINUE OR DELIBERATELY DEFER (do not forget):")
        for thread in open_threads[:6]:
            lines.append(f"  • {thread}")

    if forbidden:
        lines.append("")
        lines.append("FORBIDDEN CONTRADICTIONS — NEVER DO THESE:")
        for fc in forbidden:
            lines.append(f"  ✗ {fc}")

    if forbidden_inferences:
        lines.append("")
        lines.append("FORBIDDEN INFERENCES — DO NOT IMPLY THESE (even without stating directly):")
        for fi in forbidden_inferences:
            lines.append(f"  ⚠ {fi}")

    lines.append("")
    lines.append("ANTI-DRIFT CONSTRAINTS (enforce strictly):")
    lines.append("  ✗ Do not kill or erase a living character unless the current user prompt explicitly does so.")
    lines.append("  ✗ Do not change a character's core nature, species, or unique supernatural mechanic without explicit instruction.")
    lines.append("  ✗ Do not replace unique mechanics with generic tropes (e.g. do not rewrite a supernatural effect as a standard transformation arc).")
    lines.append("  ✗ Do not contradict any hard truth listed above.")
    lines.append("  ✓ When uncertain, preserve existing canon.")

    lines.append(sep)

    return "\n".join(lines)


# ── contradiction detection ───────────────────────────────────────────────────

_DEATH_PHRASES = (
    "{name} died",
    "{name} was killed",
    "{name} is dead",
    "{name} had been killed",
    "{name}'s death",
    "death of {name}",
    "{name} perished",
    "{name} was murdered",
    "{name} was slain",
    "{name} was dead",
    "{name} had died",
    "{name} has died",
    "{name} is gone",
    "killed {name}",
    "{name} lay dead",
    "{name} lies dead",
)

_LATE_TITLE_PHRASES = (
    "the late {name}",
    "late {name}",
    "deceased {name}",
)

_PRONOUN_DEATH_PHRASES = (
    "his dead {role}",
    "her dead {role}",
    "their dead {role}",
    "his deceased {role}",
    "her deceased {role}",
    "their deceased {role}",
    "his late {role}",
    "her late {role}",
    "their late {role}",
)

_TRANSFORMATION_PHRASES = (
    "{name} transformed into a werewolf",
    "{name} became a werewolf",
    "{name} is becoming a werewolf",
    "{name}'s transformation",
    "{name} turned into a werewolf",
)

# ── v3: inference pattern sets ────────────────────────────────────────────────

_DISAPPEARANCE_PHRASES = (
    "{name} disappeared",
    "{name} vanished",
    "{name}'s disappearance",
    "{name} went missing",
    "{name} had vanished",
    "{name} had disappeared",
)

_FAKE_DEATH_NAME_PHRASES = (
    "{name} faked his death",
    "{name} faked her death",
    "{name} faked their death",
    "{name} is presumed dead",
    "{name} was presumed dead",
    "{name} presumed dead",
)

# Fired when any confirmed-alive character is present in memory.
_GENERAL_INFERENCE_PHRASES = (
    "letting the world believe him dead",
    "letting the world believe her dead",
    "letting the world believe them dead",
    "faked his death",
    "faked her death",
    "faked their death",
    "fake his death",
    "fake her death",
    "fake their death",
    "fake death",
    # Intentional-disappearance constructions ("disappeared to <purpose>"):
    "disappeared to protect",
    "disappeared to keep",
    "disappeared to save",
    "disappeared to hide",
    "disappeared to escape",
    "vanished to protect",
    "vanished to keep",
    "vanished to save",
)

# Root words used by the sentence-level co-occurrence check (v4).
_DISAPPEAR_ROOTS: frozenset[str] = frozenset({"disappear", "vanish"})

# Fired when a family relationship exists in memory.
_IDENTITY_TRANSFER_ROLE_PHRASES = (
    "becoming what your father is",
    "becoming what his father is",
    "becoming what her father is",
    "becoming what their father is",
    "becoming what your mother is",
    "becoming what his mother is",
    "becoming what her mother is",
    "becoming what their mother is",
    "becoming what your parent is",
)

_FAMILY_STATUS_WORDS = frozenset({"father", "mother", "parent", "family", "son", "daughter", "child"})


def check_for_contradictions(
    generated_text: str,
    memory: dict[str, Any],
) -> list[str]:
    """Scan generated text for obvious contradictions and forbidden inferences against canon.

    Returns a list of human-readable violation descriptions.
    Empty list means no obvious violations were detected.

    Surfaces checked:
    1. canon.hard_truths "X is alive" — death phrases, late-title phrases, disappearance,
       fake-death, pronoun-death patterns.
    2. characters[name]["current_status"] containing "alive" — same checks, deduplicated.
    3. General inference phrases (presumed-dead, fake-death, letting-world-believe-dead) —
       fired whenever any confirmed-alive character is in memory.
    4. Identity-transfer inferences — role-based ("becoming what your father is"), name-based
       ("becoming what {char} is"), and trait-noun-based ("becoming the Demon Wolf") — fired
       when family relationships or living characters with supernatural traits are present.
    """
    if not generated_text or not memory or not isinstance(memory, dict):
        return []

    contradictions: list[str] = []
    text_lower = generated_text.lower()
    characters_mem = memory.get("characters", {})
    relationships = memory.get("relationships", [])

    # ── Pre-scan: collect all confirmed-alive character names ─────────────────
    # Used by Surfaces 3 and 4 without re-iterating.
    _alive_char_names: set[str] = set()
    for _ht in memory.get("canon", {}).get("hard_truths", []):
        if " is alive" in _ht.lower():
            _nm = _ht.split(" is alive")[0].strip()
            if _nm and not _nm.lower().startswith("story premise:"):
                _alive_char_names.add(_nm)
    for _cn, _cd in characters_mem.items():
        if isinstance(_cd, dict):
            _sl = _cd.get("current_status", [])
            if isinstance(_sl, list) and any("alive" in str(_s).lower() for _s in _sl):
                _alive_char_names.add(_cn)

    def _check_alive_name(char_name_raw: str, source_label: str) -> None:
        """Fire death-phrase, late-title, and inference checks for a confirmed-alive character."""
        name_lower = char_name_raw.lower()
        for pattern in _DEATH_PHRASES:
            phrase = pattern.format(name=name_lower)
            if phrase in text_lower:
                contradictions.append(
                    f"Hard canon violated ({source_label}): '{char_name_raw} is alive'"
                    f" — generated text appears to kill them (matched: '{phrase}')"
                )
                return
        for pattern in _LATE_TITLE_PHRASES:
            phrase = pattern.format(name=name_lower)
            if phrase in text_lower:
                contradictions.append(
                    f"Hard canon violated ({source_label}): '{char_name_raw} is alive'"
                    f" — generated text uses death-title phrasing (matched: '{phrase}')"
                )
                return
        # v3: full-name disappearance exact phrases
        for pattern in _DISAPPEARANCE_PHRASES:
            phrase = pattern.format(name=name_lower)
            if phrase in text_lower:
                contradictions.append(
                    f"Forbidden inference ({source_label}): '{char_name_raw} is alive'"
                    f" — generated text implies disappearance (matched: '{phrase}')."
                    f" Absence must be framed as estrangement or lack of contact, not disappearance."
                )
                return
        # v3: fake-death / presumed-dead inferences
        for pattern in _FAKE_DEATH_NAME_PHRASES:
            phrase = pattern.format(name=name_lower)
            if phrase in text_lower:
                contradictions.append(
                    f"Forbidden inference ({source_label}): '{char_name_raw} is alive'"
                    f" — generated text implies fake death or presumed dead (matched: '{phrase}')"
                )
                return
        # v4: sentence-level co-occurrence — catches first-name-only usage like
        # "Angelo disappeared to protect you" where full name is not present.
        first_name = name_lower.split()[0]
        snippet = _sentence_cooccur_disappearance(first_name, text_lower)
        if snippet:
            contradictions.append(
                f"Forbidden inference ({source_label}): '{char_name_raw} is alive'"
                f" — first name co-occurs with disappearance verb in same sentence"
                f" (context: '…{snippet}…')."
                f" Absence must be framed as estrangement or distance, not disappearance."
            )
            return

    def _check_pronoun_patterns(char_name_raw: str) -> None:
        """Check pronoun+role death patterns (e.g. 'his dead father') when the
        character is stored as a parent/family role in relationships."""
        name_lower = char_name_raw.lower()
        family_roles: list[str] = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            a = str(rel.get("a", "")).lower()
            b = str(rel.get("b", "")).lower()
            status = str(rel.get("status", "")).lower()
            if name_lower in (a, b) and any(w in status for w in ("father", "mother", "parent", "family")):
                family_roles.extend(["father", "mother", "parent"])
        for role in set(family_roles):
            for pattern in _PRONOUN_DEATH_PHRASES:
                phrase = pattern.format(role=role)
                if phrase in text_lower:
                    contradictions.append(
                        f"Hard canon violated (pronoun pattern): '{char_name_raw} is alive'"
                        f" — generated text references them as dead via '{phrase}'"
                    )
                    return

    # ── Surface 1: hard_truths "X is alive" ──────────────────────────────────
    for ht in memory.get("canon", {}).get("hard_truths", []):
        ht_lower = ht.lower()
        if " is alive" not in ht_lower:
            continue
        char_name_raw = ht.split(" is alive")[0].strip()
        if char_name_raw.lower().startswith("story premise:"):
            continue
        _check_alive_name(char_name_raw, "hard_truths")
        _check_pronoun_patterns(char_name_raw)

    # ── Surface 2: characters[name]["current_status"] containing "alive" ─────
    already_checked_lower: set[str] = set()

    # Collect names already covered by hard_truths to avoid duplicate entries
    for ht in memory.get("canon", {}).get("hard_truths", []):
        if " is alive" in ht.lower():
            already_checked_lower.add(ht.lower().split(" is alive")[0].strip())

    for char_name, char_data in characters_mem.items():
        if not isinstance(char_data, dict):
            continue
        name_lower = char_name.lower()
        status_list = char_data.get("current_status", [])
        if not isinstance(status_list, list):
            continue
        is_alive = any("alive" in str(s).lower() for s in status_list)
        if not is_alive:
            continue
        if name_lower not in already_checked_lower:
            _check_alive_name(char_name, "character_status")
            _check_pronoun_patterns(char_name)

        # Character core-nature drift — check for generic transformation tropes
        traits = char_data.get("abilities_or_traits", [])
        for trait in traits:
            trait_lower = str(trait).lower()
            if any(kw in trait_lower for kw in ("echo", "supernatural effect", "echo-like")):
                for pattern in _TRANSFORMATION_PHRASES:
                    phrase = pattern.format(name=name_lower)
                    if phrase in text_lower:
                        contradictions.append(
                            f"Mechanic drift detected: {char_name} has trait '{trait}' "
                            f"but generated text suggests generic werewolf transformation"
                        )
                        break

    # Character core-nature drift for characters NOT in character_status loop
    for char_name, char_data in characters_mem.items():
        if not isinstance(char_data, dict):
            continue
        name_lower = char_name.lower()
        status_list = char_data.get("current_status", [])
        is_alive = isinstance(status_list, list) and any("alive" in str(s).lower() for s in status_list)
        if is_alive:
            continue
        traits = char_data.get("abilities_or_traits", [])
        for trait in traits:
            trait_lower = str(trait).lower()
            if any(kw in trait_lower for kw in ("echo", "supernatural effect", "echo-like")):
                for pattern in _TRANSFORMATION_PHRASES:
                    phrase = pattern.format(name=name_lower)
                    if phrase in text_lower:
                        contradictions.append(
                            f"Mechanic drift detected: {char_name} has trait '{trait}' "
                            f"but generated text suggests generic werewolf transformation"
                        )
                        break

    # ── Surface 3: general inference phrases (when any alive character present) ─
    if _alive_char_names:
        for phrase in _GENERAL_INFERENCE_PHRASES:
            if phrase in text_lower:
                contradictions.append(
                    f"Forbidden inference (general): '{phrase}' implies a living character"
                    f" disappeared, faked their death, or is presumed dead"
                )
                break  # one report per surface to avoid flooding

    # ── Surface 4: identity-transfer inferences ───────────────────────────────
    # 4a. Role-based — fires when any family relationship exists
    has_family_rel = any(
        isinstance(rel, dict)
        and any(w in str(rel.get("status", "")).lower() for w in _FAMILY_STATUS_WORDS)
        for rel in relationships
    )
    if has_family_rel:
        for phrase in _IDENTITY_TRANSFER_ROLE_PHRASES:
            if phrase in text_lower:
                contradictions.append(
                    f"Forbidden inference (identity transfer): '{phrase}'"
                    f" — do not imply a character is inheriting their parent's nature"
                    f" unless the current prompt explicitly instructs it"
                )
                break

    # 4b. Name-based — "becoming what {name} is" for any alive character
    for char_name in _alive_char_names:
        phrase = f"becoming what {char_name.lower()} is"
        if phrase in text_lower:
            contradictions.append(
                f"Forbidden inference (identity transfer): 'becoming what {char_name} is'"
                f" — do not imply identity inheritance unless explicitly instructed"
            )

    # 4c. Trait-noun-based — "becoming the {Noun}" matched against alive chars' trait nouns
    for char_name, char_data in characters_mem.items():
        if not isinstance(char_data, dict):
            continue
        status_list = char_data.get("current_status", [])
        is_alive = isinstance(status_list, list) and any("alive" in str(s).lower() for s in status_list)
        if not is_alive:
            continue
        traits = char_data.get("abilities_or_traits", [])
        for noun in _extract_trait_nouns(traits):
            phrase = f"becoming the {noun.lower()}"
            if phrase in text_lower:
                contradictions.append(
                    f"Forbidden inference (identity transfer): 'becoming the {noun}'"
                    f" — this implies inheriting '{char_name}'s supernatural identity;"
                    f" do not imply this unless explicitly instructed"
                )

    return contradictions


# ── LLM extraction (OpenRouter) ───────────────────────────────────────────────

_MEMORY_EXTRACT_SYSTEM = """\
You are a story canon memory extractor for an AI writing assistant.

Your task: read a chapter and extract structured memory updates as JSON.

Output ONLY valid JSON — no preamble, no explanation, no markdown code fences.

Use this exact schema (omit empty arrays):
{
  "new_hard_truths": ["<established canon fact>"],
  "new_world_rules": ["<world or lore rule revealed>"],
  "new_forbidden_inferences": ["<inference to forbid, e.g. 'Do not imply X disappeared'>"],
  "character_updates": {
    "<character_name>": {
      "identity": ["<identity fact>"],
      "current_status": ["<alive/injured/absent/present>"],
      "abilities_or_traits": ["<unique ability or trait>"],
      "goals": ["<goal revealed or pursued>"],
      "growth": ["<character change shown>"],
      "secrets": ["<secret revealed>"]
    }
  },
  "relationship_updates": [
    {
      "a": "<name A>",
      "b": "<name B>",
      "status": "<family/ally/enemy/romantic/complex>",
      "tension": "<none/low/moderate/high/critical>",
      "recent_change": "<what changed in this chapter>"
    }
  ],
  "new_open_threads": ["<unresolved plot thread>"],
  "recent_events": ["<key event, 1 sentence>"]
}

Rules:
- Only include fields with content — omit empty arrays.
- Be specific and factual. Do not speculate.
- Do not duplicate facts already in the provided memory.
- Preserve character names exactly as they appear.
- Focus on what is NEW or CHANGED in this chapter.\
"""


def _call_openrouter_memory_extract(
    chapter_text: str,
    existing_memory: dict[str, Any],
    chapter_number: int,
) -> dict[str, Any] | None:
    """Call OpenRouter to extract structured memory updates from a chapter.

    Returns parsed dict or None on any failure. Non-fatal by design.
    """
    mem_ctx_parts: list[str] = []

    hard_truths = existing_memory.get("canon", {}).get("hard_truths", [])
    if hard_truths:
        mem_ctx_parts.append(
            "EXISTING HARD TRUTHS:\n" + "\n".join(f"- {t}" for t in hard_truths[:12])
        )

    known_chars = list(existing_memory.get("characters", {}).keys())
    if known_chars:
        mem_ctx_parts.append("KNOWN CHARACTERS: " + ", ".join(known_chars[:10]))

    existing_threads = existing_memory.get("open_threads", [])
    if existing_threads:
        mem_ctx_parts.append(
            "EXISTING OPEN THREADS:\n" + "\n".join(f"- {t}" for t in existing_threads[:8])
        )

    mem_context = "\n\n".join(mem_ctx_parts) if mem_ctx_parts else "(No prior memory.)"

    user_content = (
        f"## Current memory (do not duplicate)\n{mem_context}\n\n"
        f"## Chapter {chapter_number}\n{chapter_text[:6000]}\n\n"
        "## Task\nExtract memory updates. Output ONLY JSON."
    )

    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": _effective_model(),
        "messages": [
            {"role": "system", "content": _MEMORY_EXTRACT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1200,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ficshon.com",
        "X-Title": "Ficshon StoryLab Memory",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        from app.services import storylab_telemetry
        storylab_telemetry.record("canon_extract", "openrouter", _effective_model(), data.get("usage") or {})
        raw = data["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw.rstrip())
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[STORY-MEMORY] Memory extract LLM call failed: %s", exc)
        return None


# ── main extraction + merge entry point ──────────────────────────────────────

def extract_and_merge_memory(
    existing_memory: dict[str, Any],
    chapter_text: str,
    chapter_number: int,
    story_id: str = "",
) -> dict[str, Any]:
    """Extract new memory facts from a chapter and merge into existing memory.

    For stub provider: preserves existing memory unchanged (no LLM call).
    For openrouter: calls LLM to extract structured updates, then merges.
    Merge is additive — never overwrites existing hard truths or character facts.
    """
    memory = _deep_copy_empty()
    _merge_existing_into(memory, existing_memory)

    provider = settings.STORYLAB_PROVIDER
    if provider != "openrouter" or not getattr(settings, "OPENROUTER_API_KEY", ""):
        logger.info(
            "[STORY-MEMORY] Memory preserved (no LLM extraction) | "
            "provider=%s story_id=%s chapter=%d",
            provider, story_id, chapter_number,
        )
        _log_memory_counts(memory, story_id, "loaded")
        return memory

    updates = _call_openrouter_memory_extract(chapter_text, memory, chapter_number)
    if updates and isinstance(updates, dict):
        _apply_memory_updates(memory, updates)

    logger.info(
        "[STORY-MEMORY] Memory updated after chapter %d | story_id=%s "
        "hard_truths=%d characters=%d relationships=%d open_threads=%d",
        chapter_number, story_id,
        len(memory["canon"]["hard_truths"]),
        len(memory["characters"]),
        len(memory["relationships"]),
        len(memory["open_threads"]),
    )
    return memory


# ── internal helpers ──────────────────────────────────────────────────────────

def _deep_copy_empty() -> dict[str, Any]:
    """Return a fresh empty memory dict."""
    return {
        "canon": {
            "hard_truths": [],
            "world_rules": [],
            "forbidden_contradictions": [],
            "forbidden_inferences": [],
        },
        "characters": {},
        "relationships": [],
        "open_threads": [],
        "recent_events": [],
    }


def _merge_existing_into(base: dict[str, Any], existing: dict[str, Any]) -> None:
    """Copy existing memory values into base, preserving all existing content."""
    if not isinstance(existing, dict):
        return

    existing_canon = existing.get("canon", {})
    if isinstance(existing_canon, dict):
        for key in ("hard_truths", "world_rules", "forbidden_contradictions", "forbidden_inferences"):
            vals = existing_canon.get(key, [])
            if isinstance(vals, list):
                base["canon"][key] = list(vals)

    existing_chars = existing.get("characters", {})
    if isinstance(existing_chars, dict):
        for name, data in existing_chars.items():
            if not isinstance(data, dict):
                continue
            base["characters"][name] = {
                "identity": list(data.get("identity", [])),
                "current_status": list(data.get("current_status", [])),
                "abilities_or_traits": list(data.get("abilities_or_traits", [])),
                "goals": list(data.get("goals", [])),
                "growth": list(data.get("growth", [])),
                "secrets": list(data.get("secrets", [])),
            }

    existing_rels = existing.get("relationships", [])
    if isinstance(existing_rels, list):
        base["relationships"] = list(existing_rels)

    existing_threads = existing.get("open_threads", [])
    if isinstance(existing_threads, list):
        base["open_threads"] = list(existing_threads)

    existing_events = existing.get("recent_events", [])
    if isinstance(existing_events, list):
        base["recent_events"] = list(existing_events[-5:])


def _apply_memory_updates(memory: dict[str, Any], updates: dict[str, Any]) -> None:
    """Apply LLM-extracted updates into memory — additive merge, no overwrites."""
    # Hard truths
    for ht in updates.get("new_hard_truths", []):
        ht_str = str(ht).strip()
        if ht_str and ht_str not in memory["canon"]["hard_truths"]:
            memory["canon"]["hard_truths"].append(ht_str)

    # World rules
    for wr in updates.get("new_world_rules", []):
        wr_str = str(wr).strip()
        if wr_str and wr_str not in memory["canon"]["world_rules"]:
            memory["canon"]["world_rules"].append(wr_str)

    # Forbidden inferences — append unique, never overwrite
    fi_list = memory["canon"].setdefault("forbidden_inferences", [])
    for fi in updates.get("new_forbidden_inferences", []):
        fi_str = str(fi).strip()
        if fi_str and fi_str not in fi_list:
            fi_list.append(fi_str)

    # Character updates — merge field-by-field, never overwrite
    for char_name, char_updates in updates.get("character_updates", {}).items():
        if not isinstance(char_updates, dict):
            continue
        char_name = str(char_name).strip()
        if not char_name:
            continue
        if char_name not in memory["characters"]:
            memory["characters"][char_name] = {
                "identity": [], "current_status": [], "abilities_or_traits": [],
                "goals": [], "growth": [], "secrets": [],
            }
        existing_char = memory["characters"][char_name]

        # current_status is replaced (it's the present state, not accumulated history).
        # PROTECTION: never allow the LLM memory extractor to downgrade an "alive"
        # character to a death-indicating status unless hard_truths already contain
        # a death fact for this character. This prevents bad chapters from poisoning
        # future generation by overwriting living status.
        new_status = char_updates.get("current_status", [])
        if new_status and isinstance(new_status, list):
            new_status_strs = [str(s).strip().lower() for s in new_status[:2] if str(s).strip()]
            _DEATH_STATUS_WORDS = {"dead", "deceased", "killed", "died", "perished", "slain", "murdered"}
            is_downgrade = any(
                any(dw in s for dw in _DEATH_STATUS_WORDS) for s in new_status_strs
            )
            was_alive = any("alive" in s for s in (str(v).lower() for v in existing_char.get("current_status", [])))
            if is_downgrade and was_alive:
                # Only allow if a death hard truth already exists for this character
                existing_hard_truths = memory.get("canon", {}).get("hard_truths", [])
                name_lower_chk = char_name.lower()
                death_already_in_canon = any(
                    name_lower_chk in ht.lower() and any(
                        dw in ht.lower() for dw in _DEATH_STATUS_WORDS
                    )
                    for ht in existing_hard_truths
                )
                if not death_already_in_canon:
                    logger.warning(
                        "[STORY-MEMORY-CONTRADICTION] LLM attempted to downgrade living "
                        "character '%s' status from %r to %r — rejected (no death hard truth found).",
                        char_name, existing_char.get("current_status"), new_status_strs,
                    )
                    # Keep existing alive status — do not overwrite
                else:
                    existing_char["current_status"] = new_status_strs
            else:
                existing_char["current_status"] = new_status_strs
                # Auto-append explicit forbidden phrases and inferences when status is set to alive
                if any("alive" in s for s in new_status_strs):
                    _auto_append_alive_forbidden(memory, char_name)
                    _auto_append_alive_inferences(memory, char_name)

        # All other fields append new unique values
        for field in ("identity", "abilities_or_traits", "goals", "growth", "secrets"):
            new_vals = char_updates.get(field, [])
            if not isinstance(new_vals, list):
                continue
            existing_list = existing_char.setdefault(field, [])
            for v in new_vals:
                v_str = str(v).strip()
                if v_str and v_str not in existing_list:
                    existing_list.append(v_str)
            # Cap at 8 items per field
            if len(existing_list) > 8:
                existing_char[field] = existing_list[-8:]

    # Relationships — upsert by (a, b) pair
    for new_rel in updates.get("relationship_updates", []):
        if not isinstance(new_rel, dict):
            continue
        a = str(new_rel.get("a", "")).strip()
        b = str(new_rel.get("b", "")).strip()
        if not a or not b:
            continue
        found = False
        for existing_rel in memory["relationships"]:
            if not isinstance(existing_rel, dict):
                continue
            ea, eb = existing_rel.get("a", ""), existing_rel.get("b", "")
            if (ea == a and eb == b) or (ea == b and eb == a):
                for field in ("status", "tension", "recent_change"):
                    val = str(new_rel.get(field, "")).strip()
                    if val:
                        existing_rel[field] = val
                found = True
                break
        if not found:
            memory["relationships"].append({
                "a": a,
                "b": b,
                "status": str(new_rel.get("status", "")).strip(),
                "tension": str(new_rel.get("tension", "")).strip(),
                "recent_change": str(new_rel.get("recent_change", "")).strip(),
            })

    # Open threads — append unique, cap at 10
    for thread in updates.get("new_open_threads", []):
        t_str = str(thread).strip()
        if t_str and t_str not in memory["open_threads"]:
            memory["open_threads"].append(t_str)
    if len(memory["open_threads"]) > 10:
        memory["open_threads"] = memory["open_threads"][-10:]

    # Recent events — append and cap at 5
    for event in updates.get("recent_events", []):
        e_str = str(event).strip()
        if e_str:
            memory["recent_events"].append(e_str)
    if len(memory["recent_events"]) > 5:
        memory["recent_events"] = memory["recent_events"][-5:]


def _auto_append_alive_forbidden(memory: dict[str, Any], char_name: str) -> None:
    """Add explicit death-phrase forbidden entries for a living character.

    Idempotent — entries are deduplicated before appending.
    Called both from seed_memory_from_story_creation and _apply_memory_updates
    whenever a character's current_status is confirmed as alive.
    """
    forbidden_list = memory.setdefault("canon", {}).setdefault("forbidden_contradictions", [])
    for death_phrase in (
        f"{char_name} is dead",
        f"{char_name} died",
        f"{char_name} was killed",
        f"the late {char_name}",
        f"{char_name} had died",
    ):
        entry = f'Never write: "{death_phrase}"'
        if entry not in forbidden_list:
            forbidden_list.append(entry)


def _auto_append_alive_inferences(memory: dict[str, Any], char_name: str) -> None:
    """Add forbidden-inference entries protecting a living character from disappearance implications.

    Idempotent — entries are deduplicated before appending.
    Called from seed_memory_from_story_creation and _apply_memory_updates whenever
    a character's current_status is confirmed as alive.
    """
    inference_list = memory.setdefault("canon", {}).setdefault("forbidden_inferences", [])
    for entry in (
        f"Do not imply {char_name} disappeared, vanished, or faked their death"
        f" unless the current prompt explicitly states this.",
        f"Absence of {char_name} from another character's life must be framed as"
        f" estrangement, secrecy, or distance — not disappearance.",
    ):
        if entry not in inference_list:
            inference_list.append(entry)


def _sentence_cooccur_disappearance(name_fragment: str, text_lower: str) -> str | None:
    """Return a short context snippet if name_fragment and a disappearance root verb
    co-occur within the same sentence boundary (period / ! / ? / ; / newline).

    Only fires for name fragments of ≥ 3 characters to avoid short false-positives.
    Catches constructions like "Angelo disappeared to protect you" where only the
    first name is used (full-name exact patterns would miss this).

    Returns None if no co-occurrence is detected.
    """
    if len(name_fragment) < 3:
        return None
    text_norm = text_lower.lower()
    name_re = re.compile(rf'\b{re.escape(name_fragment.lower())}\b')
    for sentence in re.split(r'(?<=[.!?;])\s+|\n+', text_norm):
        sentence = sentence.strip()
        if not sentence or not name_re.search(sentence):
            continue
        for root in _DISAPPEAR_ROOTS:
            if root in sentence:
                idx = sentence.find(root)
                start = max(0, idx - 25)
                end = min(len(sentence), idx + len(root) + 30)
                return sentence[start:end].strip()
    return None


def _extract_trait_nouns(traits: list[str]) -> list[str]:
    """Extract Title-Case noun phrases from trait strings for identity-transfer checks.

    Returns phrases like 'Demon Wolf' from 'Demon Wolf supernatural nature'.
    Used to detect 'becoming the {Noun}' inference patterns.
    """
    _SKIP = frozenset({"Role", "Species", "Identity", "Personality", "Trait", "Traits",
                       "Bio", "Nature", "Effect", "Type", "Form"})
    nouns: list[str] = []
    for trait in traits:
        for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', trait):
            phrase = m.group(1)
            if phrase not in _SKIP and len(phrase) > 3:
                nouns.append(phrase)
    return nouns


def _log_memory_counts(memory: dict[str, Any], story_id: str, action: str) -> None:
    logger.info(
        "[STORY-MEMORY] %s | story_id=%s hard_truths=%d characters=%d "
        "relationships=%d open_threads=%d",
        action, story_id,
        len(memory.get("canon", {}).get("hard_truths", [])),
        len(memory.get("characters", {})),
        len(memory.get("relationships", [])),
        len(memory.get("open_threads", [])),
    )


def _effective_model() -> str:
    """Return the effective OpenRouter model slug (borrows from storylab_generator)."""
    from app.services.storylab_generator import _EFFECTIVE_STORYLAB_MODEL
    return _EFFECTIVE_STORYLAB_MODEL

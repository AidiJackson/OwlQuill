"""Godmod Validator — Output Gate for RP Reply / StoryLab selected-character generation.

Detects when generated text authors content for the PARTNER character instead of the
selected character:
  • partner quoted dialogue
  • partner attributed speech (name or pronoun + speech verb)
  • partner consent / permission / decision
  • partner climax / orgasm
  • partner inner thoughts / emotional conclusions
  • partner major scene-moving actions (name-anchored only)

Severity levels
---------------
hard   — clear violation; triggers retry in generate_rp_reply and metadata flag on output
soft   — single ambiguous attribution that may be the selected character; no retry, logged only
none   — no violations detected

Minimal ALLOWED partner reactions (never flagged):
  breath caught / didn't pull away / stayed silent / shifted slightly /
  pulse quickened / physical presence described
"""
from __future__ import annotations

import re
from typing import Any

from app.services._rp_constants import _INNER_STATE_VERBS, _SPEECH_VERBS

# ── Pronoun-based patterns ─────────────────────────────────────────────────────

# "[quote]" pronoun speech-verb
_PRONOUN_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]{0,40}?\b(she|he|they)\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)
_HE_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]{0,40}?\bhe\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)
_SHE_DIALOGUE_RE = re.compile(
    r'"[^"]{3,}"[^"]{0,40}?\bshe\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)

# Bare speech verb (no quote): pronoun + speech verb
_BARE_SPEECH_RE = re.compile(
    r'\b(she|he|they)\s+(?:' + _SPEECH_VERBS + r')\b',
    re.IGNORECASE,
)

# Partner consent / agency verbs
_CONSENT_VERB_RE = re.compile(
    r'\b(she|he|they)\s+(?:'
    r'consented|surrendered|gave\s+in|gave\s+herself|gave\s+himself|gave\s+themselves|'
    r'let\s+(?:him|her|them|me)|allowed\s+(?:him|her|them|me)|'
    r'permitted\s+(?:him|her|them|me)|welcomed\s+(?:him|her|them)|'
    r'accepted\s+(?:him|her|them|me)|chose\s+(?:him|her|them)\b'
    r')\b',
    re.IGNORECASE,
)

# Quoted consent phrases
_QUOTED_CONSENT_RE = re.compile(
    r'"[^"]{0,120}(?:'
    r"I'?m\s+ready|I'?m\s+all\s+in|I\s+want\s+this|"
    r"don'?t\s+stop|yes,?\s*please|take\s+me|I\s+choose\s+you|"
    r"I\s+need\s+(?:you|this)|make\s+me\s+yours|I\s+surrender|"
    r"I\s+give\s+(?:in|up|myself)|you\s+can\s+have\s+me|I'?m\s+yours"
    r')[^"]{0,120}"',
    re.IGNORECASE,
)

# Inner emotional state verbs
_INNER_STATE_RE = re.compile(
    r'\b(she|he|they)\s+(?:' + _INNER_STATE_VERBS + r')\b',
    re.IGNORECASE,
)

# Climax / orgasm — pronoun-based
# Careful to avoid false matches: "she came from across the room" should NOT fire.
_CLIMAX_RE = re.compile(
    r'\b(she|he|they)\s+(?:'
    r'came(?!\s+(?:from|with|across|around|back|before|between|down|in|into|out|over|through|to\b|together|toward|up))|'
    r'climaxed|orgasmed|came\s+(?:undone|apart|hard)|fell\s+apart\s+(?:around|beneath|under|above|for)'
    r')\b',
    re.IGNORECASE,
)

_CLIMAX_POSSESSIVE_RE = re.compile(
    r'\b(?:her|his|their)\s+(?:orgasm|climax)\b',
    re.IGNORECASE,
)

# ── Minimal allowed reaction patterns (whitelist — never flagged) ─────────────

_MINIMAL_REACTION_RES: list[re.Pattern] = [
    re.compile(r"\b(?:breath|breathing)\s+(?:caught|hitched|quickened|came\s+faster)\b", re.IGNORECASE),
    re.compile(r"\b(?:didn'?t|did\s+not|hadn'?t|has?n'?t)\s+(?:pull|move|step|look|turn|back|flinch)\s*away\b", re.IGNORECASE),
    re.compile(r"\bstayed?\s+(?:silent|still|close|where\s+(?:she|he|they)\s+was)\b", re.IGNORECASE),
    re.compile(r"\bshifted?\s+(?:slightly|closer|a\s+little|almost\s+imperceptibly)\b", re.IGNORECASE),
    re.compile(r"\bpulse\s+(?:quickened|raced|spiked|jumped|skipped)\b", re.IGNORECASE),
    re.compile(r"\b(?:heart|pulse)\s+(?:beat|was\s+|)?(?:faster|quickened|raced)\b", re.IGNORECASE),
    re.compile(r"\b(?:did\s+not|didn'?t)\s+(?:respond|move|speak|say|answer)\b", re.IGNORECASE),
    re.compile(r"\b(?:presence|stillness|silence)\b", re.IGNORECASE),
]


def _is_minimal_reaction(text_fragment: str) -> bool:
    """Return True if the text fragment is a minimal allowed partner reaction."""
    return any(p.search(text_fragment) for p in _MINIMAL_REACTION_RES)


def _excerpt(text: str, match: re.Match, pad: int = 50) -> str:
    """Return a short excerpt centred on a regex match, for UI display."""
    start = max(0, match.start() - pad)
    end = min(len(text), match.end() + pad)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet[:150]


def _name_pattern(name: str, suffix: str) -> re.Pattern:
    """Build a case-insensitive word-boundary pattern for a character name with a suffix regex."""
    return re.compile(r'\b' + re.escape(name) + r'\b' + suffix, re.IGNORECASE)


# ── Main detector ──────────────────────────────────────────────────────────────

def detect_godmod_violations(
    text: str,
    selected_character_name: str | None = None,
    partner_character_name: str | None = None,
    selected_pronouns: list[str] | None = None,
    partner_pronouns: list[str] | None = None,
) -> dict[str, Any]:
    """Detect godmod violations in a generated RP reply.

    Parameters
    ----------
    text                    : generated reply text to validate
    selected_character_name : name of the SC writing the reply (for exclusion)
    partner_character_name  : name of the partner character (for name-anchored detection)
    selected_pronouns       : pronouns used for the SC (e.g. ["he", "him"])
    partner_pronouns        : pronouns used for the partner (e.g. ["she", "her"])

    Returns
    -------
    {
      "has_violation"         : bool
      "severity"              : "none" | "soft" | "hard"
      "violations"            : [{"type": str, "excerpt": str, "reason": str}, ...]
      "partner_dialogue_count": int
      "partner_decision_count": int
      "partner_inner_state_count": int
      "partner_major_action_count": int
    }
    """
    violations: list[dict[str, str]] = []

    partner_dialogue_count = 0
    partner_decision_count = 0
    partner_inner_state_count = 0
    partner_major_action_count = 0

    selected_name_lower = selected_character_name.strip().lower() if selected_character_name else ""
    partner_name_lower = partner_character_name.strip().lower() if partner_character_name else ""

    sel_pronouns_lower = {p.lower() for p in (selected_pronouns or [])}
    par_pronouns_lower = {p.lower() for p in (partner_pronouns or [])}

    # ── 1. Name-anchored detection ─────────────────────────────────────────────
    # When partner name is known, any attribution to that name is a hard violation.

    if partner_name_lower:
        _name = partner_character_name  # non-None here

        # a. Partner name + speech verb (with or without preceding quote)
        _named_speech_re = _name_pattern(
            _name,
            r'[^"]{0,40}(?:' + _SPEECH_VERBS + r')\b'
        )
        for m in _named_speech_re.finditer(text):
            violations.append({
                "type": "partner_attributed_speech",
                "excerpt": _excerpt(text, m),
                "reason": f"{_name} attributed speech (name + speech verb)",
            })
            partner_dialogue_count += 1

        # b. Quote attributed directly to partner name after closing quote
        _quote_named_re = re.compile(
            r'"[^"]{3,}"[^"]{0,40}\b' + re.escape(_name) + r'\b',
            re.IGNORECASE,
        )
        for m in _quote_named_re.finditer(text):
            # Avoid double-counting with (a)
            if not any(v["excerpt"] == _excerpt(text, m) for v in violations):
                violations.append({
                    "type": "partner_dialogue",
                    "excerpt": _excerpt(text, m),
                    "reason": f"Quoted dialogue attributed to {_name}",
                })
                partner_dialogue_count += 1

        # c. Partner name: "[Name]: quote" tagging format
        _tagged_re = re.compile(
            r'\b' + re.escape(_name) + r'\s*:\s*"[^"]{3,}"',
            re.IGNORECASE,
        )
        for m in _tagged_re.finditer(text):
            violations.append({
                "type": "partner_dialogue",
                "excerpt": _excerpt(text, m),
                "reason": f"Tagged dialogue line for {_name}",
            })
            partner_dialogue_count += 1

        # d. Partner name + consent verb
        _named_consent_re = _name_pattern(
            _name,
            r'\s+(?:consented|surrendered|gave\s+in|gave\s+herself|gave\s+himself|'
            r'gave\s+themselves|let\s+(?:him|her|them|me)|allowed\s+(?:him|her|them|me)|'
            r'permitted\s+(?:him|her|them)|chose\s+(?:him|her|them))\b'
        )
        for m in _named_consent_re.finditer(text):
            violations.append({
                "type": "partner_consent",
                "excerpt": _excerpt(text, m),
                "reason": f"{_name} gives consent/makes decision",
            })
            partner_decision_count += 1

        # e. Partner name + climax verb
        _named_climax_re = _name_pattern(
            _name,
            r'\s+(?:came(?!\s+(?:from|across|back|down|in|into|out|over|through|to\b|toward|up))|'
            r'climaxed|orgasmed|came\s+(?:undone|apart|hard))\b'
        )
        for m in _named_climax_re.finditer(text):
            violations.append({
                "type": "partner_climax",
                "excerpt": _excerpt(text, m),
                "reason": f"{_name} climax/orgasm authored",
            })
            partner_decision_count += 1

        # f. Partner name + inner state verb
        _named_inner_re = _name_pattern(
            _name,
            r'\s+(?:' + _INNER_STATE_VERBS + r')\b'
        )
        for m in _named_inner_re.finditer(text):
            violations.append({
                "type": "partner_inner_state",
                "excerpt": _excerpt(text, m),
                "reason": f"{_name} inner thoughts/emotional state authored",
            })
            partner_inner_state_count += 1

        # g. Partner name + major scene-moving action
        _MAJOR_ACTION_VERBS = (
            r"reached|grabbed|seized|pulled|pushed|stepped|moved|approached|turned\s+to|"
            r"kissed|pressed\s+(?:her|his|their|herself|himself)|"
            r"undressed|removed|stripped|shed|slipped\s+off|"
            r"took\s+(?:him|her|them)|drew\s+(?:him|her|them)\b"
        )
        _named_action_re = _name_pattern(_name, r'\s+(?:' + _MAJOR_ACTION_VERBS + r')\b')
        for m in _named_action_re.finditer(text):
            violations.append({
                "type": "partner_major_action",
                "excerpt": _excerpt(text, m),
                "reason": f"{_name} makes major scene-moving action",
            })
            partner_major_action_count += 1

    # ── 2. Pronoun-based detection ─────────────────────────────────────────────
    # More conservative thresholds to avoid false positives when selected character
    # is gendered and their own speech uses the same pronoun.

    # Exclude text near the selected character's name from pronoun analysis.
    # Simple approach: collect spans near selected name and skip matches that overlap.
    selected_name_spans: list[tuple[int, int]] = []
    if selected_name_lower:
        for m in re.finditer(r'\b' + re.escape(selected_name_lower) + r'\b', text, re.IGNORECASE):
            # Buffer of ±80 chars around the selected character's name
            selected_name_spans.append((max(0, m.start() - 80), min(len(text), m.end() + 80)))

    def _near_selected_name(match_start: int, match_end: int) -> bool:
        return any(s <= match_start <= e or s <= match_end <= e
                   for s, e in selected_name_spans)

    # a. Quoted dialogue: pronoun + speech verb
    he_matches = list(_HE_DIALOGUE_RE.finditer(text))
    she_matches = list(_SHE_DIALOGUE_RE.finditer(text))
    all_dialogue_matches = list(_PRONOUN_DIALOGUE_RE.finditer(text))

    # Cross-gender = both he-attributed AND she-attributed → strong two-character signal
    has_he_dialogue = any(not _near_selected_name(m.start(), m.end()) for m in he_matches)
    has_she_dialogue = any(not _near_selected_name(m.start(), m.end()) for m in she_matches)
    cross_gender_dialogue = has_he_dialogue and has_she_dialogue

    if cross_gender_dialogue:
        # Find the first match from each gender for the excerpt
        first_he = next((m for m in he_matches if not _near_selected_name(m.start(), m.end())), None)
        first_she = next((m for m in she_matches if not _near_selected_name(m.start(), m.end())), None)
        ref_match = first_he or first_she
        if ref_match:
            violations.append({
                "type": "partner_dialogue",
                "excerpt": _excerpt(text, ref_match),
                "reason": "Cross-gender dialogue: both he-attributed and she-attributed speech present",
            })
            partner_dialogue_count += 2
    else:
        # Non-cross-gender: count unambiguous attributed lines
        non_selected_dialogue = [
            m for m in all_dialogue_matches
            if not _near_selected_name(m.start(), m.end())
        ]

        # Determine which pronoun lines belong to SC vs partner
        # If we know SC pronoun, single line matching SC pronoun is soft (their own speech).
        # Two or more attributed lines → hard (both characters likely written).
        if len(non_selected_dialogue) >= 2:
            partner_dialogue_count += len(non_selected_dialogue)
            violations.append({
                "type": "partner_dialogue",
                "excerpt": _excerpt(text, non_selected_dialogue[0]),
                "reason": f"Multiple attributed dialogue lines ({len(non_selected_dialogue)}) — partner likely written",
            })
        elif len(non_selected_dialogue) == 1:
            m = non_selected_dialogue[0]
            matched_pronoun = (m.group(1) or "").lower()
            # Single attributed line matching a confirmed partner pronoun → hard
            if par_pronouns_lower and matched_pronoun in par_pronouns_lower:
                if not sel_pronouns_lower or matched_pronoun not in sel_pronouns_lower:
                    partner_dialogue_count += 1
                    violations.append({
                        "type": "partner_dialogue",
                        "excerpt": _excerpt(text, m),
                        "reason": (
                            f"Partner pronoun '{matched_pronoun}' attributed dialogue — "
                            "partner pronoun differs from selected character"
                        ),
                    })
                # else: same pronoun, single line — soft only (handled below)
            # Single ambiguous line with no pronoun hint: soft (handled in severity)

    # b. Partner consent (pronoun-based)
    for m in _CONSENT_VERB_RE.finditer(text):
        if not _near_selected_name(m.start(), m.end()):
            matched_pronoun = (m.group(1) or "").lower()
            # Skip if this matches the selected character's known pronoun (e.g., SC letting partner in)
            # but only if we KNOW the SC pronoun; otherwise flag it
            if sel_pronouns_lower and matched_pronoun in sel_pronouns_lower and not par_pronouns_lower:
                continue
            if not _is_minimal_reaction(text[max(0, m.start() - 30):m.end() + 30]):
                violations.append({
                    "type": "partner_consent",
                    "excerpt": _excerpt(text, m),
                    "reason": "Partner consent / agency authored",
                })
                partner_decision_count += 1

    # c. Quoted consent phrases
    for m in _QUOTED_CONSENT_RE.finditer(text):
        violations.append({
            "type": "partner_consent",
            "excerpt": _excerpt(text, m),
            "reason": "Partner speaks a consent/decision phrase",
        })
        partner_decision_count += 1

    # d. Partner climax (pronoun-based)
    for m in _CLIMAX_RE.finditer(text):
        if not _near_selected_name(m.start(), m.end()):
            matched_pronoun = (m.group(1) or "").lower()
            # If we know SC pronoun and this matches SC, skip (SC can climax — that's fine)
            if sel_pronouns_lower and matched_pronoun in sel_pronouns_lower:
                if not par_pronouns_lower or matched_pronoun not in par_pronouns_lower:
                    continue
            violations.append({
                "type": "partner_climax",
                "excerpt": _excerpt(text, m),
                "reason": "Partner climax / orgasm authored",
            })
            partner_decision_count += 1

    for m in _CLIMAX_POSSESSIVE_RE.finditer(text):
        if not _near_selected_name(m.start(), m.end()):
            violations.append({
                "type": "partner_climax",
                "excerpt": _excerpt(text, m),
                "reason": "Partner climax/orgasm referenced possessively",
            })
            partner_decision_count += 1

    # e. Partner inner state (pronoun-based) — requires 3+ matches for hard
    inner_matches = [
        m for m in _INNER_STATE_RE.finditer(text)
        if not _near_selected_name(m.start(), m.end())
        and not _is_minimal_reaction(text[max(0, m.start() - 30):m.end() + 30])
    ]
    partner_inner_state_count = len(inner_matches)
    if partner_inner_state_count >= 3:
        violations.append({
            "type": "partner_inner_state",
            "excerpt": _excerpt(text, inner_matches[0]),
            "reason": f"Dense partner inner-state narration ({partner_inner_state_count} instances)",
        })
    elif partner_inner_state_count >= 1 and not partner_name_lower:
        # Soft: single/double inner state without name anchor — could be SC
        pass

    # ── 3. Determine severity ──────────────────────────────────────────────────

    # Hard violation types — any of these → severity = "hard"
    HARD_TYPES = {"partner_dialogue", "partner_consent", "partner_climax",
                  "partner_inner_state", "partner_attributed_speech",
                  "partner_major_action"}

    hard_violations = [v for v in violations if v["type"] in HARD_TYPES]
    soft_violations = [v for v in violations if v["type"] not in HARD_TYPES]

    # Soft-only: a single unresolved dialogue line that could be SC's own speech
    # (not cross-gender, not partner-pronoun confirmed, no name anchor)
    soft_only_ambiguous = False
    if not hard_violations and not partner_name_lower:
        non_sel = [
            m for m in all_dialogue_matches
            if not _near_selected_name(m.start(), m.end())
        ]
        if len(non_sel) == 1:
            soft_only_ambiguous = True
            m0 = non_sel[0]
            soft_violations.append({
                "type": "ambiguous_attribution",
                "excerpt": _excerpt(text, m0),
                "reason": "Single attributed dialogue line — may be selected character's own speech",
            })

    if hard_violations:
        severity = "hard"
    elif soft_violations or soft_only_ambiguous:
        severity = "soft"
    else:
        severity = "none"

    all_violations = hard_violations + soft_violations

    return {
        "has_violation": severity != "none",
        "severity": severity,
        "violations": all_violations,
        "partner_dialogue_count": partner_dialogue_count,
        "partner_decision_count": partner_decision_count,
        "partner_inner_state_count": partner_inner_state_count,
        "partner_major_action_count": partner_major_action_count,
    }

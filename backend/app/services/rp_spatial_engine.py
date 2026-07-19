"""RP Spatial Engine — physical/tactile continuity tracking for RP scenes.

Maintains a lightweight snapshot of physical state so the model cannot
teleport hands, bodies, or clothing between turns.

This is NOT a censorship layer.
Explicit physical continuity improves the quality and coherence of
intimate and explicit RP scenes.

Provides
--------
detect_spatial_state(text)          — extract current physical scene state
build_spatial_continuity_block(state)  — build a high-priority prompt injection block

Positions tracked (from scene text):
  wall_pin, floor, lap, kneeling, standing, sitting,
  oral (on knees before / kneeling between), intercourse, pressed_against

Clothing states: on / open / off  per garment type

Active contact: hands, mouth, hips tracked per body region

Dominance state: dominant / submissive / contested / neutral

Explicit stage: mirrors the scene stage for spatial/tactile context
"""
import re

# ── position detection ────────────────────────────────────────────────────────

_POSITION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("intercourse", re.compile(
        r'\b(?:inside\s+(?:her|him|them)|thrust(?:ed|ing)?|penetrat|rode|riding|'
        r'hips\s+(?:moving|rocking|snapping)|drove\s+(?:into|deeper)|'
        r'(?:cock|length)\s+(?:inside|deep|buried))\b',
        re.IGNORECASE,
    )),
    ("oral", re.compile(
        r'\b(?:went\s+down\s+on|mouth\s+on\s+(?:her|his|their)|'
        r'on\s+(?:her|his|their)\s+knees\s+(?:before|between)|'
        r'kneeling\s+between|tongue\s+between|face\s+between|'
        r'knelt\s+(?:between|before)\b)\b',
        re.IGNORECASE,
    )),
    ("floor", re.compile(
        r'\b(?:on\s+the\s+floor|against\s+the\s+floor|pulled\s+(?:her|him|them)\s+to\s+the\s+floor|'
        r'flat\s+on\s+(?:the\s+floor|their\s+back)|'
        r'lay(?:ing)?\s+on\s+the\s+(?:floor|ground))\b',
        re.IGNORECASE,
    )),
    ("lap", re.compile(
        r'\b(?:(?:sat|sitting|climbed|settled|pulled\s+(?:her|him|them))\s+(?:on|onto|across|into)\s+'
        r'(?:his|her|their)\s+lap|straddl(?:ed|ing)|on\s+(?:his|her|their)\s+lap)\b',
        re.IGNORECASE,
    )),
    ("kneeling", re.compile(
        r'\b(?:knelt|kneeling|on\s+(?:her|his|their)\s+knees|'
        r'dropped\s+to\s+(?:her|his|their)\s+knees)\b',
        re.IGNORECASE,
    )),
    ("wall_pin", re.compile(
        r'\b(?:pinned\s+(?:her|him|them)?\s*(?:to|against)\s+the\s+wall|'
        r'pressed\s+(?:her|him|them)?\s*(?:to|against)\s+the\s+wall|'
        r'back\s+(?:to|against)\s+the\s+wall|'
        r'wall\s+(?:behind|at\s+(?:her|his|their))\s+back|'
        r'caged\s+(?:her|him|them)\s+against)\b',
        re.IGNORECASE,
    )),
    ("pressed_against", re.compile(
        r'\b(?:pressed\s+(?:hard|close|tight|up|together)\s+against|'
        r'bodies\s+(?:pressed|flush|against)|against\s+(?:him|her|them)|'
        r'hip[s]?\s+against|chest\s+against|back\s+against)\b',
        re.IGNORECASE,
    )),
    ("sitting", re.compile(
        r'\b(?:sat|sitting|seated|perched|settled)\b',
        re.IGNORECASE,
    )),
    ("standing", re.compile(
        r'\b(?:stood|standing|risen|stepped|walked)\b',
        re.IGNORECASE,
    )),
]


def _detect_position(text: str) -> str:
    """Return the most advanced physical position detected in text."""
    for position, pattern in _POSITION_PATTERNS:
        if pattern.search(text):
            return position
    return "neutral"


# ── clothing state detection ──────────────────────────────────────────────────

def _detect_clothing_state(text: str) -> dict[str, str]:
    """Return clothing states for each tracked garment: 'on' | 'open' | 'off'."""
    garments = {
        "shirt": "on",
        "pants": "on",
        "underwear": "on",
        "bra": "on",
        "dress": "on",
    }

    # OFF patterns
    off_patterns = {
        "shirt": re.compile(
            r'\b(?:shirt\s+(?:off|gone|removed|on\s+the\s+floor|discarded)|'
            r'bare\s+(?:chest|torso|shoulders|back)|stripped|shirtless|no\s+shirt)\b',
            re.IGNORECASE,
        ),
        "pants": re.compile(
            r'\b(?:pants\s+(?:off|gone|removed|around|dropped|at\s+(?:their|her|his)\s+(?:ankles|feet))|'
            r'bare\s+(?:legs|thighs|hips)|no\s+pants|stripped\s+(?:her|him|them)\s+of)\b',
            re.IGNORECASE,
        ),
        "underwear": re.compile(
            r'\b(?:underwear\s+(?:off|gone|removed|aside)|'
            r'panties?\s+(?:off|gone|aside|slipped|pulled)|'
            r'boxers?\s+(?:off|gone|removed|around)|naked|bare\s+below)\b',
            re.IGNORECASE,
        ),
        "bra": re.compile(
            r'\b(?:bra\s+(?:off|gone|removed|unhooked|discarded|clasp\s+undone)|'
            r'unhooked\s+(?:her\s+)?bra|clasp\s+(?:undone|open|free))\b',
            re.IGNORECASE,
        ),
        "dress": re.compile(
            r'\b(?:dress\s+(?:off|gone|removed|pooled|slipped|fallen)|'
            r'pulled\s+(?:her\s+)?dress\s+(?:off|up\s+and\s+off|over))\b',
            re.IGNORECASE,
        ),
    }

    # OPEN patterns
    open_patterns = {
        "shirt": re.compile(
            r'\b(?:shirt\s+(?:open|unbuttoned|hanging\s+open|pushed\s+(?:off|open|aside))|'
            r'unbuttoned|shirt\s+pulled\s+open)\b',
            re.IGNORECASE,
        ),
        "pants": re.compile(
            r'\b(?:pants\s+(?:open|unbuttoned|zipper|unzipped|pushed\s+down)|'
            r'jeans?\s+(?:open|unbuttoned|around\s+(?:his|her|their)\s+hips))\b',
            re.IGNORECASE,
        ),
        "dress": re.compile(
            r'\b(?:dress\s+(?:open|pushed\s+up|hiked|bunched)|'
            r'hem\s+(?:pushed|pulled|hiked)\s+(?:up|aside))\b',
            re.IGNORECASE,
        ),
    }

    for garment, pattern in off_patterns.items():
        if pattern.search(text):
            garments[garment] = "off"
        elif garment in open_patterns and open_patterns[garment].search(text):
            garments[garment] = "open"

    # Open checks only apply if garment wasn't already set to "off"
    for garment, pattern in open_patterns.items():
        if garments.get(garment) == "on" and pattern.search(text):
            garments[garment] = "open"

    return garments


# ── active contact detection ──────────────────────────────────────────────────

_CONTACT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("hands_on_body", re.compile(
        r'\b(?:hands?\s+(?:on|over|against|gripping|cupping|wrapped\s+around)|'
        r'fingers?\s+(?:on|at|in|around|tracing|pressed\s+to)|'
        r'palm\s+(?:against|flat\s+on|on))\b',
        re.IGNORECASE,
    )),
    ("mouth_on_body", re.compile(
        r'\b(?:mouth\s+on|lips\s+(?:on|against|at|to|pressed\s+to)|'
        r'kissed|breath\s+(?:on|against)|tongue\s+(?:on|against|along|inside))\b',
        re.IGNORECASE,
    )),
    ("hips_contact", re.compile(
        r'\b(?:hip[s]?\s+(?:against|grinding|pressing)|'
        r'grind(?:ed|ing)?|thigh\s+between|pressed\s+against)\b',
        re.IGNORECASE,
    )),
    ("body_to_body", re.compile(
        r'\b(?:bodies?\s+(?:pressed|against|flush|tangled)|chest\s+(?:to|against)|'
        r'skin\s+(?:against|on|to)\s+skin|pressed\s+together)\b',
        re.IGNORECASE,
    )),
]


def _detect_active_contact(text: str) -> list[str]:
    """Return list of active contact types detected in text."""
    return [name for name, pattern in _CONTACT_PATTERNS if pattern.search(text)]


# ── dominance state detection ─────────────────────────────────────────────────

_DOMINANT_SIGNALS: re.Pattern = re.compile(
    r'\b(?:pinned|commanded|ordered|pushed|held\s+(?:her|him|them)\s+(?:down|still|against)|'
    r'took\s+control|forced|dominant|dominan(?:ce|t)|you\'re\s+mine|commanded)\b',
    re.IGNORECASE,
)
_SUBMISSIVE_SIGNALS: re.Pattern = re.compile(
    r'\b(?:submitted|obeyed|let\s+(?:him|her|them)|gave\s+in|surrendered|'
    r'submission|submissive|on\s+(?:her|his|their)\s+knees\s+before|'
    r'beneath|under\s+(?:him|her|them))\b',
    re.IGNORECASE,
)


def _detect_dominance(text: str) -> str:
    dom = bool(_DOMINANT_SIGNALS.search(text))
    sub = bool(_SUBMISSIVE_SIGNALS.search(text))
    if dom and sub:
        return "contested"
    if dom:
        return "dominant"
    if sub:
        return "submissive"
    return "neutral"


# ── public API ────────────────────────────────────────────────────────────────

def detect_spatial_state(text: str) -> dict:
    """Extract the current physical/tactile scene state from combined scene text.

    Should be called on: canon_summary + partner_reply (combined prior context).

    Returns
    -------
    {
        "current_position":  str           — dominant physical position
        "clothing_state":    dict[str,str] — garment → "on"|"open"|"off"
        "active_contact":    list[str]     — active contact types
        "dominance_state":   str           — "dominant"|"submissive"|"contested"|"neutral"
        "explicit_stage":    str           — scene stage label for spatial context
    }
    """
    from app.services.rp_escalation import compute_scene_stage
    position = _detect_position(text)
    clothing = _detect_clothing_state(text)
    contact = _detect_active_contact(text)
    dominance = _detect_dominance(text)
    explicit_stage = compute_scene_stage(text)

    return {
        "current_position": position,
        "clothing_state":   clothing,
        "active_contact":   contact,
        "dominance_state":  dominance,
        "explicit_stage":   explicit_stage,
    }


def build_spatial_continuity_block(state: dict) -> str:
    """Build a high-priority spatial continuity instruction block for prompt injection.

    Tells the model the current physical reality of the scene — position,
    clothing, contact, and dominance state — so it cannot teleport bodies
    or contradict established physical continuity.

    Returns empty string when state is fully neutral (no physical grounding established).
    """
    position = state.get("current_position", "neutral")
    clothing = state.get("clothing_state", {})
    contact = state.get("active_contact", [])
    dominance = state.get("dominance_state", "neutral")
    explicit_stage = state.get("explicit_stage", "tension")

    # Skip block entirely if nothing has been established yet
    off_or_open = [g for g, s in clothing.items() if s != "on"]
    if position in ("neutral", "standing", "sitting") and not contact and not off_or_open:
        return ""

    lines: list[str] = [
        "SPATIAL CONTINUITY — HIGH PRIORITY:",
        "The following physical state is established and must be maintained.",
        "Do NOT teleport hands, bodies, or clothing. Transitions must be coherent.",
        "",
    ]

    if position not in ("neutral",):
        position_label = position.replace("_", " ")
        lines.append(f"Current position: {position_label}")

    if off_or_open:
        clothing_notes: list[str] = []
        for garment, state_val in clothing.items():
            if state_val != "on":
                clothing_notes.append(f"{garment} {state_val}")
        if clothing_notes:
            lines.append(f"Clothing state: {', '.join(clothing_notes)}")

    if contact:
        lines.append(f"Active contact: {', '.join(c.replace('_', ' ') for c in contact)}")

    if dominance != "neutral":
        lines.append(f"Dominance dynamic: {dominance}")

    if explicit_stage not in ("tension", "confession"):
        lines.append(f"Scene stage: {explicit_stage}")

    lines += [
        "",
        "Rules:",
        "- Continue physical sequencing from this exact state.",
        "- Do NOT regress to an earlier clothing or position state.",
        "- Do NOT teleport body parts — movement must be described.",
        "- Maintain tactile coherence — what was being touched stays touched unless explicitly released.",
    ]

    return "\n".join(lines)

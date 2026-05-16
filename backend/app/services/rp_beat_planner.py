"""Lightweight beat planner for multi-beat RP instruction sequences.

Public API
----------
    detect_multi_beat_instruction(instructions)  -> bool
    extract_requested_beats(instructions)        -> list[str]
    build_beat_execution_block(beats)            -> str
"""
import re

_MULTI_BEAT_KEYWORDS = (
    "and then", "then", "after", "later", "eventually",
    "midnight", "next", "before",
)

# (beat_label, lowercase match terms)
_BEAT_MAP: list[tuple[str, tuple[str, ...]]] = [
    ("confession",          ("confess", "confession", "admits", "admit", "tells her", "tells him")),
    ("warning",             ("warn", "warning", "warns", "caution")),
    ("kiss",                ("kiss", "kisses", "kissed", "goodbye kiss")),
    ("reveal",              ("reveal", "reveals", "revelation", "darker world", "secret")),
    ("time_skip",           ("midnight", "time skip", "hours later", "later that", "morning", "night falls", "skips to")),
    ("arrival",             ("arrive", "arrives", "arrival", "enters", "entering", "walk in", "walks in", "doorway")),
    ("hotel_scene",         ("hotel", "hotel room", "hotel warning", "the room")),
    ("physical_escalation", ("touch", "touches", "grab", "grabs", "pulls", "pushes", "press", "presses")),
    ("explicit_request",    ("explicit", "sex", "make love", "explicit request")),
    ("confrontation",       ("confront", "confrontation", "argues", "argument", "clash")),
    ("leave",               ("goodbye", "leaves the", "steps out", "walks out", "departs")),
    ("return",              ("return", "returns", "comes back", "walks back")),
]

_ACTION_VERB_RE = re.compile(
    r"\b(?:warns?|reveals?|kisses?|kiss|confesses?|arrives?|enters?|leaves?|"
    r"touches?|touch|grabs?|tells?|shows?|moves?|takes?|gives?|asks?|pushes?|"
    r"push|pulls?|turns?|walks?|runs?|stands?|holds?|opens?|closes?|reaches?|"
    r"reach|breaks?|fights?|finds?|makes?|brings?|leads?|follows?|speaks?|"
    r"cries?|cry|laughs?|smiles?|steps?|draws?|admits?|whispers?|presses?|"
    r"press|returns?|departs?|escapes?)\b"
)


def detect_multi_beat_instruction(instructions: str) -> bool:
    """Return True if instructions contain multiple requested scene beats.

    Also returns True when 4+ named beats are extractable, regardless of
    keyword presence (the beat count itself is sufficient evidence).
    """
    if not instructions or not instructions.strip():
        return False

    text = instructions.lower()

    for kw in _MULTI_BEAT_KEYWORDS:
        if kw in text:
            return True

    # Three or more distinct punctuation-separated clauses
    clauses = [s.strip() for s in re.split(r"[.!?;\n—]", text) if s.strip()]
    if len(clauses) >= 3:
        return True

    # Four or more distinct action verbs
    found_verbs = set(_ACTION_VERB_RE.findall(text))
    if len(found_verbs) >= 4:
        return True

    # Four or more named beats extracted → force true
    if len(extract_requested_beats(instructions)) >= 4:
        return True

    return False


def extract_requested_beats(instructions: str) -> list[str]:
    """Return an ordered list of beat labels found in the instructions."""
    if not instructions or not instructions.strip():
        return []

    text = instructions.lower()
    found: list[str] = []
    seen: set[str] = set()

    for label, terms in _BEAT_MAP:
        for term in terms:
            if term in text and label not in seen:
                found.append(label)
                seen.add(label)
                break

    return found


_BEAT_EXECUTION_BLOCK = (
    "## Beat Execution — Multi-Beat Sequence\n"
    "This instruction contains multiple requested scene beats.\n"
    "You must progress through the requested sequence.\n"
    "Do not spend excessive space on the opening emotional reaction.\n"
    "Complete the major requested beats in order.\n"
    "Prioritize narrative execution over atmospheric elaboration.\n"
    "Use concise transitions where needed.\n"
    "Do not summarize; dramatize the key beats.\n"
    "Preserve partner agency.\n"
    "Do not spend more than roughly one third of the reply on the first beat."
)

_BEAT_COMPLETION_BLOCK = (
    "## Beat Completion — Full Sequence Required\n"
    "This instruction contains four or more requested scene beats.\n"
    "You must complete all major requested beats before ending the reply.\n"
    "Do not linger on the opening exchange. Move through the sequence.\n"
    "Do not spend more than roughly one third of the reply on the first beat.\n"
    "Use concise scene transitions where needed.\n"
    "Do not summarize; dramatize each key beat.\n"
    "Preserve partner agency throughout."
)


def build_beat_execution_block(beats: list[str]) -> str:
    """Return the appropriate beat execution block based on beat count.

    4+ beats: stronger completion directive.
    3 beats:  standard multi-beat block.
    <3 beats: empty string (no injection).
    """
    if len(beats) >= 4:
        return _BEAT_COMPLETION_BLOCK
    if len(beats) >= 3:
        return _BEAT_EXECUTION_BLOCK
    return ""


def beat_completion_mode(beats: list[str]) -> str:
    """Return a label for the active beat execution mode."""
    if len(beats) >= 4:
        return "full_sequence"
    if len(beats) >= 3:
        return "multi_beat"
    return "single"

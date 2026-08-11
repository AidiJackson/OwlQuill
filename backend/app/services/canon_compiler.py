"""Canon prompt compiler — Identity OS minimal prompt.

P12 architecture:

    USER PROMPT → Scene Router → Canon Card Selection → Provider

Identity truth (facial identity, anatomy, proportions, visible body truth,
and tattoo placement) is carried by the canon **reference cards** selected by
the scene router — NOT by prose. The provider infers identity from those
cards. This compiler therefore keeps the user's scene prompt essentially
unchanged, adding only:

  * a minimal safety directive, and
  * any removable accessory the user explicitly requested via trigger keyword.

There are intentionally NO canon paragraphs, tattoo-visibility essays,
relocation / side-lock invariants, or covered/hidden marking blocks. Those
prose systems were removed in P12 (rollback tag: pre-p12-canon-routing-simplification)
because they conflicted with, and provided no leverage over, the card truth.

The old identity_compiler.py remains for legacy characters without a canon record.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from app.services.canon_service import (
    load_accessories,
    load_body_canon,
    load_face_canon,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import RemovableAccessory

logger = logging.getLogger(__name__)

# ── Minimal safety directive ──────────────────────────────────────────
# The only standing prose the compiler prepends. Kept short and content-policy
# only — it carries no identity engineering.
_SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

# Provider prompt cap. Prompts are now small (safety + accessories + scene), so
# this almost never triggers; retained purely as a defensive truncation guard.
_PROMPT_CAP = 2400

# ── Identity-priority directive (name-neutralisation) ─────────────────
# Added only when the canon has image references. Tells the provider that
# identity comes from the reference cards, not from any personal name the
# user typed in the scene (which otherwise drifts toward a real-person/celebrity
# likeness — e.g. "Leonardo" resembling a famous actor).
_IDENTITY_PRIORITY = (
    "Depict the exact character shown in the reference images. "
    "Treat any personal name in the scene as a label only — do not infer the "
    "face from the name and do not resemble any real person or celebrity."
)

# ── Permanence + skin-binding directive (C + P13b) ────────────────────
# One compact directive appended to the marking clause. Not the pre-P12 essay.
# Targets the "floating symbol" failure mode: an isolated tattoo crop being
# rendered as a free-standing graphic/accessory beside the body instead of a
# skin-bound marking applied to the correct anatomy.
_MARKING_HEADER = "Permanent markings are immutable skin-bound anatomy:"

_PERMANENCE_DIRECTIVE = (
    "Do not redesign, relocate, mirror, enlarge, detach, float, duplicate, or "
    "reinterpret markings as symbols, graphics, accessories, or background elements. "
    "Permanent tattoos/scars must remain attached to the correct body region and side. "
    "Reproduce each marking's exact shape, line work, and scale from the reference "
    "images — this specific design, not a stylistic or tribal reinterpretation."
)

# Clothing truth outranks tattoo visibility. The model must never restyle a
# garment to expose a covered marking; a tattoo is only visible when the
# requested clothing naturally leaves that skin region uncovered.
_CLOTHING_TRUTH_DIRECTIVE = (
    "Permanent markings obey scene clothing. Do not alter, cut, remove, roll "
    "higher, tear, or reinterpret garments to reveal covered tattoos/scars. "
    "Hidden markings remain hidden."
)


# ── Mark anatomy under unresolved clothing ────────────────────────────
#
# Two different questions were being answered with one gate:
#     WHERE a marking belongs   — permanent canon truth, ALWAYS knowable
#     WHETHER that skin is bare — scene truth, often unknowable
# Exposure gating is right for the second and wrong for the first. The binding
# clause below therefore states anatomy unconditionally for any region the scene
# left UNRESOLVED, and leaves VISIBILITY conditional.
#
# It used to require the scene text to mention markings as well, and the real
# Summer yellow-dress failures were the result: three generations of "Summer
# wearing a yellow summer dress" produced completely clean arms. That scene
# matched exactly one word of scene vocabulary — "dress", a torso-cover signal —
# so both arm regions resolved covered_default, no mark was exposed, no crop
# routed, this clause stayed silent, and the ONLY tattoo sentences in the
# compiled prompt were negative ones. The provider read the same words, rendered
# a sleeveless dress, and painted the bare arms clean. Permanent canon exists
# whether or not the user says the word "tattoo".
#
# Generic by construction: every binding line is built from structured canon
# fields (region, side, description). No character id, no design-name matching,
# no garment special-casing, no assumption that the character is undressed.
#
# ``scene_requests_marks`` survives as DIAGNOSTICS only — it is recorded on the
# generation record so an operator can see whether the user asked, but it gates
# nothing. Kept narrow so that signal stays meaningful.
#
# Deliberately NOT matched: bare "ink" ("an ink pen", "an ink drawing"), bare
# singular "marking" ("marking papers", "marking the register"), and bare
# "scar(s)" ("the scars of the old city wall"). Those personal senses are still
# reachable through the possessive form below, which is a cheap deterministic
# pattern rather than an NLP system.
_MARK_REQUEST_RE = re.compile(
    r"\b(?:tattoos?|tattooed|tatts?|body\s+art|body\s+ink|inked|"
    r"markings|birthmarks?)\b"
    r"|\b(?:his|her|their|its|my|your|the\s+character(?:'s|s')?)\s+"
    r"(?:\w+\s+){0,2}(?:ink|scars?|marks?|markings?)\b"
)

# Compound nouns naming a PLACE, OBJECT or PROFESSION rather than making a
# request about this character's skin. "Kofi visiting a tattoo parlour" is a
# setting; it should not pull his own designs forward.
_MARK_REQUEST_NOT_ABOUT_SKIN = (
    "tattoo parlour", "tattoo parlor", "tattoo shop", "tattoo studio",
    "tattoo artist", "tattoo gun", "tattoo machine", "tattoo needle",
    "tattoo convention", "tattoo removal", "tattoo design book",
    "ink pen", "ink drawing", "ink bottle", "ink well", "inkwell",
)

# Minimal negation guard: a negator within this many characters before the mark
# word flips the reading. Not a general negation system — it catches the common
# "no tattoos visible" / "without visible tattoos" phrasings and nothing more.
_MARK_NEGATORS = ("no ", "not ", "without ", "never ", "zero ", "none ",
                  "hides ", "hidden ", "concealed ", "covers ", "covered ")
# Negators that FOLLOW the word instead of preceding it — "her tattoos hidden
# under her sleeves" is the same request as "no visible tattoos", inverted.
_MARK_NEGATORS_TRAILING = ("hidden", "concealed", "covered up", "out of sight",
                           "not visible", "not showing")
_MARK_NEGATION_WINDOW = 28
_MARK_NEGATION_WINDOW_TRAILING = 20
# The window stops at a clause boundary, so an unrelated negation elsewhere in
# the sentence cannot swallow a real request: in "Kofi, no jacket, show his
# tattoos" the "no" belongs to the jacket, not to the tattoos.
_MARK_CLAUSE_BREAKS = (",", ";", ".", " - ", " — ", ":")

_MARK_BINDING_HEADER = (
    "This character has permanent markings. Their canonical anatomy is fixed "
    "and is not a matter of interpretation:"
)

# States the visibility rule WITHOUT asserting that any region is bare — the
# scene never said. Both failure directions are closed in one place: a covered
# mark must not be revealed or printed on fabric, and it must not be relocated
# onto whatever skin does happen to be visible.
_MARK_BINDING_VISIBILITY = (
    "Render a marking only where this scene's own clothing leaves that skin "
    "bare. Where clothing covers it, it stays underneath the fabric — never "
    "printed, traced or echoed onto the garment, and never moved onto skin "
    "that is visible instead. Never place a marking on a body region or side "
    "other than the one named above, and never add a marking that is not "
    "listed above."
)

_OPPOSITE_SIDE = {"left": "right", "right": "left"}


# ── Structured anatomy is the only anatomy the provider may read ──────
#
# Two separate leaks closed here, both of which put a SECOND, contradicting
# anatomy into the prompt beside the structured one:
#
#   * the ``side`` field is stored independently of ``body_region`` and nothing
#     validates the two against each other. ``region="right_forearm"`` with
#     ``side="left"`` produced "belongs on the right forearm … never the right
#     arm" — a flat contradiction. ``side="centre"`` on a side-named region
#     silently dropped the side protection entirely.
#   * ``label`` and ``description`` are free text, and the schema's own example
#     label is 'Left arm gothic script sleeve'. A mark labelled "Right shoulder
#     eagle" whose region is ``left_forearm`` produced "Right shoulder eagle:
#     belongs on the left forearm".
#
# body_region is authoritative. Side is DERIVED from it whenever it encodes one;
# the ``side`` field may only supplement a region that genuinely carries none.
# Free text that disagrees with the structured region is never emitted — the
# design falls back to neutral wording and the disagreement is logged, because
# it is a canon data defect that should surface rather than silently render.

# Free-text anatomy terms → the region groups they claim. Same group vocabulary
# as card_coverage.mark_region_groups, so a claim can be compared with the
# structured region's own groups.
_TEXT_REGION_TERMS: tuple[tuple[str, frozenset[str]], ...] = (
    ("upper arm", frozenset({"upper_arms"})),
    ("upper-arm", frozenset({"upper_arms"})),
    ("shoulder blade", frozenset({"back"})),
    ("shoulder", frozenset({"upper_arms"})),
    ("bicep", frozenset({"upper_arms"})),
    ("deltoid", frozenset({"upper_arms"})),
    ("forearm", frozenset({"forearms"})),
    ("lower arm", frozenset({"forearms"})),
    ("elbow", frozenset({"forearms", "upper_arms"})),
    ("wrist", frozenset({"forearms", "hands"})),
    ("knuckle", frozenset({"hands"})),
    ("finger", frozenset({"hands"})),
    ("palm", frozenset({"hands"})),
    ("hand", frozenset({"hands"})),
    ("cheek", frozenset({"face"})),
    ("forehead", frozenset({"face"})),
    ("jaw", frozenset({"face"})),
    ("temple", frozenset({"face"})),
    ("chin", frozenset({"face"})),
    ("face", frozenset({"face"})),
    ("throat", frozenset({"neck"})),
    ("neck", frozenset({"neck"})),
    ("sternum", frozenset({"torso"})),
    ("chest", frozenset({"torso"})),
    ("midriff", frozenset({"torso"})),
    ("abdomen", frozenset({"torso"})),
    ("stomach", frozenset({"torso"})),
    ("ribs", frozenset({"torso"})),
    ("torso", frozenset({"torso"})),
    ("spine", frozenset({"back"})),
    ("back", frozenset({"back"})),
    ("thigh", frozenset({"legs"})),
    ("calf", frozenset({"legs"})),
    ("shin", frozenset({"legs"})),
    ("ankle", frozenset({"legs"})),
    ("leg", frozenset({"legs"})),
)

# Extent claims: free text asserting the mark spans a WHOLE arm. This is the
# original label-driven-anatomy bug (a "sleeve" label widening an upper-arm
# mark), so it is checked against the region's exact extent rather than by
# overlap — "sleeve" is only consistent with a full-arm region.
_TEXT_FULL_ARM_EXTENT = ("full sleeve", "whole arm", "full arm",
                         "shoulder to wrist", "sleeve")
_TEXT_HALF_SLEEVE = ("half sleeve", "half-sleeve")
_FULL_ARM_GROUPS = frozenset({"upper_arms", "forearms"})

# Terms that can be SIDE-qualified but make no region claim of their own. Bare
# "arm" is the important one: "Right arm rose" on a left_forearm mark is a side
# contradiction, but "arms crossed over the chest" in a chest mark's description
# is just a pose and must not invalidate the design text.
_TEXT_SIDE_QUALIFIABLE = ("arm", "arms", "side", "leg", "legs", "foot",
                          "ear", "eye", "hip", "flank")

# Wording that makes an anatomy mention EXCLUSIONARY rather than a positive
# claim. Summer's butterfly description ends "; hand unmarked" — a statement
# that the hand is CLEAN — and reading the word "hand" as a positive claim
# disjoint from left_full_arm threw the entire description away, replacing
# "Butterflies and wildflowers in fine black line work…" with generic wording on
# every generation. A mark description that says where the mark does NOT go is
# agreeing with the structured region, not contradicting it.
_TEXT_EXCLUSION_BEFORE = (
    "no ", "not ", "never ", "without ", "except", "excluding", "aside from",
    "apart from", "other than", "free of", "clear of", "bare of", "none on",
    "nothing on", "stops before", "stopping before", "short of", "above the",
    "below the", "up to", "down to", "ending at", "ending just", "but not",
)
_TEXT_EXCLUSION_AFTER = (
    "unmarked", "is unmarked", "left unmarked", "remains unmarked", "is clean",
    "stays clean", "untouched", "is bare", "excluded", "is not marked",
    "has no", "free of", "kept clear",
)
_TEXT_EXCLUSION_WINDOW = 26

# A side word is only an anatomical claim when it qualifies an anatomical term:
# "the right shoulder" claims a side, "its right wing raised" does not.
_TEXT_SIDE_CLAIM_RE = re.compile(
    r"\b(left|right)\b[-\s]+(?:\w+[-\s]+){0,2}?\b("
    + "|".join(re.escape(t) for t, _ in _TEXT_REGION_TERMS)
    + "|" + "|".join(re.escape(t) for t in _TEXT_SIDE_QUALIFIABLE)
    + r")\b"
)

# Word-boundary matching for the region terms. Plain substring matching read
# "leg" inside "elegant" and "back" inside "backlit", which would have thrown
# away perfectly consistent design text.
_TEXT_REGION_RES: tuple[tuple[object, frozenset[str]], ...] = tuple(
    (re.compile(r"\b" + re.escape(term) + r"s?\b"), groups)
    for term, groups in _TEXT_REGION_TERMS
)


def _side_from_region(body_region: str) -> str | None:
    """The side encoded IN the structured region, or None if it encodes none."""
    r = (body_region or "").lower().replace("-", "_").replace(" ", "_")
    tokens = set(r.split("_"))
    has_left, has_right = "left" in tokens, "right" in tokens
    if has_left and not has_right:
        return "left"
    if has_right and not has_left:
        return "right"
    return None


def _mark_side(mark: object, char_id: str = "?") -> str | None:
    """Authoritative side for a mark: the region's, else the ``side`` field.

    When the two disagree the REGION wins and the disagreement is logged. This
    is the single place either value is read, so no clause can pick the other.
    """
    region = getattr(mark, "body_region", "") or ""
    declared = (getattr(mark, "side", "") or "").lower().strip()
    from_region = _side_from_region(region)
    if from_region:
        if declared in _OPPOSITE_SIDE and declared != from_region:
            logger.warning(
                "CANON_MARK_SIDE_CONFLICT character_id=%s region=%r side=%r "
                "using=region",
                char_id, region, declared,
            )
        return from_region
    return declared if declared in _OPPOSITE_SIDE else None


def _text_contradicts_region(text: str, body_region: str,
                             structured_side: str | None) -> bool:
    """True when free text makes an anatomical claim the structured region denies.

    Compared against the region's own groups: a claim whose groups are disjoint
    from the structured region's is a contradiction. When the region cannot be
    mapped onto the group vocabulary at all, ANY anatomical term in the text is
    treated as a contradiction — consistency cannot be proven, and an unprovable
    claim must not reach the provider (the same conservative veto
    ``mark_location_authority`` applies to the same input).
    """
    from app.services.card_coverage import mark_region_groups

    t = (text or "").lower()
    if not t:
        return False
    groups = mark_region_groups(body_region)

    # Side claims must agree with the structured side.
    for m in _TEXT_SIDE_CLAIM_RE.finditer(t):
        if structured_side and m.group(1) != structured_side:
            return True
        if not structured_side:
            return True  # region carries no side; text asserting one adds truth

    # Whole-arm extent claims must match a genuinely full-arm region.
    if any(term in t for term in _TEXT_HALF_SLEEVE):
        if groups != frozenset({"upper_arms"}):
            return True
    elif any(term in t for term in _TEXT_FULL_ARM_EXTENT):
        if groups != _FULL_ARM_GROUPS:
            return True

    # Region claims must overlap the structured region — unless the mention is
    # exclusionary, in which case it is agreeing with the region, not disputing
    # it ("…ending just above the wrist; hand unmarked").
    for pattern, claimed in _TEXT_REGION_RES:
        for m in pattern.finditer(t):
            if not groups or not (claimed & groups):
                if _is_exclusionary(t, m.start(), m.end()):
                    continue
                return True
    return False


def _is_exclusionary(text: str, start: int, end: int) -> bool:
    """True when an anatomy mention says the mark is ABSENT there."""
    before = text[max(0, start - _TEXT_EXCLUSION_WINDOW):start]
    if any(w in before for w in _TEXT_EXCLUSION_BEFORE):
        return True
    after = text[end:end + _TEXT_EXCLUSION_WINDOW]
    return any(w in after for w in _TEXT_EXCLUSION_AFTER)


def _neutral_design(mark: object, region_phrase: str) -> str:
    """Design wording carrying no anatomy of its own beyond the structured region."""
    t = (getattr(mark, "type", "") or "").lower().strip()
    kind = t if t in ("tattoo", "scar", "birthmark", "mole") else "permanent marking"
    return f"the canonical {region_phrase} {kind}"


def _safe_design_text(
    mark: object,
    region_phrase: str,
    *,
    prefer: str,
    max_chars: int | None = None,
    char_id: str = "?",
) -> str:
    """Design wording for prompt prose, guaranteed not to contradict the region.

    ``prefer`` picks which free-text field leads ("label" for the compact
    binding lines, "description" for the geometry block). Fallback order is
    preferred field → the other field → neutral structured wording: a
    contradictory description must not cost the design its name when the label
    is perfectly consistent (Summer's "Butterfly floral sleeve"). Only when
    BOTH disagree with the structured region is neutral wording used, and the
    canon defect is logged either way. The design is never ANATOMY here — it
    exists only to tell two of a character's designs apart.
    """
    region = getattr(mark, "body_region", "") or ""
    side = _mark_side(mark, char_id)
    other = "description" if prefer == "label" else "label"
    for field_name in (prefer, other):
        text = (getattr(mark, field_name, None) or "").strip()
        if not text:
            continue
        if _text_contradicts_region(text, region, side):
            logger.warning(
                "CANON_MARK_TEXT_ANATOMY_IGNORED character_id=%s region=%r "
                "field=%s text=%r",
                char_id, region, field_name, text[:80],
            )
            continue
        if max_chars is not None and len(text) > max_chars:
            head = text[:max_chars]
            cut = max(head.rfind(", "), head.rfind("; "), head.rfind(" "))
            text = (head[:cut] if cut > max_chars // 3 else head).rstrip(" ,;")
        return text
    return _neutral_design(mark, region_phrase)

# A binding line only has to make one design distinguishable from another well
# enough that it cannot be swapped onto the wrong side — "Butterfly floral
# sleeve" does that; the mark's full 500-character description does not do it
# any better. Length matters because these lines are additive: a character with
# eight registered marks (Davies) overflowed _PROMPT_CAP with full descriptions,
# and truncation takes the tail of the prompt — which is the clean-skin clause,
# the occlusion clause and the USER'S OWN SCENE TEXT. A clause that silently
# deletes the scene is far worse than the swap it prevents.
_BINDING_DESIGN_CHARS = 90

# Ceiling on the per-mark lines. A heavily marked character must not be able to
# spend the whole prompt on bindings. Overflow is SUMMARISED, never silently
# dropped: the remaining marks still get the region/side rule, just not their
# own line.
_MARK_BINDING_BUDGET = 700


def scene_requests_marks(scene_prompt: str) -> bool:
    """True when the scene text itself asks about this character's markings.

    Word-boundary matching, not substring: "scarf" is not "scar", and the "ink"
    in "thinking" is not a request for tattoos. Character-agnostic — it reads
    the scene, never the canon.

    Three deterministic filters, in order: the vocabulary must match; the match
    must not be part of a compound naming a place/object/profession; and the
    match must not be negated within a short window before it. Every filter
    fails CLOSED (not a request), because the conservative direction is to say
    nothing about markings rather than to emphasise them unasked.
    """
    text = (scene_prompt or "").lower()
    matches = list(_MARK_REQUEST_RE.finditer(text))
    if not matches:
        return False
    for m in matches:
        before = _same_clause(
            text[max(0, m.start() - _MARK_NEGATION_WINDOW):m.start()], tail=True)
        if any(neg in before for neg in _MARK_NEGATORS):
            continue
        after = _same_clause(
            text[m.end():m.end() + _MARK_NEGATION_WINDOW_TRAILING], tail=False)
        if any(neg in after for neg in _MARK_NEGATORS_TRAILING):
            continue
        # Compound check: only a compound overlapping THIS match disqualifies it,
        # so "a tattoo parlour — show his tattoos" still reads as a request.
        if _inside_compound(text, m.start()):
            continue
        return True
    return False


def _same_clause(window: str, *, tail: bool) -> str:
    """Trim a negation window at the nearest clause boundary.

    ``tail=True`` keeps the text AFTER the last boundary (a window that precedes
    the match); ``tail=False`` keeps the text BEFORE the first one.
    """
    if tail:
        cut = max((window.rfind(b) + len(b) for b in _MARK_CLAUSE_BREAKS
                   if b in window), default=0)
        return window[cut:]
    cut = min((window.find(b) for b in _MARK_CLAUSE_BREAKS if b in window),
              default=len(window))
    return window[:cut]


def _inside_compound(text: str, pos: int) -> bool:
    """True when ``pos`` falls inside a place/object/profession compound."""
    for phrase in _MARK_REQUEST_NOT_ABOUT_SKIN:
        start = text.find(phrase)
        while start != -1:
            if start <= pos < start + len(phrase):
                return True
            start = text.find(phrase, start + 1)
    return False


def _side_exclusion(mark: object, region_phrase: str, char_id: str = "?") -> str:
    """Explicit negative for the mirrored anatomy, e.g. 'never the right arm'.

    The side comes from :func:`_mark_side` — the structured region first — so a
    ``side`` field that disagrees with the region can no longer produce
    "belongs on the right forearm … never the right arm".
    """
    other = _OPPOSITE_SIDE.get(_mark_side(mark, char_id) or "")
    if other and "arm" in region_phrase:
        return f"never the {other} arm"
    if other:
        return f"never the {other} side"
    # A genuinely sideless region (centre/bilateral, or a region encoding no
    # side): there is no mirrored counterpart to exclude, so say only what is
    # true rather than inventing a mirror.
    return "never mirrored or moved across the body"


def _skin_phrase(mark: object) -> str:
    """Type-aware skin-binding suffix that frames the mark as inked-in anatomy."""
    t = (getattr(mark, "type", "") or "").lower()
    if t == "scar":
        return "permanently set into the skin"
    if t in ("tattoo", "body_marking", ""):
        return "permanently inked into skin"
    return "permanently part of the skin"


# ── Reference image collector ─────────────────────────────────────────
# Unchanged from P8: the canonical static priority ordering. The scene router
# (scene_router.py) selects/weights cards for routed scenes and falls back to
# this ordering when the prompt is ambiguous.

def collect_canon_reference_urls(
    canon: "CharacterIdentityCanon",
) -> list[str]:
    """Collect reference image URLs in provider-priority order.

    S24AK note: this is the ambiguous-prompt FALLBACK ordering (the scene
    router weights cards per-camera when an orientation is detectable). The v2
    cards are woven in by priority — NOT blindly appended — so the strongest
    six still win under the 6-image provider cap. A fully-populated v2 canon
    sends face_front, face_left_3q, face_right_3q, face_profile, body_front,
    body_map (4 face angles + body truth + marking placement).

    Priority (positions 0–5 are the ones most likely sent under the 6-cap):
      0. face_front            — primary face identity seed
      1. face_left_3q          — face geometry supplement
      2. face_right_3q         — face geometry supplement
      3. face_profile          — v2: side-profile face geometry
      4. body_front            — body morphology + tattoo placement truth
      5. body_map              — canonical marking placement sheet

    May drop under provider cap (positions 6+):
      6.  final_character_card — holistic identity grounding
      7.  body_left            — side detail (optional)
      8.  body_right           — side detail (optional)
      9.  body_back            — back detail (optional)
      10. face_expression      — lowest-value face variant
      11. torso_front          — v2: upper-body truth (optional)
      12. torso_side           — v2: upper-body side truth (optional)
      13. standing_relaxed     — v2: relaxed full-body pose (optional)
      14. seated_relaxed       — v2: relaxed seated pose (optional)

    Rationale: face angles + body truth + marking placement carry the most
    identity signal and lead. The v2 relaxed/torso cards are supporting body
    truth and sit behind the legacy core so they only surface when room remains
    or higher-priority slots are absent (sparse canons stay compact).
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)

    def _f(obj: object, attr: str) -> str | None:
        return getattr(obj, attr, None) if obj else None

    # Build in strict priority order — each entry is (url_or_None,).
    # Skip None entries so sparse canons produce a compact list.
    ordered = [
        _f(face, "face_front_image_url"),            # 0 — always first
        _f(face, "face_left_3q_image_url"),          # 1
        _f(face, "face_right_3q_image_url"),         # 2
        _f(face, "face_profile_image_url"),          # 3 — v2 profile face
        _f(body, "body_front_image_url"),            # 4 — body truth
        _f(body, "body_map_image_url"),              # 5 — marking placement
        _f(body, "final_character_card_image_url"),  # 6 — holistic grounding
        _f(body, "body_left_image_url"),             # 7 — may drop
        _f(body, "body_right_image_url"),            # 8 — may drop
        _f(body, "body_back_image_url"),             # 9 — may drop
        _f(face, "face_expression_image_url"),       # 10 — low-value face variant
        _f(body, "torso_front_image_url"),           # 11 — v2 torso truth
        _f(body, "torso_side_image_url"),            # 12 — v2 torso side
        _f(body, "standing_relaxed_image_url"),      # 13 — v2 relaxed pose
        _f(body, "seated_relaxed_image_url"),        # 14 — v2 seated pose
    ]
    return [url for url in ordered if url]


# ── Requested removable accessories ───────────────────────────────────

def _requested_accessories(
    canon: "CharacterIdentityCanon",
    scene_lower: str,
) -> list["RemovableAccessory"]:
    """Return removable accessories whose trigger keyword appears in the scene.

    Deterministic substring match only. Accessories are never inferred — they
    appear solely when the user's prompt explicitly asks for them.
    """
    requested: list["RemovableAccessory"] = []
    for acc in load_accessories(canon):
        for kw in (acc.trigger_keywords or []):
            if kw.lower() in scene_lower:
                requested.append(acc)
                break
    return requested


# ── Permanent marking clause (A) ──────────────────────────────────────

def _region_phrase(region: str) -> str:
    """Turn a body_region key into a short human phrase.

    'left_full_arm' → 'left arm'; 'right_upper_arm' → 'right upper arm';
    'neck' → 'neck'; 'right_cheek' → 'right cheek'.
    """
    r = (region or "").lower().strip()
    if r.endswith("_full_arm"):
        return r[: -len("_full_arm")].replace("_", " ") + " arm"
    return r.replace("_", " ")


def _has_image_refs(canon: "CharacterIdentityCanon") -> bool:
    """True if the canon carries any face or body image reference."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    if face and any([
        face.face_front_image_url,
        face.face_left_3q_image_url,
        face.face_right_3q_image_url,
    ]):
        return True
    if body and any([
        body.body_front_image_url,
        body.body_map_image_url,
        body.final_character_card_image_url,
    ]):
        return True
    return False


def _permanent_marks_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    design_chars: int | None = None,
) -> str:
    """Compile a scene-aware permanent-marking clause (A + C).

    Clothing truth > tattoo visibility. The text is aligned with the routing
    layer's already-correct visibility decisions so the prompt never instructs
    the provider to reproduce a tattoo the scene covers (which previously made
    garments split/cut open to expose hidden marks).

    Visibility is decided by the SAME logic the scene router uses for crop
    routing — `_detect_camera` and `_mark_region_exposed` — so
    text and references can never drift apart (single source of truth).

    Emission rules:
      * portrait / close-up        → no marking block at all (face-only frame).
      * exposed marks (this scene) → skin-bound header + per-mark geometry lines
                                      + permanence/exact-geometry directive.
      * covered marks present      → ONLY the compact clothing-truth directive;
                                      covered marks are never named, never given
                                      a permanence/geometry reproduction clause.
      * no exposed marks           → permanence/geometry section suppressed
                                      entirely (just the clothing-truth line).

    Returns '' when there are no permanent marks, or for portraits.
    """
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return ""

    # Single source of truth: reuse the router's deterministic scene logic.
    from app.services.scene_router import (
        _detect_camera,
        _mark_region_exposed,
    )

    prompt_lower = (scene_prompt or "").lower()

    # Portrait / close-up frames carry no body region — emit no marking block
    # (matches the router skipping all body-crop routing for portraits).
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""

    # Partition marks by THIS scene's exposure, using the identical per-mark gate
    # the router applies to crop routing. Covered/uncertain regions → not exposed.
    exposed: list = []
    for m in marks:
        if _mark_region_exposed(getattr(m, "body_region", ""), prompt_lower):
            exposed.append(m)

    parts: list[str] = []

    # Exposed marks only: skin-bound wording + permanence + exact-geometry clause.
    if exposed:
        char_id = str(getattr(canon, "character_id", "?"))
        lines: list[str] = []
        for m in exposed:
            region = _region_phrase(getattr(m, "body_region", ""))
            # Descriptions are free text and can carry their own anatomy ("an
            # eagle across the right shoulder blade" on a left_forearm mark).
            # Structured region wins; contradictory prose is replaced, not
            # emitted alongside. ``design_chars`` lets the prompt-fitting policy
            # shed verbose design detail before anything structural.
            design = _safe_design_text(
                m, region, prefer="description", max_chars=design_chars,
                char_id=char_id,
            )
            lines.append(f"- {region}: {design} {_skin_phrase(m)}")
        parts.append(
            _MARKING_HEADER + "\n"
            + "\n".join(lines)
            + "\n" + _PERMANENCE_DIRECTIVE
        )

    # Clothing truth always asserted when the character has marks in a body
    # scene — this is what keeps covered marks hidden instead of forcing them.
    parts.append(_CLOTHING_TRUTH_DIRECTIVE)

    return "\n".join(parts)


def _mark_binding_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    budget: int = _MARK_BINDING_BUDGET,
) -> str:
    """Bind each mark to its canonical region/side when the scene leaves it open.

    Fires when ALL of:
      * the canon carries structured permanent marks,
      * the frame is not a portrait close-up (no body in shot),
      * and, per mark, the scene has NOT resolved its anatomy either way.

    **Deliberately NOT gated on the scene text mentioning markings.** It was,
    and the real Summer yellow-dress failures were the result: "Summer wearing
    a yellow summer dress" says nothing about tattoos and matched no arm
    vocabulary, so this clause stayed silent, no crop routed, and the only
    tattoo-related sentences in the compiled prompt were negative ones
    ("hidden markings remain hidden", "clean-skin truth: no ink on the
    hands…"). The provider read the same sentence, rendered a sleeveless dress,
    and painted the bare arms clean. Permanent canon exists whether or not the
    user says the word "tattoo"; withholding it because they didn't is how a
    tattoo disappears from skin the image plainly shows.

    That last gate is what keeps this from duplicating or contradicting the
    two clauses either side of it:

      exposed          → :func:`_permanent_marks_clause` already emits the full
                         geometry block for this mark; nothing to add.
      covered_explicit → the scene named a garment that covers every region the
                         mark occupies. Naming a hidden design is the Davies
                         mistake (the model cuts the garment open to show it),
                         so the occlusion clause keeps sole ownership and this
                         clause stays silent about it.
      ambiguous        → contradictory garment evidence. Conservative, same as
                         covered: no anatomy stated, because a scene that says
                         both things must not be resolved by us.
      otherwise        → UNRESOLVED, the case this exists for: clothing unstated
                         or unrecognised, so visibility is unknown but ANATOMY
                         is not. The provider decides what skin its own rendered
                         garment leaves visible; we supply where the marks live.

    Design descriptions are included because the failure was a design/side
    swap: naming the region alone cannot say which of two designs belongs
    there. Visibility is never asserted — see _MARK_BINDING_VISIBILITY.
    """
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return ""

    from app.services.card_coverage import mark_region_groups, scene_region_states
    from app.services.scene_router import _detect_camera, _mark_region_exposed

    prompt_lower = (scene_prompt or "").lower()
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""

    states = scene_region_states(prompt_lower)
    char_id = str(getattr(canon, "character_id", "?"))
    any_explicitly_covered = any(
        s == "covered_explicit" for s in states.values()
    )
    lines: list[str] = []
    for m in marks:
        region = getattr(m, "body_region", "") or ""
        if _mark_region_exposed(region, prompt_lower):
            continue  # the exposed block owns this mark
        groups = mark_region_groups(region)
        if groups:
            # ANY blocked segment is enough. covered_explicit → the occlusion
            # clause owns it and naming a hidden design is the Davies mistake.
            # ambiguous → the scene gave contradictory garment evidence and we
            # must not resolve it in either direction.
            if any(states.get(g) in ("covered_explicit", "ambiguous")
                   for g in groups):
                continue
        elif any_explicitly_covered:
            # The region cannot be mapped onto the coverage vocabulary, so we
            # cannot show this mark is visible. Naming a design that may be
            # hidden is the Davies mistake (the model cuts the garment open),
            # and the guard above only protected MAPPABLE regions — an
            # unmappable one used to be named in a fully dressed scene.
            continue
        phrase = _region_phrase(region)
        design = _safe_design_text(
            m, phrase, prefer="label", max_chars=_BINDING_DESIGN_CHARS,
            char_id=char_id,
        )
        lines.append(
            f"- {design}: belongs on the {phrase} and only there — "
            f"{_side_exclusion(m, phrase, char_id)}, never another body region"
        )
    if not lines:
        return ""

    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) > budget:
            break
        kept.append(line)
        used += len(line) + 1
    dropped = len(lines) - len(kept)
    if dropped:
        kept.append(
            f"- and {dropped} further permanent marking(s): each stays on its own "
            "canonical region and side, never relocated or mirrored"
            if kept else
            f"- all {dropped} of this character's permanent markings stay on their "
            "own canonical region and side, never relocated or mirrored"
        )
        logger.info(
            "CANON_MARK_BINDING_SUMMARISED character_id=%s named=%d summarised=%d",
            getattr(canon, "character_id", "?"), len(kept) - 1, dropped,
        )
    return (
        _MARK_BINDING_HEADER + "\n"
        + "\n".join(kept)
        + "\n" + _MARK_BINDING_VISIBILITY
    )


# ── Coverage occlusion clause (CANON SKIN/CLOTHING sprint) ────────────
# Region-level phrases for the occlusion invariant. Deliberately anatomical and
# generic — the clause must NEVER name or describe a hidden tattoo design.
_REGION_PHRASES = {
    "torso": "chest and torso",
    "back": "back",
    "upper_arms": "arms",
    "forearms": "arms",
    "neck": "neck",
    "legs": "legs",
}


# ── Clean-skin authority clause (PERMANENT-MARK CANON sprint) ─────────
# Anti-migration mechanism. When the canon carries mark-location authority
# (structured marks and/or marked_regions), every scene-relevant region
# OUTSIDE that authority is asserted as unmarked skin. This is what stops a
# heavily-tattooed reference pack teaching the provider that the character's
# neck, hands or face are tattooed (the Davies office collar/knuckle
# inventions): those regions are VISIBLE, but visibility is not authority.
# Region-level and character-agnostic — never a per-character negative-prompt
# hack, so it scales to every canon that declares authority.
# Flat noun lists so the joined sentence never nests "and" inside a phrase.
_CLEAN_REGION_PHRASES = {
    "torso": ["chest", "torso"],
    "back": ["back"],
    "upper_arms": ["upper arms"],
    "forearms": ["forearms"],
    "neck": ["neck", "throat"],
    "legs": ["legs"],
    "hands": ["hands", "fingers", "knuckles"],
    "face": ["face"],
}

# Order clean regions are named in — head-down, deterministic output.
_CLEAN_REGION_ORDER = (
    "face", "neck", "torso", "back", "upper_arms", "forearms", "hands", "legs",
)


def _join_phrases(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + " and " + phrases[-1]


def _clean_region_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
) -> str:
    """Assert clean skin for scene-relevant regions outside mark authority.

    Fires only when the canon carries authority data (see
    card_coverage.mark_location_authority). Scene relevance keeps the clause
    compact:
      * face and hands — always relevant (always visible);
      * neck — relevant unless the scene explicitly covers it (a suit collar
        still leaves the neck visible — the exact Davies migration site);
      * torso/back/arms/legs — relevant only when the scene EXPOSES them
        (when covered, the occlusion machinery already owns the wording).
    Portrait close-ups reduce to face + neck (the only skin in frame).
    """
    from app.services.card_coverage import (
        mark_location_authority,
        scene_region_states,
    )
    from app.services.scene_router import _detect_camera

    body = load_body_canon(canon)
    authority = mark_location_authority(body)
    if authority is None:
        return ""

    prompt_lower = (scene_prompt or "").lower()
    states = scene_region_states(prompt_lower)

    clean = [r for r in _CLEAN_REGION_ORDER if r not in authority]
    relevant: list[str] = []
    portrait = _detect_camera(prompt_lower) == "portrait_closeup"
    for region in clean:
        if portrait and region not in ("face", "neck"):
            continue
        if region in ("face", "hands"):
            relevant.append(region)
        elif region == "neck":
            if states.get("neck") != "covered_explicit":
                relevant.append(region)
        elif states.get(region) == "exposed":
            relevant.append(region)
    if not relevant:
        return ""

    nouns: list[str] = []
    for r in relevant:
        nouns.extend(_CLEAN_REGION_PHRASES[r])
    joined = _join_phrases(nouns)
    return (
        f"Clean-skin truth: this character has no tattoos, markings, or ink on the "
        f"{joined} — those areas are unmarked natural skin. Never add, extend, or "
        "migrate any marking onto them, even if reference images show tattoos on "
        "nearby skin."
    )


def _legacy_mark_presence_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
) -> str:
    """Positive existence line for DECLARED-authority canons without structured marks.

    An enriched legacy character (marked_regions set, permanent_body_marks
    still empty — Davies after enrichment) has no per-mark geometry lines, so
    when the scene exposes an authority region this asserts that its markings
    exist and are defined by the reference images. Design details stay in the
    cards — prose never describes them (the P12 lesson).
    """
    from app.services.card_coverage import (
        mark_location_authority,
        scene_region_states,
    )
    from app.services.scene_router import _detect_camera

    body = load_body_canon(canon)
    if body is None or getattr(body, "permanent_body_marks", None):
        return ""  # structured marks own their own positive lines
    authority = mark_location_authority(body)
    if not authority:
        return ""

    prompt_lower = (scene_prompt or "").lower()
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""
    states = scene_region_states(prompt_lower)
    exposed = [
        r for r in _CLEAN_REGION_ORDER
        if r in authority and states.get(r) == "exposed"
    ]
    if not exposed:
        return ""
    nouns: list[str] = []
    for r in exposed:
        nouns.extend(_CLEAN_REGION_PHRASES[r])
    joined = _join_phrases(nouns)
    return (
        f"The character's {joined} carry their permanent markings exactly as shown "
        "in the reference images — same designs, same positions, same scale."
    )


def _conditional_occlusion_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
) -> str:
    """Conditional ink-on-fabric invariant for regions the scene leaves UNSTATED.

    The production failure this closes: "Davies in his office - any tattoos
    that should be visible are visible" reproduced his chest artwork ON the
    shirt. The scene names no garment, so every torso signal resolves to
    ``covered_default`` and :func:`_coverage_occlusion_clause` (which requires
    ``covered_explicit``) stayed silent — while the user's own wording pushed
    the model to render torso ink. The model then dressed him for an office,
    as it should, and printed the ink onto the fabric.

    The fix is deliberately CONDITIONAL. It never asserts that the region IS
    covered — asserting that on an unstated scene would break shirtless,
    swimwear and fantasy prompts, and would be exactly the "assume everything
    is clothed" overreach we must avoid. It asserts only the implication:
    *if* clothing covers this region here, the marking is under it, never on
    it. That is true in every scene, so it is safe to state whenever the
    region is not explicitly exposed.

    Fires only when ALL of:
      * the canon carries mark-location authority (structured marks and/or a
        ``marked_regions`` declaration) — legacy undeclared canons keep
        byte-identical prompts, so Angelo and friends are untouched,
      * the region is one the character is actually MARKED in (clean regions
        are handled by the clean-skin clause; naming them here would be noise),
      * the canon carries bare-skin card evidence for that region — without it
        there is no ink for the model to migrate,
      * the scene does not EXPOSE the region (exposed → the mark should show),
      * the scene does not explicitly cover it either (explicit → the stronger
        absolute clause above owns the wording; no duplication).
    """
    from app.services.card_coverage import (
        card_visible_regions,
        mark_location_authority,
        scene_region_states,
    )
    from app.services.scene_router import _detect_camera, _get_canon_slot_urls

    body = load_body_canon(canon)
    if body is None:
        return ""
    authority = mark_location_authority(body)
    if not authority:
        return ""

    prompt_lower = (scene_prompt or "").lower()
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""

    states = scene_region_states(prompt_lower)

    bare: set[str] = set()
    for slot in _get_canon_slot_urls(canon):
        regions, _source = card_visible_regions(body, slot)
        if regions:
            bare |= regions
    candidates = (bare & set(authority)) - {
        r for r, s in states.items() if s in ("exposed", "covered_explicit")
    }
    if not candidates:
        return ""

    phrases: list[str] = []
    for region in ("torso", "back", "upper_arms", "forearms", "neck", "legs"):
        if region in candidates:
            p = _REGION_PHRASES[region]
            if p not in phrases:
                phrases.append(p)
    if not phrases:
        return ""
    return (
        f"Wherever clothing covers the {_join_phrases(phrases)} in this scene, the "
        "permanent markings there are underneath the fabric: never printed, "
        "traced, echoed or patterned onto the garment itself."
    )


def _coverage_occlusion_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
) -> str:
    """Region-level occlusion invariant for canons with bare card evidence.

    Davies: permanent_body_marks is empty, so `_permanent_marks_clause` emits
    nothing — not even the clothing-truth line — while his shirtless canon
    cards hand the provider strong visual tattoo evidence. This clause is the
    text counterweight for exactly that case. It fires only when ALL of:

      * the scene is not a portrait close-up (no body in frame),
      * at least one region is EXPLICITLY covered by scene clothing vocabulary
        (covered_default scenes stay byte-identical — no prompt bloat, and the
        Angelo probe prompts keep their prompt_sha),
      * the canon carries bare-skin evidence for such a region — a declared
        bare card or the slot-default bare body_map. A canon with no bare
        evidence has nothing to occlude.

    Region-level only: names body regions and the fact of coverage, never the
    design. Derived from the SAME scene-coverage engine routing uses.
    """
    body = load_body_canon(canon)
    if body is None:
        return ""
    # Mark-bearing canons get the COMPACT form below rather than nothing.
    # Returning "" for them (the original behaviour, when only markless
    # canons could reach here) meant that registering structured marks on a
    # character DELETED his region-named occlusion wording and left only the
    # generic clothing-truth directive — a silent downgrade of the exact text
    # that made the white-shirt scene pass before enrichment.
    has_marks = bool(getattr(body, "permanent_body_marks", None))

    from app.services.card_coverage import (
        card_visible_regions,
        scene_region_states,
    )
    from app.services.scene_router import _detect_camera, _get_canon_slot_urls

    prompt_lower = (scene_prompt or "").lower()
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""

    states = scene_region_states(prompt_lower)
    explicit = {r for r, s in states.items() if s == "covered_explicit"}
    if not explicit:
        return ""

    bare: set[str] = set()
    for slot in _get_canon_slot_urls(canon):
        regions, _source = card_visible_regions(body, slot)
        if regions:
            bare |= regions
    hidden = explicit & bare
    if not hidden:
        return ""

    phrases: list[str] = []
    for region in ("torso", "back", "upper_arms", "forearms", "neck", "legs"):
        if region in hidden:
            p = _REGION_PHRASES[region]
            if p not in phrases:
                phrases.append(p)
    joined = _join_phrases(phrases)
    if has_marks:
        # The generic _CLOTHING_TRUTH_DIRECTIVE already states the rule for
        # mark-bearing canons; this only has to name the regions, so it stays
        # short rather than repeating the full sentence.
        return (
            f"Opaque clothing covers {joined} here — markings there stay "
            "under the fabric, never on it."
        )
    return (
        f"The character's {joined} are fully covered by opaque clothing in this "
        "scene. Permanent skin markings in those regions are not visible on or "
        "through the fabric."
    )


# ── Prompt fitting by priority ────────────────────────────────────────
#
# The cap used to be a tail cut, and the scene is assembled last, so a long
# prompt lost the occlusion clause, the clean-skin clause and the user's own
# sentence while keeping boilerplate. The first repair preserved the scene but
# introduced a worse branch: when the scene ALONE approached the cap it emitted
# the scene and nothing else — no safety directive, no identity directive, no
# invariants. That regression was mark-independent; it hit every character.
#
# Fitting is now by PRIORITY, not by position:
#
#   RANK_FIXED     safety directive, identity grounding      never shed
#   RANK_INVARIANT anatomy bindings, occlusion, clean-skin   shed only as a last
#                                                            resort, from the end
#   RANK_PROSE     descriptive canon prose, accessories      shed first
#
# and design DETAIL (mark descriptions, binding design names) is compressed
# before any part is shed at all. The scene is always represented: it is trimmed
# to fit rather than dropped, and never trimmed below _SCENE_MIN_CHARS while any
# sheddable part remains.
_RANK_FIXED = 0
_RANK_INVARIANT = 1
_RANK_PROSE = 2

# Floor on the scene's share of the prompt. Above this, the scene is trimmed
# before invariants are shed; below it, invariants go first.
_SCENE_MIN_CHARS = 320


def _join_parts(parts: list[tuple[int, str]], scene: str) -> str:
    return ", ".join([t for _r, t in parts if t] + ([scene] if scene else []))


def _fit_prompt(
    parts: list[tuple[int, str]],
    scene: str,
    cap: int,
    char_id: str,
) -> str:
    """Fit the prompt to ``cap`` by shedding the least important content first.

    Guarantees, in order of precedence:
      1. every ``_RANK_FIXED`` part survives verbatim,
      2. the scene is represented (possibly trimmed) whenever any room remains,
      3. structural invariants survive unless the fixed parts plus the scene
         floor cannot fit without them,
      4. the result never exceeds ``cap``.
    """
    parts = list(parts)
    prompt = _join_parts(parts, scene)
    if len(prompt) <= cap:
        return prompt

    # (a) Shed descriptive prose — the scene is not touched if this is enough.
    for i in sorted(
        (i for i, (r, _) in enumerate(parts) if r >= _RANK_PROSE), reverse=True
    ):
        dropped = parts.pop(i)
        logger.info(
            "CANON_PROMPT_SHED character_id=%s rank=%d chars=%d",
            char_id, dropped[0], len(dropped[1]),
        )
        prompt = _join_parts(parts, scene)
        if len(prompt) <= cap:
            return prompt

    # (b) Make room for the scene, shedding invariants from the END only while
    #     the scene cannot even reach its floor.
    scene_floor = min(len(scene), _SCENE_MIN_CHARS)
    while True:
        room = cap - len(_join_parts(parts, "")) - 2
        sheddable = [i for i, (r, _) in enumerate(parts) if r != _RANK_FIXED]
        if room >= scene_floor or not sheddable:
            break
        # Highest rank number first, then latest — so prose goes before
        # invariants and earlier invariants outlive later ones.
        i = max(sheddable, key=lambda i: (parts[i][0], i))
        dropped = parts.pop(i)
        logger.warning(
            "CANON_PROMPT_INVARIANT_SHED character_id=%s rank=%d chars=%d",
            char_id, dropped[0], len(dropped[1]),
        )

    room = max(0, cap - len(_join_parts(parts, "")) - 2)
    trimmed = scene[:room].rstrip(" ,;") if room else ""
    if len(trimmed) < len(scene):
        logger.warning(
            "canon_prompt_scene_trimmed character_id=%s scene_len=%d kept=%d",
            char_id, len(scene), len(trimmed),
        )
    return _join_parts(parts, trimmed)[:cap]


# ── Main compiler ─────────────────────────────────────────────────────

def compile_canon_prompt(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    *,
    include_accessories: bool = True,
    diagnostics: dict | None = None,
) -> str:
    """Compile a minimal generation prompt from the user's scene.

    Output order:
      1. minimal safety directive
      2. requested removable accessories (keyword-triggered only)
      3. the user's scene prompt, essentially unchanged

    Identity is supplied by the routed canon reference cards, not by this
    prompt. No canon prose, marking essays, or relocation/side-lock invariants
    are emitted.

    Pass a dict as ``diagnostics`` to receive which clauses were emitted and
    whether prompt fitting ran. Write-only, populated on the single compile pass
    that already happens — it never changes the returned prompt.
    """
    scene = scene_prompt.strip()
    char_id = str(getattr(canon, "character_id", "?"))

    requested: list["RemovableAccessory"] = []
    if include_accessories:
        requested = _requested_accessories(canon, scene.lower())

    def _build(
        design_chars: int | None, binding_budget: int
    ) -> tuple[list[tuple[int, str]], str, str]:
        """Assemble the ranked canon parts at a given design-detail budget."""
        parts: list[tuple[int, str]] = [(_RANK_FIXED, _SAFETY_PREFIX)]

        # Identity-priority directive — only when image refs back it (name fix).
        if _has_image_refs(canon):
            parts.append((_RANK_FIXED, _IDENTITY_PRIORITY))

        if requested:
            parts.append((
                _RANK_PROSE,
                "wearing " + "; ".join(a.description for a in requested),
            ))

        # Scene-aware permanent-marking clause (A + C) — exposed marks get the
        # skin-bound/geometry block; covered marks get only the clothing-truth
        # line. Ranked as an invariant: it carries the permanence and
        # anti-relocation directives, not merely design prose.
        marks_clause = _permanent_marks_clause(canon, scene, design_chars=design_chars)
        if marks_clause:
            parts.append((_RANK_INVARIANT, marks_clause))
        else:
            # Enriched legacy canon: positive presence for exposed authority regions.
            presence = _legacy_mark_presence_clause(canon, scene)
            if presence:
                parts.append((_RANK_INVARIANT, presence))

        # Anatomy bindings for marks the scene left unresolved, when the scene
        # text itself asks about markings. Complements the block above rather
        # than replacing it: that one answers "this skin is bare, put the mark
        # there", this one answers "wherever this skin turns out to be bare,
        # THIS mark and no other belongs there". Silent on every scene that does
        # not mention markings, so unrelated prompts compile byte-identically.
        binding_clause = _mark_binding_clause(canon, scene, budget=binding_budget)
        if binding_clause:
            parts.append((_RANK_INVARIANT, binding_clause))

        # Region-level occlusion. Runs on BOTH paths: a canon that carries bare
        # card evidence needs its covered regions named whether or not its marks
        # are structured (registering marks must not silently remove this).
        occlusion = _coverage_occlusion_clause(canon, scene)
        if occlusion:
            parts.append((_RANK_INVARIANT, occlusion))
        else:
            # Unstated scene: the conditional ink-on-fabric invariant. This is
            # what "Davies in his office - any tattoos that should be visible
            # are visible" needed — no garment named, so the clause above stays
            # silent while the prompt actively encourages torso ink.
            #
            # Only when the absolute clause did NOT fire: the two are the same
            # invariant at different confidence levels, and a scene that already
            # names its garments has the stronger, region-named wording above.
            # Emitting both just repeats the rule and inflates the prompt.
            conditional = _conditional_occlusion_clause(canon, scene)
            if conditional:
                parts.append((_RANK_INVARIANT, conditional))

        # Clean-skin authority (anti-migration) — emitted on BOTH paths whenever
        # the canon knows where marks are allowed to exist. Marked and markless
        # canons previously took entirely different prompt machinery; this clause
        # is the shared negative-truth layer both need.
        clean_clause = _clean_region_clause(canon, scene)
        if clean_clause:
            parts.append((_RANK_INVARIANT, clean_clause))

        return parts, marks_clause, clean_clause, binding_clause

    # Compress design DETAIL before shedding anything: full mark descriptions
    # and per-design binding names are the most expendable content in the
    # prompt, and shedding a whole clause to keep them would be backwards.
    compressed = False
    for design_chars, binding_budget in (
        (None, _MARK_BINDING_BUDGET),
        (140, _MARK_BINDING_BUDGET // 2),
        (70, 0),
    ):
        parts, marks_clause, clean_clause, binding_clause = _build(
            design_chars, binding_budget)
        prompt = _join_parts(parts, scene)
        if len(prompt) <= _PROMPT_CAP:
            break
        compressed = True
        logger.info(
            "CANON_PROMPT_DETAIL_COMPRESSED character_id=%s design_chars=%s "
            "binding_budget=%d len=%d",
            char_id, design_chars, binding_budget, len(prompt),
        )

    fitted = len(prompt) > _PROMPT_CAP
    if fitted:
        prompt = _fit_prompt(parts, scene, _PROMPT_CAP, char_id)

    logger.info(
        "CANON_PROMPT character_id=%s accessories=%d marks_clause=%s "
        "binding_clause=%s clean_skin_clause=%s scene_mentions_marks=%s "
        "detail_compressed=%s fitted=%s prompt_len=%d",
        canon.character_id, len(requested), bool(marks_clause),
        bool(binding_clause), bool(clean_clause),
        scene_requests_marks(scene), compressed, fitted, len(prompt),
    )
    if diagnostics is not None:
        diagnostics.update({
            # marks_clause is non-empty whenever the character has marks (it
            # carries the clothing-truth directive even with none exposed);
            # geometry_lines is the stronger signal — per-mark exposed anatomy.
            "marks_clause": bool(marks_clause),
            "geometry_lines": _MARKING_HEADER in (marks_clause or ""),
            "binding_clause": bool(binding_clause),
            "clean_skin_clause": bool(clean_clause),
            "scene_mentions_marks": scene_requests_marks(scene),
            "detail_compressed": compressed,
            "prompt_fitted": fitted,
            "prompt_len": len(prompt),
            "scene_len": len(scene),
            "scene_preserved": scene in prompt,
        })

    return prompt


def has_any_canon_content(canon: "CharacterIdentityCanon") -> bool:
    """Return True if the canon record has any face or body content."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    if face and any([
        face.face_front_image_url, face.face_description,
    ]):
        return True
    if body and any([
        body.body_front_image_url, body.body_description,
        body.permanent_body_marks,
    ]):
        return True
    return False

"""Scene-aware reference router — deterministic, keyword-based.

Selects and orders canon reference images based on detected camera
orientation and body-exposure signals in the scene prompt.

No LLM parsing. No probabilistic inference.
All detection uses exact substring matching against frozensets.

Public API:
  route_canon_refs(prompt, canon) → (list[str], SceneMeta)
  SceneMeta                        — structured scene metadata

Rollback: git checkout pre-p10-scene-router
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon

from app.services.canon_service import load_body_canon, load_face_canon

logger = logging.getLogger(__name__)


# ── Camera orientation signals ────────────────────────────────────────
# Detection priority (highest to lowest):
#   portrait_closeup > back > 3q > profile > full_body > front

_PORTRAIT_CLOSEUP_SIGNALS = frozenset({
    "close-up", "closeup", "close up", "close shot",
    "headshot", "head shot", "face only", "tight portrait",
})

_BACK_SIGNALS = frozenset({
    "back to camera", "from behind", "rear view", "seen from behind",
    "back view", "turning away", "walking away", "facing away",
    "showing back", "back turned",
})

_LEFT_3Q_SIGNALS = frozenset({
    "three-quarter left", "three quarter left", "3/4 left",
    "left three-quarter", "left 3/4", "3q left", "left 3q",
})

_RIGHT_3Q_SIGNALS = frozenset({
    "three-quarter right", "three quarter right", "3/4 right",
    "right three-quarter", "right 3/4", "3q right", "right 3q",
})

_LEFT_PROFILE_SIGNALS = frozenset({
    "left profile", "from the left", "profile from left",
    "profile left", "side profile left", "left-facing",
})

_RIGHT_PROFILE_SIGNALS = frozenset({
    "right profile", "from the right", "profile from right",
    "profile right", "side profile right", "right-facing",
})

_FULL_BODY_SIGNALS = frozenset({
    "full body", "full-body", "head to toe", "full length",
})

_FRONT_SIGNALS = frozenset({
    "facing camera", "facing forward", "facing front", "front view",
    "front facing", "front-facing", "looking at camera",
    "face on", "head on", "direct gaze",
})


# ── Exposure signals ──────────────────────────────────────────────────

_SHIRTLESS_EXPOSURE = frozenset({
    "shirtless", "bare-chested", "bare chest", "bare chested", "no shirt",
    "topless", "bare torso",
})

_SLEEVELESS_EXPOSURE = frozenset({
    "sleeveless", "tank top", "tank",
    # Same definitionally-sleeveless garments as _CROP_FULL_ARM, so
    # meta.exposure reports "sleeveless" for them and diagnostics match routing.
    "sports bra", "sports-bra", "bralette", "vest top", "singlet",
    "strappy top", "spaghetti strap", "halter top", "halterneck",
    "halter neck", "halter-neck", "halter dress",
})

_ROLLED_SLEEVE_EXPOSURE = frozenset({
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up",
})

_SHORT_SLEEVE_EXPOSURE = frozenset({
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
})

_LONG_SLEEVE_EXPOSURE = frozenset({
    "long sleeve", "long-sleeve", "long sleeved", "long-sleeved",
})

_JACKET_EXPOSURE = frozenset({
    "jacket", "leather jacket", "blazer",
})

_COAT_EXPOSURE = frozenset({
    "coat", "overcoat", "trenchcoat", "trench coat",
})

# S24I — exposure signal NAMES (from _detect_exposure) that genuinely bare skin.
# Only these promote an orientation-less scene to the body-led front route. The
# cover signals (long_sleeves, jacket, coat) are deliberately excluded: a covered
# scene must stay on the face-led fallback so a clothed body-truth card leads,
# never a bare-skin body_map / whole-body card pushing garments open.
_SKIN_EXPOSURE_NAMES = frozenset({
    "shirtless", "sleeveless", "rolled_sleeves", "short_sleeves",
})


# ── Provider reference cap ────────────────────────────────────────────
# Maximum references the provider consumes. The routed slot lists below may
# list one extra "if room" slot (e.g. front's face_expression); anything past
# this cap is dropped after weighting. Mirrors the [:6] cap at the call sites.

MAX_PROVIDER_REFS = 6


# ── P13: exposure-gated cropped-mark reference routing ────────────────
# When a scene exposes the skin region a permanent mark sits on, its high-
# fidelity crop (PermanentBodyMark.detail_crop_url or .reference_image_url) is routed ahead of the
# lower-priority whole-body/face variants. Whole-body cards average tattoo
# detail away; a tight crop preserves geometry. Covered marks are never routed.

# Cap on crops per scene — leaves room for body_front + body_map under the 6-cap.
_MAX_MARK_CROPS = 2

_CROP_FULL_ARM = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "sleeveless", "tank top", "tank",
    # "vest" was removed: in tailoring vocabulary a vest is the COVERED middle
    # layer of a three-piece suit ("suit vest", "waistcoat"), and the bare word
    # flipped formal suit scenes into exposed-arm routing (the Davies-era
    # false positive). The UK sleeveless-undershirt sense stays reachable via
    # "sleeveless", "tank top" and "muscle shirt" — an unambiguous exposure
    # reading requires one of those.
    "muscle shirt", "muscle tee", "camisole", "racerback",
    # Garments that are sleeveless BY DEFINITION — naming one is an unambiguous
    # statement that the arms are bare, exactly like "tank top". Each entry is a
    # phrase, not a bare noun, wherever the bare noun would collide: "sports bra"
    # and "bralette" (never "bra" — it is inside "bracelet"), "vest top" (never
    # "vest" — the Davies-era three-piece-suit false positive), "strappy top"
    # (never "strappy" — strappy sandals say nothing about sleeves).
    # ("halter" is NOT here as a bare noun — a horse is led by its halter. It is
    # reachable only as "halter top" / "halter neck" / "halterneck".)
    "sports bra", "sports-bra", "bralette", "vest top", "singlet",
    "strappy top", "spaghetti strap", "halter top", "halterneck",
    "halter neck", "halter-neck", "halter dress",
    "bare arms", "arms bare", "bare arm", "arms out", "arm out",
    "arms visible", "arm visible", "both arms visible", "arms exposed",
    "arm exposed", "exposed arms", "arms uncovered", "arms shown",
    "swimwear", "swimsuit", "swimming", "swimming pool", "poolside",
    "pool party", "at the pool", "in the pool", "bikini",
})
_CROP_FOREARM_ONLY = frozenset({
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up", "pushed-up sleeves", "pushed up sleeves",
    "rolled to the elbow", "rolled to the elbows", "rolled past the elbow",
    "rolled above the elbow", "sleeves up", "sleeve up",
    "forearm visible", "forearms visible", "forearm exposed", "forearms exposed",
    "forearms out", "bare forearm", "bare forearms", "forearms bare",
})
# Garments that USUALLY leave the arms bare but do not say so by definition:
# a crop top is a statement about LENGTH, a sundress about weight and cut, and
# either can have sleeves. They therefore expose the arms only when the scene
# names no arm-covering garment — "long-sleeved sundress" is covered.
_CROP_ARM_IF_UNCOVERED = frozenset({
    "crop top", "cropped top", "sundress", "sun dress",
})

# ── Arm-covering garment vocabulary (owned here, beside the exposure sets) ──
# Named garments that cover the upper arm AND forearm. This lives next to the
# exposure vocabulary rather than in card_coverage because it is one half of a
# single decision — arm_exposure_states() weighs the two against each other,
# and splitting them across modules is what let them drift before.
#
# Deliberately arm-only: a parka covers the torso too, but claiming torso
# coverage here would change card suppression for existing canons, which is
# outside this correction. Unclaimed regions stay covered_default, which
# suppresses nothing and routes nothing — conservative in both directions.
_COVER_ARM_SIGNALS = frozenset({
    "long sleeve", "long-sleeve", "long sleeved", "long-sleeved",
    "suit", "tuxedo", "blazer", "jacket", "coat", "sweater", "jumper",
    "hoodie", "turtleneck", "dress shirt", "gown",
    # Outerwear that is long-sleeved by construction. Added because the
    # contradiction rule below is only as good as its cover vocabulary: without
    # "parka", "a sports bra under a heavy winter parka" reads as bare arms.
    "parka", "anorak", "cardigan", "overcoat", "raincoat", "windbreaker",
    "sweatshirt", "pullover", "peacoat", "pea coat", "cloak", "poncho",
    # Wrapped garments with long, wide sleeves. Bare "robe" is deliberately
    # absent: it is a substring of "wardrobe".
    "kimono", "bathrobe", "dressing gown",
})

_CROP_NECK_EXPOSE = frozenset({
    "open collar", "open shirt", "shirt open", "unbuttoned", "v-neck", "v neck",
    "scoop neck", "low neckline", "deep neckline", "bare neck", "neck visible",
    "shirtless", "bare chest", "tank top", "sleeveless", "swimming",
    "swimming pool", "poolside",
})
_CROP_NECK_COVER = frozenset({
    "turtleneck", "high collar", "scarf", "buttoned-up", "buttoned up",
    "closed collar", "hood up", "balaclava",
})
_CROP_TORSO_EXPOSE = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "open shirt", "shirt open", "unbuttoned",
    "swimming", "swimming pool", "poolside", "swimwear", "bikini",
    # Swim garments contain the substring "suit"; naming them here lets the
    # exposure-first precedence in card_coverage.scene_region_states resolve
    # them as exposure before "suit" can read as formal covered clothing.
    "swimsuit", "bathing suit", "swim trunks",
})
_CROP_BACK_EXPOSE = frozenset({
    "shirtless", "bare back", "back visible", "from behind", "back view", "topless",
})


# Union of all skin-exposure signals (P14). Any of these implies the body is in
# frame with skin exposed, even when the prompt carries no camera-orientation
# keyword. Used to promote an otherwise-ambiguous scene to a front body shot so
# body-truth + exposed-mark crop routing engages (e.g. "open shirt, arms out at
# the pool" — a named acceptance scenario). Cover signals are deliberately
# excluded; per-region exposure is still gated by _mark_region_exposed.
_SKIN_EXPOSURE_PROMOTION = (
    _CROP_FULL_ARM | _CROP_FOREARM_ONLY | _CROP_NECK_EXPOSE | _CROP_TORSO_EXPOSE
)


# ── Structured anatomy is the only authority ──────────────────────────
#
# There was a ``_is_sleeve_mark`` helper here that searched a mark's LABEL and
# DESCRIPTION for the substring "sleeve" and, when it matched, granted an
# upper-arm mark forearm exposure as well.
#
# It is deleted rather than narrowed. Summer's butterfly piece was registered as
# ``left_upper_arm`` — shoulder to elbow, copied from the text legend on her own
# body-map card — but is LABELLED "Butterfly floral sleeve". The substring match
# widened its anatomy to the forearm, so a rolled-sleeve scene judged it exposed,
# described it as visible and routed its crop; the model then rendered it on the
# only bare arm skin in frame. A descriptive name silently redefined anatomy.
#
# The label happened to be right about the real tattoo and the region wrong (her
# cards show the work running shoulder to wrist; the region is now
# ``left_full_arm``), which is exactly why this must not be inferred from text:
# a label that guesses correctly today is still a guess. The canon FACT is fixed
# in the canon, not compensated for in the router.
#
# The structured vocabulary already draws this distinction with no text at all:
#   left_full_arm / right_full_arm  → shoulder to wrist (both segments)
#   left_upper_arm / right_upper_arm→ shoulder to elbow
#   left_forearm / right_forearm    → elbow to wrist
# A genuine full sleeve is a full-arm REGION, not an upper-arm region with a
# suggestive label. Free text stays what it should be: the design description
# injected into the prompt, with no authority over anatomy, side, exposure,
# crop routing or occlusion.


# ── Region-state vocabulary ───────────────────────────────────────────
# The four values every region state in this engine may take. Shared with
# card_coverage.scene_region_states, which returns the same vocabulary.
#
#   exposed          the scene resolves this skin as bare
#   covered_explicit the scene NAMES a garment that covers it
#   covered_default  the scene says nothing — conservative, unresolved
#   ambiguous        the scene says BOTH, and neither reading wins
#
# "ambiguous" and "covered_default" are both unresolved and both route nothing;
# they are kept distinct so diagnostics can tell "we were told nothing" from
# "we were told two contradictory things", and so the conditional occlusion
# clause (which fires on everything not exposed and not explicitly covered)
# still protects an ambiguous region.
STATE_EXPOSED = "exposed"
STATE_COVERED_EXPLICIT = "covered_explicit"
STATE_COVERED_DEFAULT = "covered_default"
STATE_AMBIGUOUS = "ambiguous"


def arm_exposure_states(prompt_lower: str) -> tuple[str, str]:
    """Return (upper_arm_state, forearm_state) for this scene.

    THE arm-exposure decision — the router's per-mark gate, the camera
    promotion and ``card_coverage.scene_region_states`` all call this, so they
    cannot drift into disagreeing about the same prompt.

    The rule that matters, and the reason this returns states rather than
    booleans: **when the scene provides credible evidence both ways, neither
    wins.** A definitionally sleeveless garment used to beat any cover word
    outright, on a layering argument ("jacket over a tank top") that has no
    notion of layer order — so "a sports bra under a heavy winter parka"
    resolved to bare arms, routed a crop, asserted bare skin, and invited ink
    onto a parka sleeve. Contradictory evidence now resolves to ``ambiguous``:
    route nothing, assert nothing bare, assert no explicit coverage either.

    Precedence, highest first:
      1. definitionally sleeveless garment + arm-covering garment → ambiguous
      2. definitionally sleeveless garment alone                  → exposed
      3. usually-sleeveless garment (crop top, sundress)          → exposed only
         if no arm-covering garment is named, else covered_explicit
      4. an arm-covering garment alone                            → covered_explicit
      5. nothing said                                             → covered_default

    Short/rolled-sleeve vocabulary is then applied to the FOREARM only, and it
    is deliberately NOT subject to the contradiction rule: "a long-sleeved
    shirt with the sleeves rolled up" is not a contradiction, it is a
    description of how forearms become bare. That vocabulary talks about the
    state of the sleeve; tier 1 talks about a different garment.

    No natural-language parsing, no layer-order inference: conservative
    ambiguity is the whole design.
    """
    bare_by_definition = any(s in prompt_lower for s in _CROP_FULL_ARM)
    bare_unless_covered = any(s in prompt_lower for s in _CROP_ARM_IF_UNCOVERED)
    forearm_bare = any(s in prompt_lower for s in _CROP_FOREARM_ONLY)
    covered = any(s in prompt_lower for s in _COVER_ARM_SIGNALS)

    if bare_by_definition:
        upper = STATE_AMBIGUOUS if covered else STATE_EXPOSED
    elif bare_unless_covered:
        upper = STATE_COVERED_EXPLICIT if covered else STATE_EXPOSED
    elif covered or forearm_bare:
        # ``forearm_bare`` here is short/rolled-sleeve vocabulary, which NAMES a
        # sleeve: "sleeves rolled up" and "t-shirt" both state that a garment
        # covers the shoulder and upper arm while leaving the forearm bare. That
        # is explicit coverage of the upper arm, not merely an unresolved
        # wardrobe, and saying so is what keeps an upper-arm-only mark from
        # being offered to the provider on a rolled-sleeve scene — the original
        # label-driven-anatomy failure, where the design was then painted onto
        # the only bare arm skin in frame (the forearm).
        upper = STATE_COVERED_EXPLICIT
    else:
        upper = STATE_COVERED_DEFAULT

    fore = STATE_EXPOSED if forearm_bare else upper
    return upper, fore


def _mark_region_exposed(body_region: str, prompt_lower: str) -> bool:
    """Return True when the scene exposes the skin region a mark sits on.

    Deterministic substring matching only — no inference. Conservative: when
    there is no positive exposure signal for a region it returns False so the
    crop is NOT routed (the whole-body cards still carry the covered mark).
    """
    region = (body_region or "").lower().strip().replace(" ", "_")
    # Tolerate position-first arm wording ("full_right_arm") → canonical
    # side-first form ("right_full_arm") so free-text region drift still matches.
    if region in ("full_right_arm", "full_left_arm"):
        region = "right_full_arm" if "right" in region else "left_full_arm"
    upper_state, fore_state = arm_exposure_states(prompt_lower)
    full_arm = upper_state == STATE_EXPOSED
    forearm = fore_state == STATE_EXPOSED

    # ── Arms ──
    if "forearm" in region or "lower_arm" in region:
        return bool(full_arm or forearm)
    if "upper_arm" in region:
        # Shoulder to elbow. Short/rolled sleeves leave only the FOREARM bare,
        # so an upper-arm mark stays covered; only a genuinely bare arm
        # (sleeveless, shirtless) exposes it. A mark that truly spans the whole
        # arm must say so structurally as a full-arm region below.
        return bool(full_arm)
    if region in ("left_full_arm", "right_full_arm", "left_arm", "right_arm"):
        # Shoulder to wrist: exposed when the arm is bare, and still partly
        # exposed when only the forearm shows (rolled sleeves reveal its lower
        # portion). This is the structured way to express a full sleeve.
        return bool(full_arm or forearm)
    # ── Neck / throat ──
    if region in ("neck", "throat"):
        if any(s in prompt_lower for s in _CROP_NECK_COVER):
            return False
        return any(s in prompt_lower for s in _CROP_NECK_EXPOSE)
    # ── Torso ──
    if region in ("chest", "sternum", "abdomen", "ribs", "side", "stomach"):
        return any(s in prompt_lower for s in _CROP_TORSO_EXPOSE)
    # ── Back ──
    if "back" in region:
        return any(s in prompt_lower for s in _CROP_BACK_EXPOSE)
    # ── Hands / face are visible unless a garment explicitly covers them ──
    # Default-exposed (the inverse of every region above), because bare hands
    # and an uncovered face are the norm. Gloves/mask are the only signals that
    # hide them, and honouring those keeps a gloved scene from routing a
    # knuckle-tattoo crop the frame cannot show.
    from app.services.card_coverage import (
        _COVER_FACE_SIGNALS,
        _COVER_HAND_SIGNALS,
    )

    if region in ("left_hand", "right_hand", "hand", "knuckles", "fingers",
                  "left_wrist", "right_wrist", "wrist"):
        return not any(s in prompt_lower for s in _COVER_HAND_SIGNALS)
    if region in (
        "face", "right_cheek", "left_cheek", "jaw", "forehead", "chin",
        "temple", "brow",
    ):
        return not any(s in prompt_lower for s in _COVER_FACE_SIGNALS)
    # Legs / other regions → conservative (not routed without explicit signal).
    return False


# Body-anchor slots: a routed tattoo crop must always be paired with at least
# one of these so the provider grounds the crop on anatomy rather than treating
# it as a free-floating symbol/accessory. Crops are never routed without one.
_BODY_ANCHOR_SLOTS = frozenset({
    "body_front", "body_map", "body_back", "body_left", "body_right",
})

# Face identity slots — used to identify the camera's primary face anchor so it
# leads the routed list (P14 Phase 3: body/crop refs must not overpower face).
_FACE_SLOTS = frozenset({
    "face_front", "face_left_3q", "face_right_3q", "face_profile", "face_expression",
})

# P14 Phase 1/2 — Body-truth dominance ordering.
# When a scene exposes a permanent mark, the *body truth* refs (whole-body
# anatomy + canonical marking placement) must precede the high-fidelity mark
# crop so the provider reads "this person with these tattoos" rather than
# isolating "a tattoo concept". The crop is supporting evidence only and is
# NEVER allowed to lead. body_front + body_map are pulled from the full canon
# (not just the camera route) so they are always present when the body is
# visible, joined by the orientation-matched side for the active camera.
_ORIENTATION_BODY: dict[str, str] = {
    "back": "body_back",
    "left_profile": "body_left",
    "left_3q": "body_left",
    "right_profile": "body_right",
    "right_3q": "body_right",
}


@dataclass
class MarkCropBinding:
    """Body-binding metadata travelling with a routed permanent-mark crop.

    Carries the anatomy the crop must be applied to, so the crop is interpreted
    as 'apply this marking to <region>/<side>' rather than 'include this object'.
    """
    url: str
    body_region: str
    side: str
    label: str
    visibility: str  # "exposed" — only exposed-region crops are ever routed
    # Audit-only provenance (no routing effect): which mark this crop came from
    # and which canon field supplied the URL (detail_crop_url | reference_image_url).
    mark_id: str = ""
    source: str = ""


def _mark_crop_visibility(
    body_region: str,
    prompt_lower: str,
    scene_states: dict[str, str] | None,
) -> tuple[str | None, str]:
    """How this mark's skin stands in this scene, and why.

    Returns ``(visibility, reason)`` where visibility is ``"exposed"``,
    ``"unresolved"`` or ``None`` (do not route a crop).

    ``exposed`` — the scene resolves that skin as bare.

    ``unresolved`` — the scene named no garment this region recognises, so
    coverage is unknown. **The crop routes anyway.** This is the correction the
    real Summer yellow-dress failures forced: the engine's uncertainty is not
    the provider's uncertainty. "Summer wearing a yellow summer dress" matched
    exactly one word of scene vocabulary — "dress", a torso-cover signal — so
    both arm regions resolved ``covered_default``, no mark was judged exposed,
    no crop routed, and the compiled prompt mentioned tattoos only in the
    negative. The provider then read the same sentence, correctly rendered a
    sleeveless dress, and painted the bare arms it had invented with clean
    skin. Withholding mark truth on an unresolved region is not conservative;
    it guarantees the marks vanish whenever the garment vocabulary has a gap,
    and garment words are unbounded while a character's marks are finite and
    already structured.

    Routing the scoped crop asserts nothing about bare skin — the prompt's
    binding clause states visibility conditionally, and the crop is bound to
    one region and side.

    Never routes when:
      * any region the mark occupies is EXPLICITLY covered — the hard
        invariant: a covered mark cannot route,
      * any region it occupies is AMBIGUOUS (contradictory garment evidence —
        conservative, same as covered),
      * the region cannot be mapped onto the coverage vocabulary at all, so
        coverage cannot be checked (matches mark_location_authority's veto).

    Deliberately NOT gated on whether the scene text mentions markings.
    Permanent canon exists whether or not the user says the word "tattoo".
    """
    if _mark_region_exposed(body_region, prompt_lower):
        return "exposed", "scene exposes this region"
    if scene_states is None:
        return None, "no scene coverage states available"
    from app.services.card_coverage import mark_region_groups

    groups = mark_region_groups(body_region)
    if not groups:
        return None, "region not mappable onto the coverage vocabulary"
    blocked = sorted(
        g for g in groups
        if scene_states.get(g) in (STATE_COVERED_EXPLICIT, STATE_AMBIGUOUS)
    )
    if blocked:
        return None, "region " + ", ".join(
            f"{g}={scene_states.get(g)}" for g in blocked
        )
    return "unresolved", "scene leaves this region unresolved"


def _collect_exposed_mark_crops(
    canon: "CharacterIdentityCanon",
    prompt_lower: str,
    camera: str,
    scene_states: dict[str, str] | None = None,
    decisions: list[dict] | None = None,
) -> list["MarkCropBinding"]:
    """Return body-bound crop records for marks whose skin this scene may show.

    Portrait close-ups never route body crops. The high-fidelity mark-detail
    card is preferred (detail_crop_url) with a fallback to the general reference
    photo (reference_image_url); marks with neither degrade gracefully (skipped).
    Capped at _MAX_MARK_CROPS. Each record preserves body_region / side / label /
    visibility so the crop stays bound to the correct anatomy downstream
    (binding metadata, #1).

    Exposed marks route as they always have. Marks whose regions the scene left
    unresolved also route, carrying ``visibility="unresolved"`` so no downstream
    consumer can read them as a claim that the skin is bare — see
    :func:`_mark_crop_visibility`.

    ``decisions`` collects a per-mark diagnostic record (region, side,
    visibility, crop availability, reason) so a future visual QA failure can be
    diagnosed from the stored generation record instead of replaying the
    compiler. Diagnostics only — it never affects routing.
    """
    if camera == "portrait_closeup":
        if decisions is not None:
            body = load_body_canon(canon)
            for m in (getattr(body, "permanent_body_marks", None) or []):
                decisions.append({
                    "mark_id": getattr(m, "id", "") or "",
                    "region": getattr(m, "body_region", "") or "",
                    "side": getattr(m, "side", "") or "",
                    "visibility": None,
                    "crop_available": bool(getattr(m, "detail_crop_url", None)
                                           or getattr(m, "reference_image_url", None)),
                    "crop_routed": False,
                    "reason": "portrait close-up routes no body crops",
                })
        return []
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return []
    # Evaluate every mark first, then fill the capped crop slots EXPOSED-FIRST.
    # Priority matters now that unresolved regions are eligible: a heavily marked
    # character can have more eligible marks than slots, and skin the scene
    # actually bares must never lose its crop to skin whose coverage is merely
    # unknown. Davies proved it — his genuinely visible hand marks were displaced
    # by an unresolved chest and forearm purely because those marks come first in
    # the canon list.
    candidates: list[tuple[object, str, str, str, bool]] = []
    for m in marks:
        # Prefer the dedicated close-up detail crop; fall back to a general ref.
        detail = getattr(m, "detail_crop_url", None)
        url = detail or getattr(m, "reference_image_url", None)
        visibility, reason = _mark_crop_visibility(
            getattr(m, "body_region", ""), prompt_lower, scene_states,
        )
        candidates.append((m, url or "", visibility or "", reason, bool(detail)))

    eligible = [c for c in candidates if c[1] and c[2]]
    # Stable within each group, so canon order still decides between two marks of
    # equal standing and the binding slice stays predictable.
    eligible.sort(key=lambda c: 0 if c[2] == "exposed" else 1)
    chosen = {id(c[0]) for c in eligible[:_MAX_MARK_CROPS]}

    crops: list[MarkCropBinding] = []
    for m, url, visibility, reason, has_detail in candidates:
        routed = id(m) in chosen
        if decisions is not None:
            decisions.append({
                "mark_id": getattr(m, "id", "") or "",
                "region": getattr(m, "body_region", "") or "",
                "side": getattr(m, "side", "") or "",
                "visibility": visibility or None,
                "crop_available": bool(url),
                "crop_routed": routed,
                "reason": (
                    reason if not visibility
                    else "no crop image on this mark" if not url
                    else reason if routed
                    else f"crop cap of {_MAX_MARK_CROPS} reached; "
                         "exposed marks take priority"
                ),
            })
        if not routed:
            continue
        # Side comes from the structured region when it encodes one, so the
        # crop's audit metadata cannot disagree with the anatomy the prompt
        # states (a canon may store region="right_forearm" with side="left").
        from app.services.canon_compiler import _mark_side

        crops.append(MarkCropBinding(
            url=url,
            body_region=getattr(m, "body_region", "") or "",
            side=_mark_side(m) or (getattr(m, "side", "") or ""),
            label=getattr(m, "label", "") or "",
            visibility=visibility,
            mark_id=getattr(m, "id", "") or "",
            source="detail_crop_url" if has_detail else "reference_image_url",
        ))
    return crops


# ── Why there is no placement-sheet exception here ────────────────────
# A previous iteration kept the bare body_map against the S24I suppression gate
# whenever a scene asked about markings, because the map is the only reference
# that shows which design sits on which side, and a sampled test swapped two
# designs across arms without it.
#
# It was removed in favour of routing each mark's own anatomically-scoped crop
# on the same unresolved path (_mark_crop_visibility). Same side evidence, one
# reference per mark instead of a whole-body bare sheet, and no bare torso or
# legs imported into a scene whose wardrobe was never stated — which is the
# reference-contamination class the card-coverage engine exists to prevent.
# The sampled swap was also measured BEFORE _mark_binding_clause existed, i.e.
# when the prompt asserted no anatomy at all; it does not establish that the
# bare sheet is needed now that both the crop and the binding line carry side.


def _has_covered_marks(
    canon: "CharacterIdentityCanon",
    prompt_lower: str,
    camera: str,
) -> bool:
    """True when the character has permanent marks and the scene exposes NONE.

    Drives S24I coverage-aware suppression of the bare-skin body_map placement
    sheet: when every mark sits under clothing for this scene, routing a bare
    tattoo diagram would push marks onto covered skin. The clothed body_front
    stays (it is covered body truth); only the inherently-bare body_map is
    dropped. Returns False for portrait_closeup (no body routed) and for
    mark-less characters (nothing to cover).
    """
    if camera == "portrait_closeup":
        return False
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return False
    for m in marks:
        if _mark_region_exposed(getattr(m, "body_region", ""), prompt_lower):
            return False
    return True


def _merge_crops(
    camera: str,
    slots_avail: list[str],
    slot_urls: dict[str, str],
    crops: list["MarkCropBinding"],
) -> tuple[list[str], list[str]]:
    """Order refs so BODY TRUTH dominates and mark crops are supporting only.

    P14 Phase 1/2 — body-truth dominance. The provider must see "this person
    with these exact tattoos", not "a tattoo concept". The routed order is:

        1. primary face anchor   — face identity leads (Phase 3); never buried
        2. body truth block      — body_front, body_map, orientation side,
                                    final card (in that dominance order)
        3. mark crops            — SUPPORTING evidence only, never primary
        4. remaining face geometry

    body_front + body_map are pulled from the full canon (slot_urls), not just
    the camera route, so they are always present when the body is visible and a
    crop is about to be routed (Phase 2: "never allow exposed-mark routing
    without body truth present").

    Routing guarantee (#3): a tattoo crop is NEVER routed alone or ahead of the
    leading body anchors. If no real body anchor is available the crops are
    dropped and plain slot routing is returned, so the provider always has
    anatomy to bind onto.

    P15b — OpenAI rolled-sleeve forearm fidelity. The leading anchors
    (body_front, body_map, orientation side) stay first to dominate and prevent
    floating, but the exposed-mark crops are spliced in BEFORE the holistic
    final_character_card. OpenAI's images.edit is position-weighted and
    first-image-dominant; behind the holistic card the crop was too weak and the
    forearm tattoo under-rendered. Promoting the crop ahead of the holistic card
    (still behind the two grounding anchors) restores OpenAI forearm fidelity
    without weakening body-truth dominance, reopening over-forcing, or affecting
    Google (which weights all refs evenly).

    Returns (slot_tokens, urls); crop entries use the token 'mark_crop'. Crops
    stay contiguous and in input order, so the caller's crops[:crop_count]
    binding slice remains correct after the provider cap.
    """
    plain_slots = slots_avail[:MAX_PROVIDER_REFS]
    plain_urls = [slot_urls[s] for s in plain_slots]

    # Leading body anchors in dominance priority (Phase 1): front body truth
    # first, canonical marking-placement map second, orientation-matched side
    # third. These stay AHEAD of the crops as the anti-float grounding anchors.
    seen: set[str] = set()
    body_anchors: list[str] = []
    for s in ("body_front", "body_map", _ORIENTATION_BODY.get(camera)):
        if s and s in slot_urls and s not in seen:
            body_anchors.append(s)
            seen.add(s)

    # Holistic identity card — support only; demoted to AFTER the crops (P15b).
    holistic = [s for s in ("final_character_card",)
                if s in slot_urls and s not in seen]
    for s in holistic:
        seen.add(s)

    # Guarantee (#3): never route a crop without a real body anchor (the holistic
    # card alone is not anatomy to bind onto). Drop crops → plain routing.
    if not any(s in _BODY_ANCHOR_SLOTS for s in body_anchors):
        return plain_slots, plain_urls

    # Face dominance (Phase 3): lead with the camera's primary face anchor so the
    # body-truth block and crops never overpower facial identity.
    primary_face = [s for s in slots_avail if s in _FACE_SLOTS][:1]
    for s in primary_face:
        seen.add(s)
    rest_face = [s for s in slots_avail if s in _FACE_SLOTS and s not in seen]

    ordered = (
        primary_face                    # 1. face identity anchor
        + body_anchors                  # 2. leading body anchors (anti-float)
        + ["mark_crop"] * len(crops)    # 3. exposed crops — ahead of holistic card
        + holistic                      # 4. holistic identity card — support only
        + rest_face                     # 5. remaining face geometry
    )

    crop_iter = iter(crops)
    out_slots: list[str] = []
    out_urls: list[str] = []
    for s in ordered:
        out_urls.append(next(crop_iter).url if s == "mark_crop" else slot_urls[s])
        out_slots.append(s)
        if len(out_urls) >= MAX_PROVIDER_REFS:
            break
    return out_slots, out_urls


# ── P11 orientation-aware weighting: camera → priority-ordered slots ───
# Slots are listed in descending reference priority for each camera. P10
# detection chooses the camera; this layer chooses the order in which that
# camera's slots reach the provider. Missing canon slots are skipped
# silently; the surviving list is capped at MAX_PROVIDER_REFS.
#
# Weighting intent per camera:
#   front/full_body — body truth first, exact face reinforced, identity
#                     compression card early, tattoo placement retained,
#                     support geometry last (face_expression only "if room")
#   back            — back anatomy dominates; body truth preserved; face
#                     retained as a lower-priority identity anchor
#   left/right      — that side's anatomy + matching 3q face dominate
#   portrait        — facial identity dominates (face-only stack)

# S24AK — v2 cards are spliced in by priority, NOT appended blindly. They sit
# behind the proven legacy core in each route so a populated legacy canon keeps
# its exact pre-v2 top-6 ordering; the v2 cards only reach the provider when a
# slot is sparse or room remains under MAX_PROVIDER_REFS. face_profile is the
# exception: it ranks high in profile cameras (its matching face angle).
_ROUTES: dict[str, list[str]] = {
    # S24I face-dominance: face_front leads, then body truth (body_front, then the
    # marking-placement sheet), mirroring _merge_crops' face-first ordering so the
    # whole-body card never overpowers facial identity on the plain (no-crop) route.
    "front": [
        "face_front", "body_front", "final_character_card",
        "body_map", "face_left_3q", "face_right_3q", "face_profile", "face_expression",
        "torso_front", "standing_relaxed", "seated_relaxed", "torso_side",
    ],
    "full_body": [
        "face_front", "body_front", "final_character_card",
        "body_map", "face_left_3q", "face_right_3q", "face_profile", "face_expression",
        "standing_relaxed", "torso_front", "seated_relaxed", "torso_side",
    ],
    "back": [
        "body_back", "final_character_card", "body_map",
        "face_front", "face_left_3q", "face_right_3q", "face_profile",
        "standing_relaxed", "seated_relaxed",
    ],
    "left_profile": [
        "body_left", "face_left_3q", "face_profile", "final_character_card",
        "body_map", "face_front", "face_right_3q",
        "torso_side", "standing_relaxed",
    ],
    "right_profile": [
        "body_right", "face_right_3q", "face_profile", "final_character_card",
        "body_map", "face_front", "face_left_3q",
        "torso_side", "standing_relaxed",
    ],
    "left_3q": [
        "body_left", "face_left_3q", "final_character_card",
        "body_map", "face_front", "face_right_3q",
        "face_profile", "torso_side", "standing_relaxed",
    ],
    "right_3q": [
        "body_right", "face_right_3q", "final_character_card",
        "body_map", "face_front", "face_left_3q",
        "face_profile", "torso_side", "standing_relaxed",
    ],
    # P14 Phase 3 — face dominance hardening. A close-up is pure facial identity:
    # lead with face_front, reinforce with both 3/4 geometry refs (matching face),
    # then the v2 profile card, the optional expression card, then the holistic
    # card. No body routing.
    "portrait_closeup": [
        "face_front", "face_left_3q", "face_right_3q", "face_profile",
        "face_expression", "final_character_card",
    ],
}


# ── Scene metadata ────────────────────────────────────────────────────

@dataclass
class SceneMeta:
    """Structured metadata describing the detected scene."""
    camera: str                                       # detected orientation or "unknown"
    exposure: list[str] = field(default_factory=list) # active exposure signal names
    routed: bool = False                              # True = routing applied; False = fallback
    route_slots: list[str] = field(default_factory=list)  # slot names in returned order
    mark_crops: int = 0                               # exposed permanent-mark crops routed
    # Body-binding metadata for the crops actually routed (#1): each carries the
    # body_region/side/label the crop must be applied to, so the preserved
    # binding survives routing and is auditable downstream.
    mark_crop_bindings: list["MarkCropBinding"] = field(default_factory=list)
    # S24I: True when the bare-skin body_map placement sheet was dropped because
    # the character has marks and the scene covers all of them (audit only).
    # Since the CANON SKIN/CLOTHING sprint this is also True when body_map was
    # suppressed by mark-INDEPENDENT card-coverage conflict (Davies).
    body_map_suppressed: bool = False
    # ── Card-coverage audit (CANON SKIN/CLOTHING sprint) ──────────────
    # Region → "exposed" | "covered_explicit" | "covered_default" for this scene.
    scene_coverage: dict[str, str] = field(default_factory=dict)
    # Body-bearing slots dropped because their depicted skin conflicts with the
    # scene's explicitly covered regions (Davies bleed-through prevention).
    coverage_suppressed: list[str] = field(default_factory=list)
    # Declared cards fully compatible with the scene's coverage.
    coverage_compatible: list[str] = field(default_factory=list)
    # Declared cards bare in a covered region but also in an exposed one (kept).
    coverage_partial: list[str] = field(default_factory=list)
    # Legacy cards with no coverage metadata — routed exactly as before, but
    # identified so diagnostics can tell unknown from verified-compatible.
    coverage_unknown: list[str] = field(default_factory=list)
    # The conflicting card retained as the body anchor when EVERY body card
    # conflicted (all-bare legacy canon + covered scene). Recorded, never
    # silently treated as compatible.
    coverage_conflict_anchor: str | None = None
    # ── Per-mark routing decisions (diagnostics only) ─────────────────
    # One record per registered permanent mark: mark_id, region, side,
    # visibility ("exposed" | "unresolved" | None), crop_available, crop_routed
    # and the reason. Exists so a visual-QA failure can be diagnosed from the
    # persisted generation record instead of replaying the compiler by hand —
    # which is exactly what the Summer yellow-dress investigation had to do.
    # Never read by routing.
    mark_decisions: list[dict] = field(default_factory=list)


# ── Card-coverage integration (CANON SKIN/CLOTHING sprint) ────────────
# Anchor priority when EVERY body-bearing card conflicts with a covered scene:
# the strongest single body anchor is retained (identity grounding must never
# drop to zero — the same principle the Angelo provider work enforced). Whole-
# body truth first; the inherently-bare body_map is the last resort.
_ANCHOR_PRIORITY = (
    "body_front", "torso_front", "standing_relaxed", "final_character_card",
    "body_left", "body_right", "body_back", "seated_relaxed", "torso_side",
    "body_map",
)


def _coverage_plan(
    canon: "CharacterIdentityCanon",
    slot_urls: dict[str, str],
    prompt_lower: str,
    camera: str | None,
) -> tuple[dict[str, str], dict, set[str], str | None, bool]:
    """Compute the scene/card coverage decision for this routing pass.

    Returns (scene_states, views, suppressed_slots, conflict_anchor,
    declared_present).

    * ``conflicting`` cards (bare skin only where the scene is EXPLICITLY
      covered) are suppressed — unless suppression would leave no body-bearing
      card at all, in which case the single strongest conflicting card is
      retained as ``conflict_anchor`` and recorded, never re-labelled
      compatible (legacy all-bare canons, requirement: no total body-grounding
      loss).
    * ``unknown`` (legacy, no metadata) cards are never suppressed — absent
      metadata must not be read as bare OR as clothed.
    * Portrait close-ups route no body evidence, so no suppression applies.
    * Mark-INDEPENDENT by design: Davies proved permanent_body_marks can be
      empty while the cards are covered in tattoos.
    """
    from app.services.card_coverage import classify_cards, scene_region_states

    scene_states = scene_region_states(prompt_lower)
    if camera == "portrait_closeup":
        return scene_states, {}, set(), None, False

    body = load_body_canon(canon)
    views = classify_cards(body, list(slot_urls), scene_states)
    declared_present = any(v.source == "declared" for v in views.values())

    conflicting = [s for s, v in views.items() if v.classification == "conflicting"]
    survivors = [s for s in views if s not in conflicting]
    suppressed = set(conflicting)
    conflict_anchor: str | None = None
    if conflicting and not survivors:
        ordered = [s for s in _ANCHOR_PRIORITY if s in conflicting]
        conflict_anchor = ordered[0] if ordered else sorted(conflicting)[0]
        suppressed.discard(conflict_anchor)
    return scene_states, views, suppressed, conflict_anchor, declared_present


def _reorder_body_slots(slots: list[str], views: dict) -> list[str]:
    """Stable-reorder body-bearing slots by coverage preference.

    Compatible clothed/silhouette evidence takes the earliest body positions,
    then scene-useful partials, then legacy unknowns — face slots keep their
    exact positions (face grounding is non-negotiable). Applied only when at
    least one DECLARED card exists, so purely-legacy canons keep today's
    ordering byte-for-byte.
    """
    from app.services.card_coverage import coverage_rank
    from app.schemas.canon import CARD_COVERAGE_SLOTS

    body_idx = [i for i, s in enumerate(slots) if s in CARD_COVERAGE_SLOTS]
    if len(body_idx) < 2:
        return slots
    ranked = sorted(
        (slots[i] for i in body_idx),
        key=lambda s: coverage_rank(views[s]) if s in views else 3,
    )
    out = list(slots)
    for i, s in zip(body_idx, ranked):
        out[i] = s
    return out


def _fill_coverage_meta(meta: "SceneMeta", scene_states, views, suppressed, anchor) -> None:
    meta.scene_coverage = dict(scene_states)
    meta.coverage_suppressed = sorted(suppressed)
    meta.coverage_compatible = sorted(
        s for s, v in views.items() if v.classification == "compatible" and v.source == "declared"
    )
    meta.coverage_partial = sorted(
        s for s, v in views.items() if v.classification == "partial"
    )
    meta.coverage_unknown = sorted(
        s for s, v in views.items() if v.classification == "unknown"
    )
    meta.coverage_conflict_anchor = anchor
    if "body_map" in suppressed:
        meta.body_map_suppressed = True


# ── Internal helpers ──────────────────────────────────────────────────

def _get_canon_slot_urls(canon: "CharacterIdentityCanon") -> dict[str, str]:
    """Build a slot_name → url mapping for all populated canon image slots."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    slots: dict[str, str] = {}

    if face:
        for slot, attr in (
            ("face_front",      "face_front_image_url"),
            ("face_left_3q",    "face_left_3q_image_url"),
            ("face_right_3q",   "face_right_3q_image_url"),
            ("face_profile",    "face_profile_image_url"),       # v2 (S24AK)
            ("face_expression", "face_expression_image_url"),
        ):
            url = getattr(face, attr, None)
            if url:
                slots[slot] = url

    if body:
        for slot, attr in (
            ("body_front",           "body_front_image_url"),
            ("body_left",            "body_left_image_url"),
            ("body_right",           "body_right_image_url"),
            ("body_back",            "body_back_image_url"),
            ("body_map",             "body_map_image_url"),
            ("final_character_card", "final_character_card_image_url"),
            ("torso_front",          "torso_front_image_url"),       # v2 (S24AK)
            ("torso_side",           "torso_side_image_url"),        # v2 (S24AK)
            ("standing_relaxed",     "standing_relaxed_image_url"),  # v2 (S24AK)
            ("seated_relaxed",       "seated_relaxed_image_url"),    # v2 (S24AK)
        ):
            url = getattr(body, attr, None)
            if url:
                slots[slot] = url

    return slots


def slot_names_for_urls(
    canon: "CharacterIdentityCanon",
    urls: list[str],
) -> list[str]:
    """Reverse-map reference URLs to their canon slot names. Audit only.

    ``SceneMeta.route_slots`` is populated only when a camera orientation was
    detected; the ambiguous-prompt fallback returns an empty list even though it
    still selected real slots. Diagnostics need the slot names on BOTH paths, so
    this rebuilds them from the canon slot table without touching routing.

    A URL occupying several slots (canon slots legitimately share a card) maps to
    the first slot in ``_get_canon_slot_urls`` order, which is deterministic. A
    URL that is not a canon slot maps to ``"unknown"`` — on the fallback path
    that is the only possibility, since permanent-mark crops are routed solely
    when a camera was detected and are already named in ``route_slots``.
    """
    reverse: dict[str, str] = {}
    for slot, url in _get_canon_slot_urls(canon).items():
        reverse.setdefault(url, slot)
    return [reverse.get(u, "unknown") for u in urls]


def _detect_camera(prompt_lower: str) -> str | None:
    """Detect camera orientation from a lowercased prompt.

    Returns an orientation string, or None when the prompt is ambiguous
    (no detectable orientation signal).

    Priority: portrait_closeup > back > 3q > profile > full_body > front.
    """
    if any(s in prompt_lower for s in _PORTRAIT_CLOSEUP_SIGNALS):
        return "portrait_closeup"
    if any(s in prompt_lower for s in _BACK_SIGNALS):
        return "back"
    if any(s in prompt_lower for s in _LEFT_3Q_SIGNALS):
        return "left_3q"
    if any(s in prompt_lower for s in _RIGHT_3Q_SIGNALS):
        return "right_3q"
    if any(s in prompt_lower for s in _LEFT_PROFILE_SIGNALS):
        return "left_profile"
    if any(s in prompt_lower for s in _RIGHT_PROFILE_SIGNALS):
        return "right_profile"
    if any(s in prompt_lower for s in _FULL_BODY_SIGNALS):
        return "full_body"
    if any(s in prompt_lower for s in _FRONT_SIGNALS):
        return "front"
    return None  # ambiguous → fallback


def _detect_exposure(prompt_lower: str) -> list[str]:
    """Return list of active body-exposure signal names."""
    active: list[str] = []
    checks = (
        ("shirtless",     _SHIRTLESS_EXPOSURE),
        ("sleeveless",    _SLEEVELESS_EXPOSURE),
        ("rolled_sleeves", _ROLLED_SLEEVE_EXPOSURE),
        ("short_sleeves", _SHORT_SLEEVE_EXPOSURE),
        ("long_sleeves",  _LONG_SLEEVE_EXPOSURE),
        ("jacket",        _JACKET_EXPOSURE),
        ("coat",          _COAT_EXPOSURE),
    )
    for name, signals in checks:
        if any(s in prompt_lower for s in signals):
            active.append(name)
    return active


def _resolve_route(
    camera: str,
    slot_urls: dict[str, str],
    drop_slots: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """Resolve a camera route to (urls, slot_names) for available canon slots.

    Slots are taken in the camera's weighted priority order; absent canon
    slots are skipped, any slot in ``drop_slots`` is suppressed (S24I coverage
    gate), and the surviving list is capped at MAX_PROVIDER_REFS.
    """
    route_slots = _ROUTES.get(camera, _ROUTES["front"])
    slots_hit = [s for s in route_slots if s in slot_urls and s not in drop_slots][:MAX_PROVIDER_REFS]
    urls = [slot_urls[s] for s in slots_hit]
    return urls, slots_hit


# ── Public API ────────────────────────────────────────────────────────

def routing_diagnostics(meta: "SceneMeta") -> dict:
    """Flatten a SceneMeta into persistable generation diagnostics.

    Exists because the Summer yellow-dress investigation could only establish
    what had been sent to the provider by replaying the whole compiler against
    the live canon. Everything needed to answer "what did we actually supply,
    and why?" is recorded here instead.

    Diagnostics only. Contains no secrets, no image bytes and no URLs — slot
    names and structured decisions are enough to reconstruct the routing, and
    reference URLs are already logged separately with query strings stripped.
    """
    return {
        "route_camera": meta.camera,
        "route_routed": meta.routed,
        "route_slots": list(meta.route_slots),
        "route_refs": len(meta.route_slots) or None,
        "scene_coverage": dict(meta.scene_coverage),
        "coverage_suppressed": list(meta.coverage_suppressed),
        "coverage_conflict_anchor": meta.coverage_conflict_anchor,
        "body_map_suppressed": meta.body_map_suppressed,
        "mark_crops_routed": meta.mark_crops,
        "mark_decisions": list(meta.mark_decisions),
    }


def route_canon_refs(
    prompt: str,
    canon: "CharacterIdentityCanon",
) -> tuple[list[str], SceneMeta]:
    """Select and order canon reference images for a scene prompt.

    Returns (urls, meta):
      urls — prioritised list of reference image URLs to send to the provider.
      meta — SceneMeta with camera orientation, exposure signals, and audit data.

    Routing is deterministic: keyword detection maps the prompt to a camera
    orientation, which selects a fixed slot priority list. Only canon slots
    that have URLs set are included; missing slots are silently skipped.

    Fallback: when the prompt has no detectable camera orientation the
    function returns the P8 reordered canonical sequence from
    collect_canon_reference_urls (meta.routed=False, meta.camera="unknown").
    """
    from app.services.canon_compiler import collect_canon_reference_urls

    prompt_lower = prompt.lower()
    slot_urls = _get_canon_slot_urls(canon)
    camera = _detect_camera(prompt_lower)
    exposure = _detect_exposure(prompt_lower)
    char_id = getattr(canon, "character_id", "?")

    # A skin-described scene without an explicit orientation keyword is treated as
    # a front-facing body shot so exposure-gated crop routing can engage
    # ("open shirt, arms out at the pool"). S24I: only GENUINE skin-exposure cues
    # promote — cover signals (long_sleeves / jacket / coat) must NOT, or a
    # covered scene would be forced onto the body-led route and push a bare card
    # ahead of the face. Cover-only and truly ambiguous prompts fall back to the
    # face-led canonical ordering.
    arm_upper_state, _arm_fore_state = arm_exposure_states(prompt_lower)
    skin_exposed = [e for e in exposure if e in _SKIN_EXPOSURE_NAMES]
    if arm_upper_state != STATE_EXPOSED:
        # A sleeveless GARMENT word cannot promote a scene whose arm exposure it
        # does not actually resolve. "A sports bra under a heavy winter parka"
        # sets the "sleeveless" exposure signal, but the arms are ambiguous, and
        # promoting would push a bare card ahead of the face on a scene that may
        # well be covered — the exact thing the cover-signals rule below forbids.
        skin_exposed = [e for e in skin_exposed if e != "sleeveless"]
    if camera is None and (
        skin_exposed
        or any(s in prompt_lower for s in _SKIN_EXPOSURE_PROMOTION)
        # Conditionally-sleeveless garments promote only when they actually
        # resolve to bare arms — a "long-sleeved sundress" must stay on the
        # face-led fallback like any other covered scene.
        or arm_upper_state == STATE_EXPOSED
    ):
        camera = "front"

    # ── Card-coverage plan (CANON SKIN/CLOTHING) — mark-independent ──
    # Which body-bearing cards depict skin the scene explicitly covers?
    # Computed BEFORE the mark gate below because Davies proved the two are
    # independent: his cards are covered in tattoos while permanent_body_marks
    # is empty.
    scene_states, cov_views, suppressed, conflict_anchor, declared_present = (
        _coverage_plan(canon, slot_urls, prompt_lower, camera)
    )

    # S24I coverage gate (unchanged, mark-driven): when the character has marks
    # and this scene exposes none of them, the bare-skin body_map placement
    # sheet is suppressed on every path — including covered_default scenes,
    # which the mark-independent plan deliberately leaves alone.
    bmap_present = "body_map" in slot_urls
    covered = _has_covered_marks(canon, prompt_lower, camera)
    if covered and bmap_present:
        suppressed.add("body_map")
        if conflict_anchor == "body_map":
            conflict_anchor = None
    body_map_suppressed = "body_map" in suppressed

    # Per-mark routing decisions, collected for diagnostics only. Whether the
    # scene text mentions markings is recorded (below) but gates NOTHING:
    # permanent canon exists whether or not the user says the word "tattoo".
    mark_decisions: list[dict] = []

    if camera is None:
        fallback_urls = collect_canon_reference_urls(canon)
        if suppressed or declared_present:
            from app.services.card_coverage import coverage_rank
            from app.schemas.canon import CARD_COVERAGE_SLOTS
            names = slot_names_for_urls(canon, fallback_urls)
            pairs = [
                (n, u) for n, u in zip(names, fallback_urls) if n not in suppressed
            ]
            if declared_present:
                # Stable preference reorder among body-card positions only —
                # face reference positions are untouched.
                body_idx = [
                    i for i, (n, _) in enumerate(pairs) if n in CARD_COVERAGE_SLOTS
                ]
                ranked = sorted(
                    (pairs[i] for i in body_idx),
                    key=lambda p: coverage_rank(cov_views[p[0]]) if p[0] in cov_views else 3,
                )
                for i, p in zip(body_idx, ranked):
                    pairs[i] = p
            fallback_urls = [u for _, u in pairs]

        # ── Ambiguous-prompt mark crops ───────────────────────────────
        # A vague natural prompt ("Davies in his office") detects no camera and
        # therefore used to route NO permanent-mark evidence at all: the crop
        # splice lived only on the camera path. That is the common case for
        # real users, and it is why an always-visible hand marking could be
        # declared, asserted in the prompt, and still have no high-fidelity
        # reference behind it.
        #
        # Exposure gating is unchanged and per-mark, so only marks the scene
        # actually exposes are eligible — a covered chest or sleeved arm still
        # routes nothing here. The ordering reuses _merge_crops, the same
        # proven arrangement the camera path uses (face anchor leads, body
        # truth next, crops as supporting evidence, never leading), rather
        # than inventing a second ordering: no orientation is passed, so no
        # side card is pulled in. Its body-anchor guarantee still applies, so
        # crops can never route without anatomy to bind onto.
        crop_count = 0
        routed_bindings: list["MarkCropBinding"] = []
        crop_slots: list[str] = []
        crops = _collect_exposed_mark_crops(
            canon, prompt_lower, camera, scene_states, mark_decisions)
        if crops:
            names = slot_names_for_urls(canon, fallback_urls)
            visible: dict[str, str] = {}
            for n, u in zip(names, fallback_urls):
                if n != "unknown":
                    visible.setdefault(n, u)
            slots_avail = list(visible)
            merged_slots, merged_urls = _merge_crops(camera, slots_avail, visible, crops)
            if "mark_crop" in merged_slots:
                fallback_urls = merged_urls
                crop_slots = merged_slots
                crop_count = merged_slots.count("mark_crop")
                routed_bindings = crops[:crop_count]

        meta = SceneMeta(
            camera="unknown",
            exposure=exposure,
            # routed stays False: no camera orientation was detected. The crop
            # splice does not change that, only which references were chosen.
            routed=False,
            # Populated ONLY when crops were spliced. The list no longer equals
            # the static ordering then, and reverse-mapping a crop URL through
            # slot_names_for_urls would label it "unknown" — diagnostics would
            # silently misreport the reference set.
            route_slots=crop_slots,
            mark_crops=crop_count,
            mark_crop_bindings=routed_bindings,
            body_map_suppressed=body_map_suppressed,
            mark_decisions=mark_decisions,
        )
        _fill_coverage_meta(meta, scene_states, cov_views, suppressed, conflict_anchor)
        logger.info(
            "SCENE_ROUTER char=%s camera=unknown fallback=true exposure=%s refs=%d "
            "crops=%d body_map_suppressed=%s coverage_suppressed=%s coverage_unknown=%s "
            "conflict_anchor=%s",
            char_id, exposure, len(fallback_urls), crop_count, body_map_suppressed,
            meta.coverage_suppressed, meta.coverage_unknown,
            conflict_anchor or "-",
        )
        return fallback_urls, meta

    # P13: exposure-gated cropped-mark routing. When the scene exposes a mark's
    # region, splice its high-fidelity crop ahead of lower-priority refs while
    # guaranteeing body_front + body_map survive. Coverage-suppressed slots are
    # filtered from the candidate pool first (structured marks REFINE routing;
    # they no longer gate the coverage decision).
    crops = _collect_exposed_mark_crops(
        canon, prompt_lower, camera, scene_states, mark_decisions)
    slot_urls_visible = {s: u for s, u in slot_urls.items() if s not in suppressed}
    if crops:
        route_slots = _ROUTES.get(camera, _ROUTES["front"])
        slots_avail = [s for s in route_slots if s in slot_urls_visible]
        slots_hit, urls = _merge_crops(camera, slots_avail, slot_urls_visible, crops)
        crop_count = slots_hit.count("mark_crop")
        # Crops are spliced contiguously right after the lead ref, so the first
        # crop_count bindings are exactly the ones that survived the cap (#1/#3).
        routed_bindings = crops[:crop_count]
    else:
        route_slots = _ROUTES.get(camera, _ROUTES["front"])
        slots_all = [s for s in route_slots if s in slot_urls_visible]
        if declared_present:
            slots_all = _reorder_body_slots(slots_all, cov_views)
        slots_hit = slots_all[:MAX_PROVIDER_REFS]
        urls = [slot_urls_visible[s] for s in slots_hit]
        crop_count = 0
        routed_bindings = []

    meta = SceneMeta(
        camera=camera,
        exposure=exposure,
        routed=True,
        route_slots=slots_hit,
        mark_crops=crop_count,
        mark_crop_bindings=routed_bindings,
        body_map_suppressed=body_map_suppressed,
        mark_decisions=mark_decisions,
    )
    _fill_coverage_meta(meta, scene_states, cov_views, suppressed, conflict_anchor)
    logger.info(
        "SCENE_ROUTER char=%s camera=%s routed=true exposure=%s slots=%s refs=%d "
        "crops=%d body_map_suppressed=%s coverage_suppressed=%s "
        "coverage_compatible=%s coverage_unknown=%s conflict_anchor=%s",
        char_id, camera, exposure, slots_hit, len(urls), crop_count,
        body_map_suppressed, meta.coverage_suppressed, meta.coverage_compatible,
        meta.coverage_unknown, conflict_anchor or "-",
    )
    return urls, meta

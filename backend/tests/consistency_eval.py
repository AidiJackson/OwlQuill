"""P14 — Character Consistency mini eval harness (fast, deterministic).

A lightweight, repeatable regression harness for the beta-blocker consistency
sprint. It is NOT a GPU/visual eval — it cannot call image providers in this
environment. Instead it scores the *routing + prompt contract* that PREDICTS
each visual outcome, because that contract is exactly what P11–P14 changed and
what regresses silently:

    Face identity   ← is a face anchor routed, and does it lead?
    Body identity   ← are body-truth refs (front/side/map) routed when visible?
    Tattoo fidelity ← exposed marks grounded on body truth + crop + binding clause
    Clothing truth  ← covered marks NOT leaked into refs; clothing directive present

This is a deterministic proxy. The same character × scene matrix is the drop-in
template a human uses to score real generations later (replace `score_case`
with manual 0–5 scores from generated images). Hidden marks score N/A on tattoo
fidelity — they are never penalised (per spec).

Run standalone:   python -m tests.consistency_eval     (from backend/)
Gate test:        tests/test_consistency_harness.py
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from statistics import mean
from typing import Optional

from app.schemas.canon import BodyCanonData, FaceCanonData, PermanentBodyMark
from app.services.canon_compiler import compile_canon_prompt
from app.services.scene_router import (
    _MAX_MARK_CROPS,
    _mark_region_exposed,
    route_canon_refs,
)

# Score sentinel for dimensions that don't apply to a case (e.g. tattoo fidelity
# for an unmarked control character, or any body dim in a face-only portrait).
NA = None

# Acceptance gate from the sprint spec.
HARD_FAIL_GATE = 0.05  # hard-fail rate must be < 5%

# Prompt-clause fingerprints (lowercased) the compiler must emit.
_SKIN_BOUND_FINGERPRINT = "permanent markings are immutable skin-bound anatomy"
_GEOMETRY_FINGERPRINT = "reproduce each marking's exact shape"
_CLOTHING_FINGERPRINT = "permanent markings obey scene clothing"
_HIDDEN_FINGERPRINT = "hidden markings remain hidden"


# ── Canon fixtures ────────────────────────────────────────────────────


class _CanonStub:
    """Minimal stand-in carrying the three JSON blobs the router/compiler read."""

    def __init__(self, character_id: int, face: FaceCanonData, body: BodyCanonData):
        self.character_id = character_id
        self.face_canon_json = json.dumps(face.model_dump())
        self.body_canon_json = json.dumps(body.model_dump())
        self.accessories_json = None


@dataclass
class Character:
    name: str
    canon: _CanonStub
    marks: list[PermanentBodyMark]
    face_urls: set[str]
    body_truth_urls: set[str]   # body anatomy slots (front/side/back/map)
    body_front_url: str
    body_map_url: str


def _full_face(slug: str) -> FaceCanonData:
    return FaceCanonData(
        face_front_image_url=f"https://cdn/{slug}/face_front.png",
        face_left_3q_image_url=f"https://cdn/{slug}/face_left_3q.png",
        face_right_3q_image_url=f"https://cdn/{slug}/face_right_3q.png",
        face_expression_image_url=f"https://cdn/{slug}/face_expr.png",
    )


def _full_body(slug: str, marks: list[PermanentBodyMark]) -> BodyCanonData:
    return BodyCanonData(
        body_front_image_url=f"https://cdn/{slug}/body_front.png",
        body_left_image_url=f"https://cdn/{slug}/body_left.png",
        body_right_image_url=f"https://cdn/{slug}/body_right.png",
        body_back_image_url=f"https://cdn/{slug}/body_back.png",
        body_map_image_url=f"https://cdn/{slug}/body_map.png",
        final_character_card_image_url=f"https://cdn/{slug}/final_card.png",
        permanent_body_marks=marks,
    )


def _mark(slug: str, label, mtype, region, side, desc) -> PermanentBodyMark:
    return PermanentBodyMark(
        label=label, type=mtype, body_region=region, side=side, description=desc,
        reference_image_url=f"https://cdn/{slug}/crop_{region}_{side}.png",
    )


def _character(cid: int, name: str, slug: str, marks: list[PermanentBodyMark]) -> Character:
    face = _full_face(slug)
    body = _full_body(slug, marks)
    canon = _CanonStub(cid, face, body)
    face_urls = {
        face.face_front_image_url, face.face_left_3q_image_url,
        face.face_right_3q_image_url, face.face_expression_image_url,
    }
    body_truth_urls = {
        body.body_front_image_url, body.body_left_image_url,
        body.body_right_image_url, body.body_back_image_url,
        body.body_map_image_url,
    }
    return Character(
        name=name, canon=canon, marks=marks, face_urls=face_urls,
        body_truth_urls=body_truth_urls,
        body_front_url=body.body_front_image_url,
        body_map_url=body.body_map_image_url,
    )


def build_characters() -> list[Character]:
    """The four spec characters: asymmetric, full-body, female, unmarked control."""
    leo = _character(1, "Leo (asymmetric tattoos)", "leo", [
        _mark("leo", "Left arm gothic script sleeve", "tattoo",
              "left_full_arm", "left", "gothic blackletter script full sleeve"),
        _mark("leo", "Right upper-arm wolf", "tattoo",
              "right_upper_arm", "right", "howling wolf head, fine linework"),
    ])
    shadow = _character(2, "Shadow (full-body tattoos)", "shadow", [
        _mark("shadow", "Left arm sleeve", "tattoo",
              "left_full_arm", "left", "geometric blackwork sleeve"),
        _mark("shadow", "Right arm sleeve", "tattoo",
              "right_full_arm", "right", "dragon koi sleeve"),
        _mark("shadow", "Chest piece", "tattoo",
              "chest", "centre", "ornamental mandala chest piece"),
        _mark("shadow", "Back piece", "tattoo",
              "full_back", "centre", "large phoenix back piece"),
        _mark("shadow", "Throat lettering", "tattoo",
              "neck", "centre", "small blackwork throat lettering"),
    ])
    maya = _character(3, "Maya (female, light tattoos)", "maya", [
        _mark("maya", "Right forearm floral", "tattoo",
              "right_forearm", "right", "fine-line floral spray"),
        _mark("maya", "Upper-back script", "tattoo",
              "upper_back", "centre", "small cursive script"),
    ])
    plain = _character(4, "Pat (minimal, no tattoos)", "pat", [])
    return [leo, shadow, maya, plain]


# ── Scene matrix ──────────────────────────────────────────────────────


@dataclass
class Scene:
    name: str
    prompt: str


def build_scenes() -> list[Scene]:
    return [
        Scene("portrait", "close-up portrait, soft smile, head and shoulders"),
        Scene("kitchen_rolled_sleeve",
              "standing in a modern kitchen wearing a fitted button-up shirt "
              "with sleeves rolled to the forearms, cinematic realism"),
        Scene("rain", "full body standing in heavy rain, soaked t-shirt clinging"),
        Scene("pool_open_shirt",
              "at the swimming pool, open shirt, arms out, relaxed"),
        Scene("formal_suit", "wearing a formal suit and tie at a gala dinner"),
        Scene("long_sleeve_hidden", "wearing a long-sleeve sweater indoors"),
        Scene("sleeveless", "facing camera in a sleeveless tank top, arms visible"),
        Scene("seated_indoor",
              "seated on a sofa indoors, relaxed, three-quarter right view"),
    ]


# ── Scoring ───────────────────────────────────────────────────────────


@dataclass
class CaseScore:
    character: str
    scene: str
    face: Optional[int]
    body: Optional[int]
    tattoo: Optional[int]
    clothing: Optional[int]
    notes: list[str] = field(default_factory=list)

    def dims(self) -> dict[str, Optional[int]]:
        return {"face": self.face, "body": self.body,
                "tattoo": self.tattoo, "clothing": self.clothing}

    def scored(self) -> list[int]:
        return [v for v in self.dims().values() if v is not NA]


def _exposed_hidden(char: Character, scene: Scene, camera: str):
    """Partition a character's marks into (exposed, hidden) for this scene,
    independent of the crop cap, using the router's own exposure logic."""
    if camera == "portrait_closeup":
        return [], list(char.marks)
    plower = scene.prompt.lower()
    exposed, hidden = [], []
    for m in char.marks:
        if _mark_region_exposed(m.body_region, plower):
            exposed.append(m)
        else:
            hidden.append(m)
    return exposed, hidden


def score_case(char: Character, scene: Scene) -> CaseScore:
    urls, meta = route_canon_refs(scene.prompt, char.canon)
    url_set = set(urls)
    compiled = compile_canon_prompt(char.canon, scene.prompt).lower()
    notes: list[str] = []

    exposed, hidden = _exposed_hidden(char, scene, meta.camera)
    has_face = bool(char.face_urls & url_set)
    has_body_truth = bool(char.body_truth_urls & url_set)
    has_body_front = char.body_front_url in url_set
    has_body_map = char.body_map_url in url_set

    # ── Face identity (always scored) ──
    if not has_face:
        face = 0
        notes.append("HARDFAIL face: no face anchor routed (stranger risk)")
    else:
        face = 5
        if meta.camera == "portrait_closeup" and urls and urls[0] not in char.face_urls:
            face = 4
            notes.append("face: portrait does not lead with a face anchor")

    # ── Body identity (N/A for face-only portraits) ──
    if meta.camera == "portrait_closeup":
        body = NA
    elif not has_body_truth:
        body = 0
        notes.append("HARDFAIL body: no body-truth ref routed when body visible")
    else:
        body = 5 if (has_body_front or has_body_map) else 4
        if not has_body_map:
            notes.append("body: body_map (marking placement) not routed")

    # ── Tattoo fidelity (N/A when no exposed marks) ──
    if not char.marks or not exposed:
        tattoo = NA
    elif not has_body_truth:
        tattoo = 0
        notes.append("HARDFAIL tattoo: exposed mark but no body truth → float risk")
    else:
        tattoo = 5
        if _SKIN_BOUND_FINGERPRINT not in compiled:
            tattoo -= 2
            notes.append("tattoo: skin-bound permanence clause missing")
        if _GEOMETRY_FINGERPRINT not in compiled:
            tattoo -= 1
            notes.append("tattoo: exact-geometry binding clause missing")
        expected_crops = min(len(exposed), _MAX_MARK_CROPS)
        if meta.mark_crops < expected_crops:
            tattoo -= 1
            notes.append(
                f"tattoo: {meta.mark_crops}/{expected_crops} exposed crops routed"
            )
        tattoo = max(tattoo, 1)  # 0 reserved for the float/no-anatomy hard fail

    # ── Clothing truth (N/A when char has no marks) ──
    if not char.marks:
        clothing = NA
    else:
        hidden_urls = {m.reference_image_url for m in hidden if m.reference_image_url}
        leaked = hidden_urls & url_set
        if leaked:
            clothing = 0
            notes.append("HARDFAIL clothing: covered mark crop leaked into refs")
        else:
            clothing = 5
            if _CLOTHING_FINGERPRINT not in compiled:
                clothing -= 1
                notes.append("clothing: clothing-truth directive missing")
            if _HIDDEN_FINGERPRINT not in compiled:
                clothing -= 1
                notes.append("clothing: hidden-stays-hidden directive missing")

    return CaseScore(char.name, scene.name, face, body, tattoo, clothing, notes)


# ── Aggregation ───────────────────────────────────────────────────────


@dataclass
class EvalReport:
    cases: list[CaseScore]

    @property
    def all_scores(self) -> list[int]:
        return [v for c in self.cases for v in c.scored()]

    @property
    def mean_consistency(self) -> float:
        return mean(self.all_scores) if self.all_scores else 0.0

    @property
    def worst_scene_floor(self) -> float:
        """Lowest per-scene mean across all scenes (the weakest scene)."""
        by_scene: dict[str, list[int]] = {}
        for c in self.cases:
            by_scene.setdefault(c.scene, []).extend(c.scored())
        scene_means = [mean(v) for v in by_scene.values() if v]
        return min(scene_means) if scene_means else 0.0

    @property
    def hard_fail_rate(self) -> float:
        scored = self.all_scores
        if not scored:
            return 0.0
        return sum(1 for v in scored if v == 0) / len(scored)

    @property
    def hard_fails(self) -> list[CaseScore]:
        return [c for c in self.cases if any(v == 0 for v in c.scored())]

    def passes_gate(self) -> bool:
        return self.hard_fail_rate < HARD_FAIL_GATE


def run_eval() -> EvalReport:
    chars = build_characters()
    scenes = build_scenes()
    cases = [score_case(c, s) for c in chars for s in scenes]
    return EvalReport(cases)


# ── CLI scorecard ─────────────────────────────────────────────────────


def _fmt(v: Optional[int]) -> str:
    return " NA" if v is NA else f"  {v}"


def print_scorecard(report: EvalReport) -> None:
    print("\n=== P14 CHARACTER CONSISTENCY SCORECARD (routing-contract proxy) ===\n")
    hdr = f"{'character':<30}{'scene':<22}{'face':>5}{'body':>5}{'tatt':>5}{'cloth':>6}"
    print(hdr)
    print("-" * len(hdr))
    last = None
    for c in report.cases:
        name = c.character if c.character != last else ""
        last = c.character
        print(f"{name:<30}{c.scene:<22}"
              f"{_fmt(c.face):>5}{_fmt(c.body):>5}{_fmt(c.tattoo):>5}{_fmt(c.clothing):>6}")
    print("-" * len(hdr))
    print(f"\nMean consistency : {report.mean_consistency:.2f} / 5")
    print(f"Worst-scene floor: {report.worst_scene_floor:.2f} / 5")
    print(f"Hard-fail rate   : {report.hard_fail_rate * 100:.1f}%  "
          f"(gate: < {HARD_FAIL_GATE * 100:.0f}%)")
    print(f"Gate             : {'PASS' if report.passes_gate() else 'FAIL'}")
    if report.hard_fails:
        print("\nHard fails:")
        for c in report.hard_fails:
            for n in c.notes:
                if n.startswith("HARDFAIL"):
                    print(f"  - {c.character} / {c.scene}: {n}")
    # Surface non-fatal deductions so weak spots are visible.
    weak = [(c, n) for c in report.cases for n in c.notes if not n.startswith("HARDFAIL")]
    if weak:
        print("\nDeductions (non-fatal):")
        for c, n in weak:
            print(f"  - {c.character} / {c.scene}: {n}")
    print()


if __name__ == "__main__":
    print_scorecard(run_eval())

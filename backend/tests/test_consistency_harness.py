"""P14 — consistency eval harness gate.

Fast regression guard built on the routing-contract proxy in
tests/consistency_eval.py. It pins the sprint acceptance gate (hard-fail rate
< 5%) and the structural invariants that predict each visual score dimension,
so a future routing/compiler change that silently breaks identity grounding
fails CI instead of shipping.

Hidden marks are N/A on tattoo fidelity and are never penalised (per spec).
"""
import pytest

from tests.consistency_eval import (
    HARD_FAIL_GATE,
    build_characters,
    build_scenes,
    run_eval,
    score_case,
)


@pytest.fixture(scope="module")
def report():
    return run_eval()


def test_acceptance_gate_hard_fail_rate_under_5pct(report):
    """Acceptance gate: hard-fail rate < 5%, no catastrophic identity breaks."""
    assert report.hard_fail_rate < HARD_FAIL_GATE, (
        f"hard-fail rate {report.hard_fail_rate:.1%} exceeds "
        f"{HARD_FAIL_GATE:.0%}; fails: "
        f"{[(c.character, c.scene) for c in report.hard_fails]}"
    )
    assert report.hard_fails == [], report.hard_fails


def test_consistency_floor_is_acceptable(report):
    """Worst-scene consistency floor stays high — no weak-scene cliff."""
    assert report.worst_scene_floor >= 4.0, (
        f"worst-scene floor {report.worst_scene_floor:.2f} below 4.0"
    )


def test_mean_consistency_high(report):
    assert report.mean_consistency >= 4.5


def test_matrix_shape(report):
    """4 characters × 8 scenes = 32 cases (the spec matrix)."""
    assert len(build_characters()) == 4
    assert len(build_scenes()) == 8
    assert len(report.cases) == 32


def test_face_always_scored_and_never_a_stranger(report):
    """Face identity is scored in every case and never hard-fails (priority #1)."""
    for c in report.cases:
        assert c.face is not None, f"face N/A for {c.character}/{c.scene}"
        assert c.face >= 4, f"face weak for {c.character}/{c.scene}: {c.notes}"


def test_hidden_marks_not_penalised():
    """A long-sleeve scene hides arm marks → tattoo fidelity is N/A, not a low
    score (spec: hidden tattoos = N/A, do NOT penalise)."""
    leo = build_characters()[0]
    long_sleeve = next(s for s in build_scenes() if s.name == "long_sleeve_hidden")
    sc = score_case(leo, long_sleeve)
    assert sc.tattoo is None  # N/A — covered marks are not scored for fidelity
    # ...and clothing truth must hold (covered marks not leaked).
    assert sc.clothing == 5


def test_portrait_has_no_body_or_tattoo_dims():
    """Portrait close-ups score face only; body/tattoo are N/A (no body routing)."""
    leo = build_characters()[0]
    portrait = next(s for s in build_scenes() if s.name == "portrait")
    sc = score_case(leo, portrait)
    assert sc.face == 5
    assert sc.body is None
    assert sc.tattoo is None


def test_exposed_marks_grounded_on_body_truth():
    """A sleeveless scene exposes Leo's marks → tattoo fidelity scored, grounded
    (>=4), never a float hard-fail."""
    leo = build_characters()[0]
    sleeveless = next(s for s in build_scenes() if s.name == "sleeveless")
    sc = score_case(leo, sleeveless)
    assert sc.tattoo is not None and sc.tattoo >= 4
    assert sc.body == 5

"""face_geometry_semantics — the one anatomical mapping for the six Interview
geometry fields, and proof that every prompt path uses it.

Polish Phase 3 prompt-semantics pass. Reference cards explain the option to
a human, the stored value is the data contract, and this module is what the
image model is told. These tests pin all three apart:

  * every validated stored value has a full phrase (and a lock phrase where
    the lock string carries the field), and the stored vocabulary itself is
    unchanged;
  * the schema still stores raw values, never phrases;
  * dict and pydantic consumers agree; None/""/"none" are omitted; a legacy
    value degrades to yesterday's literal wording with a warning;
  * face_shape never changes meaning because jaw_type is set or unset, and
    never describes the jaw;
  * the sketch, the identity prompt, the lock string and the V2 pack all
    read from here, and the two capped prompts still fit with their
    important sections intact for the worst fully-specified spec;
  * the legacy identity prompt never fits worse than it did before this
    module: over its cap it re-renders geometry at the compact tier of this
    same module before dropping any section, so a non-human worst case keeps
    outfit_lock / shot / extra_notes exactly as it did at the old wording;
  * the compact tier is genuinely compact: value by value it is no longer
    than the literal wording the two capped prompts used before this module,
    so a prompt near its cap because of free text (extra_notes,
    face_features) can never newly lose a section the old wording kept —
    pinned per value, exhaustively per combination, and with explicit
    near-cap free-text cases on both prompts;
  * every approved full-tier phrase is pinned verbatim;
  * an old persisted lock string is read back verbatim, never recomputed.
"""
from __future__ import annotations

import itertools
import logging

import pytest

from app.schemas.character_visual import (
    _FACIAL_GEOMETRY_FIELD_MAP,
    CharacterIdentitySpec,
    IdentityCore,
)
from app.services import face_geometry_semantics as fgs
from app.services.face_geometry_semantics import (
    GEOMETRY_FIELDS,
    LOCK_FIELDS,
    geometry_phrase,
    geometry_phrases,
)
from app.services.identity_compiler import (
    _PROMPT_CAP,
    ROLE_SHOT_DESCRIPTION,
    compile_identity_lock_string,
    compile_identity_prompt,
)
from app.services.canon_pack_builder import _spec_face_description
from app.api.routes.character_visual import _SKETCH_PROMPT_CAP, _build_sketch_prompt


# ── The stored vocabulary — the contract nothing here may move ─────────

STORED_VOCABULARY: dict[str, set[str]] = {
    "face_shape": {"oval", "round", "square", "angular", "long"},
    "eye_shape": {"almond", "round", "narrow", "deep_set"},
    "jaw_type": {"soft", "narrow", "square", "sharp"},
    "cheekbone_type": {"subtle", "high", "wide"},
    "nose_type": {"straight", "narrow", "broad", "hooked", "roman", "upturned"},
    "lip_type": {"thin", "balanced", "full", "cupid_bow"},
}

NOUN = {
    "face_shape": "face", "jaw_type": "jaw", "cheekbone_type": "cheekbones",
    "eye_shape": "eyes", "nose_type": "nose", "lip_type": "lips",
}

_BASE = dict(
    style="realistic", gender="female", age_band="26-35", species="human",
    identity=IdentityCore(hair_color="dark brown", hair_length="Long", eye_color="Hazel", skin_tone="Olive"),
    eye_spacing="wide_set", eyebrow_shape="arched", hairline_type="widows_peak", facial_hair_type="none",
    hair_texture="wavy", hair_style="loose", body_height="tall", body_build="athletic",
    extra_notes="quiet intensity",
)


def _spec(**geometry) -> CharacterIdentitySpec:
    return CharacterIdentitySpec(**_BASE, **geometry)


def _worst_geometry() -> dict[str, str]:
    """The longest full phrase in every field — the heaviest legal spec."""
    return {f: max(fgs._FULL[f], key=lambda v: len(fgs._FULL[f][v])) for f in GEOMETRY_FIELDS}


# ── Vocabulary and completeness ───────────────────────────────────────

def test_stored_vocabulary_is_unchanged():
    for field, values in STORED_VOCABULARY.items():
        assert _FACIAL_GEOMETRY_FIELD_MAP[field] == values, field
    assert set(GEOMETRY_FIELDS) == set(STORED_VOCABULARY)


def test_every_stored_value_has_full_semantics():
    for field, values in STORED_VOCABULARY.items():
        for value in values:
            phrase = geometry_phrase(field, value)
            assert phrase and phrase == fgs._FULL[field][value], (field, value)
            assert NOUN[field] in phrase, (field, value, phrase)


def test_every_stored_value_has_compact_semantics():
    """The compact tier covers all six fields (the identity prompt needs it under
    budget pressure); the lock STRING still carries only its four."""
    assert LOCK_FIELDS == ("face_shape", "jaw_type", "nose_type", "lip_type")
    for field, values in STORED_VOCABULARY.items():
        for value in values:
            phrase = geometry_phrase(field, value, tier="lock")
            assert phrase == fgs._LOCK[field][value], (field, value)
            assert NOUN[field] in phrase, (field, value, phrase)
            assert len(phrase) <= len(geometry_phrase(field, value)), "lock tier is never longer than full"
    assert set(fgs._LOCK) == set(GEOMETRY_FIELDS)


def test_compact_phrases_are_distinct_within_a_field():
    for field in GEOMETRY_FIELDS:
        phrases = list(fgs._LOCK[field].values())
        assert len(set(phrases)) == len(phrases), field


def test_phrases_describe_anatomy_not_people():
    banned = {"beautiful", "pretty", "handsome", "attractive", "ugly", "ethnic", "asian", "european",
              "african", "caucasian", "angry", "sad", "happy", "squint", "squinting", "smile"}
    for tier in (fgs._FULL, fgs._LOCK):
        for field in tier:
            for value, phrase in tier[field].items():
                words = set(phrase.lower().replace(",", " ").replace("-", " ").split())
                assert not (words & banned), (field, value, phrase)


def test_full_phrases_are_distinct_within_a_field():
    for field in GEOMETRY_FIELDS:
        phrases = list(fgs._FULL[field].values())
        assert len(set(phrases)) == len(phrases), field


# ── Semantic boundaries ───────────────────────────────────────────────

def test_face_shape_never_describes_the_jaw_or_chin():
    for value, phrase in fgs._FULL["face_shape"].items():
        low = phrase.lower()
        for word in ("jaw", "chin", "mandib"):
            assert word not in low, (value, phrase)


def test_cheekbones_never_describe_the_whole_face_width():
    for value, phrase in fgs._FULL["cheekbone_type"].items():
        assert "face" not in phrase.lower(), (value, phrase)


@pytest.mark.parametrize("face", sorted(STORED_VOCABULARY["face_shape"]))
def test_face_shape_meaning_is_independent_of_jaw_type(face):
    alone = geometry_phrases(_spec(face_shape=face))
    for jaw in sorted(STORED_VOCABULARY["jaw_type"]):
        both = geometry_phrases(_spec(face_shape=face, jaw_type=jaw))
        assert both[0] == alone[0], "face_shape phrase must not change when jaw_type is set"
        assert both == [alone[0], fgs._FULL["jaw_type"][jaw]]


def test_conflicting_pairs_emit_both_phrases_unchanged_and_nothing_wins():
    phrases = geometry_phrases(_spec(face_shape="square", jaw_type="narrow"))
    assert phrases == [fgs._FULL["face_shape"]["square"], fgs._FULL["jaw_type"]["narrow"]]
    phrases = geometry_phrases(_spec(face_shape="round", jaw_type="sharp", cheekbone_type="wide"))
    assert phrases == [
        fgs._FULL["face_shape"]["round"], fgs._FULL["jaw_type"]["sharp"], fgs._FULL["cheekbone_type"]["wide"],
    ]


# ── Inputs: dict vs pydantic, empties, unknowns ───────────────────────

def test_dict_and_spec_consumers_agree():
    geometry = dict(face_shape="angular", jaw_type="sharp", cheekbone_type="high",
                    eye_shape="deep_set", nose_type="roman", lip_type="cupid_bow")
    as_dict = geometry_phrases(geometry)
    as_spec = geometry_phrases(_spec(**geometry))
    assert as_dict == as_spec
    assert len(as_dict) == 6
    assert geometry_phrases(geometry, tier="lock", fields=LOCK_FIELDS) == \
        geometry_phrases(_spec(**geometry), tier="lock", fields=LOCK_FIELDS)


@pytest.mark.parametrize("empty", [None, "", "   ", "none", "None"])
def test_empty_values_are_omitted(empty):
    for field in GEOMETRY_FIELDS:
        assert geometry_phrase(field, empty) is None
        assert geometry_phrase(field, empty, tier="lock") is None
    assert geometry_phrases({f: empty for f in GEOMETRY_FIELDS}) == []
    assert geometry_phrases({}) == []
    assert geometry_phrases(_spec()) == []


def test_unknown_legacy_value_falls_back_to_literal_and_warns(caplog):
    legacy = {"face_shape": "heart", "nose_type": "button", "lip_type": "pouty_bow", "eye_shape": "almond"}
    with caplog.at_level(logging.WARNING, logger="app.services.face_geometry_semantics"):
        out = geometry_phrases(legacy)
    assert out == ["heart face", "almond eyes, tapered inner and outer corners", "button nose", "pouty bow lips"]
    assert sum("no full-tier phrase" in r.message for r in caplog.records) == 3
    assert legacy == {"face_shape": "heart", "nose_type": "button", "lip_type": "pouty_bow", "eye_shape": "almond"}, \
        "the caller's data is never mutated"
    with caplog.at_level(logging.WARNING, logger="app.services.face_geometry_semantics"):
        assert geometry_phrase("jaw_type", "pointed", tier="lock") == "pointed jaw"


def test_legacy_dict_casing_still_matches_its_phrase(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.face_geometry_semantics"):
        assert geometry_phrase("face_shape", "Round") == fgs._FULL["face_shape"]["round"]
        assert geometry_phrase("lip_type", "CUPID_BOW", tier="lock") == fgs._LOCK["lip_type"]["cupid_bow"]
    assert not caplog.records


def test_unknown_field_is_a_programming_error():
    with pytest.raises(KeyError):
        geometry_phrase("eye_spacing", "wide_set")


def test_validation_still_rejects_unknown_values_and_stores_raw_values():
    with pytest.raises(ValueError):
        CharacterIdentitySpec(**_BASE, nose_type="button")
    spec = _spec(face_shape="Angular ", lip_type="CUPID_BOW")
    assert spec.face_shape == "angular"
    assert spec.lip_type == "cupid_bow"
    assert "planes" not in spec.face_shape and "peaked" not in spec.lip_type


# ── The four consumers ────────────────────────────────────────────────

FULL_GEOMETRY = dict(face_shape="angular", jaw_type="sharp", cheekbone_type="high",
                     eye_shape="deep_set", nose_type="roman", lip_type="cupid_bow")


def _sentinel(field, value, *, tier="full"):
    if value is None or not str(value).strip():
        return None
    return f"<{tier}:{field}={value}>"


def test_sketch_prompt_uses_the_shared_semantics(monkeypatch):
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    prompt = _build_sketch_prompt(_spec(**FULL_GEOMETRY), "pencil")
    for field, value in FULL_GEOMETRY.items():
        assert f"<full:{field}={value}>" in prompt, field
    assert "wide set eyes" in prompt and "arched eyebrows" in prompt, "eye spacing / eyebrows keep their own wording"
    # Existing slot order: geometry, then eye spacing and eyebrows, then nose and lips.
    assert prompt.index("<full:eye_shape=deep_set>") < prompt.index("wide set eyes") < prompt.index("<full:nose_type=roman>")


def test_identity_prompt_uses_the_shared_semantics(monkeypatch):
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    prompt = compile_identity_prompt(_spec(**FULL_GEOMETRY), "anchor_front")
    for field, value in FULL_GEOMETRY.items():
        assert f"<full:{field}={value}>" in prompt, field
    assert "<lock:" not in prompt


def test_lock_string_uses_the_compact_tier_and_keeps_its_omissions(monkeypatch):
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    lock = compile_identity_lock_string(_spec(**FULL_GEOMETRY))
    for field in LOCK_FIELDS:
        assert f"<lock:{field}={FULL_GEOMETRY[field]}>" in lock, field
    assert "eye_shape" not in lock and "cheekbone" not in lock
    assert "<full:" not in lock


def test_lock_string_real_wording():
    lock = compile_identity_lock_string(_spec(**FULL_GEOMETRY))
    assert "angular face, sharp jaw, Roman nose, cupid-bow lips" in lock
    assert "beneath" not in lock and "mandibular" not in lock and "convex" not in lock


def test_v2_pack_description_uses_the_shared_semantics(monkeypatch):
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    desc = _spec_face_description({
        **FULL_GEOMETRY, "identity": {"skin_tone": "Olive", "eye_color": "Hazel"},
        "eye_spacing": "wide_set", "eyebrow_shape": "arched", "hairline_type": "widows_peak",
        "facial_hair_type": "none",
    })
    for field, value in FULL_GEOMETRY.items():
        assert f"<full:{field}={value}>" in desc, field
    # Out-of-scope fields keep their wording and slots.
    assert "wide set eyes" in desc and "arched eyebrows" in desc and "widows peak hairline" in desc
    assert "facial hair" not in desc
    assert desc.index("<full:eye_shape=deep_set>") < desc.index("wide set eyes") < desc.index("<full:nose_type=roman>")
    assert desc.index("<full:lip_type=cupid_bow>") < desc.index("widows peak hairline")


def test_v2_pack_description_real_wording_and_legacy_none():
    desc = _spec_face_description({"face_shape": "round", "identity": {}})
    assert desc == "round face, short wide proportions, rounded sides"
    assert _spec_face_description({"face_shape": "none", "nose_type": "", "identity": {}}) == ""


def test_no_prompt_path_builds_geometry_wording_on_its_own():
    """The four consumers read every geometry phrase from the module."""
    import inspect
    import app.services.identity_compiler as ic
    import app.services.canon_pack_builder as pb
    import app.api.routes.character_visual as cv
    for src in (inspect.getsource(ic), inspect.getsource(pb), inspect.getsource(cv)):
        for noun in ("face shape\"", "} face\"", "} jaw\"", "} cheekbones\"", "} nose\"", "} lips\"", "eye shape\""):
            assert noun not in src, noun


# ── Budgets: the two capped prompts with the heaviest legal spec ──────

def test_sketch_fits_its_cap_with_the_heaviest_spec():
    prompt = _build_sketch_prompt(_spec(**_worst_geometry()), "pencil")
    assert len(prompt) <= _SKETCH_PROMPT_CAP
    assert "hairline" in prompt and "age range" in prompt, "nothing trimmed"
    assert fgs._FULL["face_shape"][_worst_geometry()["face_shape"]] in prompt, "human worst case stays full tier"


@pytest.mark.parametrize("role", ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"])
def test_identity_prompt_fits_its_cap_without_losing_sections(role):
    prompt = compile_identity_prompt(_spec(**_worst_geometry()), role)
    assert len(prompt) <= _PROMPT_CAP
    assert "Keep this exact outfit unchanged" in prompt, "outfit lock must survive"
    assert "quiet intensity" in prompt, "extra notes must survive"
    assert fgs._FULL["face_shape"][_worst_geometry()["face_shape"]] in prompt


def _sections_lost(prompt: str, role: str = "anchor_front") -> set[str]:
    """Which of the three trimmable sections are missing from ``prompt``."""
    needles = {
        "outfit_lock": "Keep this exact outfit unchanged",
        "extra_notes": "quiet intensity",
        "shot": ROLE_SHOT_DESCRIPTION[role],
    }
    return {name for name, needle in needles.items() if needle not in prompt}


def _every_geometry_combination():
    for combo in itertools.product(*[sorted(STORED_VOCABULARY[f]) for f in GEOMETRY_FIELDS]):
        yield dict(zip(GEOMETRY_FIELDS, combo))


def test_identity_prompt_keeps_sections_for_every_geometry_combination():
    """Exhaustive: 5·4·3·4·6·4 combinations on the longest role, human species.
    Every human combination fits at the full tier — nothing is compacted."""
    lost: set[str] = set()
    longest = 0
    for geometry in _every_geometry_combination():
        prompt = compile_identity_prompt(_spec(**geometry), "anchor_front")
        longest = max(longest, len(prompt))
        lost |= _sections_lost(prompt)
        assert fgs._FULL["face_shape"][geometry["face_shape"]] in prompt, "human specs are never compacted"
    assert longest <= _PROMPT_CAP
    assert not lost


# ── Budget pressure: the legacy non-human worst case ──────────────────
#
# A non-human species adds a "species" section the human budget check never
# sees. With the full-tier wording, a worst-case spec + the longest species
# descriptor went to ~1551 chars on anchor_front and trimmed outfit_lock (and
# shot); before the semantics module the same spec was ~1449 and trimmed
# nothing. The compiler now re-renders geometry at the compact tier of the
# same module before it drops anything, so these specs keep every section.

_WORST_SPECIES = dict(species="werewolf", species_tells=["a" * 32, "b" * 32, "c" * 32])


def _nonhuman_worst(**geometry) -> CharacterIdentitySpec:
    return CharacterIdentitySpec(**{**_BASE, **_WORST_SPECIES}, **geometry)


@pytest.mark.parametrize("role", ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"])
def test_nonhuman_worst_case_keeps_every_section(role):
    prompt = compile_identity_prompt(_nonhuman_worst(**_worst_geometry()), role)
    assert len(prompt) <= _PROMPT_CAP
    assert not _sections_lost(prompt, role), "outfit_lock / extra_notes / shot must all survive"
    assert "werewolf character" in prompt and "subtle supernatural tells" in prompt
    assert "age range" in prompt and "hairline" in prompt and "tall" in prompt.lower()


def test_nonhuman_worst_case_is_compacted_not_trimmed():
    """Over the cap, all six geometry fields fall back to the compact tier of the
    same module — every field still present, no full phrase, nothing dropped."""
    geometry = _worst_geometry()
    prompt = compile_identity_prompt(_nonhuman_worst(**geometry), "anchor_front")
    assert not _sections_lost(prompt)
    for field, value in geometry.items():
        assert fgs._LOCK[field][value] in prompt, field
        assert fgs._FULL[field][value] not in prompt, field
    # Compaction preserves emission order and the identity slot.
    idx = [prompt.index(fgs._LOCK[f][geometry[f]]) for f in GEOMETRY_FIELDS]
    assert idx == sorted(idx)
    assert prompt.index("hairline") > idx[-1] and prompt.index("werewolf character") > idx[-1]


def test_compaction_only_happens_under_budget_pressure():
    """The same non-human spec on a shorter role fits at the full tier, so it
    is not compacted; the human worst case never is."""
    geometry = _worst_geometry()
    prompt = compile_identity_prompt(_nonhuman_worst(**geometry), "anchor_torso")
    assert fgs._FULL["face_shape"][geometry["face_shape"]] in prompt
    assert not _sections_lost(prompt, "anchor_torso")
    light = CharacterIdentitySpec(**{**_BASE, "species": "vampire", "species_tells": ["subtle_fangs"]}, face_shape="oval")
    assert fgs._FULL["face_shape"]["oval"] in compile_identity_prompt(light, "anchor_front")


def test_compaction_reads_the_shared_module(monkeypatch):
    """Under pressure the identity section asks the module for tier="lock" for
    all six fields — it does not carry wording of its own."""
    import app.services.identity_compiler as ic
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    full = compile_identity_prompt(_spec(**FULL_GEOMETRY), "anchor_front")
    monkeypatch.setattr(ic, "_PROMPT_CAP", len(full) - 1)  # force budget pressure
    prompt = compile_identity_prompt(_spec(**FULL_GEOMETRY), "anchor_front")
    for field, value in FULL_GEOMETRY.items():
        assert f"<lock:{field}={value}>" in prompt, field
    assert "<full:" not in prompt


def test_compaction_precedes_section_dropping(monkeypatch):
    """Geometry is compacted before extra_notes is considered for removal."""
    import app.services.identity_compiler as ic
    geometry = _worst_geometry()
    full = compile_identity_prompt(_spec(**geometry), "anchor_front")
    assert fgs._FULL["face_shape"][geometry["face_shape"]] in full and "quiet intensity" in full
    # A cap just below the full-tier length: compaction alone must rescue it.
    monkeypatch.setattr(ic, "_PROMPT_CAP", len(full) - 1)
    prompt = compile_identity_prompt(_spec(**geometry), "anchor_front")
    assert len(prompt) <= len(full) - 1
    assert fgs._LOCK["face_shape"][geometry["face_shape"]] in prompt
    assert not _sections_lost(prompt)


def test_compaction_falls_through_to_existing_trim_order(monkeypatch):
    """When compaction is not enough the pre-existing _TRIM_ORDER still applies,
    in its order: extra_notes goes before outfit_lock, which goes before shot."""
    import app.services.identity_compiler as ic
    geometry = _worst_geometry()
    compact = compile_identity_prompt(_nonhuman_worst(**geometry), "anchor_front")
    assert not _sections_lost(compact)
    monkeypatch.setattr(ic, "_PROMPT_CAP", len(compact) - 1)
    prompt = compile_identity_prompt(_nonhuman_worst(**geometry), "anchor_front")
    assert _sections_lost(prompt) == {"extra_notes"}
    assert fgs._LOCK["face_shape"][geometry["face_shape"]] in prompt, "geometry itself is never dropped"
    assert "werewolf character" in prompt


def test_nonhuman_worst_case_sketch_is_compacted_not_trimmed():
    """The sketch has the same shape of problem (900-char cap, species block,
    hairline first in its trim order after face_features) and the same fix."""
    geometry = _worst_geometry()
    prompt = _build_sketch_prompt(_nonhuman_worst(**geometry), "pencil")
    assert len(prompt) <= _SKETCH_PROMPT_CAP
    assert "hairline" in prompt and "age range" in prompt and "werewolf character" in prompt
    assert "Hazel eyes" in prompt and "Olive skin" in prompt and "dark brown hair" in prompt
    for field, value in geometry.items():
        assert fgs._LOCK[field][value] in prompt, field
        assert fgs._FULL[field][value] not in prompt, field
    # Eye spacing / eyebrows keep their slot inside the compacted block.
    assert prompt.index(fgs._LOCK["eye_shape"][geometry["eye_shape"]]) < prompt.index("wide set eyes") \
        < prompt.index(fgs._LOCK["nose_type"][geometry["nose_type"]])


def test_sketch_compaction_reads_the_shared_module(monkeypatch):
    """Under pressure the sketch asks the module for tier="lock" — the
    geometry block carries no wording of its own."""
    import app.api.routes.character_visual as cv
    monkeypatch.setattr(fgs, "geometry_phrase", _sentinel)
    full = _build_sketch_prompt(_spec(**FULL_GEOMETRY), "pencil")
    fitter = cv._fit_sketch_sections  # ``cap`` is bound at definition time, so pass it explicitly
    monkeypatch.setattr(cv, "_fit_sketch_sections", lambda h, m, t, **kw: fitter(h, m, t, cap=len(full) - 1, **kw))
    prompt = _build_sketch_prompt(_spec(**FULL_GEOMETRY), "pencil")
    for field, value in FULL_GEOMETRY.items():
        assert f"<lock:{field}={value}>" in prompt, field
    assert "<full:" not in prompt


def test_nonhuman_worst_case_sketch_keeps_sections_for_every_geometry_combination():
    lost = 0
    longest = 0
    for geometry in _every_geometry_combination():
        prompt = _build_sketch_prompt(_nonhuman_worst(**geometry), "pencil")
        longest = max(longest, len(prompt))
        lost += ("widows peak hairline" not in prompt or "age range 26-35" not in prompt
                 or "werewolf character" not in prompt or "subtle supernatural tells" not in prompt
                 or "Hazel eyes" not in prompt or "Olive skin" not in prompt
                 or "dark brown hair" not in prompt or "wide set eyes" not in prompt)
        for f in GEOMETRY_FIELDS:
            assert fgs._LOCK[f][geometry[f]] in prompt or fgs._FULL[f][geometry[f]] in prompt, (f, geometry)
    assert longest <= _SKETCH_PROMPT_CAP
    assert lost == 0


def test_nonhuman_worst_case_keeps_sections_for_every_geometry_combination():
    """Exhaustive, non-human: the longest species descriptor on the longest
    role with all 5,760 geometry combinations — nothing trimmed, ever."""
    lost: set[str] = set()
    longest = 0
    for geometry in _every_geometry_combination():
        prompt = compile_identity_prompt(_nonhuman_worst(**geometry), "anchor_front")
        longest = max(longest, len(prompt))
        lost |= _sections_lost(prompt)
        assert "werewolf character" in prompt and "subtle supernatural tells" in prompt, geometry
        assert "widows peak hairline" in prompt and "age range 26-35" in prompt, geometry
        assert "dark brown hair" in prompt and "Hazel eyes" in prompt and "Olive skin" in prompt, geometry
        assert "tall stature" in prompt and "athletic build" in prompt, geometry
        for f in GEOMETRY_FIELDS:
            assert fgs._LOCK[f][geometry[f]] in prompt or fgs._FULL[f][geometry[f]] in prompt, (f, geometry)
    assert longest <= _PROMPT_CAP
    assert not lost


# ── Persisted lock strings are read, never recomputed ─────────────────

def test_persisted_lock_string_is_read_back_verbatim():
    """Scene/body prompts take identity_lock_string from identity_anchor_json as
    stored at pack-accept; a character locked under the old wording keeps it."""
    import inspect
    from app.api.routes import scene_images, body_identity
    old_lock = "Long brunette hair, hazel eyes, tan skin, angular face, square jaw, broad nose, balanced lips"
    anchor_data = {"identity_lock_string": old_lock, "identity_prompt_hash": "abc"}
    assert (anchor_data.get("identity_lock_string") or "") == old_lock
    for mod in (scene_images, body_identity):
        src = inspect.getsource(mod)
        assert 'anchor_data.get("identity_lock_string")' in src, mod.__name__
        assert "compile_identity_lock_string(" not in src, f"{mod.__name__} must not recompute the lock"
    # The only writers of identity_lock_string compile it from the accepted pack's spec.
    import app.api.routes.character_visual as cv
    import app.services.candidate_slot as slot
    assert '"identity_lock_string": _lock_string' in inspect.getsource(cv)
    assert 'anchor_data["identity_lock_string"] = compile_identity_lock_string' in inspect.getsource(slot)


# ── Compact-tier invariant: never longer than the historical literal ──
#
# Before this module the two capped prompts interpolated the stored value
# almost literally. Those exact templates, copied from the pre-semantics HEAD
# (068ea6f: identity_compiler.compile_identity_prompt and
# character_visual._build_sketch_prompt), are what the compact tier is measured
# against — they are a test fixture, not a second mapping. For every value the
# compact phrase is no longer than the SHORTER of the two literal renderings,
# so a prompt rendered at the compact tier is never longer than the same
# prompt was before this module. That is what makes compaction safe: budget
# pressure from free text can only ever be relieved by it, never worsened.

_HISTORICAL_LITERAL: dict[str, dict[str, str]] = {
    "identity": {
        "face_shape": "{} face shape", "jaw_type": "{} jaw", "cheekbone_type": "{} cheekbones",
        "eye_shape": "{} eye shape", "nose_type": "{} nose", "lip_type": "{} lips",
    },
    "sketch": {
        "face_shape": "{} face", "jaw_type": "{} jaw", "cheekbone_type": "{} cheekbones",
        "eye_shape": "{} eyes", "nose_type": "{} nose", "lip_type": "{} lips",
    },
}


def _historical(path: str, field: str, value: str) -> str:
    return _HISTORICAL_LITERAL[path][field].format(str(value).replace("_", " "))


def _historical_phrase_for(path: str):
    """A stand-in for ``geometry_phrase`` that renders the pre-semantics literal
    wording of ``path`` regardless of tier — so the compilers, patched with it,
    reproduce the prompt HEAD built (compaction becomes a no-op and the
    pre-existing trim order is all that is left)."""
    def phrase(field, value, *, tier="full"):
        if value is None:
            return None
        raw = str(getattr(value, "value", value)).strip()
        if not raw or raw.lower() == "none":
            return None
        return _historical(path, field, raw.lower())
    return phrase


def _worst_compact_geometry() -> dict[str, str]:
    """The longest compact phrase in every field."""
    return {f: max(fgs._LOCK[f], key=lambda v: len(fgs._LOCK[f][v])) for f in GEOMETRY_FIELDS}


def test_compact_phrase_is_never_longer_than_the_historical_literal():
    """Value by value, for both capped paths."""
    for field, values in STORED_VOCABULARY.items():
        for value in sorted(values):
            compact = geometry_phrase(field, value, tier="lock")
            for path in ("identity", "sketch"):
                literal = _historical(path, field, value)
                assert len(compact) <= len(literal), (path, field, value, compact, literal)


def test_compact_block_is_never_longer_than_the_historical_block_for_every_combination():
    """All 5,760 combinations, both paths: the joined compact geometry block is
    no longer than the joined literal block it stands in for."""
    for geometry in _every_geometry_combination():
        compact = ", ".join(geometry_phrases(geometry, tier="lock"))
        for path in ("identity", "sketch"):
            literal = ", ".join(_historical(path, f, geometry[f]) for f in GEOMETRY_FIELDS)
            assert len(compact) <= len(literal), (path, geometry)


def test_compact_phrases_keep_the_identity_distinction():
    """Compaction shortens the wording, not the vocabulary: every compact phrase
    still carries its own label and the field noun, and no two values in a
    field collapse into one phrase (test_compact_phrases_are_distinct_within_a_field)."""
    label = {"deep_set": "deep-set", "cupid_bow": "cupid-bow", "balanced": "medium", "roman": "Roman"}
    for field, values in STORED_VOCABULARY.items():
        for value in values:
            phrase = geometry_phrase(field, value, tier="lock")
            assert label.get(value, value) in phrase, (field, value, phrase)
            assert phrase.endswith(NOUN[field]), (field, value, phrase)


# ── The approved full tier, pinned verbatim ───────────────────────────

APPROVED_FULL: dict[str, dict[str, str]] = {
    "face_shape": {
        "oval": "oval face, softly curved, slightly longer than wide",
        "round": "round face, short wide proportions, rounded sides",
        "square": "square face, broad proportions, straight outer sides",
        "angular": "angular face, defined planes, tapered lower outline",
        "long": "long face, vertically elongated, narrow proportions",
    },
    "jaw_type": {
        "soft": "soft jawline, rounded transitions",
        "narrow": "narrow jaw tapering toward the chin",
        "square": "square jaw, broad flat lower line",
        "sharp": "sharp jawline, defined mandibular angle",
    },
    "cheekbone_type": {
        "subtle": "subtle cheekbones, low ridge prominence",
        "high": "high cheekbones, ridge set high under the eyes",
        "wide": "wide-set cheekbones, broad lateral spacing",
    },
    "eye_shape": {
        "almond": "almond eyes, tapered inner and outer corners",
        "round": "round eyes, open curved aperture",
        "narrow": "narrow eyes, slim horizontal aperture",
        "deep_set": "deep-set eyes recessed beneath the brow ridge",
    },
    "nose_type": {
        "straight": "straight nose, even bridge",
        "narrow": "narrow nose, slim bridge and narrow base",
        "broad": "broad nose, wide bridge and wide base",
        "hooked": "hooked nose, bridge curving to a downward tip",
        "roman": "Roman nose, prominent convex bridge",
        "upturned": "upturned nose, tip angled upward",
    },
    "lip_type": {
        "thin": "thin lips, little vertical fullness",
        "balanced": "medium lips, even upper and lower fullness",
        "full": "full lips, pronounced vertical fullness",
        "cupid_bow": "cupid's-bow lips, clearly peaked upper lip",
    },
}


def test_approved_full_tier_wording_is_unchanged():
    assert fgs._FULL == APPROVED_FULL
    for field in GEOMETRY_FIELDS:
        for value in STORED_VOCABULARY[field]:
            assert geometry_phrase(field, value) == APPROVED_FULL[field][value]
            assert geometry_phrase(field, value, tier="full") == APPROVED_FULL[field][value]


# ── Near-cap free text: compaction can never newly lose a section ─────
#
# The regression class this rules out: a prompt that sat just under its cap at
# HEAD because of free text, kept everything, and would now lose extra_notes
# (identity) or face_features (sketch) because the geometry wording grew. Each
# case pads free text until the HEAD-wording prompt sits EXACTLY at the cap
# with every section intact, then builds the same spec with the real module:
# the full tier overflows, the compiler compacts, and — because the compact
# block is no shorter than nothing but no longer than the literal block — the
# result fits with the same sections HEAD kept.

_FEATURES = ["small scar over the left brow", "faint freckles across the nose"]
_NOTES = "quiet intensity, watchful and unhurried"
# A realistic non-human, not the 3×32-char worst case: that one is already
# over the identity cap at HEAD wording once two face features are added, so
# it cannot sit "just under" it (the _WORST_SPECIES tests above cover it).
_FREE_TEXT_SPECIES = dict(species="werewolf", species_tells=["golden_eyes", "heavy_brow", "pointed_ears"])


def _free_text_spec(*, nonhuman: bool, pad: int, **geometry) -> CharacterIdentitySpec:
    base = {**_BASE, **(_FREE_TEXT_SPECIES if nonhuman else {})}
    base["identity"] = IdentityCore(
        hair_color="dark brown", hair_length="Long", eye_color="Hazel", skin_tone="Olive",
        face_features=[_FEATURES[0] + " " + "x" * pad, _FEATURES[1]],
    )
    base["extra_notes"] = _NOTES
    return CharacterIdentitySpec(**base, **geometry)


def _identity_sections_present(prompt: str, role: str, pad: int) -> None:
    assert "Keep this exact outfit unchanged" in prompt, "outfit_lock"
    assert ROLE_SHOT_DESCRIPTION[role] in prompt, "shot"
    assert _NOTES in prompt, "extra_notes"
    assert _FEATURES[0] + " " + "x" * pad in prompt and _FEATURES[1] in prompt, "face_features"
    assert "widows peak hairline" in prompt, "hairline"
    assert "age range 26-35" in prompt, "age"
    assert "dark brown hair" in prompt and "Hazel eyes" in prompt and "Olive skin" in prompt, "identity"
    assert "tall stature" in prompt, "build"


def _pad_identity_to_cap(monkeypatch, role: str, nonhuman: bool, geometry: dict[str, str]) -> tuple[int, str]:
    """Return (pad, HEAD prompt) with the HEAD-wording prompt exactly at the cap."""
    with monkeypatch.context() as m:
        m.setattr(fgs, "geometry_phrase", _historical_phrase_for("identity"))
        probe = compile_identity_prompt(_free_text_spec(nonhuman=nonhuman, pad=0, **geometry), role)
        assert not _sections_lost(probe, role)
        pad = _PROMPT_CAP - len(probe)
        assert pad >= 0, "the fixture must sit under the cap at HEAD wording"
        head = compile_identity_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), role)
    assert len(head) == _PROMPT_CAP
    _identity_sections_present(head, role, pad)
    return pad, head


@pytest.mark.parametrize("nonhuman", [False, True], ids=["human", "werewolf"])
@pytest.mark.parametrize("role", ["anchor_front", "anchor_three_quarter", "anchor_torso", "anchor_full_body"])
@pytest.mark.parametrize("pick", ["worst_full", "worst_compact"])
def test_identity_near_cap_free_text_keeps_every_section(monkeypatch, nonhuman, role, pick):
    geometry = _worst_geometry() if pick == "worst_full" else _worst_compact_geometry()
    pad, head = _pad_identity_to_cap(monkeypatch, role, nonhuman, geometry)
    prompt = compile_identity_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), role)
    assert len(prompt) <= len(head) <= _PROMPT_CAP
    _identity_sections_present(prompt, role, pad)
    # The rescue was compaction, not trimming.
    for field, value in geometry.items():
        assert fgs._LOCK[field][value] in prompt, field


@pytest.mark.parametrize("nonhuman", [False, True], ids=["human", "werewolf"])
def test_identity_near_cap_free_text_for_every_geometry_combination(monkeypatch, nonhuman):
    """Exhaustive near-cap: for all 5,760 combinations the HEAD-wording prompt is
    padded to exactly the cap; the real prompt then never loses a section."""
    with monkeypatch.context() as m:
        m.setattr(fgs, "geometry_phrase", _historical_phrase_for("identity"))
        pads = {}
        for geometry in _every_geometry_combination():
            probe = compile_identity_prompt(_free_text_spec(nonhuman=nonhuman, pad=0, **geometry), "anchor_front")
            pads[tuple(geometry[f] for f in GEOMETRY_FIELDS)] = _PROMPT_CAP - len(probe)
    assert min(pads.values()) >= 0
    for geometry in _every_geometry_combination():
        pad = pads[tuple(geometry[f] for f in GEOMETRY_FIELDS)]
        prompt = compile_identity_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), "anchor_front")
        assert len(prompt) <= _PROMPT_CAP, geometry
        assert not _sections_lost(prompt, "anchor_front"), geometry
        assert _NOTES in prompt and _FEATURES[1] in prompt and "x" * pad in prompt, geometry
        assert "widows peak hairline" in prompt and "age range 26-35" in prompt, geometry
        if nonhuman:
            assert "werewolf character" in prompt, geometry


def _sketch_sections_present(prompt: str, pad: int, nonhuman: bool) -> None:
    assert _FEATURES[0] + " " + "x" * pad in prompt and _FEATURES[1] in prompt, "face_features"
    assert "widows peak hairline" in prompt, "hairline"
    assert "age range 26-35" in prompt, "age"
    assert "dark brown hair" in prompt and "Hazel eyes" in prompt and "Olive skin" in prompt, "identity"
    assert "wide set eyes" in prompt and "arched eyebrows" in prompt
    if nonhuman:
        assert "werewolf character" in prompt and "subtle supernatural tells" in prompt, "species"
    assert prompt.endswith("Non-sexual. PG-13."), "protected tail"


def _pad_sketch_to_cap(monkeypatch, nonhuman: bool, geometry: dict[str, str]) -> tuple[int, str]:
    with monkeypatch.context() as m:
        m.setattr(fgs, "geometry_phrase", _historical_phrase_for("sketch"))
        probe = _build_sketch_prompt(_free_text_spec(nonhuman=nonhuman, pad=0, **geometry), "pencil")
        pad = _SKETCH_PROMPT_CAP - len(probe)
        assert pad >= 0, "the fixture must sit under the cap at HEAD wording"
        head = _build_sketch_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), "pencil")
    assert len(head) == _SKETCH_PROMPT_CAP
    _sketch_sections_present(head, pad, nonhuman)
    return pad, head


@pytest.mark.parametrize("nonhuman", [False, True], ids=["human", "werewolf"])
@pytest.mark.parametrize("pick", ["worst_full", "worst_compact"])
def test_sketch_near_cap_free_text_keeps_face_features(monkeypatch, nonhuman, pick):
    """face_features is the FIRST section the sketch trims, so it is exactly what
    a longer geometry block would have cost at the cap."""
    geometry = _worst_geometry() if pick == "worst_full" else _worst_compact_geometry()
    pad, head = _pad_sketch_to_cap(monkeypatch, nonhuman, geometry)
    prompt = _build_sketch_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), "pencil")
    assert len(prompt) <= len(head) <= _SKETCH_PROMPT_CAP
    _sketch_sections_present(prompt, pad, nonhuman)
    for field, value in geometry.items():
        assert fgs._LOCK[field][value] in prompt, field


@pytest.mark.parametrize("nonhuman", [False, True], ids=["human", "werewolf"])
def test_sketch_near_cap_free_text_for_every_geometry_combination(monkeypatch, nonhuman):
    with monkeypatch.context() as m:
        m.setattr(fgs, "geometry_phrase", _historical_phrase_for("sketch"))
        pads = {}
        for geometry in _every_geometry_combination():
            probe = _build_sketch_prompt(_free_text_spec(nonhuman=nonhuman, pad=0, **geometry), "pencil")
            pads[tuple(geometry[f] for f in GEOMETRY_FIELDS)] = _SKETCH_PROMPT_CAP - len(probe)
    assert min(pads.values()) >= 0
    for geometry in _every_geometry_combination():
        pad = pads[tuple(geometry[f] for f in GEOMETRY_FIELDS)]
        prompt = _build_sketch_prompt(_free_text_spec(nonhuman=nonhuman, pad=pad, **geometry), "pencil")
        assert len(prompt) <= _SKETCH_PROMPT_CAP, geometry
        assert "x" * pad in prompt and _FEATURES[1] in prompt, geometry
        assert "widows peak hairline" in prompt and "age range 26-35" in prompt, geometry
        assert "Hazel eyes" in prompt and "Olive skin" in prompt, geometry
        if nonhuman:
            assert "werewolf character" in prompt, geometry


def test_human_sketch_keeps_sections_for_every_geometry_combination():
    """Exhaustive, human, sketch: every combination fits at the full tier with
    nothing trimmed — the human sketch is never compacted."""
    longest = 0
    for geometry in _every_geometry_combination():
        prompt = _build_sketch_prompt(_spec(**geometry), "pencil")
        longest = max(longest, len(prompt))
        assert "hairline" in prompt and "age range" in prompt and "Olive skin" in prompt, geometry
        assert fgs._FULL["face_shape"][geometry["face_shape"]] in prompt, geometry
    assert longest <= _SKETCH_PROMPT_CAP

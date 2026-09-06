"""The legacy ``save_image()`` call sites are pinned, and cannot grow.

Phase 4D1 built the canonical durable-asset primitive
(``asset_persistence.persist_image_asset``) but deliberately did NOT migrate the
existing writers — the 4D inspection established that moving the canon cluster
and changing transaction boundaries across every durable writer in one batch was
the risky way to do it. So ``save_image`` survives, and with it the property
that made every rowless object possible: it returns a bare string, and a bare
string is enough to persist bytes a user will see, keep and be accountable for,
with no owner, no safety state and no lifecycle.

Phase 4D2 migrated the ordinary durable writers and both avatar crops: 19 of the
33 pinned calls are gone, and eight modules left the list entirely. What remains
is the canon cluster (4D3) and Adult Studio / the founder artifacts (4D4), plus
the legacy wrapper inside ``stub_image_generator`` that the unmigrated callers
still use.

This test is the containment. It does not migrate anything and does not claim
the boundary is complete. It asserts one thing: the number of legacy callers may
go DOWN as 4D3/4D4 land, and may not go up.

If this fails because you added a call:
    a durable image belongs in persist_image_asset;
    bytes that are deliberately not an asset belong in put_transient_object.
If it fails because you MIGRATED one, lower the number — that is the phase
working.
"""
import ast
import os
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

#: Approved legacy call sites, as of Phase 4D1. Module → number of calls.
#:
#: The counts are per module rather than one total so a migration in one file
#: cannot silently pay for a new call in another. The comment beside each names
#: the increment that will retire it, from the 4D inspection's split.
LEGACY_SAVE_IMAGE_CALLERS: dict[str, int] = {
    # 4D4-3 — the profile-cover generator, which writes a ``UserImage``.
    # ``UserImage`` STAYS its own model: it already has an owner, a status, a
    # provider and a lifecycle, so it is not a rowless-object problem. What it
    # lacks is the shared object-storage and rollback-compensation machinery,
    # and 4D4-3 gives it that WITHOUT merging it into ``CharacterImage``.
    "api/routes/users.py": 1,
    # 4D4 — the founder artifacts. ``adult_studio.py`` left this list in 4D4-1:
    # it did not become an asset, it became an EXPLICIT transient
    # (``put_transient_object``), pinned by
    # ``test_the_adult_studio_generate_route_uses_the_transient_writer``.
    "services/adult_identity_enforcement_executor.py": 2,
}


def _count_save_image_calls() -> dict[str, int]:
    """Count ``save_image(...)`` CALLS per module under app/.

    Parsed rather than grepped: a docstring or comment mentioning the function
    is not a caller, and this file names it many times.
    """
    counts: dict[str, int] = {}
    for dirpath, _dirnames, filenames in os.walk(APP_ROOT):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = str(path.relative_to(APP_ROOT))
            if rel == "core/storage.py":
                continue  # where it is defined
            tree = ast.parse(path.read_text(), filename=str(path))
            n = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
                == "save_image"
            )
            if n:
                counts[rel] = n
    return counts


def test_no_new_legacy_save_image_caller_appears():
    actual = _count_save_image_calls()

    new_modules = sorted(set(actual) - set(LEGACY_SAVE_IMAGE_CALLERS))
    assert not new_modules, (
        f"New module(s) calling the legacy save_image(): {new_modules}. "
        "A durable image asset goes through asset_persistence.persist_image_asset; "
        "bytes that are deliberately not an asset go through "
        "storage.put_transient_object."
    )

    grew = {
        m: (LEGACY_SAVE_IMAGE_CALLERS[m], actual[m])
        for m in actual
        if actual[m] > LEGACY_SAVE_IMAGE_CALLERS[m]
    }
    assert not grew, (
        f"save_image() call count grew in {grew} (approved, actual). "
        "New durable writes must use persist_image_asset."
    )


def test_the_inventory_does_not_claim_more_than_exists():
    """Keeps the pin honest as migrations land.

    A stale entry would let a real new caller hide inside a number that was
    already too high, so a module that has been migrated must be removed from
    the list rather than left with an old count.
    """
    actual = _count_save_image_calls()
    stale = {
        m: (LEGACY_SAVE_IMAGE_CALLERS[m], actual.get(m, 0))
        for m in LEGACY_SAVE_IMAGE_CALLERS
        if actual.get(m, 0) < LEGACY_SAVE_IMAGE_CALLERS[m]
    }
    assert not stale, (
        f"Inventory over-counts {stale} (approved, actual). A migrated writer "
        "must be removed from LEGACY_SAVE_IMAGE_CALLERS, not left at its old count."
    )


def test_create_character_image_is_gone_and_stays_gone():
    """The OTHER way to create an asset row was removed in Phase 4D2.

    ``create_character_image`` was made safe in 4B2 (a required, keyword-only
    ``owner_id``) but it could never be the canonical seam: it took bytes that
    were ALREADY persisted, as a ``file_path``, so it could not own the
    storage/database ordering or compensate a failed write, and it committed its
    own transaction. Its two callers were migrated in 4D2 and the function was
    deleted rather than left standing as a second valid mechanism.

    This asserts BOTH halves — no definition and no caller — because a helper
    that reappeared under any module would restore exactly the property that was
    removed. A different NAME for the same shape is caught by the companion test
    below.
    """
    offenders = set()
    for dirpath, _dirnames, filenames in os.walk(APP_ROOT):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = str(path.relative_to(APP_ROOT))
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                named = (
                    isinstance(node, ast.Call)
                    and (
                        getattr(node.func, "id", None)
                        or getattr(node.func, "attr", None)
                    )
                    == "create_character_image"
                ) or (
                    isinstance(node, ast.FunctionDef)
                    and node.name == "create_character_image"
                )
                if named:
                    offenders.add(rel)
    assert not offenders, (
        f"create_character_image is back in {sorted(offenders)}. It was removed "
        "in Phase 4D2; durable rows go through "
        "asset_persistence.persist_image_asset."
    )


def test_no_helper_creates_a_row_from_an_already_persisted_path():
    """No EQUIVALENT of ``create_character_image`` may exist under another name.

    The dangerous shape is not the name — it is a function that accepts bytes
    somebody else already stored and inserts the row afterwards, because that
    split is what leaves an object with no row when the second half fails, and
    it is what let rows be created with no say over ownership or safety.

    Detected structurally: any function under ``app/`` that both takes a
    ``file_path``-ish parameter AND constructs a ``CharacterImage``. The
    canonical writer is exempt — it MINTS the path it stores rather than
    receiving one — and so are the model and schema modules that define the
    class and its input shape.
    """
    exempt = {
        "services/asset_persistence.py",
        "models/character_image.py",
        "schemas/character_image.py",
    }
    path_params = {"file_path", "image_url", "url", "stored_path", "avatar_url"}
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(APP_ROOT):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = str(path.relative_to(APP_ROOT))
            if rel in exempt:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                args = node.args
                names = {
                    a.arg for a in (args.args + args.kwonlyargs + args.posonlyargs)
                }
                if not (names & path_params):
                    continue
                constructs = any(
                    isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", None) == "CharacterImage"
                    for inner in ast.walk(node)
                )
                if constructs:
                    offenders.append(f"{rel}::{node.name}")
    assert not offenders, (
        f"{offenders} take an already-persisted path AND create a CharacterImage "
        "row. That is the create_character_image shape under a new name: the "
        "bytes and the row must be written by one call — "
        "asset_persistence.persist_image_asset."
    )


@pytest.mark.parametrize("name", ["persist_image_asset", "OwnedBy"])
def test_the_canonical_replacement_exists(name):
    """A pin that names a replacement has to have one."""
    import app.services.asset_persistence as canonical

    assert hasattr(canonical, name)


#: Modules Phase 4D2 moved onto the canonical writer, and the canonical entry
#: point each of them must now use.
#:
#: The POSITIVE half of the pin. The dict above proves a module stopped calling
#: ``save_image``; it cannot tell "migrated" apart from "the write was deleted",
#: and a writer that quietly stopped persisting would satisfy it perfectly. This
#: says what each module does INSTEAD.
MIGRATED_IN_4D2: dict[str, set[str]] = {
    "api/routes/scene_images.py": {"persist_image_asset"},
    "api/routes/body_identity.py": {"persist_image_asset"},
    "api/routes/character_visual.py": {
        "persist_image_asset", "persist_derived_image_asset",
    },
    "api/routes/characters.py": {"persist_derived_image_asset"},
    "api/routes/users.py": {"persist_derived_image_asset"},
    "api/routes/editor_studio.py": {"persist_image_asset"},
    "api/routes/images.py": {"persist_image_asset"},
    "api/routes/adult_studio_admin.py": {"persist_image_asset"},
    "services/candidate_slot.py": {"persist_derived_image_asset"},
    "services/image_generation_pipeline.py": {"persist_image_asset"},
}

#: The canon cluster, moved in Phase 4D3-3. Same positive pin as above.
#:
#: ``canon_card_generator.py`` is deliberately ABSENT: 4D3-3 removed persistence
#: from it entirely rather than migrating it. It generates and evaluates, and
#: returns the selected bytes; the owner-aware caller
#: (``canon_pack_builder.build_v2_pack``) is what persists. A module that
#: correctly writes nothing cannot be pinned to a writer, so
#: ``test_canon_card_generator_persists_nothing`` pins the absence instead.
MIGRATED_IN_4D3: dict[str, set[str]] = {
    "api/routes/canon_api.py": {"persist_image_asset"},
    "api/routes/body_canon.py": {"persist_image_asset"},
    "api/routes/character_accessory.py": {"persist_image_asset"},
    "services/canon_pack_builder.py": {"persist_image_asset"},
}

#: Every module pinned to the canonical writer, whichever phase moved it.
MIGRATED_MODULES: dict[str, set[str]] = {**MIGRATED_IN_4D2, **MIGRATED_IN_4D3}


def test_canon_card_generator_persists_nothing():
    """It generates and evaluates; the caller owns and persists.

    Pinned because the tempting "fix" for a generator that cannot name an owner
    is to hand it a session — which would put ownership semantics in the layer
    with the least information about them, and would re-store every losing
    candidate the selection logic discards.
    """
    called = _called_names("services/canon_card_generator.py")
    assert "save_image" not in called
    assert "persist_image_asset" not in called
    assert "persist_derived_image_asset" not in called


def test_the_legacy_placeholder_wrapper_is_gone():
    """``generate_placeholder_png`` rendered AND stored in one call, returning a
    bare path — the shape that produced rowless objects. 4D3-3 retired it with
    its last caller."""
    import app.services.stub_image_generator as stub

    assert hasattr(stub, "render_placeholder_png")
    assert not hasattr(stub, "generate_placeholder_png")
    assert "save_image" not in _called_names("services/stub_image_generator.py")


def _called_names(rel: str) -> set[str]:
    tree = ast.parse((APP_ROOT / rel).read_text(), filename=rel)
    return {
        (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }


@pytest.mark.parametrize("module, expected", sorted(MIGRATED_MODULES.items()))
def test_a_migrated_module_uses_the_canonical_writer(module, expected):
    called = _called_names(module)
    missing = expected - called
    assert not missing, (
        f"{module} no longer calls {sorted(missing)}. If the writer was removed "
        "deliberately, remove it from the MIGRATED_* map in the same change; if it "
        "was moved back to a hand-built CharacterImage, that is the regression "
        "Phase 4D2 exists to prevent."
    )


@pytest.mark.parametrize("module", sorted(MIGRATED_MODULES))
def test_a_migrated_module_does_not_build_a_character_image_by_hand(module):
    """The row is built by the writer, or it is not a canonical asset.

    A hand-constructed ``CharacterImage(...)`` is how every rowless-adjacent
    defect got in: it can omit an owner, skip the storage key, and set whatever
    safety columns the author remembered. Reading rows is unaffected — this
    catches CONSTRUCTION only.
    """
    tree = ast.parse((APP_ROOT / module).read_text(), filename=module)
    constructed = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "CharacterImage"
    ]
    assert not constructed, (
        f"{module} constructs CharacterImage directly at line(s) {constructed}. "
        "Durable rows come from asset_persistence.persist_image_asset."
    )

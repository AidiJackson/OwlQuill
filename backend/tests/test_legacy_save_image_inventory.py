"""The legacy ``save_image()`` call sites are pinned, and cannot grow.

Phase 4D1 built the canonical durable-asset primitive
(``asset_persistence.persist_image_asset``) but deliberately did NOT migrate the
existing writers — the 4D inspection established that moving the canon cluster
and changing transaction boundaries across every durable writer in one batch was
the risky way to do it. So ``save_image`` survives, and with it the property
that made every rowless object possible: it returns a bare string, and a bare
string is enough to persist bytes a user will see, keep and be accountable for,
with no owner, no safety state and no lifecycle.

This test is the containment. It does not migrate anything and does not claim
the boundary is complete. It asserts one thing: the number of legacy callers may
go DOWN as 4D2/4D3/4D4 land, and may not go up.

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
    # 4D2 — straightforward durable writers and the two avatar crops
    "api/routes/characters.py": 1,               # set_character_avatar crop (rowless)
    "api/routes/users.py": 2,                    # set_avatar crop (rowless), profile cover
    "api/routes/scene_images.py": 1,
    "api/routes/body_identity.py": 2,
    "api/routes/character_visual.py": 8,
    "api/routes/editor_studio.py": 2,            # one durable, one job snapshot (transient)
    "services/candidate_slot.py": 1,
    "services/image_generation_pipeline.py": 2,
    "services/stub_image_generator.py": 1,
    # 4D3 — the canon cluster, with its own regression verification
    "api/routes/canon_api.py": 3,
    "api/routes/body_canon.py": 2,
    "api/routes/character_accessory.py": 2,
    "services/canon_card_generator.py": 1,
    "services/canon_pack_builder.py": 1,
    # 4D4 — Adult Studio, founder artifacts, remaining writers
    "api/routes/adult_studio.py": 1,             # rowless: bytes returned to the client
    "api/routes/adult_studio_admin.py": 1,
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


def test_create_character_image_has_exactly_its_known_legacy_callers():
    """The other legacy way to create an asset row, pinned the same way.

    ``create_character_image`` was made safe in 4B2 (a required, keyword-only
    ``owner_id``) but it is NOT the canonical seam and must not become a second
    one: it takes bytes that are already persisted, so it cannot own the
    storage/DB ordering, and it commits its own transaction. Its two callers are
    scheduled for 4D2; until then, no third may appear.
    """
    approved = {"api/routes/images.py", "api/routes/adult_studio_admin.py"}
    callers = set()
    for dirpath, _dirnames, filenames in os.walk(APP_ROOT):
        if "__pycache__" in dirpath:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            rel = str(path.relative_to(APP_ROOT))
            if rel == "services/character_visual.py":
                continue  # where it is defined
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (
                    getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None)
                ) == "create_character_image":
                    callers.add(rel)
    assert callers <= approved, (
        f"New create_character_image caller(s): {sorted(callers - approved)}. "
        "Use asset_persistence.persist_image_asset."
    )


@pytest.mark.parametrize("name", ["persist_image_asset", "OwnedBy"])
def test_the_canonical_replacement_exists(name):
    """A pin that names a replacement has to have one."""
    import app.services.asset_persistence as canonical

    assert hasattr(canonical, name)

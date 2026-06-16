"""S24W — Adult LoRA v4 training-pack *candidate review* (file-backed, no DB).

Reads the candidate pack staged by ``scripts/s24v_adult_pack_builder.py`` and
persists per-image approve/reject decisions back into its ``manifest.json``.

Deliberately tiny + DB-free (the sprint defers any schema): the manifest on disk
is the source of truth. Summer-only, admin-gated at the route layer. This module
NEVER trains, exports a final pack, or regenerates images — it only flips the
``status`` field of already-generated candidates.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

# scripts/summer_lora_v4_pack_candidates lives at the repo root.
# services → app → backend → repo-root == parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
CANDIDATES_DIR = _REPO_ROOT / "scripts" / "summer_lora_v4_pack_candidates"
MANIFEST_PATH = CANDIDATES_DIR / "manifest.json"

# The only character with a staged v4 candidate pack this sprint.
SUMMER_CHARACTER_ID = 60

# Statuses a reviewer may set. "failed" is builder-only (generation error) and
# cannot be set via review; "pending_review" lets a reviewer undo a decision.
REVIEWABLE_STATUSES = {"pending_review", "approved", "rejected"}

# Serialize manifest read-modify-write so concurrent approve/reject clicks from
# the single admin can't interleave and lose a decision.
_lock = threading.Lock()


class PackNotFound(Exception):
    """No candidate pack manifest is staged on disk."""


class CandidateNotFound(Exception):
    """No candidate with the requested role exists in the manifest."""


class InvalidStatus(Exception):
    """The requested review status is not one a reviewer may set."""


def _read_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise PackNotFound(f"No candidate pack at {MANIFEST_PATH}")
    return json.loads(MANIFEST_PATH.read_text())


def _recompute_counts(manifest: dict) -> None:
    images = manifest.get("images", [])

    def _n(s: str) -> int:
        return sum(1 for e in images if e.get("status") == s)

    manifest["counts"] = {
        "total_roles": len(images),
        "pending_review": _n("pending_review"),
        "approved": _n("approved"),
        "rejected": _n("rejected"),
        "failed": _n("failed"),
    }


def load_review_state() -> dict:
    """Return the candidate pack manifest (raises PackNotFound if unstaged)."""
    manifest = _read_manifest()
    _recompute_counts(manifest)
    return manifest


def get_candidate(role: str) -> Optional[dict]:
    """Return the manifest entry for ``role`` (or None)."""
    for e in _read_manifest().get("images", []):
        if e.get("role") == role:
            return e
    return None


def image_path_for_role(role: str) -> Optional[Path]:
    """Resolve the on-disk PNG for a candidate role, if it exists.

    Guards against path traversal: the resolved file must stay inside the
    candidates images directory.
    """
    entry = get_candidate(role)
    if not entry or not entry.get("image"):
        return None
    path = (CANDIDATES_DIR / entry["image"]).resolve()
    images_root = (CANDIDATES_DIR / "images").resolve()
    if images_root not in path.parents or not path.is_file():
        return None
    return path


def set_review_status(role: str, new_status: str) -> dict:
    """Persist a reviewer's approve/reject/pending decision into manifest.json.

    Returns the updated manifest entry. Raises InvalidStatus / CandidateNotFound /
    PackNotFound on bad input. A failed (un-generated) candidate cannot be reviewed.
    """
    if new_status not in REVIEWABLE_STATUSES:
        raise InvalidStatus(new_status)
    with _lock:
        manifest = _read_manifest()
        entry = next(
            (e for e in manifest.get("images", []) if e.get("role") == role), None
        )
        if entry is None:
            raise CandidateNotFound(role)
        if entry.get("status") == "failed":
            raise InvalidStatus("cannot review a failed candidate")
        entry["status"] = new_status
        _recompute_counts(manifest)
        # Reflect that decisions are in progress; final export stays gated.
        manifest["review_state"] = (
            "review_complete"
            if manifest["counts"]["pending_review"] == 0
            else "candidates_pending_review"
        )
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return entry

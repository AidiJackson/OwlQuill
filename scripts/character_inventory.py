"""Read-only per-character dependency inventory, for planning founder cleanup.

Answers one question about ONE character: "what hangs off this character, and
what would each cleanup action (rename / private / unpublish / delete) touch?"
— in COUNTS, over a connection that cannot write.

SAME PHILOSOPHY, SAME BOUNDARY, AS ``scripts/media_inventory.py``
-----------------------------------------------------------------
This tool does not re-implement the read-only boundary; it IMPORTS it, so there
is one implementation to review and one test suite pinning it:

1. **The database role** — :func:`media_inventory.assert_no_write_privileges`
   refuses unless the server reports ``current_user`` holds no
   INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER on any table this tool
   reads (:data:`PRIVILEGE_CHECK_TABLES`) and no CREATE on ``public``.
2. **Server-side read-only transaction** — the engine is
   :func:`media_inventory.build_engine`, opened with
   ``default_transaction_read_only=on``, and :func:`media_inventory.assert_read_only`
   makes the server confirm it before any inventory query runs.
3. **Client-side statement screen** — every statement passes
   :func:`media_inventory.statement_is_read_only` at ``before_cursor_execute``.
4. **No ORM, no ``app.*`` imports, no storage/provider/HTTP client.**

``--expect`` is REQUIRED (a URL existing is not a statement of intent) and
``--verify-only`` runs the handshake and stops.

THERE IS NO ARBITRARY SQL
-------------------------
The query set is :data:`CHECKS`, fixed in this file. The ONLY value an operator
supplies to a query is ``--character-id``, an integer, passed as a BOUND
parameter. There is no ``--sql``, no query file and no REPL. Want another
count? Add a reviewed entry to :data:`CHECKS`.

WHAT IT PRINTS, AND WHAT IT NEVER FETCHES
-----------------------------------------
It prints the character's id, name, owner id, visibility and publication flags
— enough to confirm it is looking at the character you meant — and otherwise
only counts and status/kind/type labels. No post or comment prose, message
body, notification payload text, prompt, image url or path, email, username,
connection string, secret or key is SELECTed: matching and counting happen in
SQL and what comes back is aggregates. Notification payloads are matched in SQL
with ``LIKE`` on the character-id keys; the payload itself never leaves the
server.

Each section also states what ``DELETE /characters/{id}`` does to it
(CASCADE / SET NULL / soft reference), taken from the models' foreign keys and
pinned against them by ``backend/tests/test_character_inventory.py``.

INVOCATION
----------
::

    python scripts/character_inventory.py --url-env DATABASE_URL --expect DEV --verify-only
    python scripts/character_inventory.py --url-env DATABASE_URL --expect DEV --character-id 59

For any other target, export a SELECT-only role's URL into a variable of your
choosing and name that variable. The value is never printed.
"""
from __future__ import annotations

import argparse
import json as _json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Repo root, derived from this file, so the sibling modules import wherever the
# checkout lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from scripts.media_inventory import (
    EXPECTABLE,
    FORBIDDEN_IN_JSON,
    ReadOnlyViolation,
    WritePrivilegeHeld,
    assert_expected_target,
    assert_no_write_privileges,
    assert_read_only,
    build_engine,
    column_exists,
    report_identity,
    table_exists,
)

APPLICATION_NAME = "ficshon-character-inventory-readonly"

#: What ``DELETE /characters/{id}`` does to each table that references a
#: character, keyed ``(table, column)``. Mirrors the ``ondelete`` of every
#: ForeignKey to ``characters.id`` in ``backend/app/models``; the test suite
#: asserts the two agree, so a new FK cannot be added without this tool
#: learning about it.
ON_CHARACTER_DELETE: dict[tuple[str, str], str] = {
    ("users", "active_character_id"): "SET NULL",
    ("posts", "character_id"): "SET NULL",
    ("comments", "character_id"): "SET NULL",
    ("scene_posts", "character_id"): "SET NULL",
    ("story_space_posts", "character_id"): "SET NULL",
    ("published_story_segments", "character_id"): "SET NULL",
    ("post_mentions", "mentioned_character_id"): "SET NULL",
    ("character_images", "character_id"): "SET NULL",
    ("image_generation_jobs", "character_id"): "SET NULL",
    ("editor_jobs", "character_id"): "SET NULL",
    ("conversations", "character_a_id"): "CASCADE",
    ("conversations", "character_b_id"): "CASCADE",
    ("messages", "sender_character_id"): "CASCADE",
    ("character_dna", "character_id"): "CASCADE",
    ("character_identity_canon", "character_id"): "CASCADE",
    ("character_style_elements", "character_id"): "CASCADE",
    ("candidate_slots", "character_id"): "CASCADE",
    ("identity_snapshots", "character_id"): "CASCADE",
    ("identity_pack_jobs", "character_id"): "CASCADE",
    ("adult_studio_identities", "character_id"): "CASCADE",
    ("adult_identity_models", "character_id"): "CASCADE",
    ("adult_founder_jobs", "character_id"): "CASCADE",
}


@dataclass(frozen=True)
class Check:
    """One fixed, reviewed query.

    ``shape``: ``"row"`` (one row of named columns), ``"group"`` (rows of
    labels + a trailing ``n`` count) or ``"scalar"``. ``requires`` lists the
    ``table`` or ``table.column`` names that must exist; if any is missing the
    check is reported ABSENT rather than run. ``on_delete`` is the consequence
    note printed beside it.
    """
    section: str
    key: str
    sql: str
    shape: str
    requires: tuple[str, ...]
    on_delete: str = ""
    params: tuple[str, ...] = field(default=("cid",))


def _notification_patterns(cid: int, key: str) -> dict[str, str]:
    """LIKE patterns matching ``"<key>":<cid>`` followed by ``,`` or ``}``.

    Both separator spellings are covered: the compact form
    ``services/notifications.create_notification`` writes (``"k":59``) and the
    ``json.dumps`` default (``"k": 59``) that a legacy row may carry. The
    trailing delimiter is what stops 5 matching 59. Built from an ``int`` only.
    """
    cid = int(cid)
    pats = {}
    for i, sep in enumerate((":", ": ")):
        for j, end in enumerate((",", "}")):
            pats[f"{key}_{i}{j}"] = f'%"{key}"{sep}{cid}{end}%'
    return pats


def _notification_where(key: str) -> str:
    return " OR ".join(f"payload LIKE :{key}_{i}{j}" for i in range(2) for j in range(2))


_NOTIF_AUTHOR_PARAMS = tuple(f"author_character_id_{i}{j}" for i in range(2) for j in range(2))
_NOTIF_MENTIONED_PARAMS = tuple(f"mentioned_character_id_{i}{j}" for i in range(2) for j in range(2))

#: The complete query set. Every statement is portable SQL (no casts, no regex,
#: no dialect functions) so the contract test can run it for real on SQLite.
CHECKS: tuple[Check, ...] = (
    # ── Identity ─────────────────────────────────────────────────────────────
    Check("identity", "character",
          "SELECT id, name, owner_id, visibility, public_home_enabled, visual_locked, "
          "CASE WHEN avatar_url IS NULL OR avatar_url = '' THEN 0 ELSE 1 END AS avatar_set, "
          "CASE WHEN cover_url IS NULL OR cover_url = '' THEN 0 ELSE 1 END AS cover_set, "
          "CASE WHEN identity_spec_json IS NULL THEN 0 ELSE 1 END AS identity_spec_present, "
          "CASE WHEN body_canon_json IS NULL THEN 0 ELSE 1 END AS body_canon_present "
          "FROM characters WHERE id = :cid",
          "row", ("characters",)),
    Check("identity", "selected_as_active_character_by_accounts",
          "SELECT COUNT(*) FROM users WHERE active_character_id = :cid",
          "scalar", ("users.active_character_id",), "SET NULL"),
    # Which image row (if any) each display pointer names, without the pointer.
    # Suffix match: the stored pointer is a url or path ending in the row's
    # file_path. Approximate by design (LIKE wildcards in a path could widen
    # it); it answers "is the avatar one of this character's active images?".
    Check("identity", "avatar_pointer_rows",
          "SELECT ci.status, ci.kind, "
          "CASE WHEN ci.character_id = c.id THEN 'this_character' "
          "WHEN ci.character_id IS NULL THEN 'unassociated' ELSE 'other_character' END AS assoc, "
          "COUNT(*) AS n FROM characters c JOIN character_images ci "
          "ON ci.file_path IS NOT NULL AND ci.file_path <> '' AND c.avatar_url LIKE '%' || ci.file_path "
          "WHERE c.id = :cid GROUP BY ci.status, ci.kind, assoc",
          "group", ("characters", "character_images"),
          "pointer removed with the character; image row kept"),
    Check("identity", "cover_pointer_rows",
          "SELECT ci.status, ci.kind, "
          "CASE WHEN ci.character_id = c.id THEN 'this_character' "
          "WHEN ci.character_id IS NULL THEN 'unassociated' ELSE 'other_character' END AS assoc, "
          "COUNT(*) AS n FROM characters c JOIN character_images ci "
          "ON ci.file_path IS NOT NULL AND ci.file_path <> '' AND c.cover_url LIKE '%' || ci.file_path "
          "WHERE c.id = :cid GROUP BY ci.status, ci.kind, assoc",
          "group", ("characters", "character_images"),
          "pointer removed with the character; image row kept"),

    # ── Social ───────────────────────────────────────────────────────────────
    Check("social", "posts",
          "SELECT COUNT(*) AS total, "
          "COALESCE(SUM(CASE WHEN image_url IS NOT NULL AND image_url <> '' THEN 1 ELSE 0 END), 0) AS with_image, "
          "COALESCE(SUM(CASE WHEN realm_id IS NULL THEN 1 ELSE 0 END), 0) AS without_realm "
          "FROM posts WHERE character_id = :cid",
          "row", ("posts",), "SET NULL (post stays, attribution detached)"),
    Check("social", "posts_by_realm_visibility",
          "SELECT CASE WHEN r.id IS NULL THEN 'no_realm' WHEN r.is_public THEN 'public_realm' "
          "ELSE 'private_realm' END AS realm, COUNT(*) AS n "
          "FROM posts p LEFT JOIN realms r ON r.id = p.realm_id WHERE p.character_id = :cid "
          "GROUP BY realm",
          "group", ("posts", "realms")),
    Check("social", "posts_by_kind",
          "SELECT post_kind, COUNT(*) AS n FROM posts WHERE character_id = :cid GROUP BY post_kind",
          "group", ("posts",)),
    # Deleting one of THIS character's posts also deletes these (comments and
    # reactions cascade from the post), so they matter to per-post cleanup.
    Check("social", "others_comments_on_its_posts",
          "SELECT COUNT(*) AS comments, COUNT(DISTINCT cm.author_user_id) AS distinct_accounts "
          "FROM comments cm JOIN posts p ON p.id = cm.post_id "
          "WHERE p.character_id = :cid AND cm.author_user_id <> p.author_user_id",
          "row", ("comments", "posts"), "kept; deleting a POST would cascade these"),
    Check("social", "reactions_on_its_posts",
          "SELECT COUNT(*) AS reactions, COUNT(DISTINCT rx.user_id) AS distinct_accounts "
          "FROM reactions rx JOIN posts p ON p.id = rx.post_id WHERE p.character_id = :cid",
          "row", ("reactions", "posts"), "kept; deleting a POST would cascade these"),
    Check("social", "comments",
          "SELECT COUNT(*) FROM comments WHERE character_id = :cid",
          "scalar", ("comments",), "SET NULL (comment stays, attribution detached)"),
    Check("social", "scene_posts",
          "SELECT COUNT(*) FROM scene_posts WHERE character_id = :cid",
          "scalar", ("scene_posts",), "SET NULL"),
    Check("social", "mentions_targeting",
          "SELECT COUNT(*) AS mentions, COUNT(DISTINCT pm.post_id) AS posts "
          "FROM post_mentions pm WHERE pm.mentioned_character_id = :cid",
          "row", ("post_mentions",), "SET NULL (mention text stays, link removed)"),
    Check("social", "mentions_targeting_in_other_accounts_posts",
          "SELECT COUNT(DISTINCT pm.post_id) FROM post_mentions pm "
          "JOIN posts p ON p.id = pm.post_id JOIN characters c ON c.id = :cid "
          "WHERE pm.mentioned_character_id = :cid AND p.author_user_id <> c.owner_id",
          "scalar", ("post_mentions", "posts", "characters")),

    # ── Story Spaces ─────────────────────────────────────────────────────────
    Check("story_spaces", "story_space_posts",
          "SELECT COUNT(*) AS posts, COUNT(DISTINCT space_id) AS spaces "
          "FROM story_space_posts WHERE character_id = :cid",
          "row", ("story_space_posts",), "SET NULL"),
    Check("story_spaces", "published_story_segments",
          "SELECT COUNT(*) AS segments, COUNT(DISTINCT published_story_id) AS stories "
          "FROM published_story_segments WHERE character_id = :cid",
          "row", ("published_story_segments",),
          "SET NULL (character_name_snap and content are snapshots and stay)"),

    # ── Messaging ────────────────────────────────────────────────────────────
    Check("messaging", "conversations",
          "SELECT COUNT(*) FROM conversations WHERE character_a_id = :cid OR character_b_id = :cid",
          "scalar", ("conversations",), "CASCADE (removed for BOTH participants)"),
    Check("messaging", "messages_in_its_conversations",
          "SELECT COUNT(*) AS total, "
          "COALESCE(SUM(CASE WHEN m.sender_character_id = :cid THEN 1 ELSE 0 END), 0) AS sent_by_it "
          "FROM messages m JOIN conversations cv ON cv.id = m.conversation_id "
          "WHERE cv.character_a_id = :cid OR cv.character_b_id = :cid",
          "row", ("messages", "conversations"), "CASCADE (every message, both sides)"),
    Check("messaging", "conversation_counterparts",
          "SELECT COUNT(*) AS conversations_with_other_accounts, "
          "COUNT(DISTINCT oc.owner_id) AS distinct_other_accounts "
          "FROM conversations cv "
          "JOIN characters me ON me.id = :cid "
          "JOIN characters oc ON oc.id = CASE WHEN cv.character_a_id = :cid "
          "THEN cv.character_b_id ELSE cv.character_a_id END "
          "WHERE (cv.character_a_id = :cid OR cv.character_b_id = :cid) "
          "AND oc.owner_id <> me.owner_id",
          "row", ("conversations", "characters")),

    # ── Notifications (payload is JSON-as-text; matched in SQL, never fetched)
    Check("notifications", "as_actor",
          "SELECT type, COUNT(*) AS n FROM notifications WHERE "
          + _notification_where("author_character_id") + " GROUP BY type",
          "group", ("notifications",),
          "kept (payload snapshots name and preview; no FK)",
          params=_NOTIF_AUTHOR_PARAMS),
    Check("notifications", "as_mentioned",
          "SELECT type, COUNT(*) AS n FROM notifications WHERE "
          + _notification_where("mentioned_character_id") + " GROUP BY type",
          "group", ("notifications",),
          "kept (payload snapshots name and preview; no FK)",
          params=_NOTIF_MENTIONED_PARAMS),

    # ── Images ───────────────────────────────────────────────────────────────
    Check("images", "character_images_by_status_kind",
          "SELECT status, kind, COUNT(*) AS n FROM character_images "
          "WHERE character_id = :cid GROUP BY status, kind",
          "group", ("character_images",),
          "SET NULL (rows stay in the owner's library, unassociated)"),
    Check("images", "image_generation_jobs_by_status",
          "SELECT status, COUNT(*) AS n FROM image_generation_jobs "
          "WHERE character_id = :cid GROUP BY status",
          "group", ("image_generation_jobs",), "SET NULL"),
    Check("images", "editor_jobs_by_state",
          "SELECT state, COUNT(*) AS n FROM editor_jobs WHERE character_id = :cid GROUP BY state",
          "group", ("editor_jobs",), "SET NULL"),

    # ── Canon / identity ─────────────────────────────────────────────────────
    Check("canon", "identity_canon",
          "SELECT status, face_locked, body_locked, "
          "CASE WHEN face_canon_json IS NULL THEN 0 ELSE 1 END AS face_canon_present, "
          "CASE WHEN body_canon_json IS NULL THEN 0 ELSE 1 END AS body_canon_present, "
          "CASE WHEN accessories_json IS NULL THEN 0 ELSE 1 END AS accessories_present, "
          "COUNT(*) AS n FROM character_identity_canon WHERE character_id = :cid "
          "GROUP BY status, face_locked, body_locked, face_canon_present, "
          "body_canon_present, accessories_present",
          "group", ("character_identity_canon",), "CASCADE"),
    Check("canon", "dna",
          "SELECT COUNT(*) FROM character_dna WHERE character_id = :cid",
          "scalar", ("character_dna",), "CASCADE"),
    Check("canon", "identity_snapshots",
          "SELECT COUNT(*) FROM identity_snapshots WHERE character_id = :cid",
          "scalar", ("identity_snapshots",), "CASCADE"),
    Check("canon", "candidate_slots_by_status",
          "SELECT status, COUNT(*) AS n FROM candidate_slots WHERE character_id = :cid GROUP BY status",
          "group", ("candidate_slots",), "CASCADE"),
    Check("canon", "style_elements_by_status",
          "SELECT status, COUNT(*) AS n FROM character_style_elements "
          "WHERE character_id = :cid GROUP BY status",
          "group", ("character_style_elements",), "CASCADE"),
    Check("canon", "identity_pack_jobs_by_status",
          "SELECT status, COUNT(*) AS n FROM identity_pack_jobs WHERE character_id = :cid GROUP BY status",
          "group", ("identity_pack_jobs",), "CASCADE"),

    # ── Adult identity ───────────────────────────────────────────────────────
    Check("adult_identity", "adult_studio_identities_by_status",
          "SELECT status, COUNT(*) AS n FROM adult_studio_identities "
          "WHERE character_id = :cid GROUP BY status",
          "group", ("adult_studio_identities",), "CASCADE"),
    Check("adult_identity", "adult_identity_models_by_status",
          "SELECT status, COUNT(*) AS n FROM adult_identity_models "
          "WHERE character_id = :cid GROUP BY status",
          "group", ("adult_identity_models",), "CASCADE"),
    # Versions that point at trained weights stored OUTSIDE the database: the
    # rows cascade on delete, the external artefacts do not. Counted, never
    # printed.
    Check("adult_identity", "adult_model_versions",
          "SELECT COUNT(*) AS versions, "
          "COALESCE(SUM(CASE WHEN v.lora_weights_uri IS NOT NULL AND v.lora_weights_uri <> '' "
          "THEN 1 ELSE 0 END), 0) AS with_external_weights "
          "FROM adult_identity_model_versions v JOIN adult_identity_models m ON m.id = v.identity_id "
          "WHERE m.character_id = :cid",
          "row", ("adult_identity_model_versions", "adult_identity_models"),
          "CASCADE (rows); external weights are NOT removed"),
    Check("adult_identity", "adult_training_jobs_by_state",
          "SELECT j.state, COUNT(*) AS n FROM adult_identity_training_jobs j "
          "JOIN adult_identity_models m ON m.id = j.identity_id WHERE m.character_id = :cid "
          "GROUP BY j.state",
          "group", ("adult_identity_training_jobs", "adult_identity_models"), "CASCADE"),
    Check("adult_identity", "adult_mark_renders",
          "SELECT COUNT(*) FROM adult_identity_mark_renders r "
          "JOIN adult_identity_models m ON m.id = r.identity_id WHERE m.character_id = :cid",
          "scalar", ("adult_identity_mark_renders", "adult_identity_models"), "CASCADE"),
    Check("adult_identity", "adult_founder_jobs_by_state",
          "SELECT state, COUNT(*) AS n FROM adult_founder_jobs WHERE character_id = :cid GROUP BY state",
          "group", ("adult_founder_jobs",), "CASCADE"),

    # ── Soft references (no FK: nothing happens on delete; ids dangle) ───────
    Check("soft_references", "rp_story_threads_selecting_it",
          "SELECT COUNT(*) FROM rp_story_threads WHERE selected_character_id = :cid",
          "scalar", ("rp_story_threads.selected_character_id",), "no FK (id dangles)"),
)

#: Every table any check reads — the set the write-privilege refusal covers.
PRIVILEGE_CHECK_TABLES: tuple[str, ...] = tuple(sorted({
    req.split(".")[0] for check in CHECKS for req in check.requires
}))


def _available(conn, requires: tuple[str, ...]) -> bool:
    for req in requires:
        table, _, column = req.partition(".")
        if not table_exists(conn, table):
            return False
        if column and not column_exists(conn, table, column):
            return False
    return True


def _params_for(check: Check, cid: int) -> dict:
    """Bind values for *check*. The character id is the only operator input."""
    cid = int(cid)
    values: dict = {"cid": cid}
    values.update(_notification_patterns(cid, "author_character_id"))
    values.update(_notification_patterns(cid, "mentioned_character_id"))
    bound = {"cid": cid} if "cid" in check.sql else {}
    for name in check.params:
        if f":{name}" in check.sql:
            bound[name] = values[name]
    return bound


def _plain(value):
    """JSON-safe scalar: enums from the driver as their string, bools as bools."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def run_check(conn, check: Check, cid: int):
    """Execute one fixed check. Returns ``"ABSENT"`` when the schema lacks it."""
    if not _available(conn, check.requires):
        return "ABSENT"
    result = conn.execute(text(check.sql), _params_for(check, cid))
    if check.shape == "scalar":
        return int(result.scalar() or 0)
    if check.shape == "row":
        row = result.mappings().first()
        return None if row is None else {k: _plain(v) for k, v in row.items()}
    rows = []
    for row in result.mappings().all():
        rows.append({k: _plain(v) for k, v in row.items()})
    return sorted(rows, key=lambda r: [str(v) for v in r.values()])


def inventory(conn, cid: int) -> dict:
    """Run every check for character *cid*; return ``{section: {key: result}}``."""
    cid = int(cid)
    report: dict = {"character_id": cid}
    for check in CHECKS:
        report.setdefault(check.section, {})[check.key] = {
            "result": run_check(conn, check, cid),
            "on_character_delete": check.on_delete or None,
        }
    summary: dict[str, list[str]] = {}
    for (table, column), rule in sorted(ON_CHARACTER_DELETE.items()):
        summary.setdefault(rule, []).append(f"{table}.{column}")
    report["fk_on_character_delete"] = summary
    return report


def print_report(report: dict) -> None:
    ident = report.get("identity", {}).get("character", {}).get("result")
    print(f"\ncharacter {report['character_id']}")
    if not ident:
        print("  NOT FOUND (or characters table absent). Nothing else is meaningful.")
    for section, entries in report.items():
        if section == "character_id":
            continue
        if section == "fk_on_character_delete":
            print("\n== what DELETE /characters/{id} does (foreign keys to characters.id)")
            for rule, cols in entries.items():
                print(f"  {rule}: {', '.join(cols)}")
            continue
        print(f"\n== {section}")
        for key, entry in entries.items():
            note = entry["on_character_delete"]
            suffix = f"   [on delete: {note}]" if note else ""
            result = entry["result"]
            if isinstance(result, list):
                print(f"  {key}:{suffix}")
                if not result:
                    print("    (none)")
                for row in result:
                    print("    " + ", ".join(f"{k}={v}" for k, v in row.items()))
            elif isinstance(result, dict):
                print(f"  {key}: " + ", ".join(f"{k}={v}" for k, v in result.items()) + suffix)
            else:
                print(f"  {key}: {result}{suffix}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only per-character dependency inventory (see module docstring)."
    )
    ap.add_argument("--url-env", required=True,
                    help="NAME of the env var holding the connection string "
                         "(the value is never printed)")
    ap.add_argument("--expect", required=True, choices=EXPECTABLE,
                    help="the classification you believe you are connecting to; "
                         "a mismatch aborts before anything is queried")
    ap.add_argument("--verify-only", action="store_true",
                    help="run the verification handshake and exit")
    ap.add_argument("--character-id", type=int, default=None,
                    help="the character to inventory (integer id)")
    ap.add_argument("--json", default=None,
                    help="also write the report to this path as JSON")
    args = ap.parse_args(argv)

    if not args.verify_only and args.character_id is None:
        print("ABORT: --character-id is required unless --verify-only is given.")
        return 2

    url = os.environ.get(args.url_env)
    if not url:
        print(f"ABORT: environment variable {args.url_env} is not set. "
              "No connection attempted.")
        return 2

    handshake: dict = {"expected_classification": args.expect}
    try:
        actual = assert_expected_target(url, args.expect)
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 3
    print(f"target classification: {actual} (declared {args.expect}; "
          f"from ${args.url_env}, value never printed)")

    engine = build_engine(url, application_name=APPLICATION_NAME)
    report: dict = {}
    try:
        with engine.connect() as conn:
            print("\nverification handshake:")
            report_identity(conn, handshake)
            assert_read_only(conn, handshake)
            assert_no_write_privileges(conn, handshake, tables=PRIVILEGE_CHECK_TABLES)
            if args.verify_only:
                print("\n--verify-only: target verified. No inventory query run.")
                return 0
            report = inventory(conn, args.character_id)
    except WritePrivilegeHeld as exc:
        print(f"\nABORT: {exc}")
        return 4
    except ReadOnlyViolation as exc:
        print(f"\nABORT: {exc}")
        return 5

    print_report(report)

    if args.json:
        payload = _json.dumps({"handshake": handshake, "inventory": report},
                              indent=2, sort_keys=True, default=str)
        lowered = payload.lower()
        for marker in FORBIDDEN_IN_JSON:
            if marker in lowered:
                print(f"ABORT: refusing to write a report containing {marker!r}.")
                return 6
        Path(args.json).write_text(payload)
        print(f"\nJSON report written to {args.json} (counts only)")

    print("\ndone — no write was attempted and none was possible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

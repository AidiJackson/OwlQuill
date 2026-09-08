"""Read-only media inventory, for planning the private/public R2 migration.

Answers one question — "what media does this database point at, what object does
each pointer name, and what would break if direct public serving were removed?"
— in AGGREGATE, for one database, over a connection that cannot write.

THIS MUST NEVER BECOME A GENERAL PRODUCTION DATABASE SHELL.
-----------------------------------------------------------
That is the whole design constraint, and every choice below serves it. There is
no ``--sql`` argument, no query file, no REPL and no way to pass a statement in:
the query set is fixed in this module and changing it means editing this file
and having that edit reviewed. If you find yourself wanting to add arbitrary SQL
"just this once", add a NEW named section here instead, so the thing production
can be asked is always a short list somebody has read.

Nor is it a replacement for the DEV guard. ``scripts/assert_dev_db`` and
``scripts/devdb`` exist so that DEV is the only target ordinary work can reach,
and nothing here weakens either. This module uses that module's PURE classifier
(:func:`classify_database_url`) and never its DEV assertion, so the shared guard
keeps exactly the semantics its own tests pin. Ordinary maintenance scripts must
keep calling ``assert_dev_database()``.

WHERE THE WRITE BOUNDARY ACTUALLY IS
------------------------------------
Stated in order of strength, because the previous version of this docstring
implied the client-side layer was stronger than it is:

1. **THE DATABASE ROLE. This is the boundary.** The intended production run uses
   a role holding SELECT and nothing else. :func:`assert_no_write_privileges`
   refuses to run unless the server itself reports that ``current_user`` lacks
   INSERT / UPDATE / DELETE / TRUNCATE / REFERENCES / TRIGGER on every table
   this tool reads, and lacks CREATE on the schema. A hard refusal, not a
   warning. Nothing below is a substitute for it.
2. **Server-side read-only transaction.** The connection is opened with
   ``-c default_transaction_read_only=on``, so PostgreSQL rejects
   INSERT/UPDATE/DELETE/COPY-FROM and DDL against non-temporary tables.
   :func:`assert_read_only` makes the SERVER confirm both
   ``transaction_read_only`` and ``default_transaction_read_only`` before any
   inventory query runs, so a connection that silently dropped the option never
   reaches the queries.
3. **Client-side statement screen — DEFENCE IN DEPTH ONLY.**
   :func:`statement_is_read_only` strips comments and string literals, then
   requires a SELECT/SHOW/WITH opener, rejects a second statement after a
   semicolon, and rejects a write or control keyword appearing anywhere it
   could execute. It closes the two bypasses the September 2026 audit
   demonstrated against the previous first-keyword-only check
   (``WITH x AS (DELETE ... RETURNING *) SELECT ...`` and
   ``SELECT 1; UPDATE ...``). It is a keyword screen over stripped text, NOT a
   SQL parser, and it is not claimed to be exhaustive — a full parser would be
   a large dependency guarding a path that layers 1 and 2 already close.
4. **No ORM session, no models, no application imports.** Nothing here can
   flush; there is no unit of work and no identity map, only literal SELECT
   text. This module imports ``sqlalchemy`` and one pure sibling classifier and
   NOTHING from ``app.*`` — deliberately, because ``app.core.database`` builds
   an engine at import time and the FastAPI lifespan performs DDL and seeding
   writes. There is no object-storage, provider or HTTP client here at all.

Plus a statement timeout and an idle-in-transaction timeout, so a mistyped query
cannot sit on a lock, and a distinctive ``application_name`` so the connection
is identifiable in ``pg_stat_activity``.

PROVE THE TARGET BEFORE THE EXPENSIVE WORK
------------------------------------------
``--expect`` is REQUIRED and takes the classification the operator believes they
are connecting to. A URL existing is not a statement of intent; naming the
expected classification is. A mismatch aborts before a single inventory query
runs. ``--verify-only`` performs the whole verification handshake — target,
identity, read-only mode, privileges — and exits without inventorying anything.

WHAT IT WILL NOT DO
-------------------
No image bytes are read and no object-storage call of any kind is made. No post
body, message, email, username, prompt or metadata blob is fetched into Python:
matching, counting and object-key extraction happen in SQL, and what comes back
over the wire is counts. Object keys are server-minted uuids rather than user
content, and even those are only ever counted — never printed — unless an
operator explicitly supplies a hashing salt for a bounded multiplicity sample.

The connection string is read from an environment variable NAMED on the command
line. Its value is never printed, logged or echoed; only its classification
(DEV / NEON / LOCAL / UNKNOWN_EXTERNAL) appears in the output, so a transcript
of a run is safe to paste into a ticket.

INVOCATION
----------
Name the variable; never put a connection string on the command line, where it
would land in shell history and in the process list::

    python scripts/media_inventory.py --url-env DATABASE_URL --expect DEV --verify-only
    python scripts/media_inventory.py --url-env DATABASE_URL --expect DEV

For any other target, export the URL into a variable of your choosing first —
for a SELECT-only role — and name that variable instead::

    python scripts/media_inventory.py --url-env RO_URL --expect NEON \\
        --r2-host pub-example.r2.dev --json /tmp/inventory.json

No production hostname, database name, role or connection string belongs in
this file, in its output, or in the commit that carries it. ``--r2-host`` takes
a PUBLIC hostname, which is not a credential; omit it and HTTP pointers are
reported as ``http_unclassified`` rather than guessed at.
"""
from __future__ import annotations

import argparse
import hashlib
import json as _json
import os
import re
import sys
from pathlib import Path

# Repo root, derived from this file, so the sibling guard module imports
# wherever the checkout lives.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError

from scripts.assert_dev_db import classify_database_url

# ── Layer 3: client-side statement screen ─────────────────────────────────────

#: The statement must OPEN with one of these.
_READ_ONLY_OPENER = re.compile(r"^\s*(SELECT|SHOW|WITH)\b", re.IGNORECASE)

#: Write and control keywords. Rejected anywhere in the stripped statement, not
#: only at the start, because a data-modifying CTE puts them in the middle. This
#: is a keyword screen, not a parser: see layer 3 in the module docstring for
#: exactly what it does and does not claim.
#:
#: TRANSACTION-CONTROL WORDS ARE DELIBERATELY ABSENT — ``BEGIN``, ``COMMIT``,
#: ``ROLLBACK``, ``SAVEPOINT``, ``START``, ``END``. Two reasons, and the second
#: is why they cannot simply be added "to be safe":
#:
#: * they confer no write capability on their own. Committing changes nothing
#:   unless a data statement ran, and every one of those IS listed here;
#: * ``END`` closes a ``CASE`` expression, and this tool's pointer
#:   classification is built entirely from ``CASE ... END``. Listing it made the
#:   screen reject three of the tool's own queries — caught by
#:   ``test_media_inventory.py``, which puts every statement shape this module
#:   builds through the screen for exactly this reason.
#:
#: A second statement carrying transaction control is refused anyway: the
#: semicolon rule in :func:`statement_is_read_only` rejects anything after the
#: first statement, whatever it says. ``SET`` and ``RESET`` ARE listed, because
#: those are the two that could turn layer 2 off.
_FORBIDDEN_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "ALTER", "DROP", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "COPY",
    "CALL", "DO", "EXECUTE", "PREPARE",
    "VACUUM", "REINDEX", "CLUSTER", "REFRESH",
    "SET", "RESET", "LOCK", "LISTEN", "NOTIFY",
    "IMPORT", "SECURITY", "OWNER",
)
_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b", re.IGNORECASE
)

#: Shape of an object key this codebase mints (``app.core.storage``:
#: ``generated|transient`` + 32 hex + extension). Reproduced rather than
#: imported because this module must not import ``app.*``; the pin lives in
#: ``tests/test_media_inventory.py``, which imports both and asserts they agree.
DURABLE_KEY_PREFIX = "generated"
TRANSIENT_KEY_PREFIX = "transient"
MINTED_KEY_RE = re.compile(
    rf"^(?:{DURABLE_KEY_PREFIX}|{TRANSIENT_KEY_PREFIX})/[0-9a-f]{{32}}\.[a-z0-9]{{2,5}}$"
)

#: SQL fragment extracting a minted object key from a pointer value, or NULL.
#: Handles every spelling the writers produce: an absolute R2 url
#: (``https://host/generated/<hex>.<ext>``), a local relative path
#: (``static/generated/<hex>.<ext>``), and a bare key.
_KEY_EXPR = (
    r"substring({col} from '(?:^|/)((?:generated|transient)/[0-9a-f]{{32}}\.[a-z0-9]{{2,5}})$')"
)

#: Same shape, loosened: any filename stem. Used ONLY to separate "an object
#: identity we can derive with confidence" from "something object-shaped whose
#: identity we cannot state", which is a distinction the migration needs.
_LOOSE_KEY_EXPR = (
    r"substring({col} from '(?:^|/)((?:generated|transient)/[^/]+)$')"
)


class ReadOnlyViolation(RuntimeError):
    """A statement that is not provably read-only was about to be sent."""


class TargetMismatch(RuntimeError):
    """The connected database is not the classification the operator declared.

    Its message names classifications only, never the URL, host, user or
    password — a refusal that leaks the connection string has traded one
    exposure for another.
    """


class WritePrivilegeHeld(RuntimeError):
    """The connected role can write. Refusing to inventory through it.

    Not a warning. The role is the boundary; a run through a writable role
    would be protected only by a transaction setting and a keyword screen.
    """


def _strip_sql_noise(sql: str) -> str:
    """*sql* with comments and string literals removed.

    Done BEFORE keyword screening so that the tool's own privilege query —
    which legitimately contains ``'INSERT'``, ``'UPDATE'`` and ``'DELETE'`` as
    string arguments to ``has_table_privilege`` — is not rejected by its own
    guard, and so that a keyword hidden in a comment cannot smuggle a statement
    past the semicolon rule either.

    Order matters: block and line comments first (a quote inside a comment is
    not a string delimiter), then dollar-quoted bodies, then single-quoted
    literals with ``''`` escaping. Double-quoted identifiers are LEFT ALONE —
    they are names, not text, and this module quotes table and column names.
    """
    out = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    out = re.sub(r"--[^\n]*", " ", out)
    out = re.sub(r"\$([A-Za-z_]*)\$.*?\$\1\$", " '' ", out, flags=re.DOTALL)
    out = re.sub(r"'(?:[^']|'')*'", " '' ", out)
    return out


def statement_is_read_only(sql: str) -> bool:
    """True when *sql* is provably, conservatively read-only to this screen.

    Three conditions, all required:

    * it OPENS with SELECT / SHOW / WITH;
    * no second statement follows a semicolon — ``SELECT 1; UPDATE t SET ...``
      is one string to the driver and was accepted by the previous
      first-keyword-only check;
    * no write or control keyword appears anywhere in the stripped text — which
      is what rejects ``WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d``,
      the other demonstrated bypass.

    Conservative on purpose: it will refuse a harmless statement that merely
    contains one of these words outside a literal, and that is the correct trade
    for a tool whose entire query set is fixed in this file.
    """
    stripped = _strip_sql_noise(sql)
    if not _READ_ONLY_OPENER.match(stripped):
        return False
    body, _, tail = stripped.partition(";")
    if tail.strip():
        return False
    return _FORBIDDEN_RE.search(body) is None


def build_engine(url: str):
    """A connection the SERVER will refuse to let us write through."""
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "options": (
                "-c default_transaction_read_only=on "
                "-c statement_timeout=120000 "
                "-c idle_in_transaction_session_timeout=120000"
            ),
            "application_name": APPLICATION_NAME,
        },
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _screen(conn, cursor, statement, parameters, context, executemany):
        if not statement_is_read_only(statement):
            raise ReadOnlyViolation(
                "refusing to execute a statement that is not provably "
                f"read-only (opens with {statement.split()[0]!r})"
            )

    return engine


APPLICATION_NAME = "ficshon-media-inventory-readonly"

# ── Verification handshake ────────────────────────────────────────────────────

#: Classifications ``--expect`` accepts. Mirrors the labels
#: ``classify_database_url`` returns; a value it can return but this refuses
#: would make the flag unusable for a legitimate target.
EXPECTABLE = ("DEV", "NEON", "LOCAL", "UNKNOWN_EXTERNAL", "NON_POSTGRES")


def assert_expected_target(url: str, expected: str) -> str:
    """Return the classification of *url*, or raise if it is not *expected*.

    THE POINT OF THE DECLARATION. The previous version printed the
    classification and connected regardless, so aiming at the wrong database
    produced a perfectly successful run against the wrong data and no signal at
    all. A URL existing in an environment variable is not a statement of intent;
    naming the classification you believe you are reaching is.

    Deliberately NOT ``assert_dev_database``. That function means "only DEV,
    ever" and is depended on by every ordinary maintenance path; widening it so
    this one tool could reach production would remove protection from all of
    them. This is the inverse guard, built on the same pure classifier.
    """
    actual = classify_database_url(url)
    if actual != expected:
        raise TargetMismatch(
            f"Refusing to proceed: target classified {actual}, "
            f"but --expect {expected} was declared. Nothing was queried. "
            "(Connection details withheld.)"
        )
    return actual


def assert_read_only(conn, report: dict) -> None:
    """Make the SERVER confirm the transaction mode before anything else."""
    tx = conn.execute(text("SHOW transaction_read_only")).scalar()
    default = conn.execute(text("SHOW default_transaction_read_only")).scalar()
    report["transaction_read_only"] = tx
    report["default_transaction_read_only"] = default
    if tx != "on" or default != "on":
        raise SystemExit(
            "ABORT: the server did not confirm a read-only transaction "
            f"(transaction_read_only={tx!r}, default_transaction_read_only={default!r}). "
            "Refusing to run with write capability."
        )
    print(f"  read-only confirmed by server: transaction_read_only={tx}, "
          f"default_transaction_read_only={default}")


#: Privileges that must NOT be held on any table this tool reads.
#:
#: REFERENCES and TRIGGER are here with INSERT/UPDATE/DELETE/TRUNCATE because
#: both are ways to attach behaviour or constraints to a table, and a role that
#: holds them is not a read-only role however carefully this script behaves.
PROHIBITED_TABLE_PRIVILEGES = (
    "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER",
)

#: Tables whose privileges are checked. The five the brief names, plus the
#: others this tool actually reads — a role that cannot write ``users`` but can
#: write ``character_identity_canon`` is still not read-only.
PRIVILEGE_CHECK_TABLES = (
    "character_images", "user_images", "characters", "users", "posts",
    "realms", "story_spaces", "published_stories", "candidate_slots",
    "editor_jobs", "adult_founder_jobs", "style_presets",
    "character_identity_canon", "identity_snapshots",
)


def assert_no_write_privileges(conn, report: dict) -> None:
    """Refuse unless the server says ``current_user`` cannot write. HARD.

    The role is the write boundary (layer 1), so this is the check that
    establishes it rather than assuming it. Asked of the SERVER via
    ``has_table_privilege`` / ``has_schema_privilege``, so it reflects the real
    grant graph — role inheritance, PUBLIC grants and column grants included —
    and not a belief about how the role was created.

    Schema CREATE is checked too: a role that can create a table in ``public``
    can create one that shadows a name, or a trigger-bearing object, and is not
    read-only in any useful sense.

    A table that does not exist is skipped and reported ABSENT rather than
    treated as safe: absence is a schema fact worth printing, and
    ``has_table_privilege`` raises on an unknown relation, which would otherwise
    abort the handshake for an unrelated reason.
    """
    held: list[str] = []
    absent: list[str] = []
    checked: list[str] = []

    for table in PRIVILEGE_CHECK_TABLES:
        if not table_exists(conn, table):
            absent.append(table)
            continue
        checked.append(table)
        row = conn.execute(
            text(
                "SELECT "
                + ", ".join(
                    f"has_table_privilege(current_user, :t, '{p}') AS p_{p.lower()}"
                    for p in PROHIBITED_TABLE_PRIVILEGES
                )
            ),
            {"t": table},
        ).one()
        for priv in PROHIBITED_TABLE_PRIVILEGES:
            if getattr(row, f"p_{priv.lower()}"):
                held.append(f"{table}:{priv}")

    schema_create = conn.execute(
        text("SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS c")
    ).scalar()
    if schema_create:
        held.append("public:CREATE")

    report["privileges"] = {
        "tables_checked": checked,
        "tables_absent": absent,
        "prohibited_held": held,
        "schema_create": bool(schema_create),
        "read_only_role": not held,
    }

    if held:
        raise WritePrivilegeHeld(
            "Refusing to inventory: the connected role holds write privileges "
            f"({len(held)} grants, e.g. {', '.join(sorted(held)[:5])}). "
            "This tool requires a SELECT-only role. (Connection details withheld.)"
        )
    print(f"  role holds no write privilege on {len(checked)} tables "
          f"and no CREATE on schema public")
    if absent:
        print(f"  tables ABSENT from this database: {', '.join(absent)}")


def report_identity(conn, report: dict) -> None:
    """Credential-safe facts establishing WHICH database this is.

    ``current_database()`` and the major version are printed because they are
    how an operator recognises the target. ``current_user`` is NOT printed: the
    role name is a credential half, the privilege check above already proves
    what matters about it, and a transcript should stay safe to paste. Host and
    port are never read — the classification already carries what is safe to
    say about where this is.
    """
    row = conn.execute(text(
        "SELECT current_database() AS db, "
        "       current_setting('server_version_num') AS ver_num, "
        "       current_setting('application_name') AS app"
    )).one()
    major = int(row.ver_num) // 10000
    report["database"] = row.db
    report["server_version_major"] = major
    report["application_name"] = row.app
    print(f"  database={row.db}  postgres_major={major}  application_name={row.app}")


# ── Schema introspection ─────────────────────────────────────────────────────

def table_exists(conn, table: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name=:t"
    ), {"t": table}).scalar())


def column_exists(conn, table: str, column: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t AND column_name=:c"
    ), {"t": table, "c": column}).scalar())


# ── Reviewed column lists ────────────────────────────────────────────────────

#: Durable media POINTER columns: a text column holding a url or path that names
#: a stored object. Verified against ``backend/app/models/*`` at
#: d32e07a — table names taken from ``__tablename__``, never guessed.
#:
#: ``characters.body_markings_json`` does NOT exist and is deliberately absent:
#: the September 2026 audit brief named it, and the real column carrying
#: persistent markings is ``characters.body_canon_json`` (see the model's own
#: comment). It is inventoried below as CANON JSON, which is what it is.
#:
#: Explicit and reviewed rather than derived from a name pattern, because
#: :func:`unreviewed_media_columns` uses a name pattern to find what this list
#: MISSES, and a list derived from the same pattern could not disagree with it.
POINTER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("characters", "avatar_url"),
    ("characters", "cover_url"),
    ("characters", "portrait_url"),
    ("users", "avatar_url"),
    ("users", "cover_url"),
    ("posts", "image_url"),
    ("realms", "banner_url"),
    ("story_spaces", "cover_url"),
    ("published_stories", "cover_url"),
    ("style_presets", "preview_image_url"),
    ("candidate_slots", "image_url"),
    ("editor_jobs", "final_image_url"),
    ("adult_founder_jobs", "final_image_url"),
)

#: Canon / identity JSON columns holding media references inside a document.
#:
#: The first five mirror ``app.services.canon_references._CANON_SOURCES``, the
#: reviewed list the delete-protection guard already uses — reproduced rather
#: than imported because this module must not import ``app.*``.
#: ``tests/test_media_inventory.py`` imports both and asserts they stay in step,
#: so a canon store added there cannot silently go uninventoried here.
#:
#: ``identity_snapshots`` carries historical copies of the same documents. They
#: are durable references — a rollback reads them — so the objects they name
#: are part of what a storage migration must account for.
CANON_JSON_COLUMNS: tuple[tuple[str, str], ...] = (
    ("character_identity_canon", "face_canon_json"),
    ("character_identity_canon", "body_canon_json"),
    ("character_identity_canon", "accessories_json"),
    ("characters", "identity_anchor_json"),
    ("characters", "body_canon_json"),
    ("characters", "identity_spec_json"),
    ("identity_snapshots", "identity_anchor_json"),
    ("identity_snapshots", "identity_spec_json"),
    ("identity_snapshots", "body_canon_json"),
    ("editor_jobs", "result_json"),
    ("adult_founder_jobs", "result_json"),
    ("image_generation_jobs", "result_json"),
    ("identity_pack_jobs", "result_json"),
)

#: Column-name fragments that make a text column PLAUSIBLY media-bearing.
#:
#: Narrow on purpose. The coverage check below reports a column only when its
#: name contains one of these AND it is absent from both reviewed lists — so an
#: ordinary ``content``, ``bio`` or ``prompt_summary`` never appears, and a new
#: ``hero_image_url`` cannot be added to the schema without this tool saying so.
MEDIA_NAME_FRAGMENTS = (
    "image", "img", "url", "avatar", "cover", "banner", "media",
    "asset", "thumbnail", "thumb", "photo", "picture", "portrait",
    "file_path", "storage_key", "artwork", "poster", "icon",
)

#: Names matching a fragment that are NOT media pointers. Kept tiny and
#: explicit; anything else matching a fragment is reported for review.
MEDIA_NAME_EXCEPTIONS = frozenset({
    ("users", "username"),          # 'name' only via no fragment; defensive
    ("story_state", "cover_color"),  # a colour, not an asset
    ("stories", "cover_color"),
})


def unreviewed_media_columns(conn) -> list[tuple[str, str, str]]:
    """Text/JSON columns that LOOK media-bearing and are in neither reviewed list.

    The fail-loud half of coverage. A future migration adding
    ``characters.hero_image_url`` would otherwise be inventoried by nothing and
    reported by nothing, and the inventory would still print a confident total.

    Narrow by construction — a name fragment from
    :data:`MEDIA_NAME_FRAGMENTS`, restricted to text/varchar/json/jsonb — so it
    surfaces a handful of genuine candidates rather than the ~200 text columns
    this schema has. Reported, not silently accepted: the caller aborts unless
    ``--acknowledge-unreviewed-columns`` is given, so acknowledging is a
    deliberate act recorded in the invocation.
    """
    reviewed = set(POINTER_COLUMNS) | set(CANON_JSON_COLUMNS)
    rows = conn.execute(text("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND data_type IN ('text','character varying','json','jsonb')
        ORDER BY table_name, column_name
    """)).all()

    out: list[tuple[str, str, str]] = []
    for table, column, dtype in rows:
        if (table, column) in reviewed or (table, column) in MEDIA_NAME_EXCEPTIONS:
            continue
        low = column.lower()
        if any(frag in low for frag in MEDIA_NAME_FRAGMENTS):
            out.append((table, column, dtype))
    return out


# ── SQL expression builders (no value ever enters Python) ────────────────────

def _q(table: str, column: str) -> str:
    return f'"{table}"."{column}"'


def _classification_case(col: str, r2_host: str | None) -> str:
    """SQL CASE classifying one pointer value, without returning the value.

    ``data:`` is its own bucket rather than being called a sigil: the eight
    built-in account sigils are exact strings held in ``app.core.account_sigils``
    and this module cannot import them, so it reports the shape it can see and
    leaves the membership question to the application. Every built-in sigil is
    inside ``data_uri``.
    """
    host = "substring({c} from '^https?://([^/]+)')".format(c=col)
    if r2_host:
        our = f"WHEN {host} = :r2_host THEN 'our_r2'"
    else:
        our = "WHEN false THEN 'our_r2'"
    return f"""CASE
        WHEN {col} IS NULL OR {col} = '' THEN 'unset'
        WHEN {col} LIKE 'data:%' THEN 'data_uri'
        WHEN {col} NOT LIKE 'http%' THEN 'local_relative'
        {our}
        ELSE 'other_http'
    END"""


def _backed_exists(col: str) -> str:
    """SQL EXISTS asking whether a pointer resolves to an image row.

    The three spellings mirror ``character_home_media.candidate_file_paths``:
    ``file_path_to_url`` is not injective, so a stored row may be found under
    the bare path, the slash-prefixed path or the ``static/``-stripped path. A
    fourth spelling here, or a missing one, would make this count disagree with
    what the application's own resolver does.
    """
    p1 = f"ltrim({col}, '/')"
    p2 = f"('/' || ltrim({col}, '/'))"
    p3 = f"regexp_replace(ltrim({col}, '/'), '^static/', '')"
    return (
        f"(EXISTS (SELECT 1 FROM character_images ci "
        f"WHERE ci.file_path IN ({col}, {p1}, {p2}, {p3}))"
        f" OR EXISTS (SELECT 1 FROM user_images ui "
        f"WHERE ui.file_path IN ({col}, {p1}, {p2}, {p3})))"
    )


def key_expr(col: str) -> str:
    return _KEY_EXPR.format(col=col)


def loose_key_expr(col: str) -> str:
    return _LOOSE_KEY_EXPR.format(col=col)


# ── Output helpers ───────────────────────────────────────────────────────────

def section(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def _dist(conn, table: str, column: str) -> dict[str, int] | str:
    """``GROUP BY`` one column, or a marker string when it is absent.

    Returns the marker rather than an empty dict so a missing column is
    reported as ABSENT and never rendered as "zero of everything" — inventing a
    value for a column that does not exist is how a migration plan acquires a
    fact nobody checked.
    """
    if not column_exists(conn, table, column):
        return "ABSENT"
    rows = conn.execute(text(
        f'SELECT {_q(table, column)}::text AS v, count(*) AS n '
        f'FROM "{table}" GROUP BY 1 ORDER BY 2 DESC'
    )).all()
    return {str(v): int(n) for v, n in rows}


def _print_dist(label: str, dist) -> None:
    if dist == "ABSENT":
        print(f"  {label:26} ABSENT (column not in this database)")
        return
    print(f"  {label}:")
    for v, n in dist.items():
        print(f"      {v[:44]:46} {n:9}")


# ── Sections ─────────────────────────────────────────────────────────────────

def image_row_census(conn, out: dict) -> None:
    """Per-table row census. The two image models are NOT assumed alike.

    ``character_images`` carries ``visibility``, ``public_gallery_enabled``,
    ``safety_state``, ``safety_policy_version`` and ``storage_key``;
    ``user_images`` carries none of them. Asking for each column by name and
    reporting ABSENT where it is missing is the only way this section can be
    read as evidence rather than as a shape somebody assumed.
    """
    section("1. IMAGE ROW CENSUS")
    out["image_rows"] = {}
    for table in ("character_images", "user_images"):
        entry: dict = {}
        out["image_rows"][table] = entry
        if not table_exists(conn, table):
            entry["present"] = False
            print(f"  {table}: ABSENT")
            continue
        entry["present"] = True
        entry["total"] = int(conn.execute(
            text(f'SELECT count(*) FROM "{table}"')).scalar())
        print(f"\n  {table}: total={entry['total']}")
        for column in ("status", "kind", "provider", "visibility",
                       "safety_state", "safety_policy_version",
                       "public_gallery_enabled"):
            dist = _dist(conn, table, column)
            entry[column] = dist
            _print_dist(column, dist)

        # Ownership / association shape.
        if column_exists(conn, table, "character_id"):
            entry["character_id_null"] = int(conn.execute(text(
                f'SELECT count(*) FROM "{table}" WHERE character_id IS NULL'
            )).scalar())
            print(f"  character_id NULL         {entry['character_id_null']:9}")
        else:
            entry["character_id_null"] = "ABSENT"
        # An orphan by ownership: a row whose owning account no longer exists.
        # Meaningful even with an FK, because a NULLable FK or a detached row is
        # exactly what a backfill leaves behind.
        entry["user_missing"] = int(conn.execute(text(
            f'SELECT count(*) FROM "{table}" t '
            f'WHERE t.user_id IS NOT NULL AND NOT EXISTS '
            f'(SELECT 1 FROM users u WHERE u.id = t.user_id)'
        )).scalar())
        print(f"  owning user missing       {entry['user_missing']:9}")


def storage_identity(conn, out: dict, r2_host: str | None) -> None:
    """Which stored OBJECT each image row names, and whether we can say.

    THE FIELD THE PREVIOUS VERSION NEVER ASKED ABOUT. ``storage_key`` is the R2
    object identity (``generated/<hex>.<ext>``); ``file_path`` is a delivery
    spelling that varies by storage mode. A migration that has counted only
    ``file_path`` has counted urls, not objects.

    ``user_images`` HAS NO ``storage_key`` COLUMN. That is reported as the fact
    it is, and its identity is derived from ``file_path`` alone — not presented
    as though the column existed and happened to be null.
    """
    section("2. STORAGE OBJECT IDENTITY")
    out["storage_identity"] = {}
    for table in ("character_images", "user_images"):
        entry: dict = {}
        out["storage_identity"][table] = entry
        if not table_exists(conn, table):
            entry["present"] = False
            print(f"  {table}: ABSENT")
            continue
        entry["present"] = True
        has_key = column_exists(conn, table, "storage_key")
        entry["has_storage_key_column"] = has_key

        fp = _q(table, "file_path")
        case = _classification_case(fp, r2_host)
        rows = conn.execute(
            text(f'SELECT {case} AS c, count(*) AS n FROM "{table}" GROUP BY 1 ORDER BY 2 DESC'),
            {"r2_host": r2_host} if r2_host else {},
        ).all()
        entry["file_path_class"] = {str(c): int(n) for c, n in rows}

        r = conn.execute(
            text(f"""
                SELECT count(*) AS total,
                       count(DISTINCT {fp}) AS distinct_file_path,
                       count({key_expr(fp)}) AS derivable_strict,
                       count(DISTINCT {key_expr(fp)}) AS distinct_key_strict,
                       count(*) FILTER (WHERE {key_expr(fp)} IS NULL
                                          AND {loose_key_expr(fp)} IS NOT NULL)
                           AS object_shaped_but_not_minted,
                       count(*) FILTER (WHERE {loose_key_expr(fp)} IS NULL)
                           AS not_derivable,
                       count(*) FILTER (WHERE {key_expr(fp)} LIKE 'generated/%')
                           AS prefix_generated,
                       count(*) FILTER (WHERE {key_expr(fp)} LIKE 'transient/%')
                           AS prefix_transient
                FROM "{table}"
            """)
        ).one()
        entry.update({
            "total": int(r.total),
            "distinct_file_path": int(r.distinct_file_path),
            "identity_derivable": int(r.derivable_strict),
            "distinct_object_keys": int(r.distinct_key_strict),
            "object_shaped_but_not_minted": int(r.object_shaped_but_not_minted),
            "identity_not_derivable": int(r.not_derivable),
            "prefix_generated": int(r.prefix_generated),
            "prefix_transient": int(r.prefix_transient),
        })

        print(f"\n  {table}:  storage_key column: {'yes' if has_key else 'NO (identity from file_path only)'}")
        for c, n in entry["file_path_class"].items():
            print(f"      file_path {c:22} {n:9}")
        print(f"      distinct file_path           {entry['distinct_file_path']:9}")
        print(f"      identity derivable (minted)  {entry['identity_derivable']:9}")
        print(f"      distinct object keys         {entry['distinct_object_keys']:9}")
        print(f"      object-shaped, NOT minted    {entry['object_shaped_but_not_minted']:9}")
        print(f"      identity NOT derivable       {entry['identity_not_derivable']:9}")
        print(f"      prefix generated/            {entry['prefix_generated']:9}")
        print(f"      prefix transient/            {entry['prefix_transient']:9}")

        if has_key:
            k = _q(table, "storage_key")
            r = conn.execute(text(f"""
                SELECT count(*) FILTER (WHERE {k} IS NOT NULL) AS present,
                       count(*) FILTER (WHERE {k} IS NULL)     AS missing,
                       count(DISTINCT {k})                     AS distinct_key,
                       count(*) FILTER (WHERE {k} LIKE 'generated/%')  AS gen,
                       count(*) FILTER (WHERE {k} LIKE 'transient/%')  AS tra
                FROM "{table}"
            """)).one()
            entry["storage_key"] = {
                "present": int(r.present), "null": int(r.missing),
                "distinct": int(r.distinct_key),
                "prefix_generated": int(r.gen), "prefix_transient": int(r.tra),
            }
            print(f"      storage_key set/NULL         {r.present:9} / {r.missing}")
            print(f"      distinct storage_key         {r.distinct_key:9}")
        else:
            entry["storage_key"] = "ABSENT"


def pointer_census(conn, out: dict, r2_host: str | None) -> None:
    """Every reviewed durable media POINTER column, classified in aggregate.

    Thirteen columns from :data:`POINTER_COLUMNS`, verified against the models
    rather than guessed. A column or table that is absent is reported ABSENT and
    never silently skipped — "we did not find it" and "it holds nothing" are
    different answers and the migration needs to know which it got.

    Every number here is computed server-side. No pointer VALUE is returned.
    """
    section("3. DENORMALISED POINTER CENSUS")
    out["pointers"] = {}
    params = {"r2_host": r2_host} if r2_host else {}
    for table, column in POINTER_COLUMNS:
        key = f"{table}.{column}"
        if not table_exists(conn, table) or not column_exists(conn, table, column):
            out["pointers"][key] = "ABSENT"
            print(f"  {key:44} ABSENT")
            continue
        col = _q(table, column)
        case = _classification_case(col, r2_host)
        r = conn.execute(text(f"""
            SELECT count(*) FILTER (WHERE {col} IS NOT NULL AND {col} <> '') AS set_count,
                   count(*) FILTER (WHERE {case} = 'local_relative')  AS local_relative,
                   count(*) FILTER (WHERE {case} = 'our_r2')          AS our_r2,
                   count(*) FILTER (WHERE {case} = 'other_http')      AS other_http,
                   count(*) FILTER (WHERE {case} = 'data_uri')        AS data_uri,
                   count(*) FILTER (WHERE {col} IS NOT NULL AND {col} <> ''
                                      AND {_backed_exists(col)})      AS row_backed,
                   count(*) FILTER (WHERE {col} IS NOT NULL AND {col} <> ''
                                      AND NOT {_backed_exists(col)})  AS rowless,
                   count({key_expr(col)})                             AS identity_derivable,
                   count(DISTINCT {key_expr(col)})                     AS distinct_objects
            FROM "{table}"
        """), params).one()
        entry = {
            "set": int(r.set_count),
            "local_relative": int(r.local_relative),
            "our_r2": int(r.our_r2),
            "other_http": int(r.other_http),
            "data_uri_incl_builtin_sigils": int(r.data_uri),
            "row_backed": int(r.row_backed),
            "rowless": int(r.rowless),
            "identity_derivable": int(r.identity_derivable),
            "identity_not_derivable": int(r.set_count) - int(r.identity_derivable),
            "distinct_objects": int(r.distinct_objects),
        }
        if r2_host is None:
            entry["http_unclassified"] = int(r.other_http)
        out["pointers"][key] = entry
        print(f"\n  {key}")
        print(f"      set={entry['set']}  local={entry['local_relative']}  "
              f"our_r2={entry['our_r2']}  other_http={entry['other_http']}  "
              f"data_uri={entry['data_uri_incl_builtin_sigils']}")
        print(f"      row_backed={entry['row_backed']}  ROWLESS={entry['rowless']}  "
              f"identity_derivable={entry['identity_derivable']}  "
              f"not_derivable={entry['identity_not_derivable']}  "
              f"distinct_objects={entry['distinct_objects']}")


def canon_json_census(conn, out: dict) -> None:
    """Media references inside canon / identity / job JSON documents.

    THE GAP THIS REPLACES. The previous scan filtered
    ``LIKE '%static/generated%'``, which in R2 mode matches nothing at all —
    ``file_path`` there is ``https://<host>/generated/<hex>.<ext>`` and carries
    no ``static/``. Every R2 reference embedded in canon was therefore invisible
    to the tool whose entire purpose is planning the R2 migration.

    Extraction is by OBJECT KEY, in SQL, via ``regexp_matches(..., 'g')``. That
    is structural in the sense that matters: it reads the identity the writers
    mint rather than guessing at document shape, it works on TEXT columns
    holding JSON without a cast that malformed content could abort, and it
    returns only server-minted keys — never a prompt, a document or a body.

    Reported per column: total references, distinct object identities, how many
    of those resolve to an image row, and how many references are object-shaped
    but not a minted key (``unclassifiable``). Nested document structure beyond
    the key is deliberately not modelled — see the module's coverage note.
    """
    section("4. CANON / JSON MEDIA REFERENCES")
    out["canon_json"] = {}
    pattern = r"(?:generated|transient)/[0-9a-f]{32}\.[a-z0-9]{2,5}"
    loose = r"(?:static/)?(?:generated|transient)/[^\"'\\s]+"
    for table, column in CANON_JSON_COLUMNS:
        key = f"{table}.{column}"
        if not table_exists(conn, table) or not column_exists(conn, table, column):
            out["canon_json"][key] = "ABSENT"
            print(f"  {key:52} ABSENT")
            continue
        col = _q(table, column)
        r = conn.execute(text(f"""
            WITH refs AS (
                SELECT (regexp_matches({col}::text, :pat, 'g'))[1] AS k
                FROM "{table}" WHERE {col} IS NOT NULL
            ), loose AS (
                SELECT (regexp_matches({col}::text, :loose, 'g'))[1] AS k
                FROM "{table}" WHERE {col} IS NOT NULL
            )
            SELECT (SELECT count(*) FROM refs)                       AS refs,
                   (SELECT count(DISTINCT k) FROM refs)              AS distinct_objects,
                   (SELECT count(*) FROM loose)                      AS loose_refs,
                   (SELECT count(*) FROM refs r2 WHERE EXISTS (
                        SELECT 1 FROM character_images ci
                         WHERE ci.file_path LIKE '%' || r2.k
                    ) OR EXISTS (
                        SELECT 1 FROM user_images ui
                         WHERE ui.file_path LIKE '%' || r2.k
                    ))                                               AS row_backed
        """), {"pat": pattern, "loose": loose}).one()
        entry = {
            "references": int(r.refs),
            "distinct_objects": int(r.distinct_objects),
            "row_backed_references": int(r.row_backed),
            "rowless_references": int(r.refs) - int(r.row_backed),
            "object_shaped_total": int(r.loose_refs),
            "unclassifiable": int(r.loose_refs) - int(r.refs),
        }
        out["canon_json"][key] = entry
        print(f"  {key:52} refs={entry['references']:6} distinct={entry['distinct_objects']:6} "
              f"backed={entry['row_backed_references']:6} rowless={entry['rowless_references']:6} "
              f"unclassifiable={entry['unclassifiable']:5}")


def duplicate_and_orphan(conn, out: dict, salt: str | None = None) -> None:
    """Shared objects, duplicated pointers and dangling lineage.

    Distinguishes an object referenced once from an object several rows share,
    which is the difference between "safe to move with its row" and "moving it
    affects rows nobody looked at". Counts and maximum multiplicity only — no
    identifier is printed.
    """
    section("5. DUPLICATES / SHARED OBJECTS / ORPHANS")
    out["duplicates"] = {}
    for table in ("character_images", "user_images"):
        if not table_exists(conn, table):
            out["duplicates"][table] = "ABSENT"
            continue
        entry: dict = {}
        fp = _q(table, "file_path")
        r = conn.execute(text(f"""
            WITH d AS (
                SELECT {fp} AS v, count(*) AS n FROM "{table}"
                GROUP BY 1 HAVING count(*) > 1
            )
            SELECT count(*) AS dup_values, coalesce(max(n), 0) AS max_multiplicity,
                   coalesce(sum(n), 0) AS rows_involved FROM d
        """)).one()
        entry["file_path"] = {
            "duplicated_values": int(r.dup_values),
            "max_multiplicity": int(r.max_multiplicity),
            "rows_involved": int(r.rows_involved),
        }
        if column_exists(conn, table, "storage_key"):
            k = _q(table, "storage_key")
            r = conn.execute(text(f"""
                WITH d AS (
                    SELECT {k} AS v, count(*) AS n FROM "{table}"
                    WHERE {k} IS NOT NULL GROUP BY 1 HAVING count(*) > 1
                )
                SELECT count(*) AS dup_values, coalesce(max(n), 0) AS max_multiplicity
                FROM d
            """)).one()
            entry["storage_key"] = {
                "duplicated_values": int(r.dup_values),
                "max_multiplicity": int(r.max_multiplicity),
            }
        else:
            entry["storage_key"] = "ABSENT"
        out["duplicates"][table] = entry
        print(f"  {table}: duplicated file_path values="
              f"{entry['file_path']['duplicated_values']} "
              f"(max multiplicity {entry['file_path']['max_multiplicity']}, "
              f"rows {entry['file_path']['rows_involved']})")
        if entry["storage_key"] != "ABSENT":
            print(f"      duplicated storage_key values="
                  f"{entry['storage_key']['duplicated_values']} "
                  f"(max {entry['storage_key']['max_multiplicity']})")

    # A BOUNDED, HASHED sample of the most-shared objects — the one place an
    # object identifier is genuinely useful rather than merely available, since
    # "which objects do the most rows share?" is what decides whether a copy
    # job can move an object with its row. Gated on an operator-supplied salt
    # (:func:`hash_object_key`), capped at 20 rows, and omitted entirely by
    # default so a normal run puts no identifier into Python at all.
    if salt and table_exists(conn, "character_images"):
        rows = conn.execute(text(f"""
            SELECT {key_expr('file_path')} AS k, count(*) AS n
            FROM character_images
            WHERE {key_expr('file_path')} IS NOT NULL
            GROUP BY 1 HAVING count(*) > 1
            ORDER BY 2 DESC, 1 LIMIT 20
        """)).all()
        out["duplicates"]["most_shared_objects_hashed"] = [
            {"object": hash_object_key(k, salt), "rows": int(n)} for k, n in rows
        ]
        print(f"  most-shared objects sampled (hashed, max 20): {len(rows)}")
    else:
        out["duplicates"]["most_shared_objects_hashed"] = "NOT_REQUESTED"

    if column_exists(conn, "character_images", "derived_from_image_id"):
        n = int(conn.execute(text("""
            SELECT count(*) FROM character_images c
            WHERE c.derived_from_image_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM character_images p
                               WHERE p.id = c.derived_from_image_id)
        """)).scalar())
        out["duplicates"]["dangling_derived_from"] = n
        print(f"  dangling derived_from_image_id: {n}")
    else:
        out["duplicates"]["dangling_derived_from"] = "ABSENT"


def public_and_withdrawal_sets(conn, out: dict) -> None:
    """The copy-forward set, the withdrawal set, and a breakage projection.

    An INVENTORY PROJECTION, not a migration: nothing here changes visibility,
    storage or a pointer. It answers "how many distinct objects does each
    shared surface currently depend on being publicly served?", which is the
    number that decides whether a private-bucket migration is a copy job or a
    serving-layer rewrite.
    """
    section("6. PUBLIC-SURFACE SET / WITHDRAWAL SET / BREAKAGE PROJECTION")
    out["surfaces"] = {}

    def _count(label: str, sql: str, **kw) -> None:
        try:
            n = int(conn.execute(text(sql), kw).scalar() or 0)
        except SQLAlchemyError:
            out["surfaces"][label] = "UNAVAILABLE"
            print(f"  {label:52} UNAVAILABLE (schema)")
            return
        out["surfaces"][label] = n
        print(f"  {label:52} {n:9}")

    _count("published_homes", "SELECT count(*) FROM characters WHERE public_home_enabled IS TRUE")
    _count("published_homes_with_avatar_or_cover", """
        SELECT count(*) FROM characters WHERE public_home_enabled IS TRUE
          AND (avatar_url IS NOT NULL OR cover_url IS NOT NULL)""")
    _count("published_home_distinct_avatar_cover_objects", f"""
        WITH u AS (
            SELECT avatar_url AS v FROM characters WHERE public_home_enabled IS TRUE
            UNION ALL
            SELECT cover_url FROM characters WHERE public_home_enabled IS TRUE
        )
        SELECT count(DISTINCT {key_expr('v')}) FROM u WHERE v IS NOT NULL""")
    _count("gallery_selected_active_rows", """
        SELECT count(*) FROM character_images
         WHERE public_gallery_enabled IS TRUE AND status = 'active'""")
    _count("gallery_selected_distinct_objects", f"""
        SELECT count(DISTINCT {key_expr('file_path')}) FROM character_images
         WHERE public_gallery_enabled IS TRUE AND status = 'active'""")
    _count("public_realm_posts_with_attachment", """
        SELECT count(*) FROM posts p JOIN realms r ON r.id = p.realm_id
         WHERE r.is_public IS TRUE AND p.image_url IS NOT NULL""")
    _count("public_realm_distinct_attachment_objects", f"""
        SELECT count(DISTINCT {key_expr('p.image_url')})
          FROM posts p JOIN realms r ON r.id = p.realm_id
         WHERE r.is_public IS TRUE AND p.image_url IS NOT NULL""")

    # Withdrawal set — what a real (byte-level) revocation would have to reach.
    _count("archived_character_images", """
        SELECT count(*) FROM character_images WHERE status = 'archived'""")
    _count("archived_distinct_objects", f"""
        SELECT count(DISTINCT {key_expr('file_path')}) FROM character_images
         WHERE status = 'archived'""")
    _count("archived_objects_also_referenced_by_active_row", f"""
        SELECT count(DISTINCT {key_expr('a.file_path')}) FROM character_images a
         WHERE a.status = 'archived' AND EXISTS (
            SELECT 1 FROM character_images b
             WHERE b.status = 'active' AND b.file_path = a.file_path)""")


def coverage(conn, out: dict, acknowledged: bool) -> None:
    """Report media-looking columns that neither reviewed list accounts for."""
    section("7. SCHEMA COVERAGE (fail-loud)")
    unknown = unreviewed_media_columns(conn)
    out["coverage"] = {
        "reviewed_pointer_columns": len(POINTER_COLUMNS),
        "reviewed_canon_columns": len(CANON_JSON_COLUMNS),
        "unreviewed_media_like_columns": [
            {"table": t, "column": c, "data_type": d} for t, c, d in unknown
        ],
    }
    if not unknown:
        print("  no unreviewed media-looking text/json columns")
        return
    print(f"  {len(unknown)} column(s) look media-bearing and are in NEITHER reviewed list:")
    for t, c, d in unknown:
        print(f"      {t}.{c}  ({d})")
    if not acknowledged:
        raise SystemExit(
            "\nABORT: the schema contains media-looking columns this inventory "
            "does not account for (listed above). Either add them to "
            "POINTER_COLUMNS / CANON_JSON_COLUMNS (a reviewed edit), or re-run "
            "with --acknowledge-unreviewed-columns to record that they were "
            "seen and deliberately excluded. Refusing to report a total that "
            "silently omits them."
        )
    print("  (acknowledged by --acknowledge-unreviewed-columns)")


def run(conn, out: dict, *, r2_host: str | None, acknowledged: bool,
        salt: str | None = None) -> None:
    coverage(conn, out, acknowledged)
    image_row_census(conn, out)
    storage_identity(conn, out, r2_host)
    pointer_census(conn, out, r2_host)
    canon_json_census(conn, out)
    duplicate_and_orphan(conn, out, salt)
    public_and_withdrawal_sets(conn, out)


# ── Optional hashed identifiers ──────────────────────────────────────────────

def hash_object_key(key: str, salt: str) -> str:
    """A stable, non-reversible label for one object key.

    Stable across runs with the same salt, so two inventories can be diffed.
    Not reversible to a bucket path without the salt, so a report can be shared.
    The salt is ALWAYS operator-supplied (``--hash-salt-env``): a constant in
    this file would make every published digest reversible by anyone holding the
    file, which is the whole failure this avoids.
    """
    return hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()[:16]


# ── CLI ──────────────────────────────────────────────────────────────────────

FORBIDDEN_IN_JSON = ("password", "@", "postgres://", "postgresql://")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only production media inventory (see module docstring)."
    )
    ap.add_argument("--url-env", required=True,
                    help="NAME of the env var holding the connection string "
                         "(the value is never printed)")
    ap.add_argument("--expect", required=True, choices=EXPECTABLE,
                    help="the classification you believe you are connecting to; "
                         "a mismatch aborts before anything is queried")
    ap.add_argument("--verify-only", action="store_true",
                    help="run the verification handshake and exit without "
                         "inventorying anything")
    ap.add_argument("--r2-host", default=None,
                    help="PUBLIC R2 hostname, so http pointers can be split "
                         "into ours/foreign; omit and they are reported as "
                         "other_http/http_unclassified")
    ap.add_argument("--json", default=None,
                    help="write the aggregate report to this path as JSON")
    ap.add_argument("--hash-salt-env", default=None,
                    help="NAME of an env var holding a salt, enabling stable "
                         "hashed object labels in the JSON report")
    ap.add_argument("--acknowledge-unreviewed-columns", action="store_true",
                    help="proceed even though media-looking columns are not in "
                         "the reviewed lists (they are still reported)")
    args = ap.parse_args(argv)

    url = os.environ.get(args.url_env)
    if not url:
        print(f"ABORT: environment variable {args.url_env} is not set. "
              "No connection attempted.")
        return 2

    report: dict = {
        "expected_classification": args.expect,
        "verify_only": bool(args.verify_only),
        "r2_host_supplied": args.r2_host is not None,
    }

    # Target FIRST, before a socket is opened.
    try:
        actual = assert_expected_target(url, args.expect)
    except Exception as exc:
        print(f"ABORT: {exc}")
        return 3
    report["classification"] = actual
    print(f"target classification: {actual} (declared {args.expect}; "
          f"from ${args.url_env}, value never printed)")

    salt = os.environ.get(args.hash_salt_env) if args.hash_salt_env else None
    if args.hash_salt_env and not salt:
        print(f"ABORT: --hash-salt-env {args.hash_salt_env} is not set.")
        return 2

    engine = build_engine(url)
    try:
        with engine.connect() as conn:
            print("\nverification handshake:")
            report_identity(conn, report)
            assert_read_only(conn, report)
            assert_no_write_privileges(conn, report)

            if args.verify_only:
                print("\n--verify-only: target verified. No inventory query run.")
            else:
                run(conn, report, r2_host=args.r2_host,
                    acknowledged=args.acknowledge_unreviewed_columns,
                    salt=salt)
    except WritePrivilegeHeld as exc:
        print(f"\nABORT: {exc}")
        return 4
    except ReadOnlyViolation as exc:
        print(f"\nABORT: {exc}")
        return 5

    if args.json:
        payload = _json.dumps(report, indent=2, sort_keys=True, default=str)
        lowered = payload.lower()
        for marker in FORBIDDEN_IN_JSON:
            if marker in lowered:
                print(f"ABORT: refusing to write a report containing {marker!r}.")
                return 6
        Path(args.json).write_text(payload)
        print(f"\nJSON report written to {args.json} "
              f"({len(payload)} bytes, aggregates only)")

    print("\ndone — no write was attempted and none was possible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

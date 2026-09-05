"""Read-only media inventory, for planning the private/public R2 migration.

Answers one question — "what media does this database point at, and what would
have to be copied into a public bucket?" — in AGGREGATE, for one database, over
a connection that cannot write.

THIS MUST NEVER BECOME A GENERAL PRODUCTION DATABASE SHELL.
-----------------------------------------------------------
That is the whole design constraint, and every choice below serves it. There is
no ``--sql`` argument, no query file, no REPL and no way to pass a statement in:
the query set is fixed in :func:`run` and changing it means editing this file
and having that edit reviewed. If you find yourself wanting to add arbitrary SQL
"just this once", add a NEW named section here instead, so the thing production
can be asked is always a short list somebody has read.

Nor is it a replacement for the DEV guard. ``scripts/assert_dev_db`` and
``scripts/devdb`` exist so that DEV is the only target ordinary work can reach,
and nothing here weakens either — this file does not import
``assert_dev_database`` for its own target, precisely so that widening it was
never necessary. Loosening the shared guard would have removed protection from
every caller at once; adding a narrow read-only tool beside it removes it from
none. Ordinary maintenance scripts must keep calling ``assert_dev_database()``.

HOW WRITES ARE PREVENTED — four independent layers
--------------------------------------------------
1. **Server-side transaction mode.** The connection is opened with
   ``-c default_transaction_read_only=on`` in the libpq ``options`` string, so
   PostgreSQL itself rejects INSERT/UPDATE/DELETE/COPY-FROM and DDL against
   non-temporary tables with ``ERROR: cannot execute ... in a read-only
   transaction``. Enforced by the server, not by this file, and therefore in
   force for SQL this file never intended to send.
2. **Verified, not assumed.** Before any inventory query runs,
   :func:`assert_read_only` asks the server for ``transaction_read_only`` and
   ``default_transaction_read_only`` and aborts unless BOTH report ``on``. A
   connection that silently dropped the option never reaches the queries.
3. **Client-side statement allowlist.** A ``before_cursor_execute`` hook raises
   :class:`ReadOnlyViolation` on any statement that is not SELECT / SHOW / WITH,
   so a stray statement is stopped before it reaches the wire.
4. **No ORM session, no models, no application imports.** Nothing here can
   flush; there is no unit of work and no identity map, only literal SELECT
   text.

Plus a statement timeout and an idle-in-transaction timeout, so a mistyped query
cannot sit on a lock, and a distinctive ``application_name`` so the connection
is identifiable in ``pg_stat_activity``.

These are defence in depth on top of, not a substitute for, pointing this at a
role that only holds SELECT.

WHAT IT WILL NOT DO
-------------------
No image bytes are read and no object-storage call of any kind is made. No post
body, message, email, username or file content is printed. Output is counts,
distributions and column names only — even the section that scans every text
column for ``static/generated`` references prints how many matched, never what
they contained.

The connection string is read from an environment variable NAMED on the command
line. Its value is never printed, logged or echoed; only its classification
(DEV / NEON / LOCAL / UNKNOWN_EXTERNAL) appears in the output, so a transcript
of a run is safe to paste into a ticket.

INVOCATION
----------
Name the variable; never put a connection string on the command line, where it
would land in shell history and in the process list::

    python scripts/media_inventory.py --url-env DATABASE_URL

For any other target, export the URL into a variable of your choosing first —
ideally for a SELECT-only role — and name that variable instead::

    python scripts/media_inventory.py --url-env <YOUR_READONLY_URL_VAR>

No production hostname, database name, role or connection string belongs in
this file, in its output, or in the commit that carries it.

VERIFYING THE GUARD
-------------------
The refusals are reproducible against DEV, and were last confirmed there:

* an ``UPDATE`` through this module's engine raises
  :class:`ReadOnlyViolation` and never reaches the server (layer 3);
* the same statement through a hook-free engine carrying these ``connect_args``
  is refused by PostgreSQL with ``cannot execute UPDATE in a read-only
  transaction`` — as are ``DELETE`` and ``CREATE TABLE`` (layer 1).

That probe is deliberately NOT shipped here. It has to emit write statements to
prove anything, and a probe that can be pointed at production is exactly the
capability this tool is built to withhold. Reproduce it against DEV behind
``assert_dev_database()`` if you want to re-confirm the layers.
"""
from __future__ import annotations

import argparse
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

#: Only these may reach the wire. Anything else is a bug or an attack.
_READ_ONLY_SQL = re.compile(r"^\s*(SELECT|SHOW|WITH)\b", re.IGNORECASE)

#: Matches a generated-media filename inside any text or JSON column.
_GENERATED = re.compile(
    r"(?:static/)?generated/([A-Za-z0-9_.\-]+\.(?:png|jpg|jpeg|webp))"
)


class ReadOnlyViolation(RuntimeError):
    """A non-SELECT statement was about to be sent. Nothing is sent."""


def build_engine(url: str):
    """A connection that the SERVER will refuse to let us write through."""
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "options": (
                "-c default_transaction_read_only=on "
                "-c statement_timeout=120000 "
                "-c idle_in_transaction_session_timeout=120000"
            ),
            "application_name": "ficshon-media-inventory-readonly",
        },
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _block_writes(conn, cursor, statement, parameters, context, executemany):
        if not _READ_ONLY_SQL.match(statement):
            raise ReadOnlyViolation(
                f"refusing to execute a non-read statement: {statement.split()[0]!r}"
            )

    return engine


def assert_read_only(conn) -> None:
    """Make the server confirm the mode before anything else happens."""
    tx = conn.execute(text("SHOW transaction_read_only")).scalar()
    default = conn.execute(text("SHOW default_transaction_read_only")).scalar()
    if tx != "on" or default != "on":
        raise SystemExit(
            "ABORT: the server did not confirm a read-only transaction "
            f"(transaction_read_only={tx!r}, default_transaction_read_only={default!r}). "
            "Refusing to run with write capability."
        )
    print(f"  read-only confirmed by server: transaction_read_only={tx}, "
          f"default_transaction_read_only={default}")


def q1(conn, sql, **kw):
    return conn.execute(text(sql), kw).one()


def scalar(conn, sql, **kw):
    return conn.execute(text(sql), kw).scalar()


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def run(conn) -> None:
    # ── 1. image row inventory ────────────────────────────────────────────
    section("1. IMAGE ROWS — storage location")
    for tbl in ("character_images", "user_images"):
        r = q1(conn, f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE file_path LIKE 'http%')     AS absolute_url,
                   count(*) FILTER (WHERE file_path NOT LIKE 'http%') AS local_path
            FROM {tbl}
        """)
        print(f"  {tbl:18} total={r.total:7} absolute/R2={r.absolute_url:7} "
              f"local static/generated={r.local_path:7}")

    section("2. CHARACTER_IMAGES — distribution relevant to migration")
    for col in ("status", "kind", "provider", "visibility"):
        try:
            rows = conn.execute(text(
                f"SELECT {col}::text AS v, count(*) AS n FROM character_images "
                f"GROUP BY 1 ORDER BY 2 DESC"
            )).all()
        except SQLAlchemyError:
            print(f"  {col}: (column absent)")
            continue
        print(f"  by {col}:")
        for v, n in rows:
            print(f"      {str(v):32} {n:7}")

    section("3. SAFETY-EXCLUSION SHAPE — what a copy-forward job must skip")
    r = q1(conn, """
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE metadata_json::text LIKE '%"adult_studio"\: true%'
                              OR metadata_json::text LIKE '%"adult_studio"\:true%')   AS adult_studio,
          count(*) FILTER (WHERE metadata_json::text LIKE '%"editor_generated"\: true%'
                              OR metadata_json::text LIKE '%"editor_generated"\:true%') AS editor_generated,
          count(*) FILTER (WHERE provider IN ('replicate_nsfw','self_hosted'))       AS excluded_provider,
          count(*) FILTER (WHERE metadata_json::text LIKE '%"is_temp"\: true%'
                              OR metadata_json::text LIKE '%"is_temp"\:true%')        AS is_temp
        FROM character_images
    """)
    print(f"  total={r.total}  adult_studio={r.adult_studio}  "
          f"editor_generated={r.editor_generated}  "
          f"excluded_provider={r.excluded_provider}  is_temp={r.is_temp}")

    # ── 4. denormalised pointers ──────────────────────────────────────────
    section("4. DENORMALISED MEDIA POINTERS")
    r = q1(conn, """
        SELECT
          count(*) FILTER (WHERE image_url IS NOT NULL)                     AS with_image,
          count(*) FILTER (WHERE image_url IS NOT NULL
                             AND image_url NOT LIKE 'http%')                AS local_image,
          count(*)                                                          AS total
        FROM posts
    """)
    print(f"  posts: total={r.total}  with image_url={r.with_image}  local={r.local_image}")

    r = q1(conn, """
        SELECT
          count(*)                                                            AS total,
          count(*) FILTER (WHERE avatar_url IS NOT NULL)                      AS any_avatar,
          count(*) FILTER (WHERE avatar_url IS NOT NULL
                             AND avatar_url NOT LIKE 'http%')                 AS local_avatar,
          count(*) FILTER (WHERE cover_url IS NOT NULL)                       AS any_cover,
          count(*) FILTER (WHERE cover_url IS NOT NULL
                             AND cover_url NOT LIKE 'http%')                  AS local_cover
        FROM characters
    """)
    print(f"  characters: total={r.total}  avatar={r.any_avatar} (local {r.local_avatar})  "
          f"cover={r.any_cover} (local {r.local_cover})")

    # ── 5. resolvability of avatar/cover pointers ─────────────────────────
    section("5. AVATAR / COVER RESOLVABILITY (the G-2 question, at scale)")
    for col in ("avatar_url", "cover_url"):
        r = q1(conn, f"""
            WITH ptr AS (
              SELECT {col} AS u FROM characters WHERE {col} IS NOT NULL
            ), cand AS (
              SELECT u,
                     CASE WHEN u LIKE 'http%' THEN u
                          ELSE ltrim(u, '/') END AS p1,
                     CASE WHEN u LIKE 'http%' THEN u
                          ELSE '/' || ltrim(u, '/') END AS p2,
                     CASE WHEN u LIKE 'http%' THEN u
                          ELSE regexp_replace(ltrim(u, '/'), '^static/', '') END AS p3
              FROM ptr
            )
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE EXISTS (
                     SELECT 1 FROM character_images ci
                      WHERE ci.file_path IN (cand.p1, cand.p2, cand.p3))
                     OR EXISTS (
                     SELECT 1 FROM user_images ui
                      WHERE ui.file_path IN (cand.p1, cand.p2, cand.p3))
                   ) AS resolvable
            FROM cand
        """)
        print(f"  {col:11} set={r.total:5}  resolvable to an image row={r.resolvable:5}  "
              f"UNRESOLVED={r.total - r.resolvable:5}")

    # ── 6. every column referencing static/generated ──────────────────────
    section("6. COLUMNS REFERENCING static/generated")
    cols = conn.execute(text("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND data_type IN ('text','character varying','json','jsonb')
        ORDER BY table_name, column_name
    """)).all()

    names: set[str] = set()
    hits = []
    for t, c, dt in cols:
        expr = f'"{c}"::text' if dt in ("json", "jsonb") else f'"{c}"'
        try:
            n = scalar(conn, f'SELECT count(*) FROM "{t}" WHERE {expr} LIKE \'%static/generated%\'')
        except SQLAlchemyError:
            conn.rollback()
            continue
        if n:
            hits.append((t, c, n))
            vals = conn.execute(text(
                f'SELECT {expr} FROM "{t}" WHERE {expr} LIKE \'%static/generated%\''
            )).scalars().all()
            for v in vals:
                names |= set(_GENERATED.findall(v or ""))
    print(f"  scanned {len(cols)} text/json columns")
    for t, c, n in hits:
        print(f"      {t}.{c:24} rows={n}")
    if not hits:
        print("      none")
    print(f"\n  distinct local filenames referenced anywhere: {len(names)}")

    # ── 7. publication surface — the copy-forward set ─────────────────────
    section("7. PUBLIC SURFACE — what a public bucket would have to hold")
    published = scalar(conn, "SELECT count(*) FROM characters WHERE public_home_enabled IS TRUE")
    print(f"  characters with public_home_enabled : {published}")
    r = q1(conn, """
        SELECT count(*) AS n,
               count(*) FILTER (WHERE p.image_url IS NOT NULL) AS with_image
        FROM posts p JOIN realms r ON r.id = p.realm_id
        WHERE r.is_public IS TRUE
    """)
    print(f"  posts in PUBLIC realms              : {r.n} (with an attachment: {r.with_image})")
    r = q1(conn, """
        SELECT count(DISTINCT p.image_url) AS distinct_images
        FROM posts p JOIN realms r ON r.id = p.realm_id
        WHERE r.is_public IS TRUE AND p.image_url IS NOT NULL
    """)
    print(f"  distinct attachment urls, public realms: {r.distinct_images}")
    r = q1(conn, """
        SELECT count(*) AS n FROM characters
        WHERE public_home_enabled IS TRUE
          AND (avatar_url IS NOT NULL OR cover_url IS NOT NULL)
    """)
    print(f"  published characters with avatar/cover : {r.n}")

    # ── 8. rowless pointers ───────────────────────────────────────────────
    section("8. ROWLESS MEDIA POINTERS (a url with no image row behind it)")
    r = q1(conn, """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE NOT EXISTS (
                 SELECT 1 FROM character_images ci WHERE ci.file_path = p.image_url
                    OR ci.file_path = ltrim(p.image_url,'/')
                    OR '/' || ci.file_path = p.image_url)
                 AND NOT EXISTS (
                 SELECT 1 FROM user_images ui WHERE ui.file_path = p.image_url
                    OR ui.file_path = ltrim(p.image_url,'/')
                    OR '/' || ui.file_path = p.image_url)
               ) AS rowless
        FROM posts p WHERE p.image_url IS NOT NULL
    """)
    print(f"  post attachments: {r.total} total, {r.rowless} with NO image row")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url-env", required=True,
                    help="NAME of the env var holding the connection string "
                         "(the value is never printed)")
    args = ap.parse_args()

    url = os.environ.get(args.url_env)
    if not url:
        print(f"ABORT: environment variable {args.url_env} is not set. "
              "No connection attempted.")
        return 2

    print(f"target classification: {classify_database_url(url)}   "
          f"(from ${args.url_env}; value never printed)")

    engine = build_engine(url)
    with engine.connect() as conn:
        assert_read_only(conn)
        run(conn)
    print("\ndone — no write was attempted and none was possible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

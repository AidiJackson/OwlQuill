"""The production media inventory tool's guards, tested without a database.

WHY THESE TESTS EXIST. ``scripts/media_inventory.py`` is the ONE tool in this
repository intended to be pointed at the production database. Until now its
protections were documented as "last confirmed manually against DEV", which is
not a state a reviewer can check and not a state that survives an edit. The
September 2026 readiness audit demonstrated two live bypasses in its statement
screen by hand; those two are pinned here as the first thing this file asserts.

EVERY TEST IS LOCAL. Nothing here opens a socket, and nothing here needs
PostgreSQL: the guards under test are pure functions over strings, plus two
handshake functions exercised against a fake connection. That is deliberate — a
test suite for this tool must not itself be a way to reach a database.

The one exception to "no app imports" is this file: it imports
``app.core.storage`` and ``app.services.canon_references`` ON PURPOSE, to pin the
inventory's reproduced constants against the real ones. The SCRIPT must not
import ``app.*`` (``app.core.database`` builds an engine at import time, and the
FastAPI lifespan performs DDL and seeding writes); a test may, and doing so here
is what stops the copies drifting.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "media_inventory.py"


def _load():
    """Load the script by path, as a module, without executing ``main``."""
    spec = importlib.util.spec_from_file_location("media_inventory_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mi = _load()


# ══════════════════════════════════════════════════════════════════════════════
# 1. The two demonstrated bypasses, and the statement screen generally
# ══════════════════════════════════════════════════════════════════════════════

def test_a_data_modifying_cte_is_rejected():
    """BYPASS #1 from the audit. The previous check matched only the opener.

    ``WITH ... DELETE ... RETURNING`` opens with ``WITH``, so a first-keyword
    test called it read-only. It deletes rows.
    """
    assert not mi.statement_is_read_only(
        "WITH d AS (DELETE FROM users RETURNING *) SELECT * FROM d"
    )


@pytest.mark.parametrize("verb", ["INSERT INTO t VALUES (1)", "UPDATE t SET a=1",
                                  "DELETE FROM t"])
def test_every_data_modifying_cte_shape_is_rejected(verb):
    """Not just DELETE. All three writable CTE forms open with WITH."""
    assert not mi.statement_is_read_only(f"WITH x AS ({verb} RETURNING *) SELECT * FROM x")


def test_a_second_statement_after_a_semicolon_is_rejected():
    """BYPASS #2 from the audit.

    psycopg2 will execute both halves of one string. The previous check read the
    first word, found SELECT, and passed it.
    """
    assert not mi.statement_is_read_only("SELECT 1; UPDATE users SET x=1")


def test_an_ordinary_select_is_accepted():
    assert mi.statement_is_read_only("SELECT count(*) FROM character_images")
    assert mi.statement_is_read_only("  select 1")
    assert mi.statement_is_read_only("SHOW transaction_read_only")
    assert mi.statement_is_read_only("WITH x AS (SELECT 1) SELECT * FROM x")


def test_set_is_rejected():
    """``SET`` is the statement that could turn the server-side guard off.

    Layer 2 is a GUC. If a connection could ``SET
    default_transaction_read_only=off`` it would be the one keyword whose
    absence from this list actually costs protection.
    """
    assert not mi.statement_is_read_only("SET default_transaction_read_only=off")
    assert not mi.statement_is_read_only("RESET ALL")
    assert not mi.statement_is_read_only("SET ROLE postgres")


@pytest.mark.parametrize("sql", [
    "CREATE TABLE t(i int)", "DROP TABLE t", "ALTER TABLE t ADD COLUMN c int",
    "TRUNCATE t", "GRANT ALL ON t TO public", "REVOKE ALL ON t FROM public",
    "COPY t FROM STDIN", "CALL do_thing()", "DO $$ BEGIN END $$",
    "VACUUM FULL", "REFRESH MATERIALIZED VIEW v", "MERGE INTO t USING s ON true",
    "/* hi */ UPDATE t SET a=1", "-- c\nDELETE FROM t",
])
def test_write_and_control_statements_are_rejected(sql):
    assert not mi.statement_is_read_only(sql)


def test_a_keyword_inside_a_string_literal_does_not_reject():
    """The tool's OWN privilege query passes 'INSERT' as a string argument.

    Literals are stripped before keyword screening, so a guard that is
    conservative about keywords is not thereby unable to ask the one question
    that establishes the write boundary.
    """
    assert mi.statement_is_read_only(
        "SELECT has_table_privilege(current_user, 'users', 'INSERT') AS x"
    )
    assert mi.statement_is_read_only("SELECT 'DELETE FROM users' AS harmless_text")


def test_a_keyword_hidden_in_a_comment_cannot_smuggle_a_statement():
    """Comments are stripped, so they can neither hide a keyword nor a semicolon."""
    assert not mi.statement_is_read_only("SELECT 1 /* ; */ ; UPDATE t SET a=1")


def test_case_end_is_not_treated_as_transaction_control():
    """A regression this file exists to catch.

    ``END`` closes a ``CASE`` expression, and the whole pointer classification
    is ``CASE ... END``. Listing ``END`` among the forbidden control words made
    the screen reject three of the tool's own queries.
    """
    assert mi.statement_is_read_only(
        "SELECT CASE WHEN a IS NULL THEN 'x' ELSE 'y' END AS c FROM t"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE TOOL'S OWN SQL PASSES ITS OWN SCREEN
# ══════════════════════════════════════════════════════════════════════════════

def _every_statement_shape() -> dict[str, str]:
    """One representative of every statement shape the module builds.

    Reconstructed from the module's own expression builders rather than copied,
    so tightening the screen or changing a builder is checked against the other.
    """
    q = mi._q("character_images", "file_path")
    return {
        "show_tx": "SHOW transaction_read_only",
        "identity": ("SELECT current_database() AS db, "
                     "current_setting('server_version_num') AS ver_num, "
                     "current_setting('application_name') AS app"),
        "privilege": "SELECT " + ", ".join(
            f"has_table_privilege(current_user, :t, '{p}') AS p_{p.lower()}"
            for p in mi.PROHIBITED_TABLE_PRIVILEGES),
        "schema_priv": "SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS c",
        "table_exists": ("SELECT 1 FROM information_schema.tables "
                         "WHERE table_schema='public' AND table_name=:t"),
        "coverage": ("SELECT table_name, column_name, data_type FROM "
                     "information_schema.columns WHERE table_schema='public' AND "
                     "data_type IN ('text','character varying','json','jsonb') "
                     "ORDER BY table_name, column_name"),
        "dist": f'SELECT {q}::text AS v, count(*) AS n FROM "character_images" GROUP BY 1 ORDER BY 2 DESC',
        "user_missing": ('SELECT count(*) FROM "character_images" t WHERE t.user_id IS NOT NULL '
                         'AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = t.user_id)'),
        "class_with_host": f'SELECT {mi._classification_case(q, "pub-x.r2.dev")} AS c FROM "character_images"',
        "class_no_host": f'SELECT {mi._classification_case(q, None)} AS c FROM "character_images"',
        "backed": f'SELECT count(*) FROM "characters" WHERE {mi._backed_exists(mi._q("characters", "avatar_url"))}',
        "key_expr": f'SELECT count(DISTINCT {mi.key_expr(q)}) FROM "character_images"',
        "loose_key": f'SELECT count(*) FROM "character_images" WHERE {mi.loose_key_expr(q)} IS NULL',
        "canon": (f'WITH refs AS (SELECT (regexp_matches({q}::text, :pat, \'g\'))[1] AS k '
                  f'FROM "character_images" WHERE {q} IS NOT NULL) '
                  f'SELECT (SELECT count(*) FROM refs) AS refs'),
        "dupes": (f'WITH d AS (SELECT {q} AS v, count(*) AS n FROM "character_images" '
                  f'GROUP BY 1 HAVING count(*) > 1) SELECT count(*) AS dv, '
                  f'coalesce(max(n), 0) AS mm FROM d'),
        "surface_union": (f'WITH u AS (SELECT avatar_url AS v FROM characters '
                          f'WHERE public_home_enabled IS TRUE UNION ALL SELECT cover_url '
                          f'FROM characters WHERE public_home_enabled IS TRUE) '
                          f'SELECT count(DISTINCT {mi.key_expr("v")}) FROM u WHERE v IS NOT NULL'),
        "archived": "SELECT count(*) FROM character_images WHERE status = 'archived'",
        "shared_sample": (f'SELECT {mi.key_expr("file_path")} AS k, count(*) AS n '
                          f'FROM character_images WHERE {mi.key_expr("file_path")} IS NOT NULL '
                          f'GROUP BY 1 HAVING count(*) > 1 ORDER BY 2 DESC, 1 LIMIT 20'),
    }


@pytest.mark.parametrize("name", sorted(_every_statement_shape()))
def test_the_tools_own_sql_passes_its_own_screen(name):
    """A guard the tool cannot get past is a guard that stops the tool.

    Tightening the keyword list is the natural way to break this, and it did:
    listing ``END`` for transaction control silently disabled the pointer
    classification. Every shape is checked so that failure is a test failure and
    not a production run that aborts halfway.
    """
    assert mi.statement_is_read_only(_every_statement_shape()[name]), name


# ══════════════════════════════════════════════════════════════════════════════
# 3. Expected-target guard
# ══════════════════════════════════════════════════════════════════════════════

DEV_URL = "postgresql://u:p@helium/postgres"
NEON_URL = "postgresql://neondb_owner:npg_leakcanary@ep-x-y-1.eu-central-1.aws.neon.tech/neondb"


def test_a_matching_declaration_is_accepted():
    assert mi.assert_expected_target(DEV_URL, "DEV") == "DEV"
    assert mi.assert_expected_target(NEON_URL, "NEON") == "NEON"


def test_a_mismatched_declaration_is_refused():
    """Aiming at DEV while declaring NEON, and the reverse, both abort.

    The failure the previous version could not catch: it printed the
    classification and connected anyway, so a run against the wrong database
    looked exactly like a successful run against the right one.
    """
    with pytest.raises(mi.TargetMismatch):
        mi.assert_expected_target(DEV_URL, "NEON")
    with pytest.raises(mi.TargetMismatch):
        mi.assert_expected_target(NEON_URL, "DEV")


def test_the_mismatch_message_carries_no_credentials():
    """A refusal that leaks the connection string trades one exposure for another."""
    with pytest.raises(mi.TargetMismatch) as exc:
        mi.assert_expected_target(NEON_URL, "DEV")
    message = str(exc.value)
    for secret in ("npg_leakcanary", "neondb_owner", "neon.tech", "ep-x-y-1", NEON_URL):
        assert secret not in message
    assert "NEON" in message and "DEV" in message


def test_every_expectable_label_is_one_the_classifier_can_return():
    """A label ``--expect`` accepts but the classifier never returns is unusable."""
    from scripts.assert_dev_db import DEV, LOCAL, NEON, NON_POSTGRES, UNKNOWN_EXTERNAL
    assert set(mi.EXPECTABLE) == {DEV, NEON, LOCAL, UNKNOWN_EXTERNAL, NON_POSTGRES}


def test_the_shared_dev_guard_is_not_weakened():
    """This tool must not have loosened ``assert_dev_database`` to reach production.

    That function is depended on by every ordinary maintenance path; widening it
    for one read-only tool would remove protection from all of them. The
    inventory builds an INVERSE guard on the same pure classifier instead.
    """
    from scripts.assert_dev_db import DatabaseTargetError, assert_dev_database
    assert assert_dev_database(DEV_URL) == DEV_URL
    with pytest.raises(DatabaseTargetError):
        assert_dev_database(NEON_URL)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Write-privilege refusal — against a fake connection, never a real one
# ══════════════════════════════════════════════════════════════════════════════

class FakeConn:
    """The narrowest stand-in that exercises the handshake's real branching.

    Answers three question shapes by inspecting the SQL text: does a table
    exist, does the role hold a table privilege, does it hold schema CREATE.
    A fake rather than a database because this suite must not be a route to one.
    """

    def __init__(self, *, tables, table_privs=(), schema_create=False,
                 tx="on", default_tx="on"):
        self.tables = set(tables)
        self.table_privs = set(table_privs)   # {(table, "INSERT"), ...}
        self.schema_create = schema_create
        self.tx, self.default_tx = tx, default_tx
        self.statements: list[str] = []

    def execute(self, clause, params=None):
        sql = str(clause)
        self.statements.append(sql)
        params = params or {}
        if "information_schema.tables" in sql:
            return _Result(scalar=1 if params.get("t") in self.tables else None)
        if "has_schema_privilege" in sql:
            return _Result(scalar=self.schema_create)
        if "has_table_privilege" in sql:
            table = params.get("t")
            values = {
                f"p_{p.lower()}": (table, p) in self.table_privs
                for p in mi.PROHIBITED_TABLE_PRIVILEGES
            }
            return _Result(one=_Row(**values))
        if "SHOW transaction_read_only" in sql:
            return _Result(scalar=self.tx)
        if "SHOW default_transaction_read_only" in sql:
            return _Result(scalar=self.default_tx)
        if "current_database()" in sql:
            return _Result(one=_Row(db="fake", ver_num="160004",
                                    app=mi.APPLICATION_NAME))
        raise AssertionError(f"FakeConn asked an unexpected question: {sql[:80]}")


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Result:
    def __init__(self, scalar=None, one=None, all_=()):
        self._scalar, self._one, self._all = scalar, one, all_

    def scalar(self):
        return self._scalar

    def one(self):
        return self._one

    def all(self):
        return list(self._all)


ALL_TABLES = mi.PRIVILEGE_CHECK_TABLES


def test_a_read_only_role_is_accepted():
    conn = FakeConn(tables=ALL_TABLES)
    report: dict = {}
    mi.assert_no_write_privileges(conn, report)
    assert report["privileges"]["read_only_role"] is True
    assert report["privileges"]["prohibited_held"] == []
    assert set(report["privileges"]["tables_checked"]) == set(ALL_TABLES)


@pytest.mark.parametrize("priv", mi.PROHIBITED_TABLE_PRIVILEGES)
def test_any_single_write_privilege_causes_a_hard_refusal(priv):
    """Every prohibited privilege refuses, not just INSERT.

    REFERENCES and TRIGGER are included because both attach behaviour or
    constraints to a table; a role holding either is not a read-only role
    however carefully this script behaves.
    """
    conn = FakeConn(tables=ALL_TABLES, table_privs={("character_images", priv)})
    with pytest.raises(mi.WritePrivilegeHeld) as exc:
        mi.assert_no_write_privileges(conn, {})
    assert priv in str(exc.value)


def test_schema_create_privilege_causes_a_refusal():
    """A role that can create objects in ``public`` is not read-only."""
    conn = FakeConn(tables=ALL_TABLES, schema_create=True)
    with pytest.raises(mi.WritePrivilegeHeld):
        mi.assert_no_write_privileges(conn, {})


def test_the_privilege_refusal_names_no_credentials():
    conn = FakeConn(tables=ALL_TABLES, table_privs={("users", "UPDATE")})
    with pytest.raises(mi.WritePrivilegeHeld) as exc:
        mi.assert_no_write_privileges(conn, {})
    message = str(exc.value)
    assert "withheld" in message.lower()
    for secret in ("npg_", "password", "@", "postgres://"):
        assert secret not in message


def test_an_absent_table_is_reported_not_assumed_safe():
    """"We did not find it" and "it holds nothing" are different answers.

    ``has_table_privilege`` raises on an unknown relation, so a missing table
    must be skipped deliberately — and recorded, because its absence is a schema
    fact the migration needs.
    """
    conn = FakeConn(tables={"characters", "users"})
    report: dict = {}
    mi.assert_no_write_privileges(conn, report)
    assert "character_images" in report["privileges"]["tables_absent"]
    assert set(report["privileges"]["tables_checked"]) == {"characters", "users"}


def test_a_server_that_does_not_confirm_read_only_aborts():
    conn = FakeConn(tables=ALL_TABLES, default_tx="off")
    with pytest.raises(SystemExit):
        mi.assert_read_only(conn, {})


def test_identity_reporting_does_not_include_the_role_name():
    """``current_user`` is a credential half; the privilege check already proves
    what matters about the role, so a transcript need not carry its name."""
    conn = FakeConn(tables=ALL_TABLES)
    report: dict = {}
    mi.report_identity(conn, report)
    assert report["database"] == "fake"
    assert report["server_version_major"] == 16
    assert "user" not in report
    assert "current_user" not in str(report)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Classification and object identity
# ══════════════════════════════════════════════════════════════════════════════

def test_the_minted_key_pattern_matches_the_applications_own():
    """Pinned against ``app.core.storage`` so the reproduced copy cannot drift.

    The script must not import ``app.*``; this test may, and that asymmetry is
    the whole point of pinning it here.
    """
    from app.core import storage
    assert mi.DURABLE_KEY_PREFIX == storage.DURABLE_KEY_PREFIX
    assert mi.TRANSIENT_KEY_PREFIX == storage.TRANSIENT_KEY_PREFIX
    assert mi.MINTED_KEY_RE.pattern == storage._MINTED_KEY_RE.pattern


@pytest.mark.parametrize("key,ok", [
    ("generated/" + "a" * 32 + ".png", True),
    ("transient/" + "0" * 32 + ".webp", True),
    ("generated/" + "a" * 32 + ".PNG", False),      # extension is lowercase
    ("generated/not-a-uuid.png", False),
    ("uploads/" + "a" * 32 + ".png", False),        # not a minted prefix
    ("static/generated/" + "a" * 32 + ".png", False),  # a path, not a key
])
def test_object_key_classification(key, ok):
    assert bool(mi.MINTED_KEY_RE.match(key)) is ok


def test_the_canon_column_list_covers_the_applications_canon_sources():
    """Pinned against ``canon_references._CANON_SOURCES``.

    That tuple is the reviewed list the delete-protection guard already uses. If
    a canon store is added there and not here, this inventory would silently
    stop accounting for a live reference store — so the two are asserted to stay
    in step rather than trusted to.
    """
    from app.services.canon_references import _CANON_SOURCES
    expected = {
        (model.__tablename__, column)
        for model, _id_col, columns in _CANON_SOURCES
        for column in columns
    }
    assert expected <= set(mi.CANON_JSON_COLUMNS), (
        "a canon JSON store the application protects is not inventoried: "
        f"{expected - set(mi.CANON_JSON_COLUMNS)}"
    )


def test_the_reviewed_pointer_columns_all_exist_in_the_models():
    """Table and column names verified against the ORM, never guessed.

    The audit brief named ``characters.body_markings_json``, which does not
    exist — the real column is ``characters.body_canon_json``. This test is why
    that was caught rather than shipped as an ABSENT row nobody questioned.
    """
    from app.core.database import Base
    tables = Base.metadata.tables
    missing = [
        f"{t}.{c}" for t, c in mi.POINTER_COLUMNS
        if t not in tables or c not in tables[t].columns
    ]
    assert not missing, f"reviewed pointer columns absent from the models: {missing}"


def test_the_reviewed_canon_columns_all_exist_in_the_models():
    from app.core.database import Base
    tables = Base.metadata.tables
    missing = [
        f"{t}.{c}" for t, c in mi.CANON_JSON_COLUMNS
        if t not in tables or c not in tables[t].columns
    ]
    assert not missing, f"reviewed canon columns absent from the models: {missing}"


def test_the_classification_case_separates_our_r2_from_a_foreign_host():
    """With a host supplied the SQL can tell ours from theirs; without one it
    must not pretend to — the ``our_r2`` branch becomes unreachable rather than
    guessing from the shape of a URL."""
    with_host = mi._classification_case('"t"."c"', "pub-x.r2.dev")
    without = mi._classification_case('"t"."c"', None)
    assert ":r2_host" in with_host and "our_r2" in with_host
    assert "WHEN false THEN 'our_r2'" in without
    assert ":r2_host" not in without
    for case in (with_host, without):
        assert "'local_relative'" in case and "'other_http'" in case
        assert "'data_uri'" in case


def test_the_backed_exists_expression_uses_all_three_path_spellings():
    """It must ask the same question ``candidate_file_paths`` answers.

    ``file_path_to_url`` is not injective, so a row may be stored under the bare
    path, the slash-prefixed path or the ``static/``-stripped path. A missing
    spelling here would make the rowless count disagree with what the
    application's own resolver does.
    """
    expr = mi._backed_exists('"characters"."avatar_url"')
    assert "ltrim" in expr
    assert "'/' || ltrim" in expr
    assert "regexp_replace" in expr and "'^static/'" in expr
    assert "character_images" in expr and "user_images" in expr


# ══════════════════════════════════════════════════════════════════════════════
# 6. Schema-coverage detection
# ══════════════════════════════════════════════════════════════════════════════

class CoverageConn:
    """A connection that answers only the coverage query, with a given column set."""

    def __init__(self, columns):
        self.columns = columns

    def execute(self, clause, params=None):
        assert "information_schema.columns" in str(clause)
        return _Result(all_=self.columns)


def test_coverage_detection_catches_a_plausible_unknown_image_pointer():
    """The fail-loud requirement: a new media column cannot be added silently."""
    conn = CoverageConn([
        ("characters", "hero_image_url", "character varying"),
        ("characters", "avatar_url", "character varying"),   # reviewed
        ("posts", "content", "text"),                        # ordinary prose
    ])
    found = mi.unreviewed_media_columns(conn)
    assert ("characters", "hero_image_url", "character varying") in found
    assert not any(c == "avatar_url" for _t, c, _d in found)
    assert not any(c == "content" for _t, c, _d in found)


@pytest.mark.parametrize("column", [
    "thumbnail_url", "media_key", "asset_path", "banner_image",
    "poster_url", "storage_key", "profile_picture",
])
def test_coverage_detection_recognises_media_name_shapes(column):
    found = mi.unreviewed_media_columns(CoverageConn([("t", column, "text")]))
    assert found == [("t", column, "text")]


@pytest.mark.parametrize("column", [
    "content", "bio", "short_bio", "long_bio", "prompt_summary", "tags",
    "display_name", "reason", "slug", "seed", "email",
])
def test_coverage_detection_does_not_flood_on_ordinary_text(column):
    """A check that reports two hundred false positives is a check nobody reads."""
    assert mi.unreviewed_media_columns(CoverageConn([("t", column, "text")])) == []


def test_coverage_aborts_unless_acknowledged():
    """Reported AND refused: an unaccounted media column must not produce a
    confident total. Acknowledging is a deliberate act recorded in the argv."""
    conn = CoverageConn([("characters", "hero_image_url", "text")])
    with pytest.raises(SystemExit):
        mi.coverage(conn, {}, acknowledged=False)

    out: dict = {}
    mi.coverage(conn, out, acknowledged=True)      # does not raise
    assert out["coverage"]["unreviewed_media_like_columns"] == [
        {"table": "characters", "column": "hero_image_url", "data_type": "text"}
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Output safety
# ══════════════════════════════════════════════════════════════════════════════

def test_hashed_object_labels_are_stable_and_salted():
    """Stable across runs with one salt, so two inventories diff; different
    across salts, so a published digest is not a bucket key."""
    key = "generated/" + "a" * 32 + ".png"
    assert mi.hash_object_key(key, "s1") == mi.hash_object_key(key, "s1")
    assert mi.hash_object_key(key, "s1") != mi.hash_object_key(key, "s2")
    assert key not in mi.hash_object_key(key, "s1")


def test_no_default_salt_exists():
    """A constant salt in the file would make every published digest reversible
    by anyone holding the file."""
    import inspect
    source = inspect.getsource(mi.hash_object_key)
    assert "salt" in inspect.signature(mi.hash_object_key).parameters
    assert "= \"" not in source.split("salt")[0].split("def ")[1]


def test_the_json_report_shape_carries_no_forbidden_content():
    """The report is aggregates. Serialising a representative one must not
    produce a credential, a url or any user prose."""
    report = {
        "classification": "NEON",
        "expected_classification": "NEON",
        "database": "neondb",
        "server_version_major": 16,
        "privileges": {"read_only_role": True, "prohibited_held": []},
        "pointers": {"characters.avatar_url": {"set": 12, "rowless": 3}},
        "canon_json": {"characters.identity_anchor_json": {"references": 40}},
    }
    payload = json.dumps(report).lower()
    for marker in mi.FORBIDDEN_IN_JSON:
        assert marker not in payload


def test_the_json_guard_rejects_a_report_that_would_leak_a_url():
    """The last line of defence on output: a payload containing a connection
    string or an embedded credential is refused rather than written."""
    assert any(m in "postgresql://u:p@host/db" for m in mi.FORBIDDEN_IN_JSON)
    assert any(m in "s3://bucket/x?password=hunter2" for m in mi.FORBIDDEN_IN_JSON)


# ══════════════════════════════════════════════════════════════════════════════
# 8. Structural guarantees about the script itself
# ══════════════════════════════════════════════════════════════════════════════

def test_the_script_imports_nothing_from_the_application():
    """``app.core.database`` builds an engine at import time and the FastAPI
    lifespan performs DDL and seeding writes. The one tool aimed at production
    must not be able to trigger any of that, so it imports no ``app.*`` module
    and no storage/provider client."""
    source = _SCRIPT.read_text()
    import ast
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    offenders = [m for m in imported if m == "app" or m.startswith("app.")]
    assert not offenders, f"script imports application modules: {offenders}"
    for banned in ("boto3", "botocore", "requests", "httpx", "urllib.request",
                   "openai", "replicate"):
        assert banned not in imported, f"script imports {banned}"


def test_the_script_has_no_arbitrary_sql_entry_point():
    """No ``--sql``, no query file, no REPL: what production can be asked is a
    short list somebody has read.

    Checked against the parser's ACTUAL options and the AST's actual calls, not
    by grepping the source — the docstring legitimately contains the words
    "``--sql`` argument" while explaining that there isn't one, and a substring
    test failed on the very sentence promising the property.
    """
    import ast

    tree = ast.parse(_SCRIPT.read_text())
    declared: set[str] = set()
    bare_calls: set[str] = set()
    attr_calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            bare_calls.add(func.id)
        elif isinstance(func, ast.Attribute):
            attr_calls.add(func.attr)
        name = getattr(func, "attr", None) or getattr(func, "id", None)
        if name == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    declared.add(arg.value)

    for banned in ("--sql", "--query", "--statement", "--file", "--exec"):
        assert banned not in declared, f"parser exposes {banned}"
    # Bare-name builtins only: the dynamic-execution ones. ``compile`` is
    # deliberately not here — every call in the script is ``re.compile``, which
    # is how its guards are written, and banning the attribute name would fail
    # on the guards themselves.
    for banned in ("eval", "exec", "input", "__import__"):
        assert banned not in bare_calls, f"script calls {banned}()"
    # Attribute calls that would shell out or fetch. HTTP client method names
    # (``.get``/``.post``) are not listed: ``os.environ.get`` is legitimate and
    # unavoidable, and the import test above already refuses every HTTP library
    # that could give those names a network meaning.
    for banned in ("system", "popen", "check_output", "urlopen", "Popen"):
        assert banned not in attr_calls, f"script calls .{banned}()"

    # And the options it DOES declare are exactly the reviewed set.
    assert declared == {
        "--url-env", "--expect", "--verify-only", "--r2-host",
        "--json", "--hash-salt-env", "--acknowledge-unreviewed-columns",
    }, sorted(declared)


def test_expect_is_a_required_argument():
    """A URL existing is not a statement of intent."""
    with pytest.raises(SystemExit):
        mi.main(["--url-env", "SOME_VAR"])       # no --expect


def test_a_missing_url_variable_aborts_before_connecting(monkeypatch):
    monkeypatch.delenv("NO_SUCH_URL_VAR", raising=False)
    assert mi.main(["--url-env", "NO_SUCH_URL_VAR", "--expect", "DEV"]) == 2


def test_a_mismatched_target_aborts_before_connecting(monkeypatch):
    """Exit 3 and no socket: the refusal precedes the expensive work.

    ``build_engine`` is replaced with something that raises, so if the guard
    ever stopped preceding the connection this test fails loudly instead of
    quietly opening one.
    """
    monkeypatch.setenv("FAKE_URL_VAR", NEON_URL)
    monkeypatch.setattr(mi, "build_engine", lambda url: (_ for _ in ()).throw(
        AssertionError("connected despite a target mismatch")))
    assert mi.main(["--url-env", "FAKE_URL_VAR", "--expect", "DEV"]) == 3

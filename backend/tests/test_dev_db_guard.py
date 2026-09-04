"""The DEV database guard — ``scripts/assert_dev_db.py`` and ``scripts/devdb``.

Background, because it is what these tests are really pinning. On 4 September
2026 the workspace was found to carry ambient libpq variables (``PGHOST`` …
``PGPASSWORD``) pointing at production-era external infrastructure while the
application's ``DATABASE_URL`` pointed at the Replit-managed DEV database. A
bare ``psql`` therefore reached the wrong database with owner privileges. The
variables were removed; this guard is the part that does not depend on them
staying removed.

So the central case is not "a good URL is accepted" — it is **contamination**:
ambient ``PG*`` values are present and wrong, and the guard reaches the right
answer anyway, both in what it accepts and in what the client process inherits.
Those tests are section D and they are the reason this file exists.

Nothing here opens a database connection, a socket, or a subprocess. The
execution boundary is replaced, so the assertions are about what WOULD have been
run — which is exactly the thing that must never be wrong.
"""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(module_name: str, filename: str):
    """Load a script by path — ``devdb`` has no ``.py`` extension and
    ``scripts/`` is not a package, so neither is importable by name.

    The loader is named explicitly because ``spec_from_file_location`` infers it
    from the file suffix and returns ``None`` for an extensionless executable.
    """
    path = _SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(
        module_name, path, loader=importlib.machinery.SourceFileLoader(module_name, str(path))
    )
    assert spec is not None and spec.loader is not None, f"cannot load {filename}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load("assert_dev_db_undertest", "assert_dev_db.py")
devdb = _load("devdb_undertest", "devdb")


# Representative URLs. Passwords and users are distinctive strings so the
# leak tests can assert on them by value.
DEV_URL = "postgresql://devuser:devsecret@helium/heliumdb?sslmode=require"
NEON_URL = "postgresql://neondb_owner:npg_leakcanary@ep-x-y-123.eu-central-1.aws.neon.tech/neondb"
UNKNOWN_URL = "postgresql://someuser:somesecret@db.example.com:5432/appdb"
LOCAL_URL = "postgresql://localuser:localsecret@localhost:5432/appdb"
SQLITE_URL = "sqlite:///./ficshon.db"

#: Fake ambient contamination. Never a real credential — the point is only that
#: the guard must not read it.
FAKE_AMBIENT = {
    "PGHOST": "ep-fake-999.eu-central-1.aws.neon.tech",
    "PGPORT": "5432",
    "PGUSER": "neondb_owner",
    "PGPASSWORD": "npg_fake_ambient_value",
    "PGDATABASE": "neondb",
}


def _set_ambient(monkeypatch, **overrides):
    """Install fake ambient PG* variables for the duration of a test."""
    values = {**FAKE_AMBIENT, **overrides}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


# ── A. Classification ────────────────────────────────────────────────────────

def test_dev_url_is_classified_dev():
    assert guard.classify_database_url(DEV_URL) == guard.DEV


def test_dev_url_is_accepted_and_returned_unchanged():
    """The caller's own URL comes back, so the guard can sit inside the
    connection expression rather than beside it."""
    assert guard.assert_dev_database(DEV_URL) == DEV_URL


def test_neon_host_is_rejected():
    assert guard.classify_database_url(NEON_URL) == guard.NEON
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database(NEON_URL)


def test_unknown_external_host_is_rejected():
    """The case that matters most: not a known-bad host, just an unrecognised
    one. An allowlist refuses it; a denylist would have let it through."""
    assert guard.classify_database_url(UNKNOWN_URL) == guard.UNKNOWN_EXTERNAL
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database(UNKNOWN_URL)


def test_localhost_is_not_dev():
    """A developer's own Postgres is not this project's DEV database."""
    assert guard.classify_database_url(LOCAL_URL) == guard.LOCAL
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database(LOCAL_URL)


def test_non_postgres_url_is_rejected():
    assert guard.classify_database_url(SQLITE_URL) == guard.NON_POSTGRES
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database(SQLITE_URL)


@pytest.mark.parametrize("scheme", ["postgresql", "postgres", "postgresql+psycopg2"])
def test_sqlalchemy_driver_schemes_are_understood(scheme):
    """``postgresql+psycopg2://`` is the form SQLAlchemy configs carry."""
    assert guard.classify_database_url(f"{scheme}://u:p@helium/heliumdb") == guard.DEV


@pytest.mark.parametrize("missing", [None, "", "   ", "\n"])
def test_missing_url_is_rejected(missing):
    with pytest.raises(guard.DatabaseTargetError):
        guard.classify_database_url(missing)


@pytest.mark.parametrize("malformed", [
    "not a url",                     # no scheme
    "helium/heliumdb",               # bare host/path, no scheme
    "postgresql://",                 # scheme only, no host
    "postgresql:///heliumdb",        # path but no host
    "postgresql://user:pw@[::1/db",  # unterminated IPv6 literal
])
def test_malformed_url_is_rejected(malformed):
    with pytest.raises(guard.DatabaseTargetError):
        guard.classify_database_url(malformed)


def test_dev_hostname_match_is_exact_not_substring():
    """A host merely CONTAINING the dev name is not the dev database."""
    for host in ("helium.evil.example.com", "nothelium", "helium-staging"):
        assert guard.classify_database_url(
            f"postgresql://u:p@{host}/db"
        ) != guard.DEV


# ── B. Credentials never appear in output ────────────────────────────────────

@pytest.mark.parametrize("url,secret", [
    (NEON_URL, "npg_leakcanary"),
    (UNKNOWN_URL, "somesecret"),
    (LOCAL_URL, "localsecret"),
    (SQLITE_URL, "ficshon.db"),
])
def test_rejection_messages_carry_no_credentials(url, secret):
    """A guard that leaks the connection string into a traceback or CI log has
    swapped one exposure for another."""
    with pytest.raises(guard.DatabaseTargetError) as excinfo:
        guard.assert_dev_database(url)
    message = str(excinfo.value)
    assert secret not in message
    assert url not in message
    assert "neon.tech" not in message
    assert "@" not in message


def test_malformed_rejection_message_carries_no_url():
    bad = "postgresql://user:supersecret@[::1/db"
    with pytest.raises(guard.DatabaseTargetError) as excinfo:
        guard.classify_database_url(bad)
    assert "supersecret" not in str(excinfo.value)
    assert bad not in str(excinfo.value)


def test_rejection_message_names_the_classification_and_the_purpose():
    """Refusals have to be actionable without being revealing."""
    with pytest.raises(guard.DatabaseTargetError) as excinfo:
        guard.assert_dev_database(NEON_URL, purpose="to backfill image URLs")
    message = str(excinfo.value)
    assert "NEON" in message
    assert "to backfill image URLs" in message


# ── C. Environment sanitisation ──────────────────────────────────────────────

def test_sanitized_env_removes_every_ambient_libpq_var(monkeypatch):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", DEV_URL)
    monkeypatch.setenv("PATH", "/usr/bin")

    import os as _os
    env = guard.sanitized_libpq_env(_os.environ)

    for name in guard.AMBIENT_LIBPQ_VARS:
        assert name not in env, f"{name} survived sanitisation"
    # Unrelated variables are untouched — this strips, it does not scrub.
    assert env["DATABASE_URL"] == DEV_URL
    assert env["PATH"] == "/usr/bin"


def test_sanitized_env_is_a_copy_and_tolerates_absent_vars():
    source = {"PATH": "/usr/bin", "PGHOST": "x"}
    env = guard.sanitized_libpq_env(source)
    assert "PGHOST" not in env
    assert source["PGHOST"] == "x", "the caller's mapping was mutated"
    # Absent variables are a no-op, not an error.
    assert guard.sanitized_libpq_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


def test_the_stripped_set_is_exactly_the_five_libpq_vars():
    assert set(guard.AMBIENT_LIBPQ_VARS) == {
        "PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE",
    }


# ── D. Ambient PG* contamination cannot influence the verdict ────────────────
#
# The section this file exists for. In every test below the ambient variables
# are present and point somewhere else entirely.

def test_ambient_pg_vars_do_not_make_a_neon_url_acceptable(monkeypatch):
    """Contamination pointing at a dev-shaped host does not launder a Neon URL."""
    _set_ambient(monkeypatch, PGHOST="helium", PGDATABASE="heliumdb")
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database(NEON_URL)


def test_ambient_pg_vars_do_not_make_a_dev_url_unacceptable(monkeypatch):
    """And contamination pointing at Neon does not poison a genuine DEV URL."""
    _set_ambient(monkeypatch)
    assert guard.assert_dev_database(DEV_URL) == DEV_URL


def test_classification_ignores_the_environment_entirely(monkeypatch):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", NEON_URL)
    # An explicitly supplied URL wins over anything ambient.
    assert guard.classify_database_url(DEV_URL) == guard.DEV


def test_default_url_comes_from_database_url_never_from_pg_vars(monkeypatch):
    """With DATABASE_URL absent, the guard refuses rather than assembling a
    target out of the ambient variables — the exact fallback that made a bare
    ``psql`` dangerous."""
    _set_ambient(monkeypatch, PGHOST="helium", PGDATABASE="heliumdb")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(guard.DatabaseTargetError):
        guard.assert_dev_database()


def test_default_url_is_read_from_database_url(monkeypatch):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", DEV_URL)
    assert guard.assert_dev_database() == DEV_URL


# ── E. The wrapper refuses BEFORE spawning a client ──────────────────────────

@pytest.fixture()
def spawned(monkeypatch):
    """Replace the execution boundary and record what would have been run.

    No PostgreSQL binary is invoked and no connection is attempted anywhere in
    this file; every wrapper assertion is about the command and environment the
    wrapper WOULD have handed to the client.
    """
    calls: list[tuple[list[str], dict]] = []

    def _fake_execute(command, env):
        calls.append((command, env))
        return 0

    monkeypatch.setattr(devdb, "_execute", _fake_execute)
    return calls


@pytest.mark.parametrize("url", [NEON_URL, UNKNOWN_URL, LOCAL_URL, SQLITE_URL])
def test_wrapper_refuses_unsafe_targets_without_spawning(monkeypatch, spawned, url):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)

    assert devdb.main([]) == 2
    assert spawned == [], "a client was launched for a non-DEV target"


def test_wrapper_refuses_when_database_url_is_missing(monkeypatch, spawned):
    """Ambient PG* present, DATABASE_URL absent — the original foot-gun."""
    _set_ambient(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert devdb.main([]) == 2
    assert spawned == []


def test_wrapper_refusal_prints_no_credentials(monkeypatch, spawned, capsys):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", NEON_URL)

    devdb.main([])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "npg_leakcanary" not in output
    assert NEON_URL not in output
    assert "neon.tech" not in output
    assert "NEON" in output, "the refusal should still say why"


# ── F. The wrapper reaches the boundary for a valid DEV target ───────────────

def test_wrapper_launches_psql_for_a_dev_target(monkeypatch, spawned):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    assert devdb.main([]) == 0
    assert len(spawned) == 1
    command, _env = spawned[0]
    assert command[0] == "psql"
    assert command[1] == DEV_URL, "the client must receive the app's own URL verbatim"


def test_child_environment_is_stripped_even_though_ambient_vars_exist(
    monkeypatch, spawned
):
    """The contamination case at the execution boundary.

    A validated URL with an unsanitised environment is only accidentally safe:
    libpq fills in from PG* whatever the connection string omits.
    """
    ambient = _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    devdb.main([])
    _command, env = spawned[0]

    for name in guard.AMBIENT_LIBPQ_VARS:
        assert name not in env, f"{name} reached the client process"
    # And none of the contaminating values survived under any name.
    for value in ambient.values():
        assert value not in env.values()
    assert env["DATABASE_URL"] == DEV_URL


def test_extra_arguments_are_passed_through_to_psql(monkeypatch, spawned):
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    devdb.main(["-c", "SELECT 1"])
    command, _env = spawned[0]
    assert command == ["psql", DEV_URL, "-c", "SELECT 1"]


def test_pg_dump_is_selectable_as_the_client(monkeypatch, spawned):
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    devdb.main(["pg_dump", "-t", "character_images"])
    command, _env = spawned[0]
    assert command == ["pg_dump", DEV_URL, "-t", "character_images"]


def test_an_unrecognised_first_argument_is_a_psql_argument_not_a_command(
    monkeypatch, spawned
):
    """The tool name is an allowlist, so the wrapper cannot be talked into
    executing an arbitrary binary."""
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    devdb.main(["rm", "-rf", "/"])
    command, _env = spawned[0]
    assert command[0] == "psql"
    assert command[2:] == ["rm", "-rf", "/"]


def test_check_mode_validates_without_launching(monkeypatch, spawned, capsys):
    _set_ambient(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", DEV_URL)

    assert devdb.main(["--check"]) == 0
    assert spawned == [], "--check must not launch a client"
    assert "DEV" in capsys.readouterr().out


def test_check_mode_still_refuses_a_non_dev_target(monkeypatch, spawned):
    monkeypatch.setenv("DATABASE_URL", NEON_URL)
    assert devdb.main(["--check"]) == 2
    assert spawned == []


def test_argument_parsing_is_pure(monkeypatch):
    """parse_args touches nothing — worth pinning separately from main()."""
    assert devdb.parse_args([]) == ("psql", [], False)
    assert devdb.parse_args(["--check"]) == ("psql", [], True)
    assert devdb.parse_args(["pg_dump"]) == ("pg_dump", [], False)
    assert devdb.parse_args(["--check", "pg_dump", "-t", "x"]) == (
        "pg_dump", ["-t", "x"], True,
    )
    assert devdb.parse_args(["-c", "SELECT 1"]) == ("psql", ["-c", "SELECT 1"], False)

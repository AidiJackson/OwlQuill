"""Neither startup bootstrap nor Alembic may mutate a non-DEV database by accident.

WHAT THESE TESTS PIN. Two paths could perform schema and seeding writes against
whatever ``DATABASE_URL`` was set, with no confirmation and no record of intent:

* the FastAPI lifespan ran seven bootstrap mutations — including ``ALTER TABLE
  users ADD COLUMN`` — so merely BOOTING the app against production performed
  DDL on it;
* ``alembic/env.py`` passed ``settings.DATABASE_URL`` straight through, so
  ``alembic upgrade head`` migrated whichever database the environment named.

Both now require an acknowledgement naming the operation AND the target. The
tests below assert the default is refusal, that DEV is untouched, that the two
acknowledgements cannot substitute for each other in EITHER direction, and that
no refusal carries a credential.

NO EXTERNAL SOCKET IS OPENED. Every test here is a pure function over strings
and a mapping, or a lifespan run with the mutation helpers replaced by
recorders. Nothing invokes real Alembic and nothing contacts a database — a test
suite for a production guard must not itself be a route to production.
"""
from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

from app.core import db_target
from app.core.db_target import (
    MIGRATION_ACK_VAR,
    STARTUP_BOOTSTRAP_ACK_VAR,
    MutationRefused,
    classify_target,
    migration_ack_phrase,
    require_migration_authorisation,
    startup_bootstrap_ack_phrase,
    startup_bootstrap_authorised,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_shared_guard():
    """Load ``scripts/assert_dev_db.py`` by path, as the repo's other tests do.

    ``scripts/`` is not a package and is not on ``sys.path`` when tests run from
    ``backend/``, so ``import scripts.assert_dev_db`` fails — the same
    import-path fact that made ``app.core.db_target`` load it by path. Doing it
    the same way here keeps this file from depending on some other module having
    already mutated ``sys.path``.
    """
    name = "shared_dev_guard_under_test"
    path = _REPO_ROOT / "scripts" / "assert_dev_db.py"
    spec = importlib.util.spec_from_file_location(
        name, path, loader=importlib.machinery.SourceFileLoader(name, str(path))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shared_guard = _load_shared_guard()


DEV_URL = "postgresql://u:p@helium/postgres"
LOCAL_SQLITE_URL = "sqlite:///./ficshon.db"
NEON_URL = "postgresql://neondb_owner:npg_leakcanary@ep-x-y-1.eu-central-1.aws.neon.tech/neondb"
UNKNOWN_URL = "postgresql://root:hunter2@db.somewhere-else.example.com/app"
SECRETS = ("npg_leakcanary", "neondb_owner", "hunter2", "neon.tech",
           "ep-x-y-1", "somewhere-else.example.com", NEON_URL, UNKNOWN_URL)


def _assert_no_secrets(message: str) -> None:
    for secret in SECRETS:
        assert secret not in message, f"refusal leaked {secret!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Shared classification — one definition, unchanged
# ══════════════════════════════════════════════════════════════════════════════

def test_classification_comes_from_the_shared_guard():
    """No second notion of DEV. This module adds no host logic of its own."""
    assert classify_target(DEV_URL) == shared_guard.DEV
    assert classify_target(NEON_URL) == shared_guard.NEON
    assert classify_target(UNKNOWN_URL) == shared_guard.UNKNOWN_EXTERNAL
    assert db_target.DEV == shared_guard.DEV


def test_an_unclassifiable_target_fails_closed():
    """A guard that cannot answer "which database?" must not answer "go ahead".

    ``sqlite:///./x.db`` is deliberately NOT in this list any more: it is now
    classified :data:`LOCAL_SQLITE` and allowed, which the next section covers.
    """
    for bad in (None, "", "not-a-url", "://"):
        assert classify_target(bad) == db_target.UNAVAILABLE, bad
        assert startup_bootstrap_authorised(bad, environ={})[0] is False, bad
        with pytest.raises(MutationRefused):
            require_migration_authorisation(bad, environ={})


# ══════════════════════════════════════════════════════════════════════════════
# LOCAL SQLITE IS NOT A PRODUCTION TARGET
# ══════════════════════════════════════════════════════════════════════════════

def test_the_shared_classifiers_non_postgres_label_is_too_broad_to_trust():
    """WHY a narrowing exists at all, asserted rather than asserted-in-a-comment.

    ``classify_database_url`` returns ``NON_POSTGRES`` for ANY non-postgres
    scheme, so the label covers remote MySQL, remote MSSQL and networked SQLite
    dialects. Treating the whole label as safe would have opened a hole wider
    than the one this module closes — this test is what stops somebody
    "simplifying" the narrowing back into a label check.
    """
    for remote in ("mysql://root:pw@db.example.com/app",
                   "mssql+pyodbc://u:p@sql.example.com/db",
                   "sqlite+libsql://turso.example.com/db",
                   "sqlite://remote-host/db"):
        assert shared_guard.classify_database_url(remote) == shared_guard.NON_POSTGRES
        assert classify_target(remote) == db_target.NON_POSTGRES, remote


@pytest.mark.parametrize("url", [
    "sqlite:///./ficshon.db",          # the app's built-in default
    "sqlite:////tmp/ficshon-tests/app.db",   # absolute path, as the test suite uses
    "sqlite:///:memory:",
    "sqlite://",
    "sqlite+pysqlite:///./x.db",
    "sqlite+aiosqlite:///./x.db",
])
def test_a_local_sqlite_target_is_classified_local_sqlite(url):
    assert classify_target(url) == db_target.LOCAL_SQLITE


@pytest.mark.parametrize("url", [
    "sqlite+libsql://turso.example.com/db",
    "sqlite://remote-host/db",
    "sqlite://user:pw@10.0.0.5/db",
])
def test_a_sqlite_scheme_naming_a_HOST_is_not_local(url):
    """The load-bearing half of the determination.

    A scheme check alone would have accepted these: they carry the sqlite scheme
    and name a remote server. Requiring an empty authority is what makes the
    rule mean "local".
    """
    assert not db_target._is_local_sqlite(url)
    assert classify_target(url) != db_target.LOCAL_SQLITE
    assert startup_bootstrap_authorised(url, environ={})[0] is False


def test_local_sqlite_startup_bootstrap_is_allowed_without_acknowledgement():
    """(1) Requiring a production acknowledgement to bootstrap a local file
    would make the guard a nuisance where it protects nothing — which is how
    guards come to be disabled wholesale."""
    allowed, reason, label = startup_bootstrap_authorised(
        LOCAL_SQLITE_URL, environ={})
    assert allowed is True
    assert label == db_target.LOCAL_SQLITE
    assert "LOCAL_SQLITE" in reason


def test_local_sqlite_alembic_is_allowed_without_acknowledgement():
    """(2) The same for migrations: a local file is not a production schema."""
    assert require_migration_authorisation(
        LOCAL_SQLITE_URL, environ={}) == db_target.LOCAL_SQLITE


def test_the_lifespan_runs_bootstrap_on_local_sqlite(recorded_bootstrap, monkeypatch):
    """End to end on the app's own default: all seven helpers still run."""
    main, calls = recorded_bootstrap
    monkeypatch.setattr(main.settings, "DATABASE_URL", LOCAL_SQLITE_URL)
    monkeypatch.delenv(STARTUP_BOOTSTRAP_ACK_VAR, raising=False)
    _run_lifespan(main)
    assert len(calls) == 7


def test_only_dev_and_local_sqlite_skip_the_acknowledgement():
    """The allowlist is exactly two labels, and it is an allowlist.

    Pinned as a set so widening it is a visible, reviewable edit rather than a
    consequence of adding a label somewhere else.
    """
    assert db_target.NO_ACKNOWLEDGEMENT_REQUIRED == {
        db_target.DEV, db_target.LOCAL_SQLITE
    }
    for label in (shared_guard.NEON, shared_guard.UNKNOWN_EXTERNAL,
                  shared_guard.LOCAL, db_target.NON_POSTGRES,
                  db_target.UNAVAILABLE):
        assert label not in db_target.NO_ACKNOWLEDGEMENT_REQUIRED, label


def test_a_missing_classifier_module_fails_closed(monkeypatch, tmp_path):
    """``scripts/`` absent from a deployment must degrade to "no writes".

    Loading by path is the only option available (``scripts/`` is not a package
    and is not on ``sys.path`` when the app runs from ``backend/``), so the
    failure mode has to be stated: unable to classify means refused, never
    unguarded.
    """
    monkeypatch.setattr(db_target, "_GUARD_PATH", tmp_path / "absent.py")
    assert classify_target(DEV_URL) == db_target.UNAVAILABLE
    allowed, reason, label = startup_bootstrap_authorised(DEV_URL, environ={})
    assert allowed is False
    assert label == db_target.UNAVAILABLE
    assert "could not be classified" in reason


def test_the_existing_dev_guard_is_unchanged():
    """``assert_dev_database`` keeps its exact "only DEV, ever" semantics.

    Every ordinary maintenance path depends on it. This increment adds guards
    beside it and must not have loosened it to reach production.
    """
    assert shared_guard.assert_dev_database(DEV_URL) == DEV_URL
    for url in (NEON_URL, UNKNOWN_URL):
        with pytest.raises(shared_guard.DatabaseTargetError):
            shared_guard.assert_dev_database(url)


def test_media_inventory_expected_target_semantics_are_unchanged():
    """The inventory tool's own guard is untouched by this increment."""
    path = _REPO_ROOT / "scripts" / "media_inventory.py"
    spec = importlib.util.spec_from_file_location("mi_unchanged", path)
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert mi.assert_expected_target(NEON_URL, "NEON") == "NEON"
    with pytest.raises(mi.TargetMismatch):
        mi.assert_expected_target(NEON_URL, "DEV")


# ══════════════════════════════════════════════════════════════════════════════
# Startup bootstrap guard
# ══════════════════════════════════════════════════════════════════════════════

def test_dev_is_authorised_with_no_acknowledgement():
    """DEV workflows are unchanged. No new variable to set, ever."""
    allowed, reason, label = startup_bootstrap_authorised(DEV_URL, environ={})
    assert allowed is True
    assert label == "DEV"
    assert "DEV" in reason
    assert require_migration_authorisation(DEV_URL, environ={}) == "DEV"


@pytest.mark.parametrize("url", [NEON_URL, UNKNOWN_URL])
def test_non_dev_is_refused_by_default(url):
    """Possessing a production connection string is not a statement of intent."""
    allowed, reason, _label = startup_bootstrap_authorised(url, environ={})
    assert allowed is False
    assert STARTUP_BOOTSTRAP_ACK_VAR in reason
    _assert_no_secrets(reason)


@pytest.mark.parametrize("url,label", [(NEON_URL, "NEON"),
                                       (UNKNOWN_URL, "UNKNOWN_EXTERNAL")])
def test_the_correct_acknowledgement_authorises_startup_bootstrap(url, label):
    env = {STARTUP_BOOTSTRAP_ACK_VAR: startup_bootstrap_ack_phrase(label)}
    allowed, reason, got = startup_bootstrap_authorised(url, environ=env)
    assert allowed is True
    assert got == label
    assert label in reason


@pytest.mark.parametrize("wrong", [
    "true", "1", "yes", "ALLOW", "bootstrap-startup-writes",
    "bootstrap-startup-writes-on-", "bootstrap-startup-writes-on-DEV",
    "Bootstrap-Startup-Writes-On-NEON", " bootstrap-startup-writes-on-NEON",
    "bootstrap-startup-writes-on-NEON ",
])
def test_a_wrong_acknowledgement_is_refused(wrong):
    """Exact match only.

    A casual ``ALLOW_PROD=true`` is the design this deliberately is not: a
    boolean survives in a shell profile or a deployment secret and then
    authorises every future run. An awkward exact phrase does not get set by
    accident and reads wrong if it lingers.
    """
    allowed, _reason, _ = startup_bootstrap_authorised(
        NEON_URL, environ={STARTUP_BOOTSTRAP_ACK_VAR: wrong})
    assert allowed is False


def test_an_acknowledgement_for_one_target_does_not_authorise_another():
    """The classification is embedded in the phrase.

    A value left over from a NEON bootstrap must not authorise writes to an
    unrecognised host that appeared afterwards — which is exactly what an
    ambient variable pointing somewhere new looks like.
    """
    env = {STARTUP_BOOTSTRAP_ACK_VAR: startup_bootstrap_ack_phrase("NEON")}
    assert startup_bootstrap_authorised(UNKNOWN_URL, environ=env)[0] is False
    assert startup_bootstrap_authorised(NEON_URL, environ=env)[0] is True


def test_the_acknowledgement_is_read_from_the_environment_not_from_settings(monkeypatch):
    """``Settings`` consults ``.env``; this must not.

    A value placed in the dotenv file would be picked up silently and would then
    authorise every future run on that checkout — the persistence failure this
    design exists to avoid. Asserted by setting the variable ONLY on the real
    environment and confirming the default-environ path reads it, and by
    confirming ``Settings`` has no such field to read.
    """
    from app.core.config import Settings
    assert STARTUP_BOOTSTRAP_ACK_VAR not in Settings.model_fields
    assert MIGRATION_ACK_VAR not in Settings.model_fields

    monkeypatch.setenv(STARTUP_BOOTSTRAP_ACK_VAR,
                       startup_bootstrap_ack_phrase("NEON"))
    assert startup_bootstrap_authorised(NEON_URL)[0] is True
    # An explicit empty mapping is not the real environment, so it refuses.
    assert startup_bootstrap_authorised(NEON_URL, environ={})[0] is False


# ══════════════════════════════════════════════════════════════════════════════
# The lifespan itself: classification precedes every mutation helper
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def recorded_bootstrap(monkeypatch):
    """Replace every startup mutation with a recorder.

    Fakes rather than the real helpers, so this test can assert the ORDER of
    events — was the target classified before anything was called? — without a
    database being touched at all. If a new bootstrap mutation is added to the
    lifespan outside the guarded block, ``test_no_bootstrap_helper_runs_...``
    will not see it and the static sweep is what catches that; this fixture
    pins the seven that exist.
    """
    import app.main as main

    calls: list[str] = []
    for name in ("ensure_identity_schema", "ensure_admin_user",
                 "ensure_seeder_flags", "ensure_commons_realm",
                 "ensure_starter_realms_and_posts", "seed_invite_codes"):
        monkeypatch.setattr(main, name,
                            lambda _n=name: calls.append(_n), raising=True)
    monkeypatch.setattr(main, "seed_style_presets",
                        lambda _db: calls.append("seed_style_presets"), raising=True)
    return main, calls


def _run_lifespan(main) -> None:
    async def _go():
        async with main.lifespan(main.app):
            pass
    asyncio.run(_go())


def test_the_lifespan_runs_bootstrap_on_dev(recorded_bootstrap, monkeypatch):
    """DEV startup behaviour is unchanged: all seven still run."""
    main, calls = recorded_bootstrap
    monkeypatch.setattr(main.settings, "DATABASE_URL", DEV_URL)
    _run_lifespan(main)
    assert calls == [
        "ensure_identity_schema", "ensure_admin_user", "ensure_seeder_flags",
        "ensure_commons_realm", "ensure_starter_realms_and_posts",
        "seed_invite_codes", "seed_style_presets",
    ]


@pytest.mark.parametrize("url", [NEON_URL, UNKNOWN_URL])
def test_no_bootstrap_helper_runs_against_a_non_dev_target(
    recorded_bootstrap, monkeypatch, url
):
    """Not one write attempted — the guard precedes every call.

    This is the assertion that matters most: the refusal has to happen before
    ``ensure_identity_schema``, because that one is DDL.
    """
    main, calls = recorded_bootstrap
    monkeypatch.setattr(main.settings, "DATABASE_URL", url)
    monkeypatch.delenv(STARTUP_BOOTSTRAP_ACK_VAR, raising=False)
    _run_lifespan(main)
    assert calls == []


def test_a_refused_bootstrap_does_not_stop_the_app_from_serving(
    recorded_bootstrap, monkeypatch, caplog
):
    """Skipped, logged loudly, still serving.

    Crashing startup would couple the public read surface to a development
    seeding routine and turn a safety guard into an outage. Alembic takes the
    opposite line on purpose, and the next section asserts that.
    """
    main, calls = recorded_bootstrap
    monkeypatch.setattr(main.settings, "DATABASE_URL", NEON_URL)
    monkeypatch.delenv(STARTUP_BOOTSTRAP_ACK_VAR, raising=False)
    with caplog.at_level("WARNING"):
        _run_lifespan(main)          # completes; does not raise
    assert calls == []
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "STARTUP_BOOTSTRAP_SKIPPED" in logged
    _assert_no_secrets(logged)


def test_an_acknowledged_non_dev_target_runs_the_bootstrap(
    recorded_bootstrap, monkeypatch
):
    """The deliberate path still works — this is a guard, not a permanent block."""
    main, calls = recorded_bootstrap
    monkeypatch.setattr(main.settings, "DATABASE_URL", NEON_URL)
    monkeypatch.setenv(STARTUP_BOOTSTRAP_ACK_VAR,
                       startup_bootstrap_ack_phrase("NEON"))
    _run_lifespan(main)
    assert len(calls) == 7


# ══════════════════════════════════════════════════════════════════════════════
# Alembic guard
# ══════════════════════════════════════════════════════════════════════════════

def test_dev_migration_is_authorised_with_no_acknowledgement():
    """The ordinary Alembic workflow stays ordinary and convenient."""
    assert require_migration_authorisation(DEV_URL, environ={}) == "DEV"


@pytest.mark.parametrize("url", [NEON_URL, UNKNOWN_URL])
def test_non_dev_migration_is_refused_by_default(url):
    with pytest.raises(MutationRefused) as exc:
        require_migration_authorisation(url, environ={})
    message = str(exc.value)
    assert MIGRATION_ACK_VAR in message
    _assert_no_secrets(message)


@pytest.mark.parametrize("url,label", [(NEON_URL, "NEON"),
                                       (UNKNOWN_URL, "UNKNOWN_EXTERNAL")])
def test_the_correct_migration_acknowledgement_is_accepted(url, label):
    env = {MIGRATION_ACK_VAR: migration_ack_phrase(label)}
    assert require_migration_authorisation(url, environ=env) == label


@pytest.mark.parametrize("wrong", [
    "true", "1", "run-migrations", "run-migrations-on-", "run-migrations-on-DEV",
    "Run-Migrations-On-NEON", "run-migrations-on-NEON ",
])
def test_a_wrong_migration_acknowledgement_is_refused(wrong):
    with pytest.raises(MutationRefused):
        require_migration_authorisation(NEON_URL, environ={MIGRATION_ACK_VAR: wrong})


def test_the_migration_guard_raises_rather_than_skipping():
    """A migration that silently did not run leaves the operator believing the
    schema moved. That is worse than a refusal, so this one aborts."""
    with pytest.raises(MutationRefused):
        require_migration_authorisation(NEON_URL, environ={})


def test_both_alembic_entry_points_ask_before_touching_anything():
    """Online AND offline. Covering one and not the other would invite
    "just use ``--sql``" as the way around the guard."""
    source = (Path(__file__).resolve().parents[1] / "alembic" / "env.py").read_text()
    for func in ("def run_migrations_offline", "def run_migrations_online"):
        body = source.split(func, 1)[1]
        guard = body.find("_require_authorised_target")
        assert guard != -1, f"{func} does not call the guard"
        for mutator in ("context.configure", "engine_from_config", "run_migrations"):
            position = body.find(mutator)
            if position != -1:
                assert guard < position, f"{func}: guard runs after {mutator}"


# ══════════════════════════════════════════════════════════════════════════════
# THE TWO AUTHORISATIONS ARE NOT INTERCHANGEABLE — asserted in both directions
# ══════════════════════════════════════════════════════════════════════════════

def test_a_startup_acknowledgement_does_not_authorise_alembic():
    """Authorising app bootstrap must not implicitly authorise arbitrary
    migrations, which can drop columns and rewrite tables."""
    env = {STARTUP_BOOTSTRAP_ACK_VAR: startup_bootstrap_ack_phrase("NEON")}
    with pytest.raises(MutationRefused):
        require_migration_authorisation(NEON_URL, environ=env)


def test_a_migration_acknowledgement_does_not_authorise_startup_bootstrap():
    """And the reverse: running a migration must not implicitly re-seed
    production with development fixtures."""
    env = {MIGRATION_ACK_VAR: migration_ack_phrase("NEON")}
    assert startup_bootstrap_authorised(NEON_URL, environ=env)[0] is False


def test_the_two_variables_and_phrases_are_distinct():
    """Distinct on BOTH axes, so neither a copied value nor a mistyped variable
    name can cross over."""
    assert STARTUP_BOOTSTRAP_ACK_VAR != MIGRATION_ACK_VAR
    for label in ("NEON", "UNKNOWN_EXTERNAL", "LOCAL"):
        startup, migration = (startup_bootstrap_ack_phrase(label),
                              migration_ack_phrase(label))
        assert startup != migration
        assert not startup.startswith(migration.split("-")[0])


def test_even_swapping_the_values_into_the_other_variable_fails():
    """The phrases are checked per-variable, so a value in the wrong variable is
    simply a wrong value."""
    swapped = {
        STARTUP_BOOTSTRAP_ACK_VAR: migration_ack_phrase("NEON"),
        MIGRATION_ACK_VAR: startup_bootstrap_ack_phrase("NEON"),
    }
    assert startup_bootstrap_authorised(NEON_URL, environ=swapped)[0] is False
    with pytest.raises(MutationRefused):
        require_migration_authorisation(NEON_URL, environ=swapped)


# ══════════════════════════════════════════════════════════════════════════════
# Output safety and repo hygiene
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("url", [NEON_URL, UNKNOWN_URL])
def test_no_refusal_carries_a_credential(url):
    _, startup_reason, _ = startup_bootstrap_authorised(url, environ={})
    _assert_no_secrets(startup_reason)
    with pytest.raises(MutationRefused) as exc:
        require_migration_authorisation(url, environ={})
    _assert_no_secrets(str(exc.value))
    for message in (startup_reason, str(exc.value)):
        assert "withheld" in message.lower()


def test_neither_acknowledgement_is_committed_anywhere_in_the_repo():
    """The value must never be stored. A phrase living in ``.env`` or a script
    would authorise every future run and undo the whole design."""
    import subprocess
    root = _REPO_ROOT
    tracked = subprocess.run(
        ["git", "-C", str(root), "grep", "-l", "-e",
         "bootstrap-startup-writes-on-", "-e", "run-migrations-on-"],
        capture_output=True, text=True,
    ).stdout.split()
    allowed = {
        "backend/app/core/db_target.py",              # builds the phrase
        "backend/tests/test_production_target_safety.py",  # tests it
    }
    unexpected = set(tracked) - allowed
    assert not unexpected, f"acknowledgement phrase present in: {sorted(unexpected)}"


# ══════════════════════════════════════════════════════════════════════════════
# Import-time safety
# ══════════════════════════════════════════════════════════════════════════════

def test_engine_creation_is_lazy_and_opens_no_connection():
    """No mutation-capable network action may occur before authorisation.

    ``app.core.database`` builds an engine at import time. That is only safe
    because SQLAlchemy engines are lazy — asserted here against a real pool
    rather than assumed from documentation, by checking the engine holds no
    checked-out connection after construction.
    """
    from sqlalchemy import create_engine
    engine = create_engine("postgresql://u:p@does-not-resolve.invalid:5432/db")
    assert engine.pool.checkedout() == 0
    assert engine.url.host == "does-not-resolve.invalid"


def test_the_guard_module_imports_nothing_that_connects():
    """``db_target`` is imported by both call sites, so it must be inert."""
    import ast
    path = Path(db_target.__file__)
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # An ALLOWLIST, so a new import here is a visible edit rather than a silent
    # capability. ``urllib.parse`` is pure string parsing and is the module the
    # shared classifier itself uses; ``urllib.request`` — which would open
    # sockets — is a different module and is not admitted by this set.
    assert imported <= {
        "__future__", "importlib.util", "os", "pathlib", "typing", "urllib.parse",
    }, imported
    assert "urllib.request" not in imported

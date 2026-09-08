"""Authorisation for DB MUTATION against a non-DEV database target.

WHY THIS EXISTS. Two paths in this codebase could perform schema and seeding
writes against whatever ``DATABASE_URL`` happened to be set, with no
confirmation step and no record that anybody intended it:

* the FastAPI lifespan, which runs seven bootstrap mutations at startup —
  including ``ALTER TABLE users ADD COLUMN`` — so merely BOOTING the app against
  production would have performed DDL on it;
* ``alembic/env.py``, which passed ``settings.DATABASE_URL`` straight to
  ``engine_from_config``, so ``alembic upgrade head`` migrated whichever database
  the environment named.

Possession of a connection string is not a statement of intent. The September
2026 readiness audit found the workspace carrying ambient libpq variables that
had once pointed at production-era infrastructure; a removal is a state that can
regress, and the same is true of a ``DATABASE_URL`` export. So both paths now
require an ACKNOWLEDGEMENT that names the operation and the target, and neither
runs on the strength of a URL alone.

WHAT THIS IS NOT. Not authentication — it grants no access and protects nothing
from someone who holds the credential and means to use it. It is an operator
acknowledgement, and its whole job is to make an ACCIDENT structurally
impossible while leaving a DELIBERATE act available. It is also not a permanent
block on production migration: production migration remains possible, it just
has to be asked for.

ONE DEFINITION OF "IS THIS DEV?". The classification comes from
``scripts/assert_dev_db.py`` — the same module ``scripts/devdb`` and
``scripts/media_inventory.py`` use — and this module adds no host logic of its
own. Two notions of DEV is exactly the failure that module exists to prevent.

WHY IT IS LOADED BY PATH. ``scripts/`` sits at the repository root, is not a
package, and is not on ``sys.path`` when the app runs: both ``start-dev.sh`` and
``start-prod.sh`` ``cd backend`` before invoking uvicorn, and Alembic runs from
``backend/`` too. ``import scripts.assert_dev_db`` therefore fails at runtime in
both. Loading the file by path is not a workaround invented here — it is the
convention ``scripts/devdb`` already established, for this same reason, and it
avoids the two alternatives that would each cost something real: putting the
repository root on ``sys.path`` from application code, or moving the classifier
under ``backend/`` and thereby requiring ``backend/`` on ``sys.path`` for
``devdb``, which would break a tested guard that deliberately depends on
nothing.

IF THE CLASSIFIER CANNOT BE LOADED, MUTATION IS REFUSED. A guard that cannot
answer "which database is this?" must not answer "go ahead". The refusal is
reported the same way any other refusal is, so a deployment missing
``scripts/`` degrades to "no bootstrap writes", never to "unguarded writes".
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

#: The shared classifier, loaded from the repository root by path.
_GUARD_PATH = Path(__file__).resolve().parents[3] / "scripts" / "assert_dev_db.py"

#: Classification labels, mirrored for callers so they need not reach into the
#: dynamically loaded module. Kept as plain strings, and asserted equal to the
#: guard module's own values in ``tests/test_production_target_safety.py``.
DEV = "DEV"
NON_POSTGRES = "NON_POSTGRES"
UNAVAILABLE = "CLASSIFIER_UNAVAILABLE"

#: A local SQLite file (or in-memory) database. NOT a label the shared
#: classifier produces — it is a narrowing this module applies on top of the
#: shared classifier's :data:`NON_POSTGRES`, and it exists because that label is
#: too broad to treat as safe.
#:
#: WHY THE NARROWING IS NECESSARY. ``classify_database_url`` returns
#: ``NON_POSTGRES`` for ANY scheme that is not postgres, so the label covers
#: ``mysql://root:pw@db.example.com/app``, ``mssql+pyodbc://…`` and even
#: ``sqlite+libsql://turso.example.com/db`` — remote, writable databases that
#: could perfectly well be somebody's production. Treating the whole label as
#: safe would have opened a hole wider than the one this module closes.
LOCAL_SQLITE = "LOCAL_SQLITE"

#: Targets that need no production acknowledgement to be MUTATED.
#:
#: ``DEV`` is the Replit-managed development database. ``LOCAL_SQLITE`` is the
#: application's own built-in fallback (``sqlite:///./ficshon.db``, the default
#: in ``app.core.config``) and the throwaway files the test suite uses. Neither
#: can be the remote production database, and requiring an operator
#: acknowledgement merely to bootstrap a local file would make the guard a
#: nuisance in the one situation where it protects nothing — which is how
#: guards come to be disabled wholesale.
NO_ACKNOWLEDGEMENT_REQUIRED = frozenset({DEV, LOCAL_SQLITE})

#: Environment variable authorising the FastAPI STARTUP BOOTSTRAP writes.
STARTUP_BOOTSTRAP_ACK_VAR = "FICSHON_STARTUP_BOOTSTRAP_ACK"

#: Environment variable authorising ALEMBIC migration/stamp/downgrade.
MIGRATION_ACK_VAR = "FICSHON_MIGRATION_ACK"


def _load_guard():
    """The shared classification module, or ``None`` when it cannot be loaded."""
    try:
        spec = importlib.util.spec_from_file_location(
            "ficshon_assert_dev_db", _GUARD_PATH
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def _is_local_sqlite(url: str) -> bool:
    """True when *url* is a LOCAL SQLite database — a file, or in memory.

    THE NARROWEST DETERMINATION THAT ANSWERS THE QUESTION, and deliberately not
    a second host classification: it asks only "is the scheme sqlite?" and "does
    this URL name a host at all?". Which host, and whether that host is DEV or
    Neon, stays the shared classifier's question and is not re-asked here.

    Both halves are required, and the second is the load-bearing one.
    ``sqlite+libsql://turso.example.com/db`` and ``sqlite://remote-host/db``
    both carry the sqlite scheme and both name a REMOTE server; a scheme check
    alone would have accepted them. A local SQLite URL has an empty authority —
    ``sqlite:///./ficshon.db``, ``sqlite:////abs/path.db``,
    ``sqlite:///:memory:`` and bare ``sqlite://`` all parse to
    ``netloc == ''`` — so requiring that is what makes this local.

    The ``+driver`` suffix is stripped exactly as the shared classifier strips
    it, so ``sqlite+pysqlite`` and ``sqlite+aiosqlite`` are recognised.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    base_scheme = parsed.scheme.split("+", 1)[0].lower()
    return base_scheme == "sqlite" and not parsed.netloc


def classify_target(url: Optional[str]) -> str:
    """Classify *url* using the shared guard, or :data:`UNAVAILABLE`.

    Returns a label rather than raising, because both callers need to report a
    classification in a refusal and neither can usefully distinguish "malformed
    URL" from "unclassifiable host" — both are non-DEV, and non-DEV is the whole
    question here. ``DatabaseTargetError`` for a missing or unparseable URL is
    collapsed into :data:`UNAVAILABLE` for the same reason: it fails closed.
    """
    guard = _load_guard()
    if guard is None:
        return UNAVAILABLE
    try:
        label = guard.classify_database_url(url)
    except Exception:
        return UNAVAILABLE

    # Narrow the shared classifier's broadest label. NON_POSTGRES covers remote
    # MySQL/MSSQL and networked SQLite dialects as well as a local file, so the
    # label alone cannot be trusted; :func:`_is_local_sqlite` separates the one
    # case that genuinely cannot be production. Every other label is returned
    # unchanged, so DEV, NEON and UNKNOWN_EXTERNAL keep their exact meanings.
    if label == NON_POSTGRES and url is not None and _is_local_sqlite(url):
        return LOCAL_SQLITE
    return label


def startup_bootstrap_ack_phrase(classification: str) -> str:
    """The exact value :data:`STARTUP_BOOTSTRAP_ACK_VAR` must hold.

    The classification is EMBEDDED in the phrase, so an acknowledgement minted
    for one target does not authorise another: a value left over from a NEON
    bootstrap does not authorise writes to an UNKNOWN_EXTERNAL host that
    appeared later.
    """
    return f"bootstrap-startup-writes-on-{classification}"


def migration_ack_phrase(classification: str) -> str:
    """The exact value :data:`MIGRATION_ACK_VAR` must hold.

    A DIFFERENT variable and a DIFFERENT phrase prefix from the startup
    acknowledgement, so the two cannot substitute for each other in either
    direction — see this module's tests, which assert both directions.
    """
    return f"run-migrations-on-{classification}"


class MutationRefused(RuntimeError):
    """A mutation-capable operation was refused for its database target.

    The message is safe to print, log and paste into a ticket: it names a
    classification, a variable name and a phrase, and never the URL, host, user,
    password or query string. A refusal that leaks the connection string has
    traded one exposure for another.
    """


def _authorised(
    *,
    url: Optional[str],
    var: str,
    phrase_for,
    operation: str,
    environ: Optional[Mapping[str, str]] = None,
) -> tuple[bool, str, str]:
    """Shared decision for both callers. Returns ``(allowed, reason, label)``.

    Read from ``os.environ`` DIRECTLY, never through ``app.core.config.Settings``.
    That is deliberate and load-bearing: ``Settings`` is declared with
    ``env_file=".env"``, so a value placed in the dotenv file would be picked up
    silently and would then authorise every future run on that checkout — which
    is exactly the "persists in the environment" failure this design exists to
    avoid. An acknowledgement must be supplied per invocation.
    """
    env = os.environ if environ is None else environ
    label = classify_target(url)

    if label in NO_ACKNOWLEDGEMENT_REQUIRED:
        return True, f"target classified {label}", label

    supplied = env.get(var)
    expected = phrase_for(label)
    if supplied == expected:
        return True, f"acknowledged for {label}", label

    if label == UNAVAILABLE:
        detail = (
            "the database target could not be classified (missing, malformed, "
            "or the shared classifier could not be loaded)"
        )
    else:
        detail = (
            f"database target classified {label}, which is neither the DEV "
            "database nor a local SQLite file"
        )

    return False, (
        f"Refusing {operation}: {detail}. "
        f"To do this deliberately, set {var} to exactly "
        f"'{expected}' for this one invocation. Do not persist it in .env or "
        f"the shell profile. (Connection details withheld.)"
    ), label


def startup_bootstrap_authorised(
    url: Optional[str], *, environ: Optional[Mapping[str, str]] = None
) -> tuple[bool, str, str]:
    """May the FastAPI lifespan run its bootstrap WRITES? ``(allowed, reason, label)``.

    Returns a decision rather than raising, and that asymmetry with
    :func:`require_migration_authorisation` is intentional. The bootstrap block
    is DEVELOPMENT CONVENIENCE — it creates the dev admin, the Commons realm,
    starter posts, invite codes and style presets, and adds a column an old dev
    database may lack. None of it is required to SERVE traffic. So on a non-DEV
    target without acknowledgement the right answer is "skip the writes, say so
    loudly, keep serving reads", not "refuse to boot": crashing startup would
    couple the public read surface to a development seeding routine and turn a
    safety guard into an outage.

    A migration is the opposite case and is refused by raising.
    """
    return _authorised(
        url=url,
        var=STARTUP_BOOTSTRAP_ACK_VAR,
        phrase_for=startup_bootstrap_ack_phrase,
        operation="to run startup bootstrap writes",
        environ=environ,
    )


def require_migration_authorisation(
    url: Optional[str], *, operation: str = "to run migrations",
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Return the classification, or raise :class:`MutationRefused`.

    RAISES, unlike the startup guard. A migration that silently did not run is
    worse than one that refused: the operator would believe the schema had
    moved. Alembic must stop, loudly, with the exact variable and phrase needed
    to proceed on purpose.
    """
    allowed, reason, label = _authorised(
        url=url,
        var=MIGRATION_ACK_VAR,
        phrase_for=migration_ack_phrase,
        operation=operation,
        environ=environ,
    )
    if not allowed:
        raise MutationRefused(reason)
    return label

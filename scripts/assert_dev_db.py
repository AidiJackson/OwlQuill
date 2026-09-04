"""Shared DEV-database target classification and assertion.

One definition of "is this the DEV database?", used by every path that is about
to touch a database from this workspace: the ``scripts/devdb`` shell wrapper and
any future maintenance or data-touching script. Two subtly different notions of
DEV is exactly the failure this module exists to prevent, so ``devdb`` imports
from here rather than reimplementing the check in shell.

WHY THIS EXISTS
---------------
On 4 September 2026 an audit found the workspace carried ambient libpq
variables (``PGHOST``/``PGPORT``/``PGUSER``/``PGPASSWORD``/``PGDATABASE``)
pointing at production-era external infrastructure, while the application's
``DATABASE_URL`` pointed at the Replit-managed DEV database. Any bare ``psql``
or ``pg_dump`` therefore resolved to the wrong database with owner privileges,
silently and with no confirmation step. Those variables were removed, but a
removal is a state that can regress — a re-attached integration or a restored
secret puts them back. This module is the part that does not regress: it fails
closed on anything it cannot positively identify as DEV.

DESIGN
------
* **Allowlist, not denylist.** A target is DEV only if its hostname is in
  :data:`DEV_HOSTNAMES`. Everything else is refused, including hosts nobody has
  classified yet. The NEON/LOCAL/UNKNOWN_EXTERNAL labels exist to make refusals
  legible, never to widen what is accepted — a new Replit host will refuse with
  ``UNKNOWN_EXTERNAL`` until somebody adds it here deliberately, which is the
  correct outcome.
* **Credentials never appear in output.** Errors carry a classification, never
  the URL, hostname, user, password or query string. A guard that leaks the
  connection string into a traceback or a CI log has traded one exposure for
  another.
* **Explicit input beats ambient input.** Callers pass a URL, or the URL is read
  from ``DATABASE_URL``. Ambient ``PG*`` variables are never consulted for
  classification — they are the untrusted residue this module defends against.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional
from urllib.parse import urlparse

#: Hostnames that ARE the Replit-managed DEV database for this project.
#:
#: Deliberately exact strings rather than a pattern. A pattern such as
#: "anything Replit-looking" would silently admit a host nobody has inspected;
#: an exact list means a genuinely new DEV host fails closed and is added by a
#: reviewable edit.
DEV_HOSTNAMES = frozenset({"helium"})

#: Substrings marking a Neon-hosted target. Used only to LABEL a refusal, never
#: to decide acceptance — a Neon host is refused because it is not in
#: DEV_HOSTNAMES, and would be refused just the same if this tuple were empty.
NEON_HOST_MARKERS = ("neon.tech", "neon-", ".neon.")

#: Hostnames treated as a developer's own machine.
LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1", ""})

#: URL schemes this module understands as PostgreSQL, including SQLAlchemy's
#: ``+driver`` forms (``postgresql+psycopg2``), which are split before matching.
POSTGRES_SCHEMES = frozenset({"postgres", "postgresql"})

#: The ambient libpq variables that must never reach a database client spawned
#: from this workspace. Defined here, beside the classification, so the wrapper
#: and any future Python script strip the SAME set — a list that drifts is a
#: variable that survives.
AMBIENT_LIBPQ_VARS = ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")

# Classification labels.
DEV = "DEV"
NEON = "NEON"
LOCAL = "LOCAL"
UNKNOWN_EXTERNAL = "UNKNOWN_EXTERNAL"
NON_POSTGRES = "NON_POSTGRES"


class DatabaseTargetError(RuntimeError):
    """A database target is missing, unparseable, or not the DEV database.

    Its message is safe to print, log, and paste into a ticket: it names a
    classification and never the URL, host, user, password or query string.
    """


def _hostname(url: str) -> Optional[str]:
    """Hostname from *url*, or None when it cannot be determined.

    ``urlparse`` raises on some malformed authorities (an unterminated IPv6
    literal, for one), and ``.hostname`` is the accessor that raises rather than
    ``urlparse`` itself — so the access is inside the try, not just the parse.
    """
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def classify_database_url(url: Optional[str]) -> str:
    """Classify *url* as :data:`DEV`, :data:`NEON`, :data:`LOCAL`,
    :data:`UNKNOWN_EXTERNAL` or :data:`NON_POSTGRES`.

    Raises :class:`DatabaseTargetError` when *url* is missing or malformed,
    because an unparseable target is not a classification — it is an input
    error, and answering "UNKNOWN" for it would invite a caller to treat the two
    as the same kind of refusal.

    Never consults the environment. Classification depends only on the string
    passed in, which is what makes ambient ``PG*`` residue unable to influence
    the verdict for an explicitly supplied URL.
    """
    if url is None or not url.strip():
        raise DatabaseTargetError(
            "No database URL supplied. Set DATABASE_URL, or pass a URL "
            "explicitly. Refusing to fall back to ambient libpq variables."
        )

    try:
        parsed = urlparse(url)
    except ValueError:
        raise DatabaseTargetError(
            "Database URL could not be parsed. (Value withheld.)"
        ) from None

    if not parsed.scheme:
        raise DatabaseTargetError(
            "Database URL has no scheme. (Value withheld.)"
        )

    # "postgresql+psycopg2" -> "postgresql"
    base_scheme = parsed.scheme.split("+", 1)[0].lower()
    if base_scheme not in POSTGRES_SCHEMES:
        return NON_POSTGRES

    hostname = _hostname(url)
    if hostname is None:
        raise DatabaseTargetError(
            "Database URL names no host. (Value withheld.)"
        )

    host = hostname.lower()

    # Deny markers are evaluated before the allowlist purely so a refusal is
    # labelled usefully. Safety does not depend on the order: acceptance
    # requires DEV_HOSTNAMES membership either way.
    if any(marker in host for marker in NEON_HOST_MARKERS):
        return NEON
    if host in DEV_HOSTNAMES:
        return DEV
    if host in LOCAL_HOSTNAMES:
        return LOCAL
    return UNKNOWN_EXTERNAL


def assert_dev_database(
    url: Optional[str] = None,
    *,
    purpose: str = "this operation",
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Return *url* when it is the DEV database; raise otherwise.

    Call this at the top of any script that is about to create an engine,
    session or connection::

        from assert_dev_db import assert_dev_database
        assert_dev_database(purpose="to backfill image URLs")

    *purpose* is rendered directly after "Refusing", so phrase it as "to do X"
    or as a noun phrase.

    *url* defaults to ``DATABASE_URL`` from *environ* (the real environment when
    omitted). ``PG*`` variables are never read.

    The returned value is the caller's own URL, unchanged, so a caller can write
    ``engine = create_engine(assert_dev_database())`` and have the guard sit
    directly in the path it protects rather than beside it.
    """
    env = os.environ if environ is None else environ
    if url is None:
        url = env.get("DATABASE_URL")

    classification = classify_database_url(url)
    if classification == DEV:
        return url  # type: ignore[return-value]

    raise DatabaseTargetError(
        f"Refusing {purpose}: database target classified {classification}, "
        f"not DEV. Only the known Replit DEV database is permitted here. "
        f"(Connection details withheld.)"
    )


def sanitized_libpq_env(
    environ: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """A copy of *environ* with every :data:`AMBIENT_LIBPQ_VARS` entry removed.

    Lives beside the classification because both answer the same question —
    "which database is about to be contacted?" — and because a client spawned
    with a validated URL but an unsanitised environment is only accidentally
    safe: libpq fills in from ``PG*`` whatever the connection string omits.

    Removal is unconditional. A variable that is absent stays absent, and one
    that reappears (a re-attached integration, a restored secret) is stripped
    again on the next invocation without anyone having to notice it came back.
    """
    env = dict(os.environ if environ is None else environ)
    for name in AMBIENT_LIBPQ_VARS:
        env.pop(name, None)
    return env

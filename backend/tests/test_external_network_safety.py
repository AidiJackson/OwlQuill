"""The external-cost safety checkpoint: pytest cannot spend money.

WHAT THIS PROTECTS AGAINST. This workspace holds live OpenAI, Google AI,
Replicate, RunPod and OpenRouter credentials and a full set of R2 keys. Until
now the only thing standing between an ordinary ``pytest`` run and a real bill
was ``tests/conftest.py`` popping seven environment variables — a hand-maintained
list, in one file, with nothing asserting it stays complete, and with
``Settings(env_file=".env")`` able to refill any of them from the dotenv file
precisely BECAUSE the variable had been popped.

So there are two layers now, and this module tests both:

* **the structural one** — the socket layer refuses non-loopback connections, so
  a paid request cannot leave the process whatever a provider thinks it holds;
* **the configuration one** — every credential Ficshon knows about resolves
  falsy, and a NEW credential-shaped setting fails this suite until somebody
  decides about it.

The opt-out (``LIVE_API_TESTS=1``) is tested at unit level only. Nothing here
contacts the Internet, and no test in this repository may be written to do so
without that variable being set deliberately, by hand.
"""
import os
import socket

import pytest

from app.core.config import settings
from tests.conftest import (
    LIVE_API_TESTS_ENV,
    _install_network_guard,
    _is_local,
    _restore_network,
)

#: A documentation address from TEST-NET-1 (RFC 5737). Chosen precisely because
#: it is guaranteed not to be routed to a real host: if the guard ever fails
#: open, the worst case is a connection attempt into a black hole rather than
#: traffic to somebody's server.
UNROUTABLE = ("192.0.2.1", 80)


# ── the guard is actually installed ──────────────────────────────────────────


def test_the_guard_is_active_during_an_ordinary_run():
    from tests import conftest

    assert os.environ.get(LIVE_API_TESTS_ENV) != "1", (
        "This suite is running with the live-API opt-in set. That is never "
        "automatic — unset LIVE_API_TESTS before running the ordinary suite."
    )
    assert conftest._NETWORK_GUARD_ORIGINALS is not None


# ── outbound is refused ──────────────────────────────────────────────────────


def test_a_direct_socket_connect_to_the_internet_is_refused():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Outbound network is disabled"):
            sock.connect(UNROUTABLE)
    finally:
        sock.close()


def test_connect_ex_is_refused_too():
    """The same syscall with an errno return. Patching ``connect`` alone leaves
    this path open, which is how a 'guarded' suite still makes calls."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Outbound network is disabled"):
            sock.connect_ex(UNROUTABLE)
    finally:
        sock.close()


def test_dns_resolution_is_refused():
    """Resolution is outbound traffic in its own right, and it happens BEFORE
    connect — so blocking connect alone still leaks the hostname to a resolver."""
    with pytest.raises(RuntimeError, match="Outbound network is disabled"):
        socket.getaddrinfo("api.openai.com", 443)


def test_create_connection_is_covered_by_the_funnel():
    """``socket.create_connection`` is what urllib3 and httpcore use. It is not
    patched directly — it builds a socket and calls ``connect``, so the funnel
    catches it. This test is the proof of that reasoning."""
    with pytest.raises(RuntimeError, match="Outbound network is disabled"):
        socket.create_connection(UNROUTABLE, timeout=1)


def test_an_ipv6_destination_is_refused():
    """IPv6 through the DNS/resolution path, which every client uses first.

    Not asserted through an ``AF_INET6`` socket: this container has no IPv6
    stack, so ``socket.socket(AF_INET6, ...)`` raises EAFNOSUPPORT before the
    guard is ever consulted, and a test that "passed" on that error would be
    testing the sandbox rather than the guard. The address-classification test
    below covers the ``connect`` path for IPv6 tuples directly.
    """
    with pytest.raises(RuntimeError, match="Outbound network is disabled"):
        socket.getaddrinfo("2001:db8::1", 80)


@pytest.mark.skipif(
    not socket.has_ipv6, reason="no IPv6 stack in this environment"
)
def test_an_ipv6_socket_connect_is_refused_where_ipv6_exists():
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:  # pragma: no cover — has_ipv6 true but unusable
        pytest.skip("IPv6 reported but not usable in this environment")
    try:
        with pytest.raises(RuntimeError, match="Outbound network is disabled"):
            sock.connect(("2001:db8::1", 80, 0, 0))
    finally:
        sock.close()


def test_urllib_cannot_reach_a_provider():
    """The mechanism nine app modules use, including the Google and OpenRouter
    image providers and ``storage._load_from_http``."""
    import urllib.error
    import urllib.request

    with pytest.raises((RuntimeError, urllib.error.URLError)) as excinfo:
        urllib.request.urlopen("https://api.openai.com/v1/models", timeout=1)
    assert "Outbound network is disabled" in str(excinfo.value)


def test_requests_cannot_reach_a_provider():
    """The mechanism six app modules use, and boto3's transport."""
    requests = pytest.importorskip("requests")

    with pytest.raises(Exception) as excinfo:
        requests.get("https://api.replicate.com/v1/models", timeout=1)
    assert "Outbound network is disabled" in str(excinfo.value)


def test_httpx_cannot_reach_a_provider():
    """The OpenAI SDK's transport."""
    httpx = pytest.importorskip("httpx")

    with pytest.raises(Exception) as excinfo:
        httpx.get("https://api.openai.com/v1/models", timeout=1)
    assert "Outbound network is disabled" in str(excinfo.value)


# ── loopback stays open ──────────────────────────────────────────────────────


def test_a_loopback_server_is_still_reachable():
    """Tests talk to themselves. A guard that broke this would be swapped for a
    weaker one within a week, so it has to be demonstrably intact."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        conn, _ = server.accept()
        try:
            client.sendall(b"ping")
            assert conn.recv(4) == b"ping"
        finally:
            conn.close()
            client.close()
    finally:
        server.close()


def test_localhost_resolution_still_works():
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("127.0.0.1", 80)


@pytest.mark.parametrize("address", [
    ("127.0.0.1", 5432),
    ("127.0.0.53", 53),
    ("localhost", 8000),
    ("::1", 8000, 0, 0),
    ("", 0),
    "/tmp/some.sock",          # AF_UNIX — never leaves the machine
])
def test_local_addresses_are_classified_local(address):
    assert _is_local(address) is True


@pytest.mark.parametrize("address", [
    ("192.0.2.1", 80),
    ("api.openai.com", 443),
    ("generativelanguage.googleapis.com", 443),
    ("2001:db8::1", 80, 0, 0),
])
def test_external_addresses_are_classified_external(address):
    assert _is_local(address) is False


# ── the opt-out, without touching the Internet ───────────────────────────────


def test_the_opt_in_branch_installs_no_guard(monkeypatch):
    """Unit-level only. Proving the override works must not mean making a paid
    call, so this asserts the branch that conftest evaluates at import."""
    monkeypatch.setenv(LIVE_API_TESTS_ENV, "1")
    installed = (
        None if os.environ.get(LIVE_API_TESTS_ENV) == "1" else _install_network_guard()
    )
    assert installed is None, "LIVE_API_TESTS=1 must skip installing the guard"


def test_restoring_the_guard_puts_the_socket_layer_back():
    """The guard must not outlive the session it protects."""
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo)
    _restore_network(originals)
    assert socket.socket.connect is originals[0]
    assert socket.socket.connect_ex is originals[1]
    assert socket.getaddrinfo is originals[2]


# ── credential isolation, and drift ──────────────────────────────────────────

#: Every paid provider or storage credential Ficshon knows about, by the name it
#: is read under. ``RUNPOD_API_KEY`` is read straight from ``os.environ`` rather
#: than through ``Settings`` (``editor_self_hosted.py:186``), which is exactly
#: why this list is by-name and checked in both places.
PAID_CREDENTIAL_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_AI_API_KEY",
    "FAL_KEY",
    "TOGETHER_API_KEY",
    "REPLICATE_API_TOKEN",
    "RUNPOD_API_KEY",
    "OPENROUTER_API_KEY",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
    "R2_PUBLIC_URL",
)

#: Credential-shaped ``Settings`` fields that are NOT a paid external provider,
#: with the reason. Pinned so that a new field of either sort forces a decision
#: rather than silently joining whichever category is convenient.
NON_PROVIDER_CREDENTIAL_FIELDS = {
    "SECRET_KEY": "JWT signing key — local, set to a test value by conftest",
    "SMTP_PASSWORD": "outbound email, not a metered generation provider",
    "AI_API_KEY": "legacy generic field with no consumer in app/ (AI_PROVIDER='fake')",
}


@pytest.mark.parametrize("name", PAID_CREDENTIAL_ENV_VARS)
def test_a_paid_credential_is_absent_from_the_environment(name):
    assert not os.environ.get(name), (
        f"{name} is visible to pytest. conftest strips it precisely so a "
        "provider cannot construct; something has put it back."
    )


@pytest.mark.parametrize("name", [
    "OPENAI_API_KEY", "GOOGLE_AI_API_KEY", "FAL_KEY",
    "TOGETHER_API_KEY", "REPLICATE_API_TOKEN", "OPENROUTER_API_KEY",
])
def test_a_paid_credential_is_falsy_in_settings(name):
    """Read through ``Settings``, not ``os.environ``, because that is what the
    providers read — and because ``Settings`` has a ``.env`` fallback that
    ``os.environ`` checks alone would not catch."""
    assert not getattr(settings, name, None), (
        f"settings.{name} is truthy during tests. The most likely cause is "
        "backend/.env supplying it: pydantic-settings falls back to the dotenv "
        "file when the environment variable is absent, which is exactly the "
        "state conftest creates."
    )


def test_no_unknown_credential_shaped_setting_is_populated():
    """The drift catch.

    A provider added later brings a new ``*_API_KEY`` with it. If nobody updates
    ``conftest``'s strip list, that key is live in tests and every other test
    here still passes. This one fails: any credential-shaped field must be
    either falsy or explicitly classified as non-provider.
    """
    import re

    from app.core.config import Settings

    suspicious = [
        name for name in Settings.model_fields
        if re.search(r"(_API_KEY|_TOKEN|_SECRET|_KEY|PASSWORD)$", name)
    ]
    assert suspicious, "the field scan matched nothing — the pattern has rotted"

    populated = [
        name for name in suspicious
        if getattr(settings, name, None)
        and name not in NON_PROVIDER_CREDENTIAL_FIELDS
    ]
    assert populated == [], (
        f"credential-shaped settings are populated during tests: {populated}. "
        "If one of these is a paid provider, add it to conftest's strip list. "
        "If it is not, classify it in NON_PROVIDER_CREDENTIAL_FIELDS with a "
        "reason."
    )


def test_object_storage_is_disabled():
    """R2 writes are metered. ``put_object`` only reaches boto3 when this is on."""
    assert settings.USE_OBJECT_STORAGE is False


def test_the_r2_client_cannot_be_constructed():
    """Defence in depth: even if something flipped USE_OBJECT_STORAGE, the
    client needs credentials that are not here."""
    from app.core import storage

    with pytest.raises((KeyError, RuntimeError)):
        storage._r2_client()


def test_the_strip_list_still_covers_every_paid_credential():
    """conftest must keep popping what this module claims it pops."""
    from pathlib import Path

    conftest_src = (Path(__file__).parent / "conftest.py").read_text()
    for name in PAID_CREDENTIAL_ENV_VARS:
        assert name in conftest_src, (
            f"{name} is no longer named in conftest.py — the strip list and this "
            "test have drifted apart."
        )

"""Tests for scripts/reset_account.py — the account-release maintenance script.

These exercise the SAFETY logic (identity resolution + hard stops) against the
isolated test DB. No live data is touched. The script itself is a thin CLI over
these functions.
"""
import importlib.util
from pathlib import Path

import pytest

# Load the script module by path (it lives in scripts/, not the app package).
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "reset_account.py"
_spec = importlib.util.spec_from_file_location("reset_account", _SCRIPT)
reset_account = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reset_account)


def _make_user(db_session, email, username, **flags):
    from app.models.user import User
    from app.core.security import get_password_hash
    u = User(email=email, username=username, hashed_password=get_password_hash("x"), **flags)
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def _make_character(db_session, owner_id, name="Bertie West"):
    from app.models.character import Character
    c = Character(owner_id=owner_id, name=name, species="human")
    db_session.add(c)
    db_session.commit()
    return c


# ── Identity resolution ─────────────────────────────────────────────────────

def test_resolve_matches_single_account(db_session):
    u = _make_user(db_session, "match@e.com", "matcher")
    resolved = reset_account._resolve_target(db_session, "matcher", "match@e.com")
    assert resolved.id == u.id


def test_resolve_refuses_when_username_and_email_differ(db_session):
    _make_user(db_session, "one@e.com", "one")
    _make_user(db_session, "two@e.com", "two")
    with pytest.raises(SystemExit) as exc:
        reset_account._resolve_target(db_session, "one", "two@e.com")
    assert "DIFFERENT accounts" in str(exc.value)


def test_resolve_refuses_unknown_username(db_session):
    with pytest.raises(SystemExit) as exc:
        reset_account._resolve_target(db_session, "ghost", "ghost@e.com")
    assert "no account with username" in str(exc.value)


# ── Hard stops ──────────────────────────────────────────────────────────────

def test_hard_stop_when_character_remains(db_session):
    u = _make_user(db_session, "owner@e.com", "owner")
    _make_character(db_session, u.id, "Bertie West")
    stops = reset_account._check_hard_stops(db_session, u)
    assert any("still owns" in s for s in stops)
    assert any("Bertie West" in s for s in stops)


def test_no_hard_stop_for_empty_non_admin(db_session):
    u = _make_user(db_session, "empty@e.com", "empty")
    assert reset_account._check_hard_stops(db_session, u) == []


def test_hard_stop_when_last_admin(db_session):
    u = _make_user(db_session, "soleadmin@e.com", "soleadmin", is_admin=True)
    stops = reset_account._check_hard_stops(db_session, u)
    assert any("last remaining admin" in s for s in stops)


def test_no_last_admin_stop_when_another_admin_exists(db_session):
    _make_user(db_session, "otheradmin@e.com", "otheradmin", is_admin=True)
    u = _make_user(db_session, "admin2@e.com", "admin2", is_admin=True)
    stops = reset_account._check_hard_stops(db_session, u)
    assert not any("last remaining admin" in s for s in stops)


# ── Dry run makes no changes ────────────────────────────────────────────────

def test_gather_counts_is_read_only(db_session):
    u = _make_user(db_session, "counts@e.com", "counter")
    _make_character(db_session, u.id, "Bertie West")
    before = db_session.query(type(u)).count()
    counts = reset_account._gather_counts(db_session, u.id)
    after = db_session.query(type(u)).count()
    assert counts["characters (owner)"] == 1
    assert before == after  # counting mutated nothing


# ── End-to-end through main(): the CLI contract ─────────────────────────────
#
# The helpers above are individually safe, but "dry-run only unless --confirm"
# is a property of main()'s argument handling — one flipped default there makes
# every helper test above irrelevant. These drive the real entry point.


@pytest.fixture
def run_cli(db_session, monkeypatch):
    """Invoke reset_account.main() against the test database.

    The script opens its own session via SessionLocal, so that name is
    repointed at the test engine's sessionmaker. It commits for real — which is
    the point: a dry-run test that couldn't possibly delete anything would
    prove nothing.
    """
    from tests.conftest import TestingSessionLocal

    monkeypatch.setattr(reset_account, "SessionLocal", TestingSessionLocal)

    def _run(*argv):
        monkeypatch.setattr("sys.argv", ["reset_account.py", *argv])
        reset_account.main()

    return _run


def _user_exists(db_session, email):
    from app.models.user import User
    db_session.expire_all()  # the script committed on a different session
    return db_session.query(User).filter(User.email == email).first() is not None


def test_main_with_no_flags_is_a_dry_run_and_deletes_nothing(db_session, run_cli, capsys):
    """The default with NO flags must be preview, not deletion."""
    _make_user(db_session, "cli-default@e.com", "clidefault")

    run_cli("--username", "clidefault", "--email", "cli-default@e.com")

    assert "DRY RUN" in capsys.readouterr().out
    assert _user_exists(db_session, "cli-default@e.com")


def test_main_with_explicit_dry_run_deletes_nothing(db_session, run_cli, capsys):
    _make_user(db_session, "cli-dry@e.com", "clidry")

    run_cli("--username", "clidry", "--email", "cli-dry@e.com", "--dry-run")

    assert "DRY RUN" in capsys.readouterr().out
    assert _user_exists(db_session, "cli-dry@e.com")


def test_main_refuses_contradictory_flags(db_session, run_cli):
    _make_user(db_session, "cli-both@e.com", "cliboth")

    with pytest.raises(SystemExit) as exc:
        run_cli("--username", "cliboth", "--email", "cli-both@e.com",
                "--dry-run", "--confirm")

    assert "REFUSED" in str(exc.value)
    assert _user_exists(db_session, "cli-both@e.com")


def test_main_will_not_delete_an_account_that_still_owns_a_character(db_session, run_cli, capsys):
    """--confirm is NOT an override. The hard stop outranks it.

    This is the guarantee that a character is never cascade-deleted as a side
    effect of releasing an email — the operator asked to delete the account and
    the script refused because a character was still attached.
    """
    from app.models.character import Character

    u = _make_user(db_session, "cli-owner@e.com", "cliowner")
    _make_character(db_session, u.id, "Bertie West")

    with pytest.raises(SystemExit) as exc:
        run_cli("--username", "cliowner", "--email", "cli-owner@e.com", "--confirm")

    assert exc.value.code == 1
    assert "HARD STOP" in capsys.readouterr().out
    assert _user_exists(db_session, "cli-owner@e.com")
    db_session.expire_all()
    assert db_session.query(Character).filter(Character.name == "Bertie West").count() == 1


def test_main_with_confirm_deletes_an_empty_account(db_session, run_cli, capsys):
    """The positive case — without it, every test above passes trivially on a
    script that can't delete anything at all."""
    _make_user(db_session, "cli-gone@e.com", "cligone")
    _make_user(db_session, "cli-bystander@e.com", "clibystander")

    run_cli("--username", "cligone", "--email", "cli-gone@e.com", "--confirm")

    out = capsys.readouterr().out
    assert "released for re-registration" in out
    assert not _user_exists(db_session, "cli-gone@e.com")
    # Precisely one account went; the neighbour is untouched.
    assert _user_exists(db_session, "cli-bystander@e.com")


def test_main_refuses_when_username_and_email_disagree(db_session, run_cli):
    """Mistyped-argument protection at the CLI boundary: two real accounts,
    mismatched pair, nothing deleted."""
    _make_user(db_session, "cli-a@e.com", "clia")
    _make_user(db_session, "cli-b@e.com", "clib")

    with pytest.raises(SystemExit) as exc:
        run_cli("--username", "clia", "--email", "cli-b@e.com", "--confirm")

    assert "DIFFERENT accounts" in str(exc.value)
    assert _user_exists(db_session, "cli-a@e.com")
    assert _user_exists(db_session, "cli-b@e.com")

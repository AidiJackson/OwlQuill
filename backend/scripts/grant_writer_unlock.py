"""Grant (or revoke) the paid Writer Unlock on an account.

Ficshon has no payment provider wired yet. Rather than pretend a purchase
happened inside the product, the closed-beta grant path is this operator
script: it writes the same ``users.writer_unlocked_at`` column a real purchase
would, so nothing downstream has to know the difference — and there is no
in-product route that can set it.

Run from the backend/ directory. The account is NEVER hardcoded:

    # Safe preview (default) — reports what WOULD happen, mutates nothing:
    python scripts/grant_writer_unlock.py --email someone@example.com --dry-run

    # Real grant — requires the explicit confirmation flag:
    python scripts/grant_writer_unlock.py --email someone@example.com --confirm

    # Revoke an unlock (e.g. a refund):
    python scripts/grant_writer_unlock.py --email someone@example.com --revoke --confirm

Safety guarantees:
  * --email is required and must resolve to exactly one account.
  * --dry-run is the default; mutation needs --confirm, and passing both is
    rejected as contradictory.
  * Granting is idempotent: an already-unlocked account is reported and left
    with its original unlock timestamp.
  * Characters, images and every other row are untouched — this script only
    ever writes one column on one row.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

# Allow running from backend/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.user import User


def main() -> int:
    parser = argparse.ArgumentParser(description="Grant or revoke the Writer Unlock.")
    parser.add_argument("--email", required=True, help="Account email (exact, case-insensitive).")
    parser.add_argument("--revoke", action="store_true", help="Remove the unlock instead of granting it.")
    parser.add_argument("--dry-run", action="store_true", default=None, help="Preview only (default).")
    parser.add_argument("--confirm", action="store_true", help="Actually write the change.")
    args = parser.parse_args()

    if args.dry_run and args.confirm:
        print("ERROR: --dry-run and --confirm are contradictory.")
        return 2
    mutate = bool(args.confirm)

    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        matches = db.query(User).filter(func.lower(User.email) == email).all()
        if len(matches) != 1:
            print(f"ERROR: {len(matches)} accounts match {email!r}; refusing to act.")
            return 1
        user = matches[0]

        action = "REVOKE" if args.revoke else "GRANT"
        print(f"Account : id={user.id} username={user.username!r} email={user.email}")
        print(f"Current : writer_unlocked_at={user.writer_unlocked_at}")
        print(f"Action  : {action} ({'APPLY' if mutate else 'dry run — no changes'})")

        if args.revoke:
            if user.writer_unlocked_at is None:
                print("Result  : already locked; nothing to do.")
                return 0
            new_value = None
        else:
            if user.writer_unlocked_at is not None:
                print("Result  : already unlocked; leaving the original timestamp.")
                return 0
            new_value = datetime.utcnow()

        if not mutate:
            print(f"Result  : would set writer_unlocked_at={new_value}. Re-run with --confirm.")
            return 0

        user.writer_unlocked_at = new_value
        db.commit()
        print(f"Result  : writer_unlocked_at={new_value}. Done.")
        return 0
    except Exception as exc:  # pragma: no cover - operator-facing safety net
        db.rollback()
        print(f"ERROR: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

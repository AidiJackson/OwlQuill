"""Safely delete a user account so its email can be re-registered.

Purpose-built for releasing a test/seed account back to a clean, zero-character
Wanderer registration — NOT a general moderation tool. It refuses to run unless
the account is already emptied of characters, so it can never cascade-delete a
character (and everything hanging off it) as a side effect.

Run from the backend/ directory. The email is NEVER hardcoded — pass it in:

    # Safe preview (default) — reports what WOULD happen, mutates nothing:
    python scripts/reset_account.py --username AidiJ --email someone@example.com --dry-run

    # Real deletion — requires the explicit confirmation flag:
    python scripts/reset_account.py --username AidiJ --email someone@example.com --confirm

Safety guarantees:
  * --username AND --email are both required and must resolve to the SAME row.
  * Refuses on ambiguous identity (username/email pointing at different rows,
    or either matching more than one account).
  * Refuses while the account still owns ANY character.
  * Refuses if the account is the last remaining admin.
  * Runs in a single transaction; any error rolls the whole thing back.
  * --dry-run is the default; mutation needs --confirm. --dry-run + --confirm
    is rejected as contradictory.
"""
import argparse
import sys
from pathlib import Path

# Allow running from backend/ without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.user import User
from app.models.character import Character


# Tables that reference the user and what deleting the account does to each,
# for the affected-record report. Derived from the live FK delete rules; kept
# here so the dry-run can show counts without guessing.
#   (table label, model attr on User for the relationship count query)
def _gather_counts(db: Session, user_id: int) -> dict[str, int]:
    """Read-only per-table counts of rows attached to this user."""
    from app.models.post import Post
    from app.models.comment import Comment
    from app.models.reaction import Reaction
    from app.models.notification import Notification
    from app.models.realm import RealmMembership
    from app.models.character_image import CharacterImage
    from app.models.password_reset_token import PasswordResetToken

    counts: dict[str, int] = {}

    def c(model, col) -> int:
        return db.query(func.count()).select_from(model).filter(col == user_id).scalar() or 0

    counts["characters (owner)"] = c(Character, Character.owner_id)
    counts["posts"] = c(Post, Post.author_user_id)
    counts["comments"] = c(Comment, Comment.author_user_id)
    counts["reactions"] = c(Reaction, Reaction.user_id)
    counts["notifications"] = c(Notification, Notification.user_id)
    counts["realm_memberships"] = c(RealmMembership, RealmMembership.user_id)
    counts["character_images (owned assets)"] = c(CharacterImage, CharacterImage.user_id)
    counts["password_reset_tokens"] = c(PasswordResetToken, PasswordResetToken.user_id)
    return counts


def _resolve_target(db: Session, username: str, email: str) -> User:
    """Resolve the single account matching BOTH username and email.

    Raises SystemExit with a precise reason on any ambiguity — never guesses,
    never partial-matches, so it can't delete the wrong account.
    """
    email_norm = email.strip().lower()

    by_username = db.query(User).filter(User.username == username).all()
    by_email = db.query(User).filter(func.lower(User.email) == email_norm).all()

    if len(by_username) == 0:
        raise SystemExit(f"REFUSED: no account with username {username!r}.")
    if len(by_username) > 1:
        raise SystemExit(f"REFUSED: {len(by_username)} accounts share username {username!r} — ambiguous.")
    if len(by_email) == 0:
        raise SystemExit(f"REFUSED: no account with email {email_norm!r}.")
    if len(by_email) > 1:
        raise SystemExit(f"REFUSED: {len(by_email)} accounts share email {email_norm!r} — ambiguous.")

    u_user = by_username[0]
    u_email = by_email[0]
    if u_user.id != u_email.id:
        raise SystemExit(
            "REFUSED: username and email belong to DIFFERENT accounts "
            f"(username→id {u_user.id}, email→id {u_email.id}). Refusing to act."
        )
    return u_user


def _check_hard_stops(db: Session, user: User) -> list[str]:
    """Return a list of blocking conditions. Empty list = safe to proceed."""
    stops: list[str] = []

    char_count = (
        db.query(func.count()).select_from(Character)
        .filter(Character.owner_id == user.id).scalar() or 0
    )
    if char_count > 0:
        names = [
            n for (n,) in db.query(Character.name).filter(Character.owner_id == user.id).all()
        ]
        stops.append(
            f"Account still owns {char_count} character(s): {', '.join(names)}. "
            "Delete them first — this script will not cascade-delete characters."
        )

    # Last-admin protection: don't strand the system without an admin.
    is_admin = bool(user.is_admin) or (user.email or "").lower() in settings.get_admin_emails()
    if is_admin:
        other_admins = (
            db.query(func.count()).select_from(User)
            .filter(User.is_admin.is_(True), User.id != user.id).scalar() or 0
        )
        if other_admins == 0:
            stops.append("Account is the last remaining admin — refusing to delete.")

    return stops


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely delete an account to release its email.")
    parser.add_argument("--username", required=True, help="Exact username of the target account.")
    parser.add_argument("--email", required=True, help="Exact email of the target account.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only (default). Mutates nothing.")
    parser.add_argument("--confirm", action="store_true", help="Perform the deletion. Required to mutate.")
    args = parser.parse_args()

    if args.confirm and args.dry_run:
        raise SystemExit("REFUSED: pass either --dry-run or --confirm, not both.")
    mutate = args.confirm  # default (neither flag / --dry-run) => preview only

    db: Session = SessionLocal()
    try:
        user = _resolve_target(db, args.username, args.email)

        print("── Target account ─────────────────────────────")
        print(f"  id            : {user.id}")
        print(f"  username      : {user.username}")
        print(f"  email         : {user.email}")
        print(f"  is_admin      : {user.is_admin}")
        print(f"  is_seeder     : {user.is_seeder}")
        print(f"  active_char   : {user.active_character_id}")
        print()

        stops = _check_hard_stops(db, user)
        if stops:
            print("── HARD STOP — not safe to delete ─────────────")
            for s in stops:
                print(f"  ✗ {s}")
            raise SystemExit(1)

        counts = _gather_counts(db, user.id)
        print("── Records attached to this account ───────────")
        for label, n in counts.items():
            print(f"  {label:<34} {n}")
        print()
        print("  On delete: CASCADE rows are removed; character_images.user_id and")
        print("  post/comment mentions are SET NULL; public attribution stays character-first.")
        print()
        print("  NOTE: character_images.user_id is the asset's OWNING ACCOUNT (Phase 4B1),")
        print("  not 'who generated it'. Its SET NULL is inert today — this script refuses")
        print("  while any character is owned, and an image cannot outlive its character.")
        print("  That stops being true in Phase 4C; the owning FK is settled in 4B2 first.")
        print()

        if not mutate:
            print("DRY RUN — no changes made. Re-run with --confirm to delete.")
            return

        # ── Mutation, single transaction, rolls back on any error ──────────
        deleted_email = user.email
        db.delete(user)
        db.commit()
        print(f"✓ Account id {user.id} deleted. Email {deleted_email!r} is released for re-registration.")

    except SystemExit:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — surface + roll back any failure
        db.rollback()
        raise SystemExit(f"ERROR (rolled back, no changes made): {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

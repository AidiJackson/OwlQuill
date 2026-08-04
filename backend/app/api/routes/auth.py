"""Authentication routes."""
import hashlib
import secrets
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.dependencies import get_current_user
from app.core.admin_seed import auto_join_commons
from app.core.usernames import UsernameError, username_is_taken, validate_username
from app.models.user import User as UserModel
from app.models.password_reset_token import PasswordResetToken
from app.models.invite_code import InviteCode
from app.schemas.user import (
    UserCreate, User, Token, LoginRequest,
    ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest,
)
from app.services.email import send_reset_email

router = APIRouter()

# Rate limiter for auth endpoints (in-memory, per-IP, per-endpoint).
#
# Key: ``get_remote_address`` reads ``request.client.host``. Behind the Replit
# edge that value is *not* the proxy — uvicorn's ProxyHeadersMiddleware rewrites
# it from X-Forwarded-For, taking the right-most entry that is not a trusted
# host (trusted defaults to 127.0.0.1 only). The edge appends the true peer IP
# on the right, so a client-supplied X-Forwarded-For prefix is ignored and
# cannot be used to rotate through fresh buckets. Verified by probing the public
# origin with rotating spoofed X-Forwarded-For values: the limit still fired.
#
# Consequence worth knowing: requests that reach uvicorn without going through
# the edge (the Vite dev proxy forwarding from 127.0.0.1 with no
# X-Forwarded-For) all key to "127.0.0.1" and therefore share one bucket. That
# is a local-development-only path; real browser traffic is keyed per client IP.
limiter = Limiter(key_func=get_remote_address)

# Message shown to a human who has tripped an auth limiter. Deliberately free of
# status codes and of any hint about whether the account exists.
RATE_LIMIT_MESSAGE_LOGIN = (
    "Too many login attempts. Please wait a few minutes and try again."
)
RATE_LIMIT_MESSAGE_GENERIC = (
    "Too many attempts. Please wait a few minutes and try again."
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a readable 429 instead of slowapi's raw default.

    slowapi's stock handler answers ``{"error": "Rate limit exceeded: 5 per 1
    minute"}`` with no ``Retry-After``. The frontend reads ``detail`` and so fell
    back to rendering the bare string "HTTP 429". This handler keeps the limit
    itself untouched and only fixes what the caller is told: a ``detail`` the UI
    can show verbatim, plus ``Retry-After`` in seconds so the client can say how
    long the wait is.
    """
    path = request.url.path
    message = (
        RATE_LIMIT_MESSAGE_LOGIN
        if path.endswith("/auth/login") or path.endswith("/login")
        else RATE_LIMIT_MESSAGE_GENERIC
    )

    headers: dict[str, str] = {}
    current_limit = getattr(request.state, "view_rate_limit", None)
    if current_limit:
        try:
            reset_at, _remaining = limiter.limiter.get_window_stats(
                current_limit[0], *current_limit[1]
            )
            headers["Retry-After"] = str(max(1, int(reset_at - time.time())))
        except Exception:  # pragma: no cover - never fail the error response
            pass

    return JSONResponse(
        {"detail": message}, status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers=headers
    )


def _clear_rate_limit(request: Request) -> None:
    """Release this request's limiter allowance.

    Called after a *successful* login so that a legitimate user who mistyped a
    few times is not left one attempt away from a lockout for the rest of the
    window. Failed attempts always keep their cost, so brute-force protection is
    unchanged: the counter only resets when the correct password was supplied.
    """
    current_limit = getattr(request.state, "view_rate_limit", None)
    if not current_limit:
        return
    try:
        limiter.limiter.clear(current_limit[0], *current_limit[1])
    except Exception:  # pragma: no cover - a failed reset must not fail login
        pass


def _hash_token(token: str) -> str:
    """Hash a reset token with SHA-256 for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)) -> User:
    """Register a new user.

    When BETA_INVITE_REQUIRED=True a valid, enabled, non-exhausted invite code
    must be supplied.  The code's use_count is incremented atomically with the
    user INSERT so no two registrations can consume the same last slot.
    """
    # ── Invite code gate ──────────────────────────────────────────────────────
    invite: InviteCode | None = None
    if settings.BETA_INVITE_REQUIRED:
        raw_code = (user_data.invite_code or "").strip().upper()
        if not raw_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An invite code is required to create an account during closed beta.",
            )
        invite = (
            db.query(InviteCode)
            .filter(InviteCode.code == raw_code, InviteCode.is_enabled.is_(True))
            .first()
        )
        if invite is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired invite code.",
            )
        if invite.max_uses is not None and invite.use_count >= invite.max_uses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invite code has reached its maximum number of uses.",
            )

    # ── Duplicate checks ──────────────────────────────────────────────────────
    # Emails are stored lowercase and compared case-insensitively so no two
    # accounts can differ only by email casing (login lookup is case-insensitive).
    normalized_email = user_data.email.strip().lower()
    existing_user = db.query(UserModel).filter(
        func.lower(UserModel.email) == normalized_email
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Username rules live in app.core.usernames and are shared with the change
    # endpoint — a name that can't be registered can't be renamed into either.
    try:
        username = validate_username(user_data.username)
    except UsernameError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if username_is_taken(db, username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    # ── Create user (+ increment invite use_count in same transaction) ────────
    db_user = UserModel(
        email=normalized_email,
        username=username,
        hashed_password=get_password_hash(user_data.password),
        display_name=user_data.display_name or username
    )
    db.add(db_user)

    if invite is not None:
        invite.use_count += 1
        db.add(invite)

    db.commit()
    db.refresh(db_user)

    # Auto-join The Commons
    auto_join_commons(db_user.id, db)

    return db_user


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(request: Request, login_data: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """Login with email and password via JSON body.

    Security: Credentials must be sent in request body, not query parameters.
    """
    # Case-insensitive email lookup: stored emails are lowercase, but users may
    # type their address with capital letters — that must not fail the lookup.
    normalized_email = login_data.email.strip().lower()
    user = db.query(UserModel).filter(func.lower(UserModel.email) == normalized_email).first()

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Correct credentials: hand the allowance back (see _clear_rate_limit).
    _clear_rate_limit(request)

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me", response_model=User)
def get_me(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Get current user information, including identity context
    (is_admin/is_seeder, active character, character count)."""
    from app.services.identity import build_user_out

    return build_user_out(db, current_user)


# ---------- Password reset ----------


@router.post("/forgot-password", response_model=ForgotPasswordResponse, status_code=status.HTTP_200_OK)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    """Request a password reset email.

    Always returns 200 to avoid leaking whether the email exists.
    In dev mode only, the response includes reset_url for convenience; in
    production the reset link is delivered exclusively by email.
    """
    msg = "If an account exists, a reset link has been sent."
    hint = "Check spam/junk folders. Delivery can take a few minutes."
    # Case-insensitive lookup — must match the login behaviour so a user who can
    # log in with mixed-case email can also reset their password with it.
    user = db.query(UserModel).filter(
        func.lower(UserModel.email) == body.email.strip().lower()
    ).first()

    if not user:
        return ForgotPasswordResponse(message=msg, hint=hint)

    # Generate cryptographically random token
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)

    # Invalidate any existing unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": datetime.utcnow()})

    # Store hashed token
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)
    db.commit()

    # Build reset URL and send email
    frontend_url = settings.get_frontend_url()
    reset_url = f"{frontend_url}/reset-password?token={raw_token}"
    try:
        send_reset_email(user.email, reset_url)
    except Exception:
        pass  # Don't fail the request if email sending fails

    # Return reset_url in the response ONLY in dev mode. In production the link is
    # delivered exclusively by email — never echoed in the API response — so a reset
    # token can never be harvested via an unauthenticated request (S24D FIX 1).
    if settings.is_dev_mode():
        return ForgotPasswordResponse(message=msg, hint=hint, reset_url=reset_url)

    return ForgotPasswordResponse(message=msg, hint=hint)


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Reset password using a valid token."""
    token_hash = _hash_token(body.token)

    reset_record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
    ).first()

    if not reset_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    if reset_record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset token has already been used.",
        )

    if reset_record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset token has expired.",
        )

    # Update password
    user = db.query(UserModel).filter(UserModel.id == reset_record.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    user.hashed_password = get_password_hash(body.new_password)

    # Mark token as used
    reset_record.used_at = datetime.utcnow()

    # Invalidate all other unused tokens for this user
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != reset_record.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": datetime.utcnow()})

    db.commit()

    return {"message": "Password has been reset successfully."}

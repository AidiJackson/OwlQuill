"""User schemas."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)


class UserCreate(UserBase):
    """User creation schema."""
    password: str = Field(..., min_length=8)
    display_name: Optional[str] = None
    invite_code: Optional[str] = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    """User update schema.

    Deliberately excludes ``username`` (see :class:`UsernameUpdate`) and
    ``email`` — the public identity and the login identity each change through
    their own validated, rate-limited endpoint, never as a side effect of a
    profile save.
    """
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None


class UsernameUpdate(BaseModel):
    """Body for changing the account's public (Wanderer) username.

    Only the length bounds are declared here; the full rule (character set,
    reserved names) lives in ``app.core.usernames`` so registration and this
    endpoint cannot drift apart.
    """
    username: str = Field(..., min_length=1, max_length=100)


class UserInDB(UserBase):
    """User in database schema."""
    id: int
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    next_character_allowed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActiveCharacterSummary(BaseModel):
    """Minimal summary of the account's active character (its visible identity)."""
    id: int
    name: str
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class User(UserInDB):
    """Authenticated user schema (never shown publicly — accounts are private
    infrastructure; characters are the social identities)."""
    is_admin: bool = False
    is_seeder: bool = False
    # Explicitly selected active character, or the single-character fallback.
    active_character: Optional[ActiveCharacterSummary] = None
    # Number of characters the account owns. 0 (for non-founders) = Wanderer:
    # browse/react/comment only, no creator tools.
    character_count: int = 0
    # True once the paid Writer Unlock is held. Founders/admins/seeders are
    # exempt rather than unlocked, so this stays False for them — read
    # `can_create_character` for the "may I start the flow" answer.
    writer_unlocked: bool = False
    # Authoritative-mirror of app.core.entitlements.can_create_character, so the
    # client never has to reconstruct the rule from flags.
    can_create_character: bool = False
    # When the account may next change its public username (cooldown), or None.
    username_change_available_at: Optional[datetime] = None
    # When the account joined the Writer waitlist, or None if it has not.
    # Interest only — it grants nothing, and `writer_unlocked` stays False.
    writer_waitlist_joined_at: Optional[datetime] = None


class LoginRequest(BaseModel):
    """Login request schema."""
    email: EmailStr
    password: str = Field(..., min_length=1)


class Token(BaseModel):
    """Token response schema."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Token payload schema."""
    user_id: Optional[int] = None

# --- Profile / Public schemas ---

class PublicUserProfile(BaseModel):
    """Public-facing user profile (no email)."""
    id: int
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Password reset schemas ---

class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Forgot password response schema."""
    ok: bool = True
    message: str
    hint: Optional[str] = None
    reset_url: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

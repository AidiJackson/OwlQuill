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


class UserUpdate(BaseModel):
    """User update schema."""
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None


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


class User(UserInDB):
    """Public user schema."""
    is_admin: bool = False


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


class ProfileTimelineItem(BaseModel):
    """Mixed timeline item for a user's profile."""
    type: str  # "post" | "scene"
    created_at: datetime
    realm_id: Optional[int] = None
    realm_name: Optional[str] = None
    payload: dict


# --- Password reset schemas ---

class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

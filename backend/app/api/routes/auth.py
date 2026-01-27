"""Authentication routes."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.dependencies import get_current_user
from app.models.user import User as UserModel
from app.schemas.user import UserCreate, User, Token, LoginRequest

router = APIRouter()

# Rate limiter for auth endpoints (in-memory, per-IP)
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=User, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)) -> User:
    """Register a new user."""
    # Check if email exists
    existing_user = db.query(UserModel).filter(UserModel.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Check if username exists
    existing_user = db.query(UserModel).filter(UserModel.username == user_data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    # Create new user
    db_user = UserModel(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        display_name=user_data.display_name or user_data.username
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=Token)
@limiter.limit(settings.RATE_LIMIT_AUTH)
def login(request: Request, login_data: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """Login with email and password via JSON body.

    Security: Credentials must be sent in request body, not query parameters.
    """
    user = db.query(UserModel).filter(UserModel.email == login_data.email).first()

    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token)


@router.get("/me", response_model=User)
def get_me(current_user: UserModel = Depends(get_current_user)) -> User:
    """Get current user information."""
    return current_user

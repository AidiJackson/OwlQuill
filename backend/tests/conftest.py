"""Pytest configuration and fixtures."""
import os

# Set test environment variables BEFORE any app imports
# This ensures Settings() sees these values when instantiated at import time
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Fix bcrypt/passlib compatibility issue (bcrypt 4.0+ requires explicit truncation)
# Must be done before passlib is imported
import bcrypt
_original_hashpw = bcrypt.hashpw
def _patched_hashpw(password, salt):
    # Truncate password to 72 bytes as required by bcrypt
    if isinstance(password, bytes) and len(password) > 72:
        password = password[:72]
    return _original_hashpw(password, salt)
bcrypt.hashpw = _patched_hashpw

from app.core.database import Base, get_db
from app.main import app
from app.api.routes.auth import limiter

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client."""
    app.dependency_overrides[get_db] = override_get_db
    # Disable rate limiting during tests by enabling the limiter's enabled flag to False
    limiter.enabled = False
    with TestClient(app) as test_client:
        yield test_client
    # Re-enable rate limiting after tests
    limiter.enabled = True
    app.dependency_overrides.clear()

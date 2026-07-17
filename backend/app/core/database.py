"""Database configuration and session management."""
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings

# Create engine
# pool_pre_ping: validate pooled connections before use. On autoscale
# deployments the container idles between requests and the Postgres server
# closes idle SSL connections; without the pre-ping the first request after
# idle reuses a dead connection and fails with
# "psycopg2.OperationalError: SSL connection has been closed unexpectedly".
# pool_recycle proactively retires connections older than 5 minutes.
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

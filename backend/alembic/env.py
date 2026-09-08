"""Alembic environment configuration."""
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.core.config import settings
from app.core.database import Base
from app.core.db_target import require_migration_authorisation
from app.models import *  # noqa: F401, F403 - Import all models for autogenerate

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_url() -> str:
    """Get database URL from settings."""
    return settings.DATABASE_URL


def _require_authorised_target(operation: str) -> None:
    """Refuse a migration against a non-DEV target without acknowledgement.

    WHAT THIS CLOSES. ``get_url()`` returns ``settings.DATABASE_URL`` verbatim,
    so ``alembic upgrade head`` migrated whichever database the environment
    named — no classification, no confirmation, and nothing recorded to say the
    operator meant that one. An exported ``DATABASE_URL`` was sufficient
    authority to alter a production schema.

    Applied to BOTH the offline and online paths. Offline mode emits SQL rather
    than executing it, which is harmless in itself — but it is harmless only
    because of what the operator then does with the script, and a guard that
    covered one path and not the other would invite "just use ``--sql``" as the
    way around it. Both are mutation-INTENT, so both ask.

    RAISES rather than skipping. A migration that silently did not run leaves
    the operator believing the schema moved, which is worse than a refusal.

    See ``app.core.db_target``: the acknowledgement variable and phrase are
    deliberately DIFFERENT from the FastAPI startup bootstrap's, so authorising
    a production migration does not also authorise startup seeding, and vice
    versa. No credential ever appears in the refusal.
    """
    require_migration_authorisation(get_url(), operation=operation)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    _require_authorised_target("to generate migration SQL (offline mode)")

    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    _require_authorised_target("to run migrations")

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""Alembic environment configuration.

Reads DATABASE_URL from src.shared.config and uses the shared SQLAlchemy
Base.metadata as the migration target. Run `alembic upgrade head` to apply
migrations. For existing databases, first run `alembic stamp head` to
mark the current state as the baseline.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `src.` imports work in Alembic scripts
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.config import settings  # noqa: E402
from src.shared.database import Base  # noqa: E402

# Import all model modules so Base.metadata has every table registered
# before autogenerate / migration runs.
from src.shared import database as _db_module  # noqa: E402, F401
from src.memory import models as _memory_models  # noqa: E402, F401
from src.memory import problem_memory as _problem_memory  # noqa: E402, F401
from src.scheduler import models as _scheduler_models  # noqa: E402, F401

config = context.config

# Override sqlalchemy.url from app settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

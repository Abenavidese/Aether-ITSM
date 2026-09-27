"""
Alembic environment: same engine and models as the app, so a migration can
never target a different database than the one the API talks to.
"""
from logging.config import fileConfig

from alembic import context

from src.db import models  # noqa: F401 — registers every table on Base.metadata
from src.db.database import Base, engine
from src.db.migrate import include_object

config = context.config
# The app configures its own logging; only take alembic.ini's when run from the CLI.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_object=include_object,
        # SQLite can't ALTER/DROP columns in place; batch mode recreates the
        # table. Same migration file then runs on SQLite (dev/tests) and Postgres.
        render_as_batch=True,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=str(engine.url), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

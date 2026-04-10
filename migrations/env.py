import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Import all models so they register with Base.metadata
from app.database import Base
from app.models import Device, Credential, Backup, JobRun, Schedule, Destination, Group

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow DATABASE_URL env var (or .env file) to override alembic.ini
_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    from dotenv import load_dotenv
    load_dotenv()
    _db_url = os.environ.get("DATABASE_URL")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

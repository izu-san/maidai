from __future__ import annotations
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if os.environ.get("RINO_LIFE_DATABASE_URL"):
    database_url = os.environ["RINO_LIFE_DATABASE_URL"]
    # Application code uses psycopg directly and therefore keeps a standard
    # PostgreSQL DSN.  SQLAlchemy requires an explicit psycopg dialect here.
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    config.set_main_option("sqlalchemy.url", database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)

def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

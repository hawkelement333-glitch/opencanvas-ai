from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

from opencanvas_api.core.config import AppMode, DatabaseRole, get_settings
from opencanvas_api.db.migrations import run_guarded_postgresql_migration
from opencanvas_api.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if not config.get_main_option("sqlalchemy.url"):
    settings = get_settings()
    settings.require_database_role(DatabaseRole.MIGRATION)
    if settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION} and not config.attributes.get(
        "managed_migration"
    ):
        raise RuntimeError("deployed migrations require the guarded migration runner")
    database_url = settings.database_url_value
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    def migrate() -> None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

    run_guarded_postgresql_migration(
        connection,
        expected_current=config.attributes.get("expected_current_revision"),
        expected_target=config.attributes.get("expected_target_revision"),
        migrate=migrate,
    )


async def run_async_migrations() -> None:
    url = make_url(config.get_main_option("sqlalchemy.url"))
    connect_args: dict[str, object] = {}
    if url.drivername == "postgresql+asyncpg":
        connect_args = {
            "timeout": get_settings().database_connect_timeout_seconds,
            "server_settings": {
                "application_name": "solarplexus-mobius-migration",
                "statement_timeout": "0",
                "lock_timeout": str(get_settings().database_lock_timeout_ms),
                "idle_in_transaction_session_timeout": str(
                    get_settings().database_idle_transaction_timeout_ms
                ),
            },
        }
        if get_settings().database_tls_mode != "disable":
            connect_args["ssl"] = get_settings().database_tls_mode
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

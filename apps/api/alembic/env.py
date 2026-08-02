from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from opencanvas_api.core.config import AppMode, DatabaseRole, get_settings
from opencanvas_api.db.migrations import run_guarded_postgresql_migration
from opencanvas_api.db.models import Base
from opencanvas_api.db.session import Database

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
    database_url_option = config.get_main_option("sqlalchemy.url")
    if not database_url_option:
        raise RuntimeError("Alembic database URL is unavailable")
    database_url = database_url_option.replace("%%", "%")
    if config.attributes.get("managed_migration"):
        settings = get_settings()
        settings.require_database_role(DatabaseRole.MIGRATION)
        if database_url != settings.database_url_value:
            raise RuntimeError("managed migration database URL differs from runtime settings")
        database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
        engine = database.engine
    else:
        database = None
        engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    if database is None:
        await engine.dispose()
    else:
        await database.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

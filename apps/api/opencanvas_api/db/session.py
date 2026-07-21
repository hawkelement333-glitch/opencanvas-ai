from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        pool_timeout_seconds: float = 15.0,
    ) -> None:
        options: dict[str, object] = {"pool_pre_ping": True}
        if database_url.startswith("postgresql"):
            options.update(pool_size=pool_size, pool_timeout=pool_timeout_seconds)
        self.engine = create_async_engine(database_url, **options)
        if database_url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


AsyncSessionFactory = async_sessionmaker[AsyncSession]

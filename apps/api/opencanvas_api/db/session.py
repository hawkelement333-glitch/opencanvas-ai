from __future__ import annotations

import time
from typing import Any

import asyncpg
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.services.managed_identity import ManagedIdentityTokenProvider
from opencanvas_api.services.operational_observations import metric


class MeasuredAsyncQueuePool(AsyncAdaptedQueuePool):
    """Measure the actual pool acquisition including contention/connection creation."""

    def _do_get(self) -> Any:
        started = time.perf_counter()
        outcome = "success"
        try:
            return super()._do_get()
        except PoolTimeoutError:
            outcome = "unavailable"
            metric("mobius.database.timeouts", 1, "database", outcome)
            raise
        except BaseException:
            outcome = "server_error"
            raise
        finally:
            metric(
                "mobius.database.pool.acquire",
                (time.perf_counter() - started) * 1000,
                "database",
                outcome,
            )


class ObservedSession(Session):
    """Session events report actual completed transactions, never SQL contents."""


def _transaction_started(session: Session, transaction: Any, connection: Any) -> None:
    if not transaction.nested:
        session.info["operational_transaction_started"] = time.perf_counter()


def _transaction_finished(session: Session, outcome: str) -> None:
    if session.in_nested_transaction():
        return
    if session.info.pop("operational_transaction_started", None) is not None:
        metric("mobius.database.transactions", 1, "database", outcome)


def _transaction_committed(session: Session) -> None:
    _transaction_finished(session, "success")


def _transaction_rolled_back(session: Session) -> None:
    _transaction_finished(session, "server_error")


event.listen(ObservedSession, "after_begin", _transaction_started)
event.listen(ObservedSession, "after_commit", _transaction_committed)
event.listen(ObservedSession, "after_rollback", _transaction_rolled_back)


_POSTGRES_ENTRA_AUDIENCE = "https://ossrdbms-aad.database.windows.net"


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        pool_timeout_seconds: float = 15.0,
        max_overflow: int = 0,
        pool_recycle_seconds: int = 1_800,
        connect_timeout_seconds: float = 10.0,
        statement_timeout_ms: int = 30_000,
        lock_timeout_ms: int = 5_000,
        idle_transaction_timeout_ms: int = 30_000,
        tls_mode: str = "disable",
        application_name: str = "solarplexus-mobius",
        managed_identity: ManagedIdentityTokenProvider | None = None,
        pooled: bool = True,
    ) -> None:
        options: dict[str, object] = {"pool_pre_ping": True}
        if database_url.startswith("postgresql"):
            connect_args: dict[str, object] = {
                "timeout": connect_timeout_seconds,
                "server_settings": {
                    "application_name": application_name,
                    "statement_timeout": str(statement_timeout_ms),
                    "lock_timeout": str(lock_timeout_ms),
                    "idle_in_transaction_session_timeout": str(idle_transaction_timeout_ms),
                },
            }
            if tls_mode != "disable":
                connect_args["ssl"] = tls_mode
            options.update(isolation_level="READ COMMITTED", connect_args=connect_args)
            if pooled:
                options.update(
                    poolclass=MeasuredAsyncQueuePool,
                    pool_size=pool_size,
                    max_overflow=max_overflow,
                    pool_timeout=pool_timeout_seconds,
                    pool_recycle=pool_recycle_seconds,
                )
            else:
                options["poolclass"] = NullPool
            if managed_identity is not None:
                url = make_url(database_url)
                identity_connect_args = dict(connect_args)
                identity_connect_args.pop("ssl", None)

                async def create_connection() -> asyncpg.Connection:
                    return await asyncpg.connect(
                        user=url.username,
                        password=await managed_identity.token(),
                        database=url.database,
                        host=url.host,
                        port=url.port or 5432,
                        ssl=tls_mode,
                        **identity_connect_args,
                    )

                options.pop("connect_args", None)
                options["async_creator"] = create_connection
        self.engine = create_async_engine(database_url, **options)
        if database_url.startswith("sqlite"):
            event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        if database_url.startswith("postgresql"):
            event.listen(self.engine.sync_engine, "handle_error", _database_error)
            if pooled:
                capacity = pool_size + max_overflow

                def checkout(*_: Any) -> None:
                    pool = self.engine.sync_engine.pool
                    if (
                        isinstance(pool, MeasuredAsyncQueuePool)
                        and capacity > 0
                        and max_overflow >= 0
                    ):
                        metric(
                            "mobius.capacity.utilization", pool.checkedout() / capacity, "database"
                        )

                event.listen(self.engine.sync_engine, "checkout", checkout)
        self.sessions = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            sync_session_class=ObservedSession,
        )

    @classmethod
    def from_settings(cls, settings: Settings, *, expected_role: DatabaseRole) -> Database:
        settings.require_database_role(expected_role)
        managed_identity = None
        if settings.database_auth_mode == "entra":
            managed_identity = ManagedIdentityTokenProvider(
                endpoint=settings.database_managed_identity_endpoint or "",
                resource=_POSTGRES_ENTRA_AUDIENCE,
                client_id=settings.database_managed_identity_client_id or "",
                identity_header=settings.database_managed_identity_header,
                timeout_seconds=settings.database_connect_timeout_seconds,
            )
        return cls(
            settings.database_url_value,
            pool_size=settings.database_pool_size,
            pool_timeout_seconds=settings.database_pool_timeout_seconds,
            max_overflow=settings.database_max_overflow,
            pool_recycle_seconds=settings.database_pool_recycle_seconds,
            connect_timeout_seconds=settings.database_connect_timeout_seconds,
            statement_timeout_ms=settings.database_statement_timeout_ms,
            lock_timeout_ms=settings.database_lock_timeout_ms,
            idle_transaction_timeout_ms=settings.database_idle_transaction_timeout_ms,
            tls_mode=settings.database_tls_mode,
            application_name=f"{settings.database_application_name}-{expected_role.value}",
            managed_identity=managed_identity,
            pooled=expected_role in {DatabaseRole.API, DatabaseRole.WORKER},
        )

    async def dispose(self) -> None:
        await self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


AsyncSessionFactory = async_sessionmaker[AsyncSession]


def _database_error(context: Any) -> None:
    original = context.original_exception
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if state in {"57014", "55P03"} or isinstance(original, TimeoutError):
        metric("mobius.database.timeouts", 1, "database", "unavailable")

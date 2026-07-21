from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from sqlalchemy import URL, make_url

from alembic import command

TEST_URL_ENV = "OPENCANVAS_POSTGRES_TEST_URL"
_SAFE_DATABASE = re.compile(r"(^|[_-])(test|testing|ci)([_-]|$)", re.IGNORECASE)
_FORBIDDEN_DATABASE = re.compile(
    r"prod|production|stage|staging|develop|development", re.IGNORECASE
)
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def validate_postgres_test_url(raw_url: str, *, ci: bool = False) -> URL:
    try:
        url = make_url(raw_url)
    except Exception as exc:
        raise ValueError(f"{TEST_URL_ENV} is not a valid SQLAlchemy URL") from exc
    if url.drivername != "postgresql+asyncpg":
        raise ValueError(f"{TEST_URL_ENV} must use postgresql+asyncpg")
    if not url.database or not _SAFE_DATABASE.search(url.database):
        raise ValueError(f"{TEST_URL_ENV} database name must contain a test or ci segment")
    if _FORBIDDEN_DATABASE.search(url.database):
        raise ValueError(f"{TEST_URL_ENV} must not name development, staging, or production")
    if not url.host:
        raise ValueError(f"{TEST_URL_ENV} must specify a host")
    if not ci and url.host.lower() not in _LOCAL_HOSTS:
        raise ValueError(f"{TEST_URL_ENV} must use a loopback host outside CI")
    return url


def disposable_postgres_database() -> Iterator[str]:
    raw_url = os.getenv(TEST_URL_ENV)
    if raw_url is None:
        pytest.skip(
            f"PostgreSQL validation NOT RUN: set {TEST_URL_ENV} to an explicit safe test URL"
        )
    try:
        admin_url = validate_postgres_test_url(raw_url, ci=os.getenv("CI") == "true")
    except ValueError as exc:
        pytest.fail(str(exc), pytrace=False)
    database_name = f"opencanvas_agent_test_{uuid.uuid4().hex}"
    database_url = admin_url.set(database=database_name)
    try:
        asyncio.run(_create_database(admin_url, database_name))
    except Exception as exc:
        pytest.fail(f"PostgreSQL validation unavailable: {exc}", pytrace=False)

    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, "head")
        yield database_url.render_as_string(hide_password=False)
    finally:
        asyncio.run(_drop_database(admin_url, database_name))


async def _create_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(_asyncpg_dsn(admin_url))
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(_asyncpg_dsn(admin_url))
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await connection.close()


def _asyncpg_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)

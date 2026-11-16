from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

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
RESTART_CONTAINER_ENV = "OPENCANVAS_POSTGRES_RESTART_CONTAINER"


class _RedactedPostgresTestUrl(str):
    def __repr__(self) -> str:
        return "<redacted PostgreSQL test URL>"


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


def restart_disposable_postgres(database_url: str) -> None:
    """Restart only PostgreSQL inside an explicitly selected disposable local container."""
    if os.getenv("OPENCANVAS_RUN_POSTGRES_RESTART_TEST") != "1":
        raise ValueError("PostgreSQL restart requires explicit opt-in")
    url = validate_postgres_test_url(database_url)
    if not re.fullmatch(r"opencanvas_agent_test_[0-9a-f]{32}", url.database or ""):
        raise ValueError("Restart requires a database created by the disposable test fixture")
    container = os.getenv(RESTART_CONTAINER_ENV, "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]+", container):
        raise ValueError(f"Set {RESTART_CONTAINER_ENV} to the disposable container name")

    def docker(*arguments: str, timeout: int = 30) -> str:
        return subprocess.run(
            ["docker", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        ).stdout.strip()

    if os.getenv("DOCKER_HOST") and os.getenv("DOCKER_CONTEXT"):
        raise ValueError("Restart refuses ambiguous Docker host/context overrides")
    endpoint = os.getenv("DOCKER_HOST")
    if not endpoint:
        contexts = json.loads(docker("context", "inspect"))
        endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
        raise ValueError("Restart requires a local Docker socket or named pipe")
    inspected = json.loads(docker("inspect", "--type", "container", container))
    if len(inspected) != 1:
        raise ValueError("Restart requires exactly one inspected container")
    target = inspected[0]
    container_id = target.get("Id", "")
    if not re.fullmatch(r"[0-9a-f]{64}", container_id) or not target["State"]["Running"]:
        raise ValueError("Restart target must be a running container with an immutable ID")
    config = target["Config"]
    if (config.get("Labels") or {}).get("opencanvas.test-postgres") != "1":
        raise ValueError("Restart target lacks the disposable PostgreSQL test label")
    environment = dict(value.split("=", 1) for value in config.get("Env", []) if "=" in value)
    admin_database = environment.get("POSTGRES_DB", "")
    validate_postgres_test_url(
        url.set(database=admin_database).render_as_string(hide_password=False)
    )
    pgdata = environment.get("PGDATA", "")
    data_path = PurePosixPath(pgdata)
    if not data_path.is_absolute() or ".." in data_path.parts:
        raise ValueError("Restart requires an explicit absolute PGDATA path")
    tmpfs = target["HostConfig"].get("Tmpfs") or {}
    if not any(data_path.is_relative_to(PurePosixPath(mount)) for mount in tmpfs):
        raise ValueError("Restart requires disposable tmpfs-backed PGDATA")
    for mount in target.get("Mounts", []):
        destination = PurePosixPath(mount["Destination"])
        if mount["Type"] != "tmpfs" and (
            destination.is_relative_to(data_path) or data_path.is_relative_to(destination)
        ):
            raise ValueError("Restart refuses persistent mounts overlapping PGDATA")
    bindings = target["NetworkSettings"]["Ports"].get("5432/tcp") or []
    host = "127.0.0.1" if url.host == "localhost" else url.host
    if len(bindings) != 1 or bindings[0] != {"HostIp": host, "HostPort": str(url.port)}:
        raise ValueError("Restart container port binding must match the exact loopback test URL")
    if docker("exec", container_id, "cat", "/proc/1/comm") in {"postgres", "postmaster"}:
        raise ValueError("Restart needs a persistent PID 1 supervisor to preserve tmpfs PGDATA")
    docker(
        "exec",
        "--user",
        "postgres",
        container_id,
        "pg_ctl",
        "-D",
        pgdata,
        "restart",
        "-m",
        "fast",
        "-w",
        "-t",
        "60",
        "-l",
        "/tmp/opencanvas-test-postgres-restart.log",
        timeout=75,
    )


def disposable_postgres_database(*, upgrade_to: str | None = "head") -> Iterator[str]:
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
    except Exception:
        pytest.fail(
            "PostgreSQL validation unavailable; inspect protected diagnostics", pytrace=False
        )

    api_directory = Path(__file__).resolve().parents[1]
    config = Config(api_directory / "alembic.ini")
    config.set_main_option("script_location", str(api_directory / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.render_as_string(hide_password=False))
    try:
        if upgrade_to is not None:
            command.upgrade(config, upgrade_to)
        yield _RedactedPostgresTestUrl(database_url.render_as_string(hide_password=False))
    finally:
        try:
            asyncio.run(_drop_database(admin_url, database_name))
        except Exception:
            pytest.fail(
                "Disposable PostgreSQL database cleanup failed; inspect protected diagnostics",
                pytrace=False,
            )


async def _create_database(admin_url: URL, database_name: str) -> None:
    connection = await asyncpg.connect(_asyncpg_dsn(admin_url))
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(admin_url: URL, database_name: str) -> None:
    for attempt in range(20):
        try:
            connection = await asyncpg.connect(_asyncpg_dsn(admin_url))
            try:
                await connection.execute(
                    "SELECT pg_terminate_backend(activity.pid) "
                    "FROM pg_stat_activity AS activity "
                    "JOIN pg_roles AS role ON role.rolname = activity.usename "
                    "WHERE activity.datname = $1 "
                    "AND activity.pid <> pg_backend_pid() "
                    "AND activity.backend_type = 'client backend' "
                    "AND role.rolsuper = FALSE",
                    database_name,
                )
                await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
                return
            finally:
                await connection.close()
        except (
            asyncpg.CannotConnectNowError,
            asyncpg.ObjectInUseError,
            asyncpg.PostgresConnectionError,
            OSError,
        ):
            if attempt == 19:
                raise
            await asyncio.sleep(0.25)


def _asyncpg_dsn(url: URL) -> str:
    return url.set(drivername="postgresql").render_as_string(hide_password=False)

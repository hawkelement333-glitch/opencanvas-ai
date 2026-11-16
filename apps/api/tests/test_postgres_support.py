from __future__ import annotations

import json
import sqlite3
import subprocess

import pytest
from sqlalchemy.engine import URL

from tests.postgres_support import (
    _drop_database,
    _RedactedPostgresTestUrl,
    restart_disposable_postgres,
    validate_postgres_test_url,
)


def _postgres_url(*, host: str, database: str) -> str:
    return URL.create(
        drivername="postgresql+asyncpg",
        username="opencanvas",
        password="placeholder",
        host=host,
        port=55432,
        database=database,
    ).render_as_string(hide_password=False)


@pytest.mark.parametrize(
    "url",
    [
        URL.create(drivername="sqlite+aiosqlite", database=":memory:").render_as_string(),
        _postgres_url(host="localhost", database="opencanvas"),
        _postgres_url(host="localhost", database="opencanvas_production_test"),
        _postgres_url(host="db.example.test", database="opencanvas_test"),
    ],
)
def test_postgres_test_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_postgres_test_url(url)


def test_postgres_test_url_accepts_explicit_loopback_test_database() -> None:
    result = validate_postgres_test_url(
        _postgres_url(host="127.0.0.1", database="opencanvas_test_admin")
    )
    assert result.database == "opencanvas_test_admin"


def test_postgres_test_url_repr_never_exposes_connection_details() -> None:
    value = _RedactedPostgresTestUrl(
        _postgres_url(host="127.0.0.1", database="opencanvas_test_admin")
    )

    assert repr(value) == "<redacted PostgreSQL test URL>"
    assert "placeholder" not in repr(value)
    assert "127.0.0.1" not in repr(value)


@pytest.mark.parametrize(
    "unsafe",
    [
        "no_opt_in",
        "no_container",
        "non_fixture_database",
        "remote_docker",
        "ambiguous_docker",
        "missing_label",
        "persistent_pgdata",
        "overlapping_mount",
        "unsafe_admin_database",
        "wrong_port",
        "public_binding",
        "postgres_pid_one",
    ],
)
def test_disposable_restart_refuses_unsafe_targets(
    monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    calls = _restart_fixture(monkeypatch, unsafe=unsafe)
    database = (
        "ordinary_test" if unsafe == "non_fixture_database" else "opencanvas_agent_test_" + "a" * 32
    )
    with pytest.raises(ValueError):
        restart_disposable_postgres(_postgres_url(host="127.0.0.1", database=database))
    assert not any("pg_ctl" in call for call in calls)


def test_disposable_restart_targets_exact_supervised_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _restart_fixture(monkeypatch)
    restart_disposable_postgres(
        _postgres_url(host="127.0.0.1", database="opencanvas_agent_test_" + "a" * 32)
    )
    assert calls[-1] == [
        "docker",
        "exec",
        "--user",
        "postgres",
        "b" * 64,
        "pg_ctl",
        "-D",
        "/var/lib/postgresql/data",
        "restart",
        "-m",
        "fast",
        "-w",
        "-t",
        "60",
        "-l",
        "/tmp/opencanvas-test-postgres-restart.log",
    ]
    assert not any("wsl.exe" in call or call[:2] == ["docker", "restart"] for call in calls)


def _restart_fixture(monkeypatch: pytest.MonkeyPatch, *, unsafe: str = "") -> list[list[str]]:
    monkeypatch.setenv("OPENCANVAS_RUN_POSTGRES_RESTART_TEST", "1")
    monkeypatch.setenv("OPENCANVAS_POSTGRES_RESTART_CONTAINER", "opencanvas-test-restart")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    if unsafe == "no_opt_in":
        monkeypatch.delenv("OPENCANVAS_RUN_POSTGRES_RESTART_TEST")
    if unsafe == "no_container":
        monkeypatch.delenv("OPENCANVAS_POSTGRES_RESTART_CONTAINER")
    if unsafe == "ambiguous_docker":
        monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
        monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    target = {
        "Id": "b" * 64,
        "State": {"Running": True},
        "Config": {
            "Labels": {} if unsafe == "missing_label" else {"opencanvas.test-postgres": "1"},
            "Env": [
                "PGDATA=/var/lib/postgresql/data",
                "POSTGRES_DB="
                + (
                    "production_test"
                    if unsafe == "unsafe_admin_database"
                    else "opencanvas_test_admin"
                ),
            ],
        },
        "HostConfig": {
            "Tmpfs": {}
            if unsafe == "persistent_pgdata"
            else {"/var/lib/postgresql/data": "rw,size=512m"}
        },
        "Mounts": [{"Type": "bind", "Destination": "/var/lib/postgresql/data"}]
        if unsafe == "overlapping_mount"
        else [],
        "NetworkSettings": {
            "Ports": {
                "5432/tcp": [
                    {
                        "HostIp": "0.0.0.0" if unsafe == "public_binding" else "127.0.0.1",
                        "HostPort": "55433" if unsafe == "wrong_port" else "55432",
                    }
                ]
            }
        },
    }
    calls: list[list[str]] = []

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        assert kwargs["check"] is True
        assert "shell" not in kwargs
        if arguments[1:3] == ["context", "inspect"]:
            endpoint = (
                "ssh://remote" if unsafe == "remote_docker" else "unix:///var/run/docker.sock"
            )
            output = json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}])
        elif arguments[1] == "inspect":
            output = json.dumps([target])
        elif arguments[-2:] == ["cat", "/proc/1/comm"]:
            output = "postgres" if unsafe == "postgres_pid_one" else "bash"
        else:
            output = "server started"
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr("tests.postgres_support.subprocess.run", run)
    return calls


@pytest.mark.asyncio
async def test_disposable_cleanup_terminates_only_scoped_non_superuser_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = "opencanvas_agent_test_" + "a" * 32
    catalog = sqlite3.connect(":memory:")
    catalog.execute("CREATE TABLE pg_roles (rolname TEXT, rolsuper BOOLEAN)")
    catalog.execute(
        "CREATE TABLE pg_stat_activity (datname TEXT, pid INTEGER, usename TEXT, backend_type TEXT)"
    )
    catalog.executemany(
        "INSERT INTO pg_roles VALUES (?, ?)", [("test_role", False), ("admin", True)]
    )
    catalog.executemany(
        "INSERT INTO pg_stat_activity VALUES (?, ?, ?, ?)",
        [
            (database, 100, "test_role", "client backend"),
            (database, 101, "test_role", "client backend"),
            (database, 102, None, "autovacuum worker"),
            (database, 103, "admin", "client backend"),
            (database, 104, "test_role", "parallel worker"),
            ("unrelated_test", 105, "test_role", "client backend"),
            (database, 106, "unknown_role", "client backend"),
        ],
    )
    terminated: list[int] = []
    dropped: list[str] = []
    closed: list[bool] = []
    catalog.create_function("pg_backend_pid", 0, lambda: 100)
    catalog.create_function("pg_terminate_backend", 1, lambda pid: terminated.append(pid) or True)

    class Connection:
        async def execute(self, statement: str, *arguments: object) -> str:
            if statement.startswith("DROP DATABASE"):
                dropped.append(statement)
            else:
                catalog.execute(
                    statement, {str(index + 1): value for index, value in enumerate(arguments)}
                ).fetchall()
            return "OK"

        async def close(self) -> None:
            closed.append(True)

    async def connect(_dsn: str) -> Connection:
        return Connection()

    monkeypatch.setattr("tests.postgres_support.asyncpg.connect", connect)
    try:
        await _drop_database(
            validate_postgres_test_url(
                _postgres_url(host="127.0.0.1", database="opencanvas_test_admin")
            ),
            database,
        )
    finally:
        catalog.close()
    assert terminated == [101]
    assert dropped == [f'DROP DATABASE IF EXISTS "{database}"']
    assert closed == [True]

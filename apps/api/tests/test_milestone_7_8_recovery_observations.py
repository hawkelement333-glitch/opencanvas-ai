from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Never, cast

import asyncpg
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.pool import NullPool
from test_milestone_7_8_campaign_enablement import _manifest, _object_id, _set_manifest

from opencanvas_api.core.config import DatabaseRole
from opencanvas_api.db.principal_manifest import CURRENT_PRINCIPAL_ID_ENV, load_principal_manifest
from opencanvas_api.db.session import Database
from opencanvas_api.services import jobs
from opencanvas_api.services.jobs import DocumentWorker
from scripts import credential_recovery_probe as credential
from scripts import managed_postgres_evidence as evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["exact", "wrapped-exact", "timeout", "transport", "token",
                                    "wrong-role", "wrong-state", "not-fatal", "connected"])
async def test_only_exact_postgresql_nologin_proves_denial(
    monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    _set_manifest(monkeypatch, _manifest())
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(3))
    role = "id-m78-proof-api" if outcome != "wrong-role" else "unrelated-role"
    severity = "ERROR" if outcome == "not-fatal" else "FATAL"
    driver = asyncpg.exceptions.PostgresError.new({
        "S": severity, "V": severity, "C": "28P01" if outcome == "wrong-state" else "28000",
        "M": f'role "{role}" is not permitted to log in',
    })
    wrapped = RuntimeError("synthetic private driver detail")
    wrapped.__cause__ = driver
    attempts: list[str] = []

    def require_role(expected: DatabaseRole) -> None:
        assert expected is DatabaseRole.API

    async def connect() -> SimpleNamespace:
        attempts.append("connect")
        if outcome == "timeout":
            raise TimeoutError("synthetic detail")
        if outcome == "transport":
            raise ConnectionError("synthetic detail")
        if outcome == "token":
            raise RuntimeError("synthetic token failure")
        if outcome == "wrapped-exact":
            raise DBAPIError(None, None, wrapped)
        if outcome != "connected":
            raise driver
        async def close() -> None:
            return None

        return SimpleNamespace(close=close)

    async def dispose() -> None:
        attempts.append("dispose")

    monkeypatch.setattr(evidence, "get_settings", lambda: SimpleNamespace(
        database_url_value="postgresql+asyncpg://id-m78-proof-api@fixture.invalid/opencanvas",
        database_auth_mode="entra", require_database_role=require_role,
    ))
    monkeypatch.setattr(Database, "from_settings", lambda *_a, **_kw: SimpleNamespace(
        engine=SimpleNamespace(connect=connect), dispose=dispose,
    ))
    if outcome in {"exact", "wrapped-exact"}:
        observed = await evidence.credential_denial_assertion()
        assert [item.code for item in observed] == ["recovery.credential-revocation"]
        assert all(item.passed for item in observed)
    else:
        with pytest.raises((TimeoutError, ConnectionError, RuntimeError)):
            await evidence.credential_denial_assertion()
    assert attempts == ["connect", "dispose"]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["revoke", "restore", "termination-failed", "surviving"])
async def test_revocation_commits_before_exact_session_readback(
    monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    _set_manifest(monkeypatch, _manifest())
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(1))
    mode = "restore" if scenario == "restore" else "revoke"
    events: list[str] = []

    class Result:
        def __init__(self, value: object) -> None:
            self.value = value

        def one(self) -> object:
            return self.value

        def scalar_one(self) -> object:
            return self.value

        def scalars(self) -> Result:
            return self

        def all(self) -> object:
            return self.value

    class Connection:
        async def execute(self, statement: object, parameters: object = None) -> Result:
            sql = str(statement)
            if sql == "SELECT current_user, current_database()":
                return Result(("id-m78-proof-bootstrap", "opencanvas"))
            if sql.startswith("ALTER ROLE"):
                disposition = "LOGIN" if mode == "restore" else "NOLOGIN"
                assert sql == f'ALTER ROLE "id-m78-proof-api" {disposition}'
                events.append("alter")
                return Result(None)
            assert parameters == {"principal": "id-m78-proof-api"}
            assert events[:2] == ["alter", "commit"]
            if "rolcanlogin" in sql:
                events.append("login-readback")
                return Result(mode == "restore")
            if "pg_terminate_backend" in sql:
                events.append("terminate")
                return Result([scenario != "termination-failed"])
            assert "count(*)" in sql and events[-1] == "commit"
            events.append("active-sessions")
            return Result(1 if scenario == "surviving" else 0)

    @asynccontextmanager
    async def begin() -> AsyncIterator[Connection]:
        yield Connection()
        events.append("commit")

    @asynccontextmanager
    async def connect() -> AsyncIterator[Connection]:
        yield Connection()

    async def dispose() -> None:
        events.append("dispose")

    monkeypatch.setattr(credential, "get_settings", lambda: SimpleNamespace(
        require_database_role=lambda _: None,
    ))
    monkeypatch.setattr(Database, "from_settings", lambda *_a, **_kw: SimpleNamespace(
        engine=SimpleNamespace(begin=begin, connect=connect), dispose=dispose,
    ))
    if scenario in {"termination-failed", "surviving"}:
        with pytest.raises(RuntimeError, match="credential recovery"):
            await credential.apply(mode)
    else:
        marker = await credential.apply(mode)
        assert marker["loginEnabled"] is (mode == "restore")
        assert marker["activeSessions"] == (0 if mode == "revoke" else None)
        assert marker["terminatedSessions"] == (1 if mode == "revoke" else None)
    assert events[:3] == ["alter", "commit", "login-readback"]
    assert ("terminate" in events) is (mode == "revoke")
    assert events[-1] == "dispose"


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["", "pooled", "grant-drift", "lock-drift"])
async def test_migration_claims_depend_on_observed_pool_grants_and_lock(
    monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    _set_manifest(monkeypatch, _manifest())
    manifest = load_principal_manifest()
    grants_checked: list[DatabaseRole] = []
    locks_checked: list[bool] = []

    class Connection:
        async def execute(self, statement: object) -> SimpleNamespace:
            assert "pg_get_userbyid" in str(statement)
            return SimpleNamespace(one=lambda: (manifest.principals[next(
                slot for slot in manifest.principals if slot.value == "migration"
            )].name, 0))

    connection = cast(AsyncConnection, Connection())
    def unexpected_connection() -> Never:
        raise AssertionError("synthetic migration probe should not open a real connection")

    pool = object() if defect == "pooled" else NullPool(unexpected_connection)
    database = cast(Database, SimpleNamespace(engine=SimpleNamespace(pool=pool)))

    async def routines(*_args: object, **_kwargs: object) -> None:
        return None

    async def roles(*_args: object) -> bool:
        return True

    async def table_grants(
        _connection: object, _principal: str, role: DatabaseRole,
    ) -> dict[str, int]:
        grants_checked.append(role)
        if defect == "grant-drift":
            raise evidence.EvidenceError("runtime table grants differ")
        return {"SELECT": 1}

    async def function_grants(*_args: object, **_kwargs: object) -> int:
        return 2

    async def lock_checked(*_args: object) -> dict[str, bool]:
        locks_checked.append(True)
        if defect == "lock-drift":
            raise evidence.EvidenceError("migration contender was not blocked")
        return {"contenderBlocked": True, "reacquiredGuardEntered": True}

    monkeypatch.setattr(evidence, "application_routines", routines)
    monkeypatch.setattr(evidence, "_role_contract_matches", roles)
    monkeypatch.setattr(evidence, "_runtime_table_grants", table_grants)
    monkeypatch.setattr(evidence, "require_runtime_function_privileges", function_grants)
    monkeypatch.setattr(evidence, "_migration_lock_observation", lock_checked)
    if defect:
        with pytest.raises(evidence.EvidenceError):
            await evidence._migration_runtime_assertions(connection, database, manifest)
    else:
        observed = await evidence._migration_runtime_assertions(connection, database, manifest)
        assert {item.code for item in observed} == {
            "migration.nullpool", "migration.advisory-lock", "migration.reconciliation",
        }
        assert grants_checked == [DatabaseRole.API, DatabaseRole.WORKER] and locks_checked == [True]


def test_generic_evidence_marker_retains_exact_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    token = "a" * 32
    monkeypatch.setenv("M78_EVIDENCE_TOKEN", token)
    evidence.emit([evidence._assertion("catalog.roles", True, {"observed": True})])
    marker, observed_token, payload = capsys.readouterr().out.split(" ", 2)
    assert marker == "M78_EVIDENCE" and observed_token == token
    assert json.loads(payload)["status"] == "passed"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    "invalidate", "sqlstate", "timeout", "persistent", "persistent-timeout", "auth", "cancel",
])
async def test_worker_reconnects_only_from_transient_database_failure(
    monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    events = []
    clock = 0.0

    async def sleep(delay: float) -> None:
        nonlocal clock
        events.append("sleep")
        clock += delay

    @asynccontextmanager
    async def stopping_session() -> AsyncIterator[None]:
        events.append("stopping")
        raise ConnectionError("synthetic lost shutdown heartbeat")
        yield

    def failure(state: str | None, *, invalidated: bool = False) -> DBAPIError:
        original = (
            asyncpg.exceptions.PostgresError.new({"C": state, "M": "synthetic"})
            if state else ConnectionError("synthetic")
        )
        return DBAPIError(None, None, original, connection_invalidated=invalidated)

    iterations = 0

    async def run_once() -> bool:
        nonlocal iterations
        iterations += 1
        events.append("iteration")
        if outcome == "persistent":
            raise failure("57P03")
        if outcome == "persistent-timeout":
            raise TimeoutError("connection acquisition timed out")
        if outcome == "auth":
            raise failure("28P01", invalidated=True)
        if outcome == "cancel":
            raise asyncio.CancelledError
        if iterations in {1, 3}:
            if outcome == "invalidate":
                raise failure(None, invalidated=True)
            if outcome == "timeout":
                raise TimeoutError("connection acquisition timed out")
            raise failure("57P01")
        if iterations == 2:
            return True
        raise asyncio.CancelledError

    fake_worker = cast(DocumentWorker, SimpleNamespace(
        settings=SimpleNamespace(worker_poll_interval_seconds=1.0),
        sessions=stopping_session, run_once=run_once,
    ))
    monkeypatch.setattr(jobs, "time", SimpleNamespace(monotonic=lambda: clock))
    monkeypatch.setattr(jobs, "_WORKER_DATABASE_RECOVERY_SECONDS", 2.0)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    if outcome in {"persistent", "persistent-timeout", "auth"}:
        with pytest.raises(TimeoutError if outcome == "persistent-timeout" else DBAPIError):
            await DocumentWorker.run_forever(fake_worker)
        assert events == (
            ["iteration", "sleep", "iteration", "sleep"]
            if outcome in {"persistent", "persistent-timeout"}
            else ["iteration"]
        )
    else:
        with pytest.raises(asyncio.CancelledError):
            await DocumentWorker.run_forever(fake_worker)
        expected = ["iteration", "stopping"] if outcome == "cancel" else [
            "iteration", "sleep", "iteration", "iteration", "sleep", "iteration", "stopping",
        ]
        assert events == expected

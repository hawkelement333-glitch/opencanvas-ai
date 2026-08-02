from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from scripts.telemetry_gateway import application

from opencanvas_api.core.config import DatabaseRole
from opencanvas_api.db.runtime import DatabaseRuntimeError
from scripts import bootstrap_postgres, runtime_dependency_gate

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INFRASTRUCTURE_ROOT = REPOSITORY_ROOT / "infra" / "milestone_7_7"


def test_root_reaches_every_runtime_module_and_compute_binding() -> None:
    main = (INFRASTRUCTURE_ROOT / "main.bicep").read_text(encoding="utf-8")
    compute = (INFRASTRUCTURE_ROOT / "modules" / "compute.bicep").read_text(encoding="utf-8")
    for token in (
        "module postgres './modules/postgres.bicep'",
        "module redis './modules/redis.bicep'",
        "module storage './modules/storage-scanner.bicep'",
        "module compute './modules/compute.bicep'",
        "postgresHost: postSecretEnabled ? postgres.outputs.serverFqdn",
        "redisHost: postSecretEnabled ? redis.outputs.hostName",
        "storageAccountUrl: postSecretEnabled ? storage.outputs.storageAccountUrl",
    ):
        assert token in main
    for token in (
        "resource migrationJob 'Microsoft.App/jobs@2025-01-01'",
        "resource apiContainerApp 'Microsoft.App/containerApps@2026-01-01'",
        "resource workerContainerApp 'Microsoft.App/containerApps@2026-01-01'",
        "resource telemetryContainerApp 'Microsoft.App/containerApps@2026-01-01'",
        "OPENCANVAS_DATABASE_TLS_MODE",
        "OPENCANVAS_SHARED_RATE_LIMIT_PROVIDER",
        "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
        "OPENCANVAS_TELEMETRY_ENDPOINT",
        "scripts.runtime_dependency_gate",
    ):
        assert token in compute
    assert "sqlite" not in compute.casefold()


def test_private_storage_is_identity_only_versioned_and_security_classed() -> None:
    storage = (INFRASTRUCTURE_ROOT / "modules" / "storage-scanner.bicep").read_text(
        encoding="utf-8"
    )
    for token in (
        "allowSharedKeyAccess: false",
        "allowBlobPublicAccess: false",
        "publicNetworkAccess: 'Disabled'",
        "defaultToOAuthAuthentication: true",
        "isVersioningEnabled: true",
        "name: 'quarantine'",
        "name: 'clean'",
        "name: 'rejected'",
        "name: 'retained'",
        "Storage Blob Data Contributor",
        "privateDnsZoneGroups",
    ):
        if token == "Storage Blob Data Contributor":
            assert "ba92f5b4-2d11-453d-a403-e96b0029c9fe" in storage
        else:
            assert token in storage


def test_telemetry_gateway_is_bounded_authenticated_and_payload_blind(
    monkeypatch,
) -> None:
    token = "synthetic-telemetry-token-with-at-least-thirty-two-bytes"
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_TOKEN", token)
    payload = {
        "resource": {"schema": "mobius-operational-v1"},
        "signals": [{"kind": "metric", "name": "queue.age"}],
    }
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/v1/signals", json=payload).status_code == 401
        response = client.post(
            "/v1/signals",
            content=json.dumps(payload, separators=(",", ":")),
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 202
    assert token not in response.text
    payload_digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    assert payload_digest not in response.text


def test_postgres_bootstrap_is_revision_guarded_and_principal_closed() -> None:
    bootstrap = (REPOSITORY_ROOT / "apps" / "api" / "scripts" / "bootstrap_postgres.py").read_text(
        encoding="utf-8"
    )
    assert "EXPECTED_DATABASE_REVISION" in bootstrap
    assert "pgaadauth_create_principal" in bootstrap
    assert "id-mobius77-(?:api|worker)" in bootstrap
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in bootstrap
    assert "database migration state is inconsistent" in bootstrap
    assert "password" not in bootstrap.casefold()


@pytest.mark.parametrize(
    ("initial_revision", "migration_calls"),
    [
        ("base", [("base", bootstrap_postgres.EXPECTED_DATABASE_REVISION)]),
        (bootstrap_postgres.EXPECTED_DATABASE_REVISION, []),
    ],
)
def test_postgres_bootstrap_runs_once_or_reconciles_without_reapplying(
    monkeypatch: pytest.MonkeyPatch,
    initial_revision: str,
    migration_calls: list[tuple[str, str]],
) -> None:
    revisions = iter((initial_revision, bootstrap_postgres.EXPECTED_DATABASE_REVISION))
    granted: list[bool] = []
    applied: list[tuple[str, str]] = []

    async def current_revision() -> str:
        return next(revisions)

    async def grant_runtime_roles() -> None:
        granted.append(True)

    def run_migration(*, expected_current: str, target: str) -> None:
        applied.append((expected_current, target))

    monkeypatch.setattr(bootstrap_postgres, "_current_revision", current_revision)
    monkeypatch.setattr(bootstrap_postgres, "_grant_runtime_roles", grant_runtime_roles)
    monkeypatch.setattr(bootstrap_postgres, "run_migration", run_migration)

    assert bootstrap_postgres.main() == 0
    assert applied == migration_calls
    assert granted == [True]


def test_postgres_bootstrap_fails_closed_on_unexpected_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def current_revision() -> str:
        return "unexpected-revision"

    monkeypatch.setattr(bootstrap_postgres, "_current_revision", current_revision)
    assert bootstrap_postgres.main() == 1


@pytest.mark.asyncio
async def test_runtime_dependency_gate_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed: list[bool] = []
    attempts: list[int] = []

    class FakeDatabase:
        engine = object()

        async def dispose(self) -> None:
            disposed.append(True)

    database = FakeDatabase()
    settings = SimpleNamespace(database_role=DatabaseRole.API)

    async def validate(*_args: object, **_kwargs: object) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise DatabaseRuntimeError("not ready")

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(runtime_dependency_gate, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_dependency_gate.Database,
        "from_settings",
        lambda *_args, **_kwargs: database,
    )
    monkeypatch.setattr(runtime_dependency_gate, "validate_database_runtime", validate)
    monkeypatch.setattr(runtime_dependency_gate.asyncio, "sleep", no_wait)

    assert await runtime_dependency_gate.run(attempts=2, delay_seconds=0.1) == 0
    assert len(attempts) == 2
    assert disposed == [True]


@pytest.mark.asyncio
async def test_runtime_dependency_gate_fails_closed_after_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed: list[bool] = []

    class FakeDatabase:
        engine = object()

        async def dispose(self) -> None:
            disposed.append(True)

    database = FakeDatabase()
    settings = SimpleNamespace(database_role=DatabaseRole.WORKER)

    async def validate(*_args: object, **_kwargs: object) -> None:
        raise DatabaseRuntimeError("not ready")

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(runtime_dependency_gate, "get_settings", lambda: settings)
    monkeypatch.setattr(
        runtime_dependency_gate.Database,
        "from_settings",
        lambda *_args, **_kwargs: database,
    )
    monkeypatch.setattr(runtime_dependency_gate, "validate_database_runtime", validate)
    monkeypatch.setattr(runtime_dependency_gate.asyncio, "sleep", no_wait)

    with pytest.raises(DatabaseRuntimeError, match="not ready"):
        await runtime_dependency_gate.run(attempts=2, delay_seconds=0.1)
    assert disposed == [True]

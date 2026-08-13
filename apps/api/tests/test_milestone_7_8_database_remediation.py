from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opencanvas_api.core.config import EXPECTED_DATABASE_REVISION, DatabaseRole
from opencanvas_api.db.models import Base
from opencanvas_api.db.role_privileges import (
    API_SELECT_TABLES,
    RUNTIME_FUNCTION_PRIVILEGES,
    RUNTIME_SEQUENCE_PRIVILEGES,
    RUNTIME_TABLE_PRIVILEGES,
    WORKER_SELECT_TABLES,
    runtime_privilege_statements,
)
from scripts import bootstrap_postgres

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_api_inventory_covers_every_runtime_table_without_migration_only_tables() -> None:
    table_names = set(Base.metadata.tables)
    assert table_names - API_SELECT_TABLES == {
        "application_errors",
        "index_compatibility_projections",
    }
    assert "legacy_creation_request_identities" in API_SELECT_TABLES
    assert WORKER_SELECT_TABLES < API_SELECT_TABLES


def test_runtime_roles_have_independent_table_matrices_and_no_sequence_or_function_grants() -> None:
    api = RUNTIME_TABLE_PRIVILEGES[DatabaseRole.API]
    worker = RUNTIME_TABLE_PRIVILEGES[DatabaseRole.WORKER]
    assert api != worker
    assert api["UPDATE"] != worker["UPDATE"]
    assert api["DELETE"] != worker["DELETE"]
    assert set(RUNTIME_SEQUENCE_PRIVILEGES) == {DatabaseRole.API, DatabaseRole.WORKER}
    assert not any(RUNTIME_SEQUENCE_PRIVILEGES.values())
    assert set(RUNTIME_FUNCTION_PRIVILEGES) == {DatabaseRole.API, DatabaseRole.WORKER}
    assert not any(RUNTIME_FUNCTION_PRIVILEGES.values())


def test_emitted_grants_are_explicit_and_revoke_implicit_privileges() -> None:
    statements = runtime_privilege_statements(
        api_principal="id-mobius77-api",
        worker_principal="id-mobius77-worker",
        migration_principal="id-mobius77-db-migration",
    )
    rendered = "\n".join(statements)
    assert "GRANT ALL" not in rendered
    assert "GRANT EXECUTE" not in rendered
    assert "GRANT USAGE ON SEQUENCE" not in rendered
    assert "GRANT UPDATE ON SEQUENCE" not in rendered
    assert "GRANT SELECT ON SEQUENCE" not in rendered
    assert "GRANT SELECT ON ALL TABLES" not in rendered
    assert "GRANT INSERT, UPDATE, DELETE" not in rendered
    assert "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC" in rendered
    assert "REVOKE CREATE ON SCHEMA public FROM PUBLIC" in rendered
    assert "REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC" in rendered
    assert 'REVOKE "id-mobius77-db-migration" FROM "id-mobius77-api"' in rendered
    assert 'REVOKE "id-mobius77-db-migration" FROM "id-mobius77-worker"' in rendered
    assert "legacy_creation_request_identities" in rendered


def test_bootstrap_and_migration_jobs_use_separate_identities_and_roles() -> None:
    compute = (REPOSITORY_ROOT / "infra/milestone_7_7/modules/compute.bicep").read_text()
    identities = (REPOSITORY_ROOT / "infra/milestone_7_7/modules/identities.bicep").read_text()
    registry = (REPOSITORY_ROOT / "infra/milestone_7_7/modules/registry.bicep").read_text()
    assert "id-mobius77-db-migration" in identities
    assert "databasePrincipalBootstrapJob" in compute
    assert "{ name: 'OPENCANVAS_DATABASE_ROLE', value: 'provisioning' }" in compute
    assert "{ name: 'OPENCANVAS_DATABASE_ROLE', value: 'migration' }" in compute
    assert "'${databaseAdministratorIdentityId}': {}" in compute
    assert "'${databaseMigrationIdentityId}': {}" in compute
    migration_block = compute.split("resource migrationJob", maxsplit=1)[1]
    assert "databaseMigrationIdentityId" in migration_block
    assert "databaseAdministratorIdentityId" not in migration_block
    assert "migrationRegistryPull" in registry


def test_migration_runtime_preserves_direct_nullpool_and_expected_revision() -> None:
    session_source = (REPOSITORY_ROOT / "apps/api/opencanvas_api/db/session.py").read_text()
    migrate_source = (REPOSITORY_ROOT / "apps/api/scripts/migrate_and_grant.py").read_text()
    bootstrap_source = (REPOSITORY_ROOT / "apps/api/scripts/bootstrap_postgres.py").read_text()
    assert EXPECTED_DATABASE_REVISION == "20260726_0029"
    assert 'options["poolclass"] = NullPool' in session_source
    assert "expected_role=DatabaseRole.MIGRATION" in migrate_source
    assert "settings.database_role is not DatabaseRole.MIGRATION" in migrate_source
    assert "expected_role=DatabaseRole.PROVISIONING" in bootstrap_source
    assert "settings.database_role is not DatabaseRole.PROVISIONING" in bootstrap_source
    assert "rolcreaterole" in migrate_source
    assert "pgaadauth_create_principal_with_oid" in bootstrap_source
    assert "GRANT CONNECT, CREATE ON DATABASE opencanvas" in bootstrap_source
    assert "GRANT CONNECT ON DATABASE opencanvas" in bootstrap_source
    assert "GRANT ALL" not in bootstrap_source


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [True, False])
async def test_principal_creation_is_repeatable_without_widening(
    monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    flags = iter([(False, False, False, False, False)] if existing else [None, (False,) * 5])
    statements: list[str] = []

    async def role_flags(_connection: object, _principal: str):  # type: ignore[no-untyped-def]
        return next(flags)

    class FakeConnection:
        async def execute(self, statement: object, _parameters: object) -> SimpleNamespace:
            statements.append(str(statement))
            return SimpleNamespace()

    monkeypatch.setattr(bootstrap_postgres, "_role_flags", role_flags)
    await bootstrap_postgres._ensure_principal(
        FakeConnection(),  # type: ignore[arg-type]
        bootstrap_postgres.PrincipalContract(
            "id-mobius77-db-migration",
            "00000000-0000-0000-0000-000000000001",
        ),
    )
    assert len(statements) == (0 if existing else 1)
    if statements:
        assert "pgaadauth_create_principal_with_oid" in statements[0]

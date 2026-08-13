from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from infra.milestone_7_7 import observability_operator_bootstrap_adapter as adapter
from infra.milestone_7_7 import terminal_lifecycle_adapter
from infra.milestone_7_7.scripts import scanner_bridge_deployment
from preflight.milestone_7_7 import observability_operator_bootstrap as contract

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
DEADLINE = "2026-08-12T20:00:00Z"
HEAD = "a" * 40
SUBSCRIPTION = "11111111-2222-4333-8444-555555555555"
OWNER_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ROOT = Path(__file__).resolve().parents[3] / "infra" / "milestone_7_7"


def _authorization(
    *,
    now: datetime = NOW,
) -> contract.ObservabilityOperatorBootstrapAuthorization:
    return contract.build_observability_operator_bootstrap_authorization(
        repository_head=HEAD,
        subscription_id=SUBSCRIPTION,
        cleanup_deadline_utc=DEADLINE,
        now_utc=now,
    )


def test_azure_job_timestamp_accepts_fractional_utc() -> None:
    assert adapter._parse_azure_utc("2026-08-12T12:34:56.123456Z", "timestamp-invalid") == datetime(
        2026, 8, 12, 12, 34, 56, 123456, tzinfo=UTC
    )
    assert adapter._parse_duration_seconds("PT1M2.6635314S", "duration-invalid") == pytest.approx(
        62.6635314
    )


def test_authorization_is_exact_private_and_image_free() -> None:
    authorization = _authorization()

    assert (
        contract.validate_observability_operator_bootstrap_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW + timedelta(minutes=1),
        )
        is authorization
    )
    assert authorization.apiImageDigest == contract.IMMUTABLE_API_IMAGE
    assert (
        authorization.canonicalImageInputSha256
        == "5f1a5b71c45e7b9183ed09205a5bd815b120e3c278026c4238c05834684b4c81"
    )
    assert authorization.sessionSecretName == "opencanvas-session-secret"
    assert authorization.maximumMigrationExecutions == 1
    assert authorization.maximumOwnerReadbackExecutions == 1
    assert authorization.maximumBootstrapApiResources == 1
    assert authorization.minimumDatabaseAdministratorPropagationSeconds == 600
    assert authorization.privateIngressRequired is True
    assert authorization.imageBuildAuthorized is False
    assert authorization.imagePublicationAuthorized is False
    assert authorization.scannerProofAuthorized is False
    assert authorization.publicIngressAuthorized is False
    assert authorization.fullApplicationDeploymentAuthorized is False
    assert authorization.workerDeploymentAuthorized is False
    assert authorization.telemetryDeploymentAuthorized is False
    assert authorization.redisDeploymentAuthorized is False
    assert authorization.keyVaultSecretValueAccessAuthorized is False
    assert authorization.keyVaultSecretMutationAuthorized is False
    assert authorization.databaseUserInsertAuthorized is False
    assert authorization.migration0029Authorized is False
    assert authorization.cleanupExecutionAuthorized is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("targetResourceGroupId", "/subscriptions/wrong/resourceGroups/wrong"),
        ("apiContainerAppId", "/subscriptions/wrong/containerApps/wrong"),
        ("apiImageDigest", "registry.invalid/api@sha256:" + "0" * 64),
        ("expectedDatabaseRevision", "20260726_0029"),
        ("maximumMigrationExecutions", 2),
        ("maximumOwnerReadbackExecutions", 2),
        ("minimumDatabaseAdministratorPropagationSeconds", 0),
        ("publicIngressAuthorized", True),
        ("scannerProofAuthorized", True),
        ("imageBuildAuthorized", True),
        ("databaseUserInsertAuthorized", True),
    ],
)
def test_authorization_rejects_scope_or_capability_expansion(field: str, value: object) -> None:
    authorization = replace(_authorization(), **{field: value})

    with pytest.raises(contract.ObservabilityOperatorBootstrapError):
        contract.validate_observability_operator_bootstrap_authorization(
            authorization,
            expected_repository_head=HEAD,
            now_utc=NOW + timedelta(minutes=1),
        )


def test_owner_bootstrap_deployment_parameters_are_digest_only() -> None:
    parameters = scanner_bridge_deployment.deployment_parameters(
        stage="owner-bootstrap",
        ledger_integrity="b" * 64,
        repository_head=HEAD,
        cleanup_at_utc=DEADLINE,
        expected_cost=1,
        maximum_cost=25_000,
        lifecycle_tags={"scope": "private-owner-bootstrap"},
        runtime_config={"apiImageDigest": contract.IMMUTABLE_API_IMAGE},
        scanner_bridge_evidence=None,
        now=NOW,
    )

    assert "deploymentStage=owner-bootstrap" in parameters
    assert f"apiImageDigest={contract.IMMUTABLE_API_IMAGE}" in parameters
    joined = "\n".join(parameters)
    assert "scannerResultBridge" not in joined
    assert "smtpHost" not in joined
    assert "docker" not in joined.casefold()

    with pytest.raises(
        scanner_bridge_deployment.ScannerBridgeDeploymentError,
        match="owner-bootstrap-runtime-config-invalid",
    ):
        scanner_bridge_deployment.deployment_parameters(
            stage="owner-bootstrap",
            ledger_integrity="b" * 64,
            repository_head=HEAD,
            cleanup_at_utc=DEADLINE,
            expected_cost=1,
            maximum_cost=25_000,
            lifecycle_tags={},
            runtime_config={
                "apiImageDigest": contract.IMMUTABLE_API_IMAGE,
                "imageBuild": True,
            },
            scanner_bridge_evidence=None,
            now=NOW,
        )


def test_bicep_bootstrap_is_private_and_excludes_full_runtime() -> None:
    main = (ROOT / "main.bicep").read_text(encoding="utf-8")
    owner = (ROOT / "modules" / "owner-bootstrap.bicep").read_text(encoding="utf-8")
    compute = (ROOT / "modules" / "compute.bicep").read_text(encoding="utf-8")

    assert "deploymentStage == 'owner-bootstrap'" in main
    assert "module ownerBootstrap './modules/owner-bootstrap.bicep'" in main
    assert "applicationDeploymentEnabled: false" in owner
    assert "ownerBootstrapDeploymentEnabled: true" in owner
    assert "module redis" not in owner
    assert "module postgres './postgres.bicep'" in owner
    assert "module compute './compute.bicep'" in owner
    postgres = (ROOT / "modules" / "postgres.bicep").read_text(encoding="utf-8")
    assert "storageSizeGB: 64, tier: 'P6'" in postgres
    assert "name: 'azure.extensions'" in postgres
    assert "source: 'user-override'" in postgres
    assert "value: 'vector'" in postgres
    administrator_definition = postgres[
        postgres.index("resource administrator") : postgres.index(
            "resource vectorExtensionAllowlist"
        )
    ]
    assert "dependsOn: [vectorExtensionAllowlist]" in administrator_definition
    assert "dependsOn: [administrator, vectorExtensionAllowlist]" in postgres
    assert "output publicApplicationIngress bool = false" in owner
    assert "output workerDeploymentEnabled bool = false" in owner
    assert "output telemetryDeploymentEnabled bool = false" in owner
    assert "output redisDeploymentEnabled bool = false" in owner
    assert "logAnalyticsWorkspaceId: ''" in owner
    assert "resourceId(\n      targetResourceGroupName" not in owner
    assert "external: false" in compute
    assert "ownerBootstrapSecretNames = [\n  'opencanvas-session-secret'\n]" in compute
    assert (
        "OPENCANVAS_OBSERVABILITY_OPERATOR_USER_IDS"
        not in compute[
            compute.index("var ownerBootstrapSettings") : compute.index("var serviceShapeContract")
        ]
    )
    assert "OPENCANVAS_APP_MODE', value: 'development'" in compute
    assert "OPENCANVAS_AUTH_TEST_BYPASS', value: 'false'" in compute
    assert "args: ['-c', migrationBootstrapProgram]" in compute
    migration_definition = compute[
        compute.index("resource migrationJob") : compute.index("resource ownerReadbackJob")
    ]
    assert "env: concat(ownerBootstrapSettings, [" in migration_definition
    assert "ownerBootstrapSecretEnvironment" not in migration_definition
    assert (
        compute.count("{ name: 'PGSSLROOTCERT', value: '/etc/ssl/certs/ca-certificates.crt' }") == 2
    )
    assert compute.count("{ name: 'OPENCANVAS_DATABASE_TLS_MODE', value: 'verify-full' }") >= 2
    assert "OPENCANVAS_DATABASE_TLS_MODE', value: 'require'" not in compute
    assert "from scripts.bootstrap_postgres import main" in compute
    assert "from scripts.migrate_and_grant import main" in compute
    assert "resource databasePrincipalBootstrapJob" in compute
    assert "databaseAdministratorIdentityId" in compute
    assert "databaseMigrationIdentityId" in migration_definition
    assert "databaseAdministratorIdentityId" not in migration_definition
    assert "OPENCANVAS_DATABASE_MIGRATION_PRINCIPAL_ID" in compute
    assert "OPENCANVAS_DATABASE_RUNTIME_API_PRINCIPAL_ID" in compute
    assert "OPENCANVAS_DATABASE_RUNTIME_WORKER_PRINCIPAL_ID" in compute
    assert "apiIdentityPrincipalId: apiIdentity!.properties.principalId" in owner
    assert "workerIdentityPrincipalId: workerIdentity!.properties.principalId" in owner
    assert "databaseMigrationIdentity!.properties.principalId" in owner
    assert "dependsOn: [databasePrincipalBootstrapJob]" in migration_definition
    assert "dependsOn: appEnabled ? [telemetryContainerApp] : []" in compute


def test_migration_failure_is_mapped_from_sanitized_closed_subcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> str:
        calls.append(argv)
        return '{"Log":"observability-bootstrap-runtime-role-grant-failed"}\n'

    monkeypatch.setattr(adapter.lifecycle, "_run", run)

    assert (
        adapter._migration_failure_code(SUBSCRIPTION, "caj-mobius77-migration-one")
        == "observability-bootstrap-runtime-role-grant-failed"
    )
    assert calls[0][:5] == ("az", "containerapp", "job", "logs", "show")


def test_migration_failure_rejects_ambiguous_or_unknown_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter.lifecycle,
        "_run",
        lambda _argv, **_kwargs: "PostgreSQL bootstrap failed safely.",
    )

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="migration-failure-unclassified",
    ):
        adapter._migration_failure_code(SUBSCRIPTION, "caj-mobius77-migration-one")


def test_postgres_readback_requires_exact_vector_extension_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    responses: list[object] = [
        {
            "highAvailability": "ZoneRedundant",
            "public": "Disabled",
            "state": "Ready",
            "version": "17",
        },
        {
            "name": "azure.extensions",
            "source": "user-override",
            "value": "vector",
        },
    ]
    monkeypatch.setattr(
        adapter.lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: responses.pop(0),
    )
    rest_calls: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> object:
        rest_calls.append(argv)
        return responses.pop(0)

    monkeypatch.setattr(adapter.lifecycle, "_run", run)

    adapter._verify_postgres(authorization)

    assert "/configurations/azure.extensions?api-version=" in rest_calls[0][5]


def test_postgres_readback_rejects_missing_vector_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    monkeypatch.setattr(
        adapter.lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: {
            "highAvailability": "ZoneRedundant",
            "public": "Disabled",
            "state": "Ready",
            "version": "17",
        },
    )
    monkeypatch.setattr(
        adapter.lifecycle,
        "_run",
        lambda _argv, **_kwargs: {
            "name": "azure.extensions",
            "source": "system-default",
            "value": "",
        },
    )

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="postgresql-extension-allowlist-drift",
    ):
        adapter._verify_postgres(authorization)


def test_migration_definition_wait_fails_immediately_on_terminal_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()

    def missing(*_args: object, **_kwargs: object) -> None:
        raise adapter.lifecycle.LifecycleError("resource-not-found")

    monkeypatch.setattr(
        adapter.lifecycle,
        "_verify_resource_projection",
        missing,
    )
    monkeypatch.setattr(adapter, "_deployment_state", lambda _a: "Failed")

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="deployment-terminal-failure",
    ):
        adapter._wait_migration_job_definition(authorization)


def test_migration_definition_is_bound_to_exact_checked_in_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    program = adapter._expected_migration_bootstrap_program()
    assert program == ("from scripts.migrate_and_grant import main\n\nraise SystemExit(main())\n")
    monkeypatch.setattr(
        adapter.lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: {
            "args": ["-c", program],
            "command": ["python"],
            "image": authorization.apiImageDigest,
            "state": "Succeeded",
        },
    )

    adapter._wait_migration_job_definition(authorization)


def test_fresh_authorization_starts_after_one_prior_terminal_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    prior = {
        "end": "2026-08-12T11:51:00Z",
        "name": "caj-mobius77-migration-prior",
        "start": "2026-08-12T11:50:00Z",
        "status": "Failed",
    }
    current = {
        "end": None,
        "name": "caj-mobius77-migration-current",
        "start": "2026-08-12T12:01:00Z",
        "status": "Running",
    }
    inventories = [[prior], [prior, current]]
    starts: list[str] = []
    monkeypatch.setattr(adapter, "_job_execution_rows", lambda *_args: inventories.pop(0))
    monkeypatch.setattr(
        adapter.lifecycle,
        "_run",
        lambda _argv, **_kwargs: starts.append("started"),
    )

    assert (
        adapter._start_or_reconcile_one_job(
            authorization=authorization,
            job_name=contract.MIGRATION_JOB,
            claimed_at_utc="2026-08-12T12:00:00Z",
        )
        == "caj-mobius77-migration-current"
    )
    assert starts == ["started"]


@pytest.mark.parametrize("status", ["Running", "Succeeded"])
def test_fresh_authorization_rejects_concurrent_or_prior_success(
    status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "end": None if status == "Running" else "2026-08-12T11:51:00Z",
                "name": "caj-mobius77-migration-prior",
                "start": "2026-08-12T11:50:00Z",
                "status": status,
            }
        ],
    )

    with pytest.raises(adapter.ObservabilityOperatorBootstrapExecutionError):
        adapter._start_or_reconcile_one_job(
            authorization=authorization,
            job_name=contract.MIGRATION_JOB,
            claimed_at_utc="2026-08-12T12:00:00Z",
        )


def test_wait_accepts_prior_terminal_failure_but_one_current_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "end": "2026-08-12T11:51:00Z",
                "name": "caj-mobius77-migration-prior",
                "start": "2026-08-12T11:50:00Z",
                "status": "Failed",
            },
            {
                "end": "2026-08-12T12:02:00Z",
                "name": "caj-mobius77-migration-current",
                "start": "2026-08-12T12:01:00Z",
                "status": "Succeeded",
            },
        ],
    )

    adapter._wait_job(
        subscription_id=SUBSCRIPTION,
        job_name=contract.MIGRATION_JOB,
        execution_name="caj-mobius77-migration-current",
        timeout_seconds=1,
    )


def test_recent_exact_success_is_adopted_without_second_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    execution = "caj-mobius77-migration-success"
    calls: list[str] = []
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "end": "2026-08-12T12:01:00Z",
                "name": execution,
                "start": "2026-08-12T12:00:00Z",
                "status": "Succeeded",
            }
        ],
    )
    monkeypatch.setattr(
        adapter,
        "_wait_migration_job_definition",
        lambda _a: calls.append("definition"),
    )
    monkeypatch.setattr(
        adapter,
        "_migration_job_modified_at",
        lambda _a: NOW - timedelta(minutes=2),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_migration_success_marker",
        lambda _subscription, _execution: calls.append("success-marker"),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_postgres",
        lambda _a: calls.append("postgres"),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_private_bootstrap_api",
        lambda _a: calls.append("private-api") or "https://private.example",
    )

    assert adapter._adopt_completed_prepare(authorization, now_utc=NOW + timedelta(minutes=2)) == (
        execution,
        "https://private.example",
    )
    assert calls == ["definition", "success-marker", "postgres", "private-api"]


def test_success_adoption_reconciles_retired_execution_replica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    execution = "caj-mobius77-migration-success"
    calls: list[str] = []
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "end": "2026-08-12T12:01:00Z",
                "name": execution,
                "start": "2026-08-12T12:00:00Z",
                "status": "Succeeded",
            }
        ],
    )
    monkeypatch.setattr(adapter, "_wait_migration_job_definition", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_migration_job_modified_at",
        lambda _a: NOW - timedelta(minutes=2),
    )
    monkeypatch.setattr(
        adapter.lifecycle,
        "_run",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        adapter,
        "_verify_postgres",
        lambda _a: calls.append("postgres"),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_private_bootstrap_api",
        lambda _a: calls.append("private-api") or "https://private.example",
    )

    assert adapter._adopt_completed_prepare(authorization, now_utc=NOW + timedelta(minutes=2)) == (
        execution,
        "https://private.example",
    )
    assert calls == ["postgres", "private-api"]


def test_success_adoption_rejects_definition_modified_after_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "end": "2026-08-12T12:01:00Z",
                "name": "caj-mobius77-migration-success",
                "start": "2026-08-12T12:00:00Z",
                "status": "Succeeded",
            }
        ],
    )
    monkeypatch.setattr(adapter, "_wait_migration_job_definition", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_migration_job_modified_at",
        lambda _a: NOW + timedelta(seconds=1),
    )

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="definition-mutated-after-success",
    ):
        adapter._adopt_completed_prepare(authorization, now_utc=NOW + timedelta(minutes=2))


def test_private_bootstrap_accepts_azure_running_at_max_scale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = _authorization()
    fqdn = "ca-mobius77-api.internal.example"
    monkeypatch.setattr(
        adapter.lifecycle,
        "_verify_resource_projection",
        lambda *_args, **_kwargs: {
            "env": [
                {"name": "OPENCANVAS_APP_MODE", "value": "development"},
                {"name": "OPENCANVAS_AUTH_ENABLED", "value": "true"},
                {"name": "OPENCANVAS_AUTH_TEST_BYPASS", "value": "false"},
                {
                    "name": "OPENCANVAS_DATABASE_EXPECTED_REVISION",
                    "value": contract.EXPECTED_DATABASE_REVISION,
                },
                {
                    "name": "OPENCANVAS_SESSION_SECRET",
                    "secretRef": contract.SESSION_SECRET,
                },
            ],
            "external": False,
            "fqdn": fqdn,
            "image": authorization.apiImageDigest,
            "mode": "Single",
            "secrets": [contract.SESSION_SECRET],
            "state": "Succeeded",
        },
    )
    monkeypatch.setattr(
        adapter.lifecycle,
        "_run",
        lambda _argv, **_kwargs: [
            {
                "health": "Healthy",
                "name": "ca-mobius77-api--0000001",
                "running": "RunningAtMaxScale",
                "state": "Provisioned",
            }
        ],
    )

    assert adapter._verify_private_bootstrap_api(authorization) == f"https://{fqdn}"


def test_adapter_consumes_once_and_maps_prepare_without_image_or_scanner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    calls: list[str] = []
    private_url = "https://ca-mobius77-api.private.example"

    monkeypatch.setattr(adapter, "_verify_repository_boundary", lambda _a: calls.append("repo"))
    monkeypatch.setattr(
        adapter,
        "_verify_cleanup_and_cost",
        lambda _a, now_utc: calls.append("cleanup") or (1, 25_000),
    )
    monkeypatch.setattr(
        adapter,
        "_verify_session_secret_metadata",
        lambda _a: calls.append("secret-metadata"),
    )
    monkeypatch.setattr(
        adapter,
        "_adopt_completed_prepare",
        lambda _a, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "_deploy_owner_bootstrap",
        lambda _a, **_kwargs: calls.append("deploy-owner-bootstrap"),
    )
    monkeypatch.setattr(
        adapter,
        "_wait_postgres_administrator_propagation",
        lambda _a: calls.append("postgres-administrator-propagated"),
    )
    monkeypatch.setattr(
        adapter,
        "_start_or_reconcile_one_job",
        lambda **kwargs: (
            calls.append(f"start:{kwargs['job_name']}") or "caj-mobius77-migration-one"
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_wait_job",
        lambda **kwargs: calls.append(f"wait:{kwargs['job_name']}"),
    )
    monkeypatch.setattr(adapter, "_verify_postgres", lambda _a: calls.append("postgres"))
    monkeypatch.setattr(
        adapter,
        "_wait_deployment_readback",
        lambda _a: calls.append("deployment-readback") or {"private-application-url": private_url},
    )
    monkeypatch.setattr(
        adapter,
        "_wait_private_bootstrap_api",
        lambda _a: calls.append("private-api") or private_url,
    )

    result = adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="prepare",
        now_utc=NOW + timedelta(minutes=1),
    )

    assert result["authorizationConsumed"] is True
    assert result["marker"] == "PRE_RUNTIME_OWNER_BOOTSTRAP_REQUIRED"
    assert result["privateApplicationUrl"] == private_url
    assert calls == [
        "repo",
        "cleanup",
        "secret-metadata",
        "deploy-owner-bootstrap",
        "postgres-administrator-propagated",
        "start:caj-mobius77-migration",
        "wait:caj-mobius77-migration",
        "postgres",
        "deployment-readback",
        "private-api",
    ]
    receipt_path = tmp_path / adapter.RECEIPT_FILE
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["phase"] == "prepared"
    assert receipt["migrationTerminalStatus"] == "Succeeded"

    calls.clear()
    replay = adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="prepare",
        now_utc=NOW + timedelta(minutes=2),
    )
    assert replay == result
    assert calls == []


def test_adapter_adopts_completed_prepare_without_deploy_or_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    execution = "caj-mobius77-migration-success"
    private_url = "https://ca-mobius77-api.private.example"
    monkeypatch.setattr(adapter, "_verify_repository_boundary", lambda _a: None)
    monkeypatch.setattr(adapter, "_verify_cleanup_and_cost", lambda _a, now_utc: (1, 25_000))
    monkeypatch.setattr(adapter, "_verify_session_secret_metadata", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_adopt_completed_prepare",
        lambda _a, **_kwargs: (execution, private_url),
    )
    monkeypatch.setattr(
        adapter,
        "_deploy_owner_bootstrap",
        lambda *_args, **_kwargs: pytest.fail("adoption must not deploy"),
    )
    monkeypatch.setattr(
        adapter,
        "_start_or_reconcile_one_job",
        lambda **_kwargs: pytest.fail("adoption must not start a job"),
    )

    result = adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="prepare",
        now_utc=NOW + timedelta(minutes=2),
    )

    assert result["marker"] == "PRE_RUNTIME_OWNER_BOOTSTRAP_REQUIRED"
    assert result["privateApplicationUrl"] == private_url
    receipt = json.loads((tmp_path / adapter.RECEIPT_FILE).read_text(encoding="utf-8"))
    assert receipt["migrationExecutionName"] == execution
    assert receipt["migrationTerminalStatus"] == "Succeeded"
    assert receipt["phase"] == "prepared"


def test_owner_readback_is_one_exact_read_only_job_and_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    private_url = "https://ca-mobius77-api.private.example"
    monkeypatch.setattr(adapter, "_verify_repository_boundary", lambda _a: None)
    monkeypatch.setattr(adapter, "_verify_cleanup_and_cost", lambda _a, now_utc: (1, 25_000))
    monkeypatch.setattr(adapter, "_verify_session_secret_metadata", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_adopt_completed_prepare",
        lambda _a, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "_deploy_owner_bootstrap",
        lambda _a, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "_wait_postgres_administrator_propagation", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_start_or_reconcile_one_job",
        lambda **kwargs: (
            "caj-mobius77-migration-one"
            if kwargs["job_name"] == contract.MIGRATION_JOB
            else "caj-mobius77-owner-readback-one"
        ),
    )
    monkeypatch.setattr(adapter, "_wait_job", lambda **_kwargs: None)
    monkeypatch.setattr(adapter, "_verify_postgres", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_wait_deployment_readback",
        lambda _a: {"private-application-url": private_url},
    )
    monkeypatch.setattr(adapter, "_wait_private_bootstrap_api", lambda _a: private_url)
    monkeypatch.setattr(adapter, "_verify_private_bootstrap_api", lambda _a: private_url)
    monkeypatch.setattr(adapter, "_owner_readback_log", lambda **_kwargs: OWNER_ID)
    deleted: list[str] = []
    monkeypatch.setattr(
        adapter,
        "_delete_owner_readback_job",
        lambda _a: deleted.append(contract.OWNER_READBACK_JOB),
    )

    adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="prepare",
        now_utc=NOW + timedelta(minutes=1),
    )
    result = adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="read-owner",
        now_utc=NOW + timedelta(minutes=2),
    )

    assert result == {
        "authorizationConsumed": True,
        "marker": "GENUINE_OWNER_APPLICATION_UUID_PROVED",
        "ownerReadbackJobDeleted": True,
        "ownerUserId": OWNER_ID,
    }
    assert deleted == [contract.OWNER_READBACK_JOB]
    receipt = json.loads((tmp_path / adapter.RECEIPT_FILE).read_text(encoding="utf-8"))
    assert receipt["phase"] == "owner-proved"
    assert receipt["ownerReadbackJobDeleted"] is True
    assert receipt["ownerUserId"] == OWNER_ID


def test_different_authorization_cannot_consume_existing_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    monkeypatch.setattr(adapter, "_verify_repository_boundary", lambda _a: None)
    monkeypatch.setattr(adapter, "_verify_cleanup_and_cost", lambda _a, now_utc: (1, 25_000))
    monkeypatch.setattr(adapter, "_verify_session_secret_metadata", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_adopt_completed_prepare",
        lambda _a, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "_deploy_owner_bootstrap",
        lambda _a, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "_wait_postgres_administrator_propagation", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_start_or_reconcile_one_job",
        lambda **_kwargs: "caj-mobius77-migration-one",
    )
    monkeypatch.setattr(adapter, "_wait_job", lambda **_kwargs: None)
    monkeypatch.setattr(adapter, "_verify_postgres", lambda _a: None)
    monkeypatch.setattr(
        adapter,
        "_wait_deployment_readback",
        lambda _a: {"private-application-url": "https://ca-mobius77-api.private.example"},
    )
    monkeypatch.setattr(
        adapter,
        "_wait_private_bootstrap_api",
        lambda _a: "https://ca-mobius77-api.private.example",
    )
    adapter.execute_observability_operator_bootstrap(
        authorization,
        receipt_directory=tmp_path,
        phase="prepare",
        now_utc=NOW + timedelta(minutes=1),
    )

    different = _authorization(now=NOW + timedelta(minutes=2))
    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="receipt-authorization-mismatch",
    ):
        adapter.execute_observability_operator_bootstrap(
            different,
            receipt_directory=tmp_path,
            phase="prepare",
            now_utc=NOW + timedelta(minutes=3),
        )


def test_owner_readback_cannot_use_expired_authorization(tmp_path: Path) -> None:
    authorization = _authorization()

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="authorization-expired",
    ):
        adapter.execute_observability_operator_bootstrap(
            authorization,
            receipt_directory=tmp_path,
            phase="read-owner",
            now_utc=NOW + timedelta(hours=2, seconds=1),
        )


def test_terminal_migration_adopts_bootstrap_execution_without_second_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"resumableCheckpoint": "migration-execution"}
    replaced: list[dict[str, object]] = []
    monkeypatch.setattr(
        terminal_lifecycle_adapter,
        "_require_stage_predecessor",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        terminal_lifecycle_adapter.lifecycle,
        "_state_path",
        lambda _directory: tmp_path / "state.json",
    )
    monkeypatch.setattr(
        terminal_lifecycle_adapter.lifecycle,
        "_read_current_transient_state",
        lambda _path, ledger: state,
    )
    monkeypatch.setattr(
        terminal_lifecycle_adapter.lifecycle,
        "_replace_state",
        lambda _path, value: replaced.append(dict(value)),
    )
    monkeypatch.setattr(
        adapter,
        "reconcile_completed_bootstrap_migration",
        lambda **_kwargs: "caj-mobius77-migration-one",
    )
    monkeypatch.setattr(
        terminal_lifecycle_adapter,
        "migration_job_ready",
        lambda _subscription: pytest.fail("migration must not be started twice"),
    )

    result = terminal_lifecycle_adapter.migration_stage(
        ledger={"repositoryHead": HEAD},
        subscription_id=SUBSCRIPTION,
        receipt_directory=tmp_path,
    )

    assert result["terminalStatus"] == "Succeeded"
    assert result["singleExecution"] is True
    assert replaced[-1]["resumableCheckpoint"] == "readiness-validation"


def test_exact_prepared_receipt_adopts_historical_migration_across_control_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    receipt = adapter._new_receipt(authorization, now_utc=NOW)
    receipt.update(
        {
            "bootstrapPrivateApplicationUrl": "https://ca-mobius77-api.private.example",
            "migrationExecutionName": "caj-mobius77-migration-one",
            "migrationTerminalStatus": "Succeeded",
            "phase": "prepared",
        }
    )
    receipt_path = tmp_path / adapter.RECEIPT_FILE
    adapter._replace_receipt(receipt_path, receipt)
    retained = adapter._load_receipt(receipt_path)
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_AUTHORIZATION_INTEGRITY",
        authorization.authorizationIntegritySha256,
    )
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_RECEIPT_INTEGRITY",
        retained["receiptIntegritySha256"],
    )
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_SOURCE_HEAD", HEAD)
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_EXECUTION", "caj-mobius77-migration-one")
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_CLAIMED_AT", adapter._format_utc(NOW))
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_PRIVATE_URL",
        "https://ca-mobius77-api.private.example",
    )
    monkeypatch.setattr(
        adapter,
        "_job_execution_rows",
        lambda *_args: [
            {
                "name": "caj-mobius77-migration-one",
                "status": "Succeeded",
                "start": "2026-08-12T12:00:00Z",
                "end": "2026-08-12T12:01:00Z",
            },
            {
                "name": "caj-mobius77-migration-old",
                "status": "Failed",
                "start": "2026-08-12T11:00:00Z",
                "end": None,
            },
        ],
    )

    execution = adapter.reconcile_completed_bootstrap_migration(
        receipt_directory=tmp_path,
        repository_head="b" * 40,
        subscription_id=SUBSCRIPTION,
    )

    assert execution == "caj-mobius77-migration-one"


def test_different_prepared_receipt_cannot_adopt_historical_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authorization = _authorization()
    receipt = adapter._new_receipt(authorization, now_utc=NOW)
    receipt.update(
        {
            "bootstrapPrivateApplicationUrl": "https://ca-mobius77-api.private.example",
            "migrationExecutionName": "caj-mobius77-migration-one",
            "migrationTerminalStatus": "Succeeded",
            "phase": "prepared",
        }
    )
    receipt_path = tmp_path / adapter.RECEIPT_FILE
    adapter._replace_receipt(receipt_path, receipt)
    retained = adapter._load_receipt(receipt_path)
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_AUTHORIZATION_INTEGRITY",
        authorization.authorizationIntegritySha256,
    )
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_RECEIPT_INTEGRITY",
        retained["receiptIntegritySha256"],
    )
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_SOURCE_HEAD", HEAD)
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_EXECUTION", "caj-mobius77-migration-one")
    monkeypatch.setattr(adapter, "RETAINED_MIGRATION_CLAIMED_AT", adapter._format_utc(NOW))
    monkeypatch.setattr(
        adapter,
        "RETAINED_MIGRATION_PRIVATE_URL",
        "https://ca-mobius77-api.private.example",
    )
    receipt["authorizationId"] = "00000000-0000-0000-0000-000000000000"
    adapter._replace_receipt(receipt_path, receipt)

    with pytest.raises(
        adapter.ObservabilityOperatorBootstrapExecutionError,
        match="observability-bootstrap-migration-adoption-receipt-invalid",
    ):
        adapter.reconcile_completed_bootstrap_migration(
            receipt_directory=tmp_path,
            repository_head="b" * 40,
            subscription_id=SUBSCRIPTION,
        )


def test_adapter_source_has_no_image_scanner_or_secret_value_operation() -> None:
    text = Path(adapter.__file__).read_text(encoding="utf-8")

    assert "docker" not in text.casefold()
    assert "acr" not in text.casefold()
    assert "scanner-proof" not in text
    assert "keyvault secret set" not in text.casefold()
    assert "build_authorization_ledger" not in text
    assert "20260726_0029" not in text

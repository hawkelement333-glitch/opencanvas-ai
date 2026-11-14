from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sys
import time
from collections.abc import Callable
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.exc import OperationalError
from test_milestone_7_8_campaign_enablement import (
    _cleanup_arm_success_results,
    _config,
    _manifest,
    _runtime,
)
from test_milestone_7_8_database_recovery import Connection, state, use_database

from infra.milestone_7_8 import operator
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CostItem,
    Phase,
    SubprocessRunner,
    sanitize,
)
from opencanvas_api.core.config import DatabaseRole
from opencanvas_api.db.principal_manifest import (
    CAMPAIGN_ENV,
    CURRENT_PRINCIPAL_ID_ENV,
    GENERATION_ENV,
    MANIFEST_ENV,
    PrincipalSlot,
    load_principal_manifest,
)
from opencanvas_api.db.session import Database
from scripts import bootstrap_postgres

NOW = datetime(2030, 1, 1, tzinfo=UTC)
CUSTOMER = "33333333-3333-4333-8333-333333333333"
PRIVATE = "private-diagnostic-response-not-for-terminal"
DIGEST = "sha256:" + "d" * 64


def result(value: object, code: int = 0) -> dict[str, object]:
    return {"exitCode": code, "stdout": json.dumps(value), "stderr": PRIVATE if code else ""}


class FakeProvider:
    def __init__(self, runtime: dict[str, str], failure: str = "") -> None:
        self.runtime = runtime
        self.failure = failure
        self.events: list[str] = []
        self.commands: list[tuple[str, ...]] = []
        self.expired = False
        self.replica_pages = 0
        self.execution = "bootstrap-execution"
        self.operation = "bootstrap"
        self.retry_execution: str | None = None
        self.retry_marker = ""
        self.retry_status = "Succeeded"
        self.retry_template: dict[str, object] | None = None
        self.actual_retry_marker = ""
        self.db_mutations: list[str] = []
        self.cleanup_reads: dict[tuple[str, ...], dict[str, object]] = {}
        self.manifest = _manifest()
        self.template: dict[str, object] = {}
        self.clock_advance = 0
        self.group_id = (
            f"/subscriptions/{runtime['subscriptionId']}"
            f"/resourceGroups/{runtime['resourceGroupName']}"
        )

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        if command[:4] == ("az", "containerapp", "job", "start"):
            if "--yaml" in command:
                template = json.loads(Path(command[command.index("--yaml") + 1]).read_text())
                assert template["containers"][0]["args"] == [
                    f"--retry-after-execution={self.execution}",
                ]
                self.retry_template = template
                self.events.append("retry-start")
                self.retry_execution = (
                    self.execution
                    if self.failure == "same-execution"
                    else "bootstrap-retry-execution"
                )
                self.run_database_retry()
                return self.execution_result(self.retry_execution, "Running")
            self.events.append("start")
            return self.execution_result(self.execution, "Running")
        if command[:5] == ("az", "containerapp", "job", "execution", "show"):
            execution = command[command.index("--job-execution-name") + 1]
            if execution == self.retry_execution:
                self.events.append("retry-terminal")
                if self.failure == "late-terminal":
                    self.expired = True
                returned = "other-execution" if self.failure == "wrong-final" else execution
                return self.execution_result(returned, self.retry_status)
            assert execution == self.execution
            self.events.append("failed-execution")
            self.expired = self.failure == "expired"
            returned = "other-execution" if self.failure == "identity" else self.execution
            return self.execution_result(
                returned, "Succeeded" if self.failure == "normal-success" else "Failed"
            )
        if command in self.cleanup_reads:
            self.events.append("cleanup-read")
            return self.cleanup_reads[command]
        if command[:4] == ("az", "containerapp", "job", "show"):
            self.events.append("retry-template")
            template = json.loads(json.dumps(self.template))
            if self.failure == "overcpu":
                template["containers"][0]["resources"]["cpu"] = 1
            if self.failure == "init-container":
                template["initContainers"] = [{"name": "unpriced", "image": "invalid"}]
            return result(
                {
                    "id": self.job_id(),
                    "properties": {
                        "template": template,
                        "configuration": {
                            "triggerType": "Manual",
                            "replicaTimeout": 900,
                            "replicaRetryLimit": 0,
                            "manualTriggerConfig": {"parallelism": 1, "replicaCompletionCount": 1},
                        },
                    },
                }
            )
        assert command[command.index("--subscription") + 1] == self.runtime["subscriptionId"]
        if command[:4] == ("az", "rest", "--method", "get"):
            self.events.append("replicas")
            url = command[command.index("--url") + 1]
            observed_execution = self.retry_execution or self.execution
            assert f"/executions/{observed_execution}/replicas?" in url
            if self.failure == "replicas":
                return result({"error": PRIVATE}, 1)
            if self.failure == "timeout":
                raise TimeoutError(PRIVATE)
            self.replica_pages += 1
            page: dict[str, object] = {
                "value": [
                    {
                        "name": f"{observed_execution}-replica-{self.replica_pages}",
                        "properties": {
                            "containers": [
                                {
                                    "name": "bootstrap",
                                    "terminated": {"exitCode": 1, "reason": PRIVATE},
                                }
                            ]
                        },
                    }
                ]
            }
            if self.failure == "endless-pages" or (
                self.failure == "two-pages" and self.replica_pages == 1
            ):
                page["nextLink"] = (
                    url.split("&$skiptoken=")[0] + f"&$skiptoken={self.replica_pages + 1}"
                )
            if self.failure == "out-of-scope-pages":
                page["nextLink"] = url.replace(
                    f"/executions/{self.execution}/", "/executions/other/"
                )
            return result(page)
        if command[:5] == ("az", "monitor", "log-analytics", "workspace", "show"):
            self.events.append("workspace")
            if self.failure == "workspace":
                return result({"error": PRIVATE}, 1)
            return result(
                {
                    "id": f"{self.group_id}/providers/Microsoft.OperationalInsights/workspaces/"
                    f"{self.runtime['logAnalyticsWorkspaceName']}",
                    "customerId": CUSTOMER,
                }
            )
        if command[:4] == ("az", "monitor", "log-analytics", "query"):
            self.events.append("logs")
            assert command[command.index("--workspace") + 1] == CUSTOMER
            query = command[command.index("--analytics-query") + 1]
            assert "startswith" not in query
            assert "ContainerGroupName_s in (" in query
            current_execution = self.retry_execution or self.execution
            assert f"'{current_execution}-replica-" in query
            assert "'bootstrap-execution-other-replica-1'" not in query
            if self.failure == "logs":
                return result({"error": PRIVATE}, 1)
            replica = (
                "bootstrap-execution-other-replica-1"
                if self.failure == "wrong-console"
                else f"{current_execution}-replica-{self.replica_pages}"
            )
            message = self.retry_marker if self.retry_execution else PRIVATE
            if self.failure == "diagnostic-expiry":
                self.expired = True
            return result([{"Log_s": message, "ContainerGroupName_s": replica}])
        raise AssertionError(f"unexpected command prefix: {command[:4]}")

    def job_id(self) -> str:
        job = self.runtime[
            "bootstrapJobName" if self.operation == "bootstrap" else "migrationJobName"
        ]
        return f"{self.group_id}/providers/Microsoft.App/jobs/{job}"

    def execution_result(self, name: str, status: str) -> dict[str, object]:
        return result(
            {
                "id": f"{self.job_id()}/executions/{name}",
                "name": name,
                "properties": {
                    "status": status,
                    "template": (
                        self.retry_template if name == self.retry_execution else self.template
                    ),
                },
            }
        )

    def run_database_retry(self) -> None:
        output = io.StringIO()
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setenv(MANIFEST_ENV, json.dumps(self.manifest))
            monkeypatch.setenv(CAMPAIGN_ENV, str(self.manifest["campaignId"]))
            monkeypatch.setenv(GENERATION_ENV, str(self.manifest["generationId"]))
            parsed = load_principal_manifest()
            monkeypatch.setenv(
                CURRENT_PRINCIPAL_ID_ENV, parsed.principals[PrincipalSlot.BOOTSTRAP].object_id
            )
            observed = state(parsed)
            if self.failure == "unsafe-db-state":
                observed["revisions"] = ["unknown-intermediate"]
            connection = Connection(observed)
            connection.output = output
            use_database(monkeypatch, connection, role=DatabaseRole.PROVISIONING)
            self.events.append("db-inspection")
            with redirect_stdout(output), redirect_stderr(io.StringIO()):
                code = bootstrap_postgres.main([f"--retry-after-execution={self.execution}"])
            self.db_mutations = connection.mutations
            if connection.mutations:
                self.events.append("db-mutation")
            self.retry_status = "Succeeded" if code == 0 else "Failed"
        self.retry_marker = output.getvalue().strip()
        self.actual_retry_marker = self.retry_marker
        if self.failure == "missing-marker":
            self.retry_marker = ""
        if self.failure == "contradictory-marker":
            marker = json.loads(self.retry_marker.removeprefix("M78_DATABASE_RECOVERY "))
            marker["state"] = "bootstrap-empty"
            self.retry_marker = "M78_DATABASE_RECOVERY " + json.dumps(marker)


def run_operator(
    directory: Path,
    failure: str = "",
    *,
    persist_fails: bool = False,
    provider: FakeProvider | None = None,
    ledger: Mock | None = None,
    resume: bool = False,
    operation: str = "bootstrap",
    allowance: bool = True,
    authorization_check: Callable[..., None] | None = None,
    execute: bool = True,
    extra_arguments: tuple[str, ...] = (),
    runtime_override: dict[str, str] | None = None,
) -> tuple[int, FakeProvider, Mock, str]:
    config = replace(
        cast(Callable[[], CampaignConfig], _config)(), cleanup_deadline_utc="2030-01-01T01:00:00Z"
    )
    if allowance:
        config = replace(
            config,
            conservative_estimate_usd="25.754075",
            resource_items=(
                *config.resource_items,
                CostItem("database-recovery-job-allowance", "0", 1, "0.0567"),
            ),
        )
    runtime = runtime_override or _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    runtime["cleanupAuthorityExpiresUtc"] = operator.runtime_authority_expiry(config)
    arm = _cleanup_arm_success_results(config, runtime)
    readbacks = [*arm[:6], arm[9], arm[11], arm[12]]
    arm_hash = operator.validate_cleanup_readback(readbacks, config, runtime)
    provider = provider or FakeProvider(runtime, failure)
    active_provider = provider
    provider.operation = operation
    module = (
        "scripts.bootstrap_postgres" if operation == "bootstrap" else "scripts.migrate_and_grant"
    )
    if not provider.template:
        provider.template = {
            "containers": [
                {
                    "name": "bootstrap",
                    "image": f"registry.invalid/app@{DIGEST}",
                    "command": ["python", "-m", module],
                    "args": [],
                    "resources": {"cpu": 0.5, "memory": "1Gi"},
                    "env": [{"name": MANIFEST_ENV, "value": json.dumps(provider.manifest)}],
                }
            ]
        }
    provider.cleanup_reads = dict(
        zip(
            (
                (*command, "--subscription", runtime["subscriptionId"])
                for command in operator.command_plan("cleanup-verify", config, runtime)
            ),
            readbacks,
            strict=True,
        )
    )
    ledger = ledger or Mock(
        phase=Phase.IMAGE_DECIDED.value,
        image_digest=DIGEST,
        actual_cost_usd=None,
        authorized_ceiling_usd="50",
        cleanup_arm_evidence_sha256=arm_hash,
    )

    def transition(phase: Phase, *_args: object, **_kwargs: object) -> None:
        ledger.phase = phase.value

    ledger.transition.side_effect = transition
    for filename in ("config", "runtime", "authorization"):
        path = directory / filename
        if not path.exists():
            path.write_text("{}", encoding="utf-8")

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Clock:
            now = NOW + timedelta(
                hours=2 if active_provider.expired else 0, seconds=active_provider.clock_advance
            )
            return cls.fromtimestamp(now.timestamp(), tz)

    errors = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                sys,
                "argv",
                [
                    "operator",
                    operation,
                    *(["--execute"] if execute else []),
                    "--config",
                    str(directory / "config"),
                    "--runtime",
                    str(directory / "runtime"),
                    "--ledger",
                    str(directory / "ledger"),
                    "--authorization",
                    str(directory / "authorization"),
                    *(["--resume-database-job"] if resume else []),
                    *extra_arguments,
                ],
            )
        )
        stack.enter_context(patch.object(CampaignConfig, "from_json", return_value=config))
        stack.enter_context(patch.object(operator, "load_runtime", return_value=runtime))
        for name in (
            "validate_prepared_bundle",
            "load_bound_fresh_controller_admission",
            "save_ledger",
        ):
            stack.enter_context(patch.object(operator, name))
        stack.enter_context(
            patch.object(operator, "load_execution_authorization", side_effect=authorization_check)
        )
        stack.enter_context(patch.object(operator, "load_ledger", return_value=ledger))
        # These cases exercise failure capture and guarded retries after prerequisite admission.
        stack.enter_context(patch.object(operator, "_database_prerequisites"))
        stack.enter_context(patch.object(operator, "SubprocessRunner", return_value=provider))
        stack.enter_context(patch.object(operator, "datetime", Clock))
        stack.enter_context(patch.object(time, "sleep"))
        stack.enter_context(
            patch.object(
                operator,
                "start_failure_cleanup",
                side_effect=lambda *_: provider.events.append("cleanup"),
            )
        )
        if persist_fails:
            stack.enter_context(
                patch(
                    "infra.milestone_7_8.controller_renewal._durable_record",
                    side_effect=OSError(PRIVATE),
                )
            )
        stack.enter_context(redirect_stderr(errors))
        stack.enter_context(redirect_stdout(io.StringIO()))
        status = operator.main()
    return status, provider, ledger, errors.getvalue()


def test_failed_bootstrap_preserves_exact_diagnostics_and_pauses_without_cleanup(
    tmp_path: Path,
) -> None:
    status, provider, ledger, errors = run_operator(tmp_path)
    assert status == 2
    assert provider.events == [
        "start",
        "failed-execution",
        "replicas",
        "workspace",
        "logs",
    ]
    assert "container job evidence failed" in errors
    assert PRIVATE not in errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value
    captures = list(tmp_path.glob("job-failure-*"))
    assert len(captures) == 1
    files = list(captures[0].glob("*.json"))
    assert any(PRIVATE in path.read_text() for path in files)
    saved = json.loads((captures[0] / "execution.json").read_text())
    assert saved["executionName"] == provider.execution
    assert saved["lastResult"]["exitCode"] == 0


@pytest.mark.parametrize(
    "failure",
    ["replicas", "workspace", "logs", "expired", "timeout", "identity"],
)
def test_diagnostic_read_failure_does_not_replace_failure_or_block_cleanup(
    tmp_path: Path,
    failure: str,
) -> None:
    status, provider, ledger, errors = run_operator(tmp_path, failure)
    assert status == 2
    assert provider.events.count("start") == 1
    assert provider.events.count("cleanup") == int(failure == "expired")
    assert "container job evidence failed" in errors
    assert PRIVATE not in errors
    assert ledger.phase == (
        Phase.CLEANING.value if failure == "expired" else Phase.IMAGE_DECIDED.value
    )
    if failure == "expired":
        assert provider.events == ["start", "failed-execution", "cleanup"]


def test_diagnostic_persistence_failure_preserves_job_error_and_cleanup(tmp_path: Path) -> None:
    status, provider, ledger, errors = run_operator(tmp_path, persist_fails=True)
    assert status == 2
    assert not provider.events  # Intent persistence failed before the first request.
    assert "record is uncertain" in errors
    assert PRIVATE not in errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value


def test_complete_replica_pages_preserved_before_cleanup(tmp_path: Path) -> None:
    status, provider, _, errors = run_operator(tmp_path, "two-pages")
    assert status == 2 and "container job evidence failed" in errors
    assert provider.events == [
        "start",
        "failed-execution",
        "replicas",
        "replicas",
        "workspace",
        "logs",
    ]
    capture = next(tmp_path.glob("job-failure-*"))
    replica = json.loads((capture / "replicas.json").read_text())
    assert replica["complete"] and len(replica["pages"]) == 2


@pytest.mark.parametrize("failure", ["endless-pages", "out-of-scope-pages"])
def test_incomplete_or_out_of_scope_replicas_cannot_delay_cleanup_unboundedly(
    tmp_path: Path,
    failure: str,
) -> None:
    status, provider, _, errors = run_operator(tmp_path, failure)
    assert status == 2 and "container job evidence failed" in errors
    assert "cleanup" not in provider.events
    assert len(provider.commands) <= 8  # Start, failed show, at most six diagnostic reads.
    assert all("/executions/other/" not in " ".join(command) for command in provider.commands)
    capture = next(tmp_path.glob("job-failure-*"))
    assert not (capture / "replicas.json").exists()
    summary = json.loads((capture / "capture-status.json").read_text())
    assert summary["replicas"] == "unavailable"
    assert summary["admissionEvidence"] is False


def test_failed_result_persistence_stops_more_diagnostics_but_not_cleanup(tmp_path: Path) -> None:
    from infra.milestone_7_8.controller_renewal import _durable_record

    def persist(path: Path, document: object) -> None:
        if path.name == "01-result.json":
            raise OSError(PRIVATE)
        _durable_record(path, document)

    with patch("infra.milestone_7_8.controller_renewal._durable_record", side_effect=persist):
        status, provider, _, errors = run_operator(tmp_path)
    assert status == 2 and "container job evidence failed" in errors
    assert provider.events == ["start", "failed-execution", "replicas"]
    assert PRIVATE not in errors


def test_bootstrap_emits_only_stage_safe_class_and_sqlstate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class DriverError(Exception):
        sqlstate = "42883"

    error = OperationalError(PRIVATE, {"token": PRIVATE}, DriverError(PRIVATE))
    monkeypatch.setattr(bootstrap_postgres, "get_settings", Mock(side_effect=error))
    assert bootstrap_postgres.main() == 1
    text = capsys.readouterr().err
    assert PRIVATE not in text
    diagnostic = json.loads(text.splitlines()[0].removeprefix("M78_BOOTSTRAP_DIAGNOSTIC "))
    assert diagnostic == {
        "stage": "configuration",
        "errorClass": "OperationalError",
        "sqlstate": "42883",
    }
    assert text.splitlines()[1] == "PostgreSQL principal bootstrap failed safely."


def test_bootstrap_diagnostic_rejects_malformed_sqlstate_and_unknown_class(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnknownPrivateError(Exception):
        sqlstate = PRIVATE

    bootstrap_postgres._failure_diagnostic("connection", UnknownPrivateError(PRIVATE))
    text = capsys.readouterr().err
    assert PRIVATE not in text and "UnknownPrivateError" not in text
    diagnostic = json.loads(text.removeprefix("M78_BOOTSTRAP_DIAGNOSTIC "))
    assert diagnostic == {"stage": "connection", "errorClass": "Exception", "sqlstate": None}


def test_prefix_sharing_execution_logs_cannot_be_accepted(tmp_path: Path) -> None:
    status, provider, _, errors = run_operator(tmp_path, "wrong-console")
    assert status == 2 and "container job evidence failed" in errors
    assert "cleanup" not in provider.events
    capture = next(tmp_path.glob("job-failure-*"))
    summary = json.loads((capture / "capture-status.json").read_text())
    assert summary["console"] == "unavailable"
    assert summary["admissionEvidence"] is False


def test_missing_replica_scope_skips_workspace_and_console_reads(tmp_path: Path) -> None:
    status, provider, _, errors = run_operator(tmp_path, "replicas")
    assert status == 2 and "container job evidence failed" in errors
    assert provider.events == ["start", "failed-execution", "replicas"]


def test_bootstrap_disposal_failure_preserves_original_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = OperationalError(PRIVATE, {}, RuntimeError(PRIVATE))
    settings = Mock(database_role=DatabaseRole.PROVISIONING)
    database = Mock()
    database.engine.begin.return_value = Mock(
        __aenter__=AsyncMock(side_effect=original),
        __aexit__=AsyncMock(return_value=False),
    )
    database.dispose = AsyncMock(side_effect=ValueError(PRIVATE))
    monkeypatch.setattr(bootstrap_postgres, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap_postgres, "_principal_contracts", lambda: (Mock(),) * 4)
    monkeypatch.setattr(bootstrap_postgres, "load_principal_manifest", Mock())
    monkeypatch.setattr(Database, "from_settings", Mock(return_value=database))
    with pytest.raises(OperationalError) as raised:
        asyncio.run(bootstrap_postgres.provision_database_principals())
    assert raised.value is original
    text = capsys.readouterr().err
    assert PRIVATE not in text
    diagnostics = [
        json.loads(line.removeprefix("M78_BOOTSTRAP_DIAGNOSTIC ")) for line in text.splitlines()
    ]
    assert [item["stage"] for item in diagnostics] == ["connection", "connection-dispose"]


def test_normal_operator_failed_bootstrap_recovers_via_real_db_guard_and_continues(
    tmp_path: Path,
) -> None:
    status, provider, ledger, errors = run_operator(tmp_path)
    assert status == 2 and "stage-paused" in errors
    arm_hash = ledger.cleanup_arm_evidence_sha256
    before = len(provider.commands)
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger)
    assert status == 2 and "plain retries" in errors
    assert len(provider.commands) == before
    status, _, _, errors = run_operator(
        tmp_path, provider=provider, ledger=ledger, operation="migrate"
    )
    assert status == 2 and len(provider.commands) == before
    provider.operation = "bootstrap"
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 0, errors
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert ledger.cleanup_arm_evidence_sha256 == arm_hash
    assert provider.events.count("retry-start") == 1
    assert provider.events.index("db-inspection") < provider.events.index("db-mutation")
    assert provider.db_mutations and "cleanup" not in provider.events
    completed = json.loads((tmp_path / "bootstrap-stage-recovery-completed.json").read_text())
    assert completed["marker"]["status"] == "retry-preflight-passed"
    assert completed["marker"]["state"] == "bootstrap-existing"
    provider.failure = "normal-success"
    provider.retry_execution = None
    provider.template = {}
    provider.execution = "migration-execution"
    status, _, _, errors = run_operator(
        tmp_path, provider=provider, ledger=ledger, operation="migrate"
    )
    assert status == 0, errors
    assert ledger.phase == Phase.MIGRATED.value
    assert "cleanup" not in provider.events


@pytest.mark.parametrize(
    "failure",
    [
        "unsafe-db-state",
        "missing-marker",
        "contradictory-marker",
        "same-execution",
        "wrong-final",
        "overcpu",
        "init-container",
    ],
)
def test_partial_unknown_or_mismatched_retry_remains_paused_without_admission(
    tmp_path: Path,
    failure: str,
) -> None:
    _, provider, ledger, _ = run_operator(tmp_path)
    provider.failure = failure
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2, errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value
    assert "cleanup" not in provider.events
    assert not (tmp_path / "bootstrap-stage-recovery-completed.json").exists()
    assert provider.events.count("retry-start") <= 1
    if failure in {"overcpu", "init-container"}:
        assert "retry-start" not in provider.events
    if failure == "unsafe-db-state":
        assert not provider.db_mutations
    prior_starts = provider.events.count("retry-start")
    run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert provider.events.count("retry-start") == prior_starts


def test_delayed_marker_reconciles_same_recorded_execution_without_mutation(tmp_path: Path) -> None:
    _, provider, ledger, _ = run_operator(tmp_path)
    provider.failure = "missing-marker"
    status, _, _, _ = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2 and ledger.phase == Phase.IMAGE_DECIDED.value
    assert provider.events.count("retry-start") == 1
    provider.failure = ""
    provider.retry_marker = provider.actual_retry_marker
    provider.clock_advance = 16 * 60  # Later readback never extends the earlier dispatch approval.
    mutation_count = len(provider.db_mutations)
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 0, errors
    assert provider.events.count("retry-start") == 1
    assert len(provider.db_mutations) == mutation_count
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert "cleanup" not in provider.events


@pytest.mark.parametrize("corruption", ["missing", "malformed", "mismatched"])
def test_original_dispatch_history_required_before_any_recovery_read(
    tmp_path: Path,
    corruption: str,
) -> None:
    _, provider, ledger, _ = run_operator(tmp_path)
    path = tmp_path / "bootstrap-stage-attempt.json"
    if corruption == "missing":
        path.unlink()
    elif corruption == "malformed":
        path.write_text("{}")
    else:
        original = json.loads(path.read_text())
        original["commandSha256"] = "1" * 64
        original["recordSha256"] = operator._stage_hash(
            "stage-attempt",
            {k: v for k, v in original.items() if k != "recordSha256"},
        )
        path.write_text(json.dumps(original))
    before = len(provider.commands)
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2 and len(provider.commands) == before, errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value and "cleanup" not in provider.events


def test_pause_write_failure_blocks_dependent_phase_and_plain_retry(tmp_path: Path) -> None:
    from infra.milestone_7_8.controller_renewal import _durable_record

    def persist(path: Path, document: object) -> None:
        if path.name.endswith("-stage-pause.json"):
            raise OSError(PRIVATE)
        _durable_record(path, document)

    with patch("infra.milestone_7_8.controller_renewal._durable_record", side_effect=persist):
        status, provider, ledger, errors = run_operator(tmp_path)
    assert status == 2 and "stage-pause-recording-incomplete" in errors
    assert "cleanup" not in provider.events
    before = len(provider.commands)
    for operation in ("bootstrap", "migrate"):
        status, _, _, _ = run_operator(
            tmp_path, provider=provider, ledger=ledger, operation=operation
        )
        assert status == 2 and len(provider.commands) == before


def test_expired_window_and_exhausted_budget_still_clean_up_despite_bad_pause(
    tmp_path: Path,
) -> None:
    _, provider, ledger, _ = run_operator(tmp_path)
    (tmp_path / "bootstrap-stage-pause.json").write_text("invalid")
    ledger.actual_cost_usd = "50"
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2, errors
    assert provider.events.count("cleanup") == 1
    assert ledger.phase == Phase.CLEANING.value


def test_retry_completion_after_campaign_deadline_enters_cleanup(tmp_path: Path) -> None:
    _, provider, ledger, _ = run_operator(tmp_path)
    provider.failure = "late-terminal"
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2, errors
    assert provider.events.count("cleanup") == 1
    assert ledger.phase == Phase.CLEANING.value
    assert not (tmp_path / "bootstrap-stage-recovery-completed.json").exists()


def test_retry_without_reviewed_cost_allowance_dispatches_nothing(tmp_path: Path) -> None:
    _, provider, ledger, _ = run_operator(tmp_path, allowance=False)
    before = len(provider.commands)
    status, _, _, errors = run_operator(
        tmp_path, provider=provider, ledger=ledger, resume=True, allowance=False
    )
    assert status == 2 and "cost allowance" in errors
    assert len(provider.commands) == before and "cleanup" not in provider.events


def test_authorization_expiry_during_retry_intent_persistence_prevents_dispatch(
    tmp_path: Path,
) -> None:
    from infra.milestone_7_8.controller_renewal import _durable_record

    _, provider, ledger, _ = run_operator(tmp_path)

    def persist(path: Path, document: object) -> None:
        _durable_record(path, document)
        if path.name == "bootstrap-stage-retry-intent.json":
            provider.clock_advance = 3

    def authorize(*_args: object, **_kwargs: object) -> None:
        if provider.clock_advance >= 3:
            raise CampaignError("phase authorization expired")

    with patch("infra.milestone_7_8.controller_renewal._durable_record", side_effect=persist):
        status, _, _, errors = run_operator(
            tmp_path, provider=provider, ledger=ledger, resume=True, authorization_check=authorize
        )
    assert status == 2 and "authorization expired" in errors
    assert "retry-start" not in provider.events and "cleanup" not in provider.events
    assert ledger.phase == Phase.IMAGE_DECIDED.value


def test_lost_retry_start_record_never_repeats_a_mutation(tmp_path: Path) -> None:
    from infra.milestone_7_8.controller_renewal import _durable_record

    _, provider, ledger, _ = run_operator(tmp_path)

    def persist(path: Path, document: object) -> None:
        if path.name == "bootstrap-stage-retry-start.json":
            raise OSError(PRIVATE)
        _durable_record(path, document)

    with patch("infra.milestone_7_8.controller_renewal._durable_record", side_effect=persist):
        status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2 and "record is uncertain" in errors
    assert provider.events.count("retry-start") == 1 and "cleanup" not in provider.events
    before = len(provider.commands)
    status, _, _, errors = run_operator(tmp_path, provider=provider, ledger=ledger, resume=True)
    assert status == 2 and len(provider.commands) == before
    assert provider.events.count("retry-start") == 1
    assert not (tmp_path / "bootstrap-stage-recovery-completed.json").exists()


def test_expired_cleanup_approval_after_job_failure_cannot_dispatch(tmp_path: Path) -> None:
    provider = FakeProvider(_runtime(), "expired")

    def authorize(*_args: object, **kwargs: object) -> None:
        if kwargs.get("operation") == "cleanup" and provider.expired:
            raise CampaignError("cleanup authorization expired")

    status, provider, ledger, errors = run_operator(
        tmp_path, provider=provider, authorization_check=authorize,
    )
    assert status == 2 and "container job evidence failed" in errors
    assert "cleanup-dispatch-blocked" in errors
    assert "cleanup authorization expired" in errors
    assert "cleanup" not in provider.events
    assert ledger.phase == Phase.IMAGE_DECIDED.value


@pytest.mark.parametrize("expires_after_reads", [False, True])
def test_cleanup_authorization_guards_runbook_and_direct_fallback_boundaries(
    expires_after_reads: bool,
) -> None:
    runtime = _runtime()
    config = _config(subscription_correlation=sanitize(
        runtime["subscriptionId"], domain="subscription",
    ))
    expired = not expires_after_reads
    commands: list[tuple[str, ...]] = []
    authorization_checks = 0

    class Provider:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            nonlocal expired
            commands.append(command)
            if command[:4] == ("az", "automation", "runbook", "start"):
                return result({}, 1)
            if command[:3] == ("az", "account", "show"):
                return result({"id": runtime["subscriptionId"]})
            if command[:3] == ("az", "group", "exists"):
                return result(True)
            assert command[:3] == ("az", "group", "show")
            expired = True  # The valid first approval expires during ownership readback.
            return result({
                "name": config.target_resource_group,
                "properties": {"provisioningState": "Succeeded"},
                "tags": {
                    "mobius.milestone": "7.8", "mobius.campaign": config.campaign_id,
                    "mobius.generation": config.generation_id,
                    "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
                    "mobius.cost-ceiling-cents": "5000",
                },
            })

    def authorize() -> None:
        nonlocal authorization_checks
        authorization_checks += 1
        if expired:
            raise CampaignError("cleanup authorization expired")

    with pytest.raises(CampaignError, match="cleanup authorization expired"):
        operator.start_failure_cleanup(
            cast(SubprocessRunner, Provider()), config, runtime, before_dispatch=authorize,
        )
    assert len(commands) == (4 if expires_after_reads else 0)
    assert authorization_checks == (2 if expires_after_reads else 1)
    assert not any(command[:3] == ("az", "group", "delete") for command in commands)


def test_expired_dry_run_refuses_without_dispatching_cleanup(tmp_path: Path) -> None:
    provider = FakeProvider(_runtime())
    provider.expired = True
    status, provider, ledger, errors = run_operator(
        tmp_path, provider=provider, execute=False,
    )
    assert status == 2 and "cleanup deadline is expired" in errors
    assert not provider.commands
    assert "cleanup" not in provider.events
    assert ledger.phase == Phase.IMAGE_DECIDED.value


def test_deadline_expiring_during_diagnostics_requires_current_authorized_cleanup(
    tmp_path: Path,
) -> None:
    status, provider, ledger, errors = run_operator(tmp_path, "diagnostic-expiry")
    assert status == 2 and "container job evidence failed" in errors
    assert provider.events == [
        "start", "failed-execution", "replicas", "workspace", "logs", "cleanup",
    ]
    assert ledger.phase == Phase.CLEANING.value
    assert (tmp_path / "bootstrap-stage-pause.json").is_file()
    assert len(list(tmp_path.glob("job-failure-*/console.json"))) == 1


class EmptyOptionalTemplateProvider(FakeProvider):
    """Replay the retained job-null versus execution-empty ARM response forms."""

    def __init__(self, *, empty_before: bool, drift_at: str = "", drift: str = "") -> None:
        super().__init__(_runtime())
        self.empty_before = empty_before
        self.drift_at = drift_at
        self.drift = drift

    def shape(self, response: dict[str, object], *, boundary: str) -> dict[str, object]:
        document = json.loads(str(response["stdout"]))
        template = document["properties"]["template"]
        template["initContainers"] = None
        template["volumes"] = None
        if boundary == "terminal" or (boundary == "original" and self.empty_before):
            template["initContainers"] = []
            template.pop("volumes")
        if boundary == self.drift_at:
            container = template["containers"][0]
            if self.drift == "volumes":
                template["volumes"] = [{"name": "unexpected", "storageType": "EmptyDir"}]
            elif self.drift == "initContainers":
                template["initContainers"] = [{"name": "unexpected", "image": "invalid"}]
            elif self.drift == "malformed":
                template["volumes"] = ""
            elif self.drift == "environment":
                container["env"].append({"name": "UNREVIEWED", "value": "changed"})
            elif self.drift == "image":
                container["image"] = "registry.invalid/app@sha256:" + "e" * 64
            elif self.drift == "command":
                container["command"] = ["python", "-m", "scripts.unreviewed"]
            elif self.drift == "resources":
                container["resources"]["cpu"] = 0.25
            else:
                raise AssertionError("unexpected synthetic drift")
        return {**response, "stdout": json.dumps(document)}

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        response = super().run(command)
        if command[:4] == ("az", "containerapp", "job", "show"):
            return self.shape(response, boundary="before")
        return response

    def execution_result(self, name: str, status: str) -> dict[str, object]:
        response = super().execution_result(name, status)
        return self.shape(
            response, boundary="terminal" if name == self.retry_execution else "original",
        )


@pytest.mark.parametrize("empty_before", [False, True])
def test_normal_retry_accepts_only_empty_optional_template_shape_changes(
    tmp_path: Path, empty_before: bool,
) -> None:
    provider = EmptyOptionalTemplateProvider(empty_before=empty_before)
    status, _, ledger, errors = run_operator(tmp_path, provider=provider)
    assert status == 2 and "stage-paused" in errors
    status, _, ledger, errors = run_operator(
        tmp_path, provider=provider, ledger=ledger, resume=True,
    )
    assert status == 0, errors
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert provider.events.count("retry-start") == 1
    assert "cleanup" not in provider.events
    intent = json.loads((tmp_path / "bootstrap-stage-retry-intent.json").read_text())
    raw_job = intent["validatedJob"]["properties"]["template"]
    assert raw_job["initContainers"] is None and raw_job["volumes"] is None
    completed = json.loads((tmp_path / "bootstrap-stage-recovery-completed.json").read_text())
    capture = tmp_path / completed["capture"]
    execution = json.loads((capture / "execution.json").read_text())
    raw_terminal = json.loads(execution["lastResult"]["stdout"])["properties"]["template"]
    assert raw_terminal["initContainers"] == [] and "volumes" not in raw_terminal
    assert completed["captureFilesSha256"]["execution.json"] == hashlib.sha256(
        (capture / "execution.json").read_bytes()
    ).hexdigest()


@pytest.mark.parametrize("boundary", ["before", "terminal"])
@pytest.mark.parametrize(
    "drift",
    ["volumes", "initContainers", "malformed", "environment", "image", "command", "resources"],
)
def test_normal_retry_still_rejects_substantive_template_drift(
    tmp_path: Path, boundary: str, drift: str,
) -> None:
    provider = EmptyOptionalTemplateProvider(empty_before=True, drift_at=boundary, drift=drift)
    _, _, ledger, _ = run_operator(tmp_path, provider=provider)
    status, _, ledger, errors = run_operator(
        tmp_path, provider=provider, ledger=ledger, resume=True,
    )
    assert status == 2, errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value
    assert provider.events.count("retry-start") == int(boundary == "terminal")
    assert "cleanup" not in provider.events
    assert not (tmp_path / "bootstrap-stage-recovery-completed.json").exists()

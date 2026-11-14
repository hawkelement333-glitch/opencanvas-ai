from __future__ import annotations

import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from test_milestone_7_8_campaign_enablement import _config, _runtime, _write_execution_authorization

from infra.milestone_7_8 import (
    cleanup_controller,
    evidence_console,
    measurement_handoff,
    operator,
    replica_readback,
)
from infra.milestone_7_8.campaign import ORDER, CampaignConfig, Ledger, Phase

SUBSCRIPTION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
GROUP = "rg-m78-aabbccddee-target"
APP = "app-m78-aabbccddee"
OLD = f"{APP}--old"
WORKER = "job-proof-worker"
SAMPLER = "job-proof-evidence"
WORKSPACE = "law-proof"
DIGEST = "sha256:" + "e" * 64
GROUP_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}"
APP_ID = f"{GROUP_ID}/providers/Microsoft.App/containerApps/{APP}"
CONTROL = {
    "primaryZone": "1", "standbyZone": "2", "haMode": "ZoneRedundant",
    "maintenanceDay": 2, "maintenanceHour": 3, "storageGiB": 64, "storageTier": "P6",
    "backupRetentionDays": 7, "geoBackup": False, "azureReservedConnections": 5,
    "poolCeilings": 80, "rolloutOverlap": 40, "operatorConsumers": 2,
    "safetyReserve": 20, "maxConnections": 200,
}
RUNTIME = {
    **_runtime(),
    "subscriptionId": SUBSCRIPTION,
    "sourceHead": "a" * 40,
    "resourceGroupName": GROUP,
    "runbookName": "Remove-M78Campaign",
    "workerJobName": WORKER,
    "evidenceJobName": SAMPLER,
    "logAnalyticsWorkspaceName": WORKSPACE,
    "apiProbeJobName": "job-proof-api-probe",
    "workerProbeJobName": "job-proof-worker-probe",
    "migrationProbeJobName": "job-proof-migration-probe",
    "recoveryJobName": "job-proof-revoke",
    "recoveryRestoreJobName": "job-proof-restore",
    "postgresServerName": "pg-proof",
    "campaignId": _config().campaign_id,
    "generationId": _config().generation_id,
}


def _result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


class FakeProvider:
    def __init__(self, failure: str | None) -> None:
        self.failure = failure
        self.commands: list[tuple[str, ...]] = []
        self.base = datetime(2030, 1, 1, tzinfo=UTC)
        self.elapsed = 0.0
        self.new_revision: str | None = None
        self.worker_reads = 0
        self.sampler_runs: dict[str, tuple[float, str]] = {}
        self.log_queries: dict[str, int] = {}
        self.operations_input: dict[str, object] | None = None

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds

    def timestamp(self, elapsed: float) -> str:
        return (self.base + timedelta(seconds=elapsed)).isoformat()

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        if "--subscription" in command:
            assert command[command.index("--subscription") + 1] == SUBSCRIPTION
        else:
            assert command[:2] == ("az", "rest")
            assert f"/subscriptions/{SUBSCRIPTION}/" in command[command.index("--url") + 1]

        def option(name: str) -> str:
            return command[command.index(name) + 1]

        if command[:4] == ("az", "containerapp", "job", "show"):
            job = option("--name")
            return _result({
                "id": f"{GROUP_ID}/providers/Microsoft.App/jobs/{job}",
                "properties": {"template": {"containers": [{
                    "name": "evidence", "image": f"registry.azurecr.io/mobius-api@{DIGEST}",
                    "command": ["python", "-m", "scripts.managed_postgres_evidence"],
                    "args": ["--phase", "catalog"],
                    "resources": {"cpu": 2, "memory": "4Gi"},
                    "env": [{"name": "OPENCANVAS_DATABASE_ROLE", "value": "observability"}],
                }]}},
            })
        if command[:4] == ("az", "containerapp", "job", "start"):
            job = option("--name")
            if job == WORKER:
                return self.execution(job, "worker-execution")
            if "--yaml" in command:
                template = json.loads(Path(option("--yaml")).read_text())
                container = template["containers"][0]
                assert container["image"].endswith(f"@{DIGEST}")
                assert container["command"] == ["python", "-m", "scripts.managed_postgres_evidence"]
                assert container["resources"] == {"cpu": 2, "memory": "4Gi"}
                variables = {item["name"]: item["value"] for item in container["env"]}
                assert variables["OPENCANVAS_DATABASE_ROLE"] == "observability"
                if container["args"] == ["--phase=measurement-sample"]:
                    execution = f"sampler-execution-{len(self.sampler_runs) + 1}"
                    self.sampler_runs[execution] = (
                        self.elapsed, variables["M78_MEASUREMENT_TOKEN"],
                    )
                    return self.execution(job, execution)
                if container["args"] == ["--phase=operations"]:
                    self.operations_input = json.loads(variables["M78_CONTROL_PLANE_EVIDENCE"])
            return self.execution(job, f"proof-{len(self.commands)}", "Succeeded")
        if command[:5] == ("az", "containerapp", "job", "execution", "show"):
            execution = option("--job-execution-name")
            start, _ = self.sampler_runs[execution]
            status = "Succeeded" if self.elapsed >= start + 3 else "Running"
            return self.execution(SAMPLER, execution, status)
        if command[:4] == ("az", "monitor", "log-analytics", "workspace"):
            assert option("--workspace-name") == WORKSPACE
            return _result({
                "id": f"{GROUP_ID}/providers/Microsoft.OperationalInsights/workspaces/{WORKSPACE}",
                "customerId": SUBSCRIPTION,
            })
        if command[:4] == ("az", "monitor", "log-analytics", "query"):
            assert option("--workspace") == SUBSCRIPTION
            query = option("--analytics-query")
            execution = next(name for name in self.sampler_runs if f"'{name}-'" in query)
            started, token = self.sampler_runs[execution]
            assert token in query
            self.log_queries[execution] = self.log_queries.get(execution, 0) + 1
            if self.log_queries[execution] == 1:
                return _result([])
            if self.failure == "stale":
                started -= 40
            overlap = execution.endswith("-2")
            latencies = [11.0, 29.0] if overlap else [4.0, 9.0]
            times = [self.timestamp(started + offset) for offset in (1.25, 2.25)]
            sample = {
                "version": "m7.8-raw-measurement-sample-v1", "status": "blocked-unverified",
                "startedAtUtc": self.timestamp(started + 0.25),
                "endedAtUtc": self.timestamp(started + 2.75),
                "connectionSamples": 2, "connectionObservationTimesUtc": times,
                "observedRuntimeConnectionPeak": 91 if overlap else 32,
                "applicationRequests": 2, "applicationRequestTimesUtc": times,
                "applicationRequestDurationsMs": latencies, "applicationP95Ms": max(latencies),
            }
            replica = f"{execution}-x"
            if self.failure == "wrong-execution":
                replica = "another-execution-x"
            return _result([{
                "replica": replica, "message": f"M78_MEASUREMENT {token} {json.dumps(sample)}",
            }])
        if command[:2] == ("az", "rest"):
            return self.inventory(urlsplit(option("--url")).path)
        if command[:4] == ("az", "containerapp", "revision", "copy"):
            assert option("--from-revision") == OLD
            if self.failure != "missing-overlap":
                self.new_revision = f"{APP}--{option('--revision-suffix')}"
            return _result({})
        if command[:4] == ("az", "containerapp", "revision", "deactivate"):
            assert option("--revision") == self.new_revision
            self.new_revision = None
            return _result({})
        if command[:4] == ("az", "containerapp", "job", "stop"):
            assert option("--job-execution-name") == "worker-execution"
            return _result({})
        if command[:4] in {
            ("az", "containerapp", "revision", "set-mode"),
            ("az", "containerapp", "ingress", "traffic"),
            ("az", "postgres", "flexible-server", "restart"),
        }:
            return _result({})
        raise AssertionError(f"unexpected provider command: {command[:5]}")

    def inventory(self, path: str) -> dict[str, object]:
        if path == f"{APP_ID}/revisions":
            active = [OLD] + ([self.new_revision] if self.new_revision else [])
            return _result({"value": [
                {"id": f"{path}/{name}", "name": name, "properties": {"active": True}}
                for name in active
            ]})
        if path.endswith("/executions/worker-execution/replicas"):
            self.worker_reads += 1
            state = "NotRunning" if self.worker_reads == 1 else "Running"
            if self.failure == "worker-stopped" and self.worker_reads > 3:
                state = "NotRunning"
            return self.replicas(path, state)
        if path.startswith(f"{APP_ID}/revisions/") and path.endswith("/replicas"):
            return self.replicas(path, "Running")
        raise AssertionError(f"unexpected inventory path: {path}")

    @staticmethod
    def execution(job: str, execution: str, status: str = "Running") -> dict[str, object]:
        return _result({
            "id": f"{GROUP_ID}/providers/Microsoft.App/jobs/{job}/executions/{execution}",
            "name": execution, "properties": {"status": status},
        })

    @staticmethod
    def replicas(path: str, state: str) -> dict[str, object]:
        scope = path.split("/")[-2]
        return _result({"value": [
            {
                "id": f"{path}/{scope}-{i}", "name": f"{scope}-{i}",
                "properties": {"runningState": state},
            }
            for i in range(4)
        ]})


class TestMeasurementHandoff(unittest.TestCase):
    def run_operator(
        self, directory: Path, failure: str | None = None,
        *, operation: str = "evidence", ledger: Ledger | None = None, save_fails: bool = False,
    ) -> tuple[int, FakeProvider, Ledger, Mock, str]:
        from test_milestone_7_8_disruption_operator import FakeCampaignEvidence

        provider = FakeCampaignEvidence()
        provider.failure = failure
        config = _config(cleanup_deadline_utc="2030-01-01T01:00:00Z")
        if ledger is None:
            ledger = Ledger(config.campaign_id, config.generation_id)
            ledger.bind_cleanup_region(config)
            ledger.bind_deadline(config.cleanup_deadline_utc)
            for phase in ORDER[1 : ORDER.index(Phase.MIGRATED) + 1]:
                if phase is Phase.CLEANUP_ARMED:
                    ledger.record_cleanup_arm_evidence("a" * 64)
                if phase is Phase.IMAGE_DECIDED:
                    ledger.record_image(DIGEST, built=True)
                    ledger.record_image_scan(DIGEST, "b" * 64)
                ledger.transition(phase, provider.base)
        _write_execution_authorization(
            directory / "auth", config, RUNTIME,
            expires_at="2030-01-01T01:30:00Z", operations=[operation, "cleanup"],
        )
        control = directory / "control.json"
        control.write_text(json.dumps({**CONTROL, "observedPeak": 1, "latencyP95Ms": 0}))
        argv = [
            "operator", operation, "--execute", "--config", str(directory / "config"),
            "--runtime", str(directory / "runtime"), "--ledger", str(directory / "ledger"),
            "--authorization", str(directory / "auth"), "--control-plane-evidence", str(control),
        ]

        class Clock(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> Clock:
                now = provider.base + timedelta(seconds=provider.elapsed)
                return cls.fromtimestamp(now.timestamp(), tz)

        errors = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(patch.object(
                CampaignConfig, "from_json", return_value=config,
            ))
            stack.enter_context(patch.object(operator, "load_runtime", return_value=RUNTIME))
            stack.enter_context(patch.object(operator, "validate_prepared_bundle"))
            stack.enter_context(patch.object(operator, "load_bound_fresh_controller_admission"))
            stack.enter_context(patch.object(operator, "load_ledger", return_value=ledger))
            stack.enter_context(patch.object(operator, "SubprocessRunner", return_value=provider))
            stack.enter_context(patch.object(
                operator, "save_ledger",
                side_effect=OSError("synthetic ledger persistence failure") if save_fails else None,
            ))
            cleanup = stack.enter_context(patch.object(operator, "start_failure_cleanup"))
            for module in (operator, cleanup_controller, measurement_handoff,
                           replica_readback, evidence_console):
                stack.enter_context(patch.object(module, "datetime", Clock))
            stack.enter_context(patch.object(time, "sleep", provider.sleep))
            stack.enter_context(patch.object(
                time, "monotonic", lambda: provider.elapsed,
            ))
            stack.enter_context(redirect_stderr(errors))
            stack.enter_context(redirect_stdout(io.StringIO()))
            status = operator.main()
        return status, provider, ledger, cleanup, errors.getvalue()

    def test_normal_evidence_phase_uses_two_bound_measurement_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            status, provider, ledger, cleanup, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            self.assertGreater(provider.worker_reads, 2)
            self.assertEqual(len(provider.sampler_runs), 2)
            self.assertIsNotNone(provider.operations_input)
            assert provider.operations_input is not None
            self.assertEqual(provider.operations_input["observedPeak"], 91)
            self.assertEqual(provider.operations_input["latencyP95Ms"], 29.0)
            self.assertTrue(provider.operations_input["failoverObserved"])
            self.assertTrue(any(command[:4] == ("az", "containerapp", "job", "stop")
                                for command in provider.commands))
            self.assertIsNone(provider.new_revision)
            cleanup.assert_not_called()
            self.assertEqual(ledger.phase, Phase.EVIDENCE_EXECUTED.value)
            receipt = json.loads((directory / "managed-evidence-execution.json").read_text())
            self.assertEqual(receipt["measurement"]["workerExecution"], "worker-execution")
            self.assertEqual(receipt["measurement"]["steady"]["apiRevisions"], [OLD])
            self.assertEqual(len(receipt["measurement"]["overlap"]["apiRevisions"]), 2)
            self.assertEqual(receipt["measurement"]["observedPeak"], 91)
            self.assertEqual(len(receipt["observations"]), 12)

    def test_missing_or_mismatched_measurement_preserves_armed_cleanup_and_pauses(self) -> None:
        for failure, error in (
            ("wrong-execution", "exact execution"),
            ("stale", "timestamps are stale"),
            ("worker-stopped", "four running workers"),
            ("missing-overlap", "intended revision"),
        ):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                status, provider, ledger, cleanup, errors = self.run_operator(directory, failure)
                self.assertEqual(status, 2, errors)
                self.assertIn(error, errors)
                self.assertIsNone(provider.operations_input)
                self.assertFalse((directory / "managed-evidence-execution.json").exists())
                cleanup.assert_not_called()
                self.assertEqual(ledger.phase, Phase.MIGRATED.value)
                self.assertEqual(ledger.cleanup_arm_evidence_sha256, "a" * 64)
                pause = operator._read_stage_record(
                    directory / "evidence-stage-pause.json", "stage-pause",
                )
                self.assertEqual(pause["operation"], "evidence")
                bindings = pause["bindings"]
                self.assertIsInstance(bindings, dict)
                assert isinstance(bindings, dict)
                self.assertEqual(bindings["sourceHead"], RUNTIME["sourceHead"])
                self.assertEqual(bindings["imageDigest"], DIGEST)
                self.assertEqual(bindings["cleanupArmSha256"], "a" * 64)
                self.assertTrue((directory / "managed-evidence-attempt.json").exists())

    def test_interrupted_attempt_does_not_start_another_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "managed-evidence-attempt.json").write_text("{}", encoding="utf-8")
            status, provider, _, cleanup, errors = self.run_operator(directory)
            self.assertEqual(status, 2, errors)
            self.assertIn("attempt already exists", errors)
            self.assertFalse(provider.commands)
            cleanup.assert_not_called()

    def test_receipt_resume_reconciles_failed_ledger_save_and_allows_dispose(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            status, _, _, cleanup, errors = self.run_operator(directory, save_fails=True)
            self.assertEqual(status, 2, errors)
            self.assertIn("synthetic ledger persistence failure", errors)
            cleanup.assert_not_called()
            receipt_path = directory / "managed-evidence-execution.json"
            pause_path = directory / "evidence-stage-pause.json"
            receipt_before, pause_before = receipt_path.read_bytes(), pause_path.read_bytes()
            status, provider, ledger, cleanup, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            self.assertFalse(provider.commands)
            self.assertEqual(ledger.phase, Phase.EVIDENCE_EXECUTED.value)
            cleanup.assert_not_called()
            status, provider, ledger, cleanup, errors = self.run_operator(
                directory, operation="dispose", ledger=ledger,
            )
            self.assertEqual(status, 0, errors)
            self.assertEqual(ledger.phase, Phase.DISPOSED.value)
            self.assertFalse(provider.commands)
            cleanup.assert_not_called()
            self.assertEqual(receipt_path.read_bytes(), receipt_before)
            self.assertEqual(pause_path.read_bytes(), pause_before)

    def test_receipt_resume_rejects_missing_or_altered_stage_history_and_other_pauses(self) -> None:
        for defect in ("missing-attempt", "altered-attempt", "another-pause", "wrong-source"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                status, _, _, _, errors = self.run_operator(directory, save_fails=True)
                self.assertEqual(status, 2, errors)
                attempt_path = directory / "evidence-stage-attempt.json"
                if defect == "missing-attempt":
                    attempt_path.unlink()
                elif defect == "altered-attempt":
                    attempt = json.loads(attempt_path.read_text())
                    attempt["bindings"]["sourceHead"] = "b" * 40
                    unsigned = {key: value for key, value in attempt.items()
                                if key != "recordSha256"}
                    attempt["recordSha256"] = operator._stage_hash("stage-attempt", unsigned)
                    attempt_path.write_text(json.dumps(attempt), encoding="utf-8")
                elif defect == "another-pause":
                    (directory / "bootstrap-stage-pause.json").write_text("{}", encoding="utf-8")
                else:
                    receipt_path = directory / "managed-evidence-execution.json"
                    receipt = json.loads(receipt_path.read_text())
                    receipt["sourceHead"] = "b" * 40
                    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
                status, provider, ledger, cleanup, errors = self.run_operator(directory)
                self.assertEqual(status, 2, errors)
                self.assertFalse(provider.commands)
                self.assertEqual(ledger.phase, Phase.MIGRATED.value)
                cleanup.assert_not_called()

    def test_historical_receipt_only_resume_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            status, _, _, _, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            (directory / "evidence-stage-attempt.json").unlink()
            status, provider, ledger, cleanup, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            self.assertFalse(provider.commands)
            self.assertEqual(ledger.phase, Phase.EVIDENCE_EXECUTED.value)
            cleanup.assert_not_called()
            self.assertFalse((directory / "evidence-stage-recovery-completed.json").exists())

    def test_completed_receipt_resumes_without_a_second_provider_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            status, _, _, _, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            status, provider, ledger, cleanup, errors = self.run_operator(directory)
            self.assertEqual(status, 0, errors)
            self.assertFalse(provider.commands)
            cleanup.assert_not_called()
            self.assertEqual(ledger.phase, Phase.EVIDENCE_EXECUTED.value)


if __name__ == "__main__":
    unittest.main()

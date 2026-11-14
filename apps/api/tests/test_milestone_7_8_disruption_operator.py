from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from scripts.managed_postgres_evidence import validate_control_plane_evidence
from test_milestone_7_8_campaign_enablement import _config, _write_execution_authorization
from test_milestone_7_8_measurement_handoff import (
    CONTROL,
    DIGEST,
    GROUP_ID,
    RUNTIME,
    WORKER,
    FakeProvider,
    _result,
)

from infra.milestone_7_8 import (
    cleanup_controller,
    evidence_console,
    measurement_handoff,
    operator,
    replica_readback,
)
from infra.milestone_7_8.campaign import (
    ORDER,
    CampaignConfig,
    CampaignError,
    Ledger,
    Phase,
    load_ledger,
    save_ledger,
)

CONFIG = _config(cleanup_deadline_utc="2030-01-01T01:00:00Z")
PHASE_CODES = {
    "api": {"catalog.roles", "catalog.runtime-grants", "capacity.max-connections"},
    "worker": {"catalog.roles", "catalog.runtime-grants", "capacity.max-connections"},
    "catalog": {"catalog.roles", "catalog.ownership", "catalog.public-restrictions"},
    "application": {
        "idempotency.canvas", "idempotency.node", "idempotency.duplicate-node", "idempotency.edge",
        "idempotency.conflict-409", "idempotency.authority-revalidation", "tenant.pool-reuse",
        "tenant.forged-workspace", "tenant.forged-canvas", "tenant.forged-replay",
        "tenant.forged-evidence-bundle", "tenant.forged-workflow",
    },
    "migration": {
        "migration.nullpool", "migration.advisory-lock", "migration.exact-revision",
        "migration.reconciliation", "idempotency.canvas", "idempotency.node",
        "idempotency.duplicate-node", "idempotency.edge",
    },
    "credential-denied": {"recovery.credential-revocation"},
    "failover-window": {
        "recovery.failover", "recovery.stale-pool", "tenant.post-failover", "idempotency.canvas",
        "idempotency.node", "idempotency.duplicate-node", "idempotency.edge",
        "idempotency.authority-revalidation",
    },
}


@dataclass
class Execution:
    job: str
    phase: str
    template: dict[str, object]
    env: dict[str, str]
    started: float


class FakeCampaignEvidence(FakeProvider):
    """Retain the existing real sampler fixture and add exact managed probe readbacks."""

    def __init__(self, defect: str | None = None) -> None:
        super().__init__(None)
        self.defect = defect
        self.probes: dict[str, Execution] = {}
        self.events: list[str] = []
        self.failover_at: float | None = None
        self.ready_at: float | None = None
        self.operations_input: dict[str, object] | None = None

    def template(self, job: str) -> dict[str, object]:
        slot = {
            RUNTIME["apiProbeJobName"]: "api", RUNTIME["workerProbeJobName"]: "worker",
            RUNTIME["migrationProbeJobName"]: "migration", RUNTIME["evidenceJobName"]: "catalog",
            RUNTIME["recoveryJobName"]: "revoke", RUNTIME["recoveryRestoreJobName"]: "restore",
        }[job]
        mutation = slot in {"revoke", "restore"}
        role = "provisioning" if mutation else "observability" if slot == "catalog" else slot
        command = ["python", "-m", "scripts.credential_recovery_probe" if mutation
                   else "scripts.managed_postgres_evidence"]
        return {"containers": [{
            "name": {"catalog": "evidence", "revoke": "credential-recovery",
                     "restore": "credential-restore"}.get(slot, f"probe-{slot}"),
            "command": [*command, slot] if mutation else command,
            "args": None if mutation else ["--phase", slot],
            "resources": {"cpu": 2, "memory": "4Gi"} if slot == "catalog"
                else {"cpu": 0.5, "memory": "1Gi"},
            "image": f"registry.azurecr.io/mobius-api@{DIGEST}",
            "env": [{"name": "OPENCANVAS_DATABASE_ROLE", "value": role}],
        }]}

    def sample_result(
        self, green: bool, elapsed: float, progressed: bool = False,
    ) -> dict[str, object]:
        latest = self.timestamp(elapsed if progressed else (self.ready_at or elapsed))
        return {
            "observedAtUtc": self.timestamp(elapsed),
            "apiReadPassed": green, "apiWritePassed": green,
            "workerDatabaseActive": green,
            "workerObservedAtUtc": self.timestamp(elapsed) if green else None,
            "workerClaims": 3 if progressed else 1,
            "workerOutcomes": 2 if progressed else 1,
            "workerLatestClaimAtUtc": latest,
            "workerLatestOutcomeAtUtc": latest,
            "evidenceSha256": "a" * 64,
        }

    def payload(self, phase: str, execution: Execution) -> dict[str, object]:
        if phase in {"revoke", "restore"}:
            return {
                "version": "m7.8-credential-recovery-observation-v1", "status": "observed",
                "campaignId": CONFIG.campaign_id, "generationId": CONFIG.generation_id,
                "mode": phase, "loginEnabled": phase == "restore",
                "activeSessions": 0 if phase == "revoke" else None,
                "terminatedSessions": 4 if phase == "revoke" else None,
            }
        if phase == "operations":
            control = execution.env["M78_CONTROL_PLANE_EVIDENCE"]
            if self.defect == "wrong-operations-input":
                control = json.dumps({**json.loads(control), "observedPeak": 12})
            return {
                "version": "m7.8-managed-postgres-evidence-v1", "status": "passed",
                "observedAtUtc": self.timestamp(self.elapsed),
                "assertions": [asdict(item) for item in validate_control_plane_evidence(
                    control,
                )],
            }
        codes = PHASE_CODES[phase]
        if phase == "credential-denied" and self.defect == "wrong-denial-code":
            codes = {"catalog.roles"}
        value: dict[str, object] = {
            "version": "m7.8-managed-postgres-evidence-v1", "status": "passed",
            "observedAtUtc": self.timestamp(self.elapsed),
            "assertions": [{"code": code, "passed": True, "observed_count": 1,
                            "evidence_sha256": "a" * 64} for code in sorted(codes)],
        }
        if phase == "failover-window":
            assert self.failover_at is not None and self.ready_at is not None
            observations = [
                self.sample_result(True, self.ready_at),
                self.sample_result(self.defect == "no-disruption", self.failover_at + 1),
                self.sample_result(True, self.failover_at + 6, progressed=True),
            ]
            if self.defect == "stale-worker-recovery":
                observations[-1]["workerLatestOutcomeAtUtc"] = self.timestamp(self.ready_at)
            value["disruption"] = {
                "version": "m7.8-failover-window-v1",
                "startedAtUtc": self.timestamp(execution.started),
                "readyAtUtc": self.timestamp(self.ready_at),
                "endedAtUtc": self.timestamp(self.elapsed), "observations": observations,
                "workerClaimsObserved": True, "workerRecoveryObserved": True,
                "ambiguousReplayVerified": True, "tenantIsolationVerified": True,
                "replayEvidenceSha256": "b" * 64, "tenantEvidenceSha256": "c" * 64,
            }
        return value

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        def option(name: str) -> str:
            return command[command.index(name) + 1]

        def evidence_result(value: object) -> dict[str, object]:
            subscription = RUNTIME["subscriptionId"]
            if "--subscription" in command:
                assert option("--subscription") == subscription
            else:
                assert command[:2] == ("az", "rest")
                assert urlsplit(option("--url")).path.startswith(f"/subscriptions/{subscription}/")
            self.commands.append(command)
            return _result(value)

        if command[:4] == ("az", "containerapp", "job", "show"):
            job = option("--name")
            return evidence_result({"id": f"{GROUP_ID}/providers/Microsoft.App/jobs/{job}",
                                    "properties": {"template": self.template(job)}})
        if command[:4] == ("az", "containerapp", "job", "start") and "--yaml" in command:
            job = option("--name")
            assert option("--subscription") == RUNTIME["subscriptionId"]
            assert option("--resource-group") == RUNTIME["resourceGroupName"]
            template = json.loads(Path(option("--yaml")).read_text())
            item = template["containers"][0]
            args = item.get("args") or []
            if args == ["--phase=measurement-sample"]:
                return super().run(command)
            env = {row["name"]: row["value"] for row in item["env"]}
            assert re.fullmatch(r"[0-9a-f]{32}", env["M78_EVIDENCE_TOKEN"])
            if item["command"][-1] in {"revoke", "restore"}:
                phase = item["command"][-1]
            elif args in (["revoke"], ["restore"]):
                phase = args[0]
            elif args[0] == "--phase":
                phase = args[1]
            else:
                phase = args[0].removeprefix("--phase=")
            assert item["image"].endswith("@" + DIGEST)
            self.events.append(f"start:{phase}")
            if phase == "failover-window":
                assert job == RUNTIME["migrationProbeJobName"]
                assert env["M78_FAILOVER_WORKER_EXECUTION"] == "worker-execution"
            if phase == "operations":
                self.operations_input = json.loads(env["M78_CONTROL_PLANE_EVIDENCE"])
            name = f"proof-execution-{len(self.probes) + 1}"
            self.probes[name] = Execution(job, phase, template, env, self.elapsed)
            self.commands.append(command)
            return self.execution(job, name, self.status(name))
        if command[:5] == ("az", "containerapp", "job", "execution", "show"):
            name = option("--job-execution-name")
            if name in self.probes:
                self.commands.append(command)
                return self.execution(self.probes[name].job, name, self.status(name))
        if command[:2] == ("az", "rest"):
            path = urlsplit(option("--url")).path
            match = re.search(r"/executions/([^/]+)(/replicas)?$", path)
            if match and match[1] in self.probes:
                name, suffix = match.groups()
                execution = self.probes[name]
                if suffix:
                    return evidence_result({"value": [{"id": f"{path}/{name}-0",
                        "name": f"{name}-0", "properties": {"runningState": "Running"}}]})
                response = self.execution(execution.job, name, self.status(name))
                value = json.loads(str(response["stdout"]))
                value["properties"]["template"] = execution.template
                return evidence_result(value)
        if command[:4] == ("az", "monitor", "log-analytics", "query"):
            query = option("--analytics-query")
            possible = next((name for name in self.probes if f"'{name}-0'" in query), None)
            if possible is not None:
                execution = self.probes[possible]
                phase = execution.phase
                token = execution.env["M78_EVIDENCE_TOKEN"]
                assert token in query
                self.events.append(f"marker:{phase}")
                marker = "M78_EVIDENCE"
                payload: dict[str, object]
                if "M78_FAILOVER_READY" in query:
                    self.ready_at = self.elapsed - (1 if self.defect == "stale-ready" else 0)
                    marker = "M78_FAILOVER_READY"
                    payload = {
                        "version": "m7.8-failover-ready-v1",
                        "observedAtUtc": self.timestamp(self.ready_at),
                        "workerExecution": "another-worker" if self.defect == "wrong-ready-worker"
                        else "worker-execution",
                    }
                    self.sleep(0.25)
                else:
                    payload = self.payload(phase, execution)
                if phase == "credential-denied" and self.defect == "missing-denial-marker":
                    return evidence_result([])
                replica = "foreign-replica" if phase == "credential-denied" and (
                    self.defect == "wrong-denial-replica"
                ) else f"{possible}-0"
                row = {"replica": replica, "message": f"{marker} {token} {json.dumps(payload)}"}
                if phase == "credential-denied" and self.defect == "duplicate-denial-marker":
                    return evidence_result([row, row])
                return evidence_result([row])
        if command[:4] == ("az", "postgres", "flexible-server", "restart"):
            assert self.failover_at is None and self.ready_at is not None
            assert option("--name") == RUNTIME["postgresServerName"]
            assert option("--resource-group") == RUNTIME["resourceGroupName"]
            assert option("--failover") == "Forced"
            self.events.append("failover")
            self.failover_at = self.elapsed
            self.sleep(3)
            return evidence_result({"status": "Succeeded"})
        if command[:4] == ("az", "containerapp", "job", "stop"):
            self.events.append("stop:worker")
        return super().run(command)

    def status(self, execution: str) -> str:
        if self.probes[execution].phase == "failover-window" and (
            self.failover_at is None or self.elapsed < self.failover_at + 7
        ):
            if self.defect == "probe-stopped-after-ready" and self.ready_at is not None:
                return "Failed"
            return "Running"
        return "Succeeded"


@pytest.mark.parametrize("defect", [None, "wrong-denial-code", "missing-denial-marker",
                                    "duplicate-denial-marker", "wrong-denial-replica",
                                    "no-disruption", "stale-ready", "wrong-ready-worker",
                                    "probe-stopped-after-ready", "stale-worker-recovery",
                                    "wrong-operations-input"])
def test_operator_requires_exact_managed_probe_and_disruption_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str | None,
) -> None:
    provider = FakeCampaignEvidence(defect)
    config = CONFIG
    runtime = {**RUNTIME, "campaignId": config.campaign_id, "generationId": config.generation_id}
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
    ledger_path = tmp_path / "ledger.json"
    save_ledger(ledger_path, ledger)
    authorization = tmp_path / "auth.json"
    _write_execution_authorization(authorization, config, runtime,
                                   expires_at="2030-01-01T01:30:00Z",
                                   operations=["evidence", "cleanup"])
    control_path = tmp_path / "control.json"
    control_path.write_text(json.dumps(CONTROL), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "operator", "evidence", "--execute", "--config", str(tmp_path / "config.json"),
        "--runtime", str(tmp_path / "runtime.json"), "--ledger", str(ledger_path),
        "--authorization", str(authorization), "--control-plane-evidence", str(control_path),
    ])
    monkeypatch.setattr(CampaignConfig, "from_json", lambda *_a, **_kw: config)
    monkeypatch.setattr(operator, "load_runtime", lambda _: runtime)
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    monkeypatch.setattr(operator, "SubprocessRunner", lambda **_kw: provider)

    def forbid_cleanup(*_args: object) -> None:
        pytest.fail("a recoverable/incomplete evidence phase must retain scheduled cleanup")

    monkeypatch.setattr(operator, "start_failure_cleanup", forbid_cleanup)

    class Clock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Clock:
            current = provider.base + timedelta(seconds=provider.elapsed)
            return cls.fromtimestamp(current.timestamp(), tz)

    for module in (operator, cleanup_controller, measurement_handoff,
                   replica_readback, evidence_console):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(time, "sleep", provider.sleep)
    monkeypatch.setattr(time, "monotonic", lambda: provider.elapsed)
    assert operator.main() == (0 if defect is None else 2)
    final = load_ledger(ledger_path, config)
    assert final.cleanup_arm_evidence_sha256 == ledger.cleanup_arm_evidence_sha256
    assert not any("delete" in command for command in provider.commands)
    assert provider.events.count("start:revoke") == provider.events.count("start:restore") == 1
    assert provider.events.count("stop:worker") == 1
    assert provider.events.index("start:revoke") < provider.events.index("start:restore")
    assert any(command[:4] == ("az", "containerapp", "job", "start")
               and WORKER in command for command in provider.commands)
    receipt = tmp_path / "managed-evidence-execution.json"
    if defect is None:
        assert final.phase == Phase.EVIDENCE_EXECUTED
        assert provider.failover_at is not None and provider.operations_input is not None
        assert provider.events.index("start:failover-window") < provider.events.index("failover")
        assert provider.events.index("failover") < provider.events.index("stop:worker")
        assert len(provider.probes) == 11
        assert provider.operations_input["observedPeak"] == 91
        assert provider.operations_input["latencyP95Ms"] == 29.0
        assert float(str(provider.operations_input["recoverySeconds"])) >= 6
        admitted = replace(config, image_digest=DIGEST)
        operator.validate_evidence_execution_receipt(
            receipt, config=admitted, runtime=runtime, control_plane_evidence=CONTROL,
        )
        proof_path = tmp_path / "managed-assertion-evidence.json"
        proof = json.loads(proof_path.read_text())
        proof["workerBefore"]["pages"][0]["value"][0]["properties"]["runningState"] = "NotRunning"
        proof["evidenceSha256"] = evidence_console.evidence_hash({
            key: value for key, value in proof.items() if key != "evidenceSha256"
        })
        proof_path.write_text(json.dumps(proof))
        record = json.loads(receipt.read_text())
        record["assertionEvidenceSha256"] = proof["evidenceSha256"]
        receipt.write_text(json.dumps(record))
        with pytest.raises(CampaignError, match="failover worker replicas"):
            operator.validate_evidence_execution_receipt(
                receipt, config=admitted, runtime=runtime, control_plane_evidence=CONTROL,
            )
    else:
        assert final.phase == Phase.MIGRATED
        assert not receipt.exists()
        assert (provider.operations_input is not None) is (defect == "wrong-operations-input")
        assert (tmp_path / "evidence-stage-pause.json").is_file()
        assert provider.events.count("failover") == int(defect in {
            "no-disruption", "stale-worker-recovery", "wrong-operations-input",
        })

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from test_milestone_7_8_campaign_enablement import _config, _runtime
from test_milestone_7_8_job_diagnostics import DIGEST, NOW, FakeProvider, run_operator

from infra.milestone_7_8 import bootstrap_transition, operator
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, CostItem, Phase
from infra.milestone_7_8.cleanup_controller import ARCHITECTURE

ORIGINAL = "c83ffb4544aae52b1b6e60e0662f4d9ab3fd0622"
CORRECTED = "f" * 40


def write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.title() for part in rest)


@dataclass
class Case:
    directory: Path
    runtime: dict[str, str]
    config: CampaignConfig
    provider: FakeProvider
    ledger: Mock
    transition: Path
    originals: dict[Path, bytes]

    def invoke(
        self, *, operation: str = "bootstrap", resume: bool = True, execute: bool = True,
    ) -> tuple[int, FakeProvider, Mock, str]:
        return run_operator(
            self.directory, provider=self.provider, ledger=self.ledger, resume=resume,
            operation=operation, execute=execute, runtime_override=self.runtime,
            extra_arguments=("--bootstrap-source-transition", str(self.transition)),
        )


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    config = replace(
        cast(Callable[[], CampaignConfig], _config)(),
        cleanup_deadline_utc="2030-01-01T01:00:00Z",
        conservative_estimate_usd="25.754075",
    )
    config = replace(config, resource_items=(
        *config.resource_items, CostItem("database-recovery-job-allowance", "0", 1, "0.0567"),
    ))
    config_document = {camel(key): value for key, value in asdict(config).items()}
    config_document["resourceItems"] = [
        {camel(key): value for key, value in asdict(item).items()}
        for item in config.resource_items
    ]
    runtime = _runtime()
    runtime["sourceHead"] = ORIGINAL
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    runtime["cleanupAuthorityExpiresUtc"] = operator.runtime_authority_expiry(config)
    write(tmp_path / "runtime", runtime)
    write(tmp_path / "config", config_document)
    unsigned = {
        "version": "m7.8-execution-authorization-v5",
        "disposition": "separately-authorized-azure-execution",
        "campaignId": config.campaign_id, "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": ORIGINAL, "controllerArchitecture": ARCHITECTURE,
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "controllerAuthorityEvidenceSha256": runtime["controllerAuthorityEvidenceSha256"],
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "freshControllerAdmissionEvidenceVersion": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "expiresAtUtc": runtime["cleanupAuthorityExpiresUtc"],
        "allowedOperations": ["bootstrap", "cleanup"],
    }
    write(tmp_path / "authorization", {**unsigned, "authorizationSha256": hashlib.sha256(
        b"m7.8/execution-authorization/v5\0"
        + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()})
    status, provider, ledger, errors = run_operator(tmp_path, runtime_override=runtime)
    assert status == 2 and "stage-paused" in errors
    assert ledger.phase == Phase.IMAGE_DECIDED.value and "cleanup" not in provider.events
    provider.clock_advance = 20 * 60  # Original dispatch window has expired.
    image = {
        "sourceHead": ORIGINAL, "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
        "imageDigest": DIGEST,
    }
    image_path = write(tmp_path / "image-admission.json", {
        **image, "version": "m7.8-local-image-result-v1",
    })
    scan_path = write(tmp_path / "scan.json", {
        **image, "version": "m7.8-image-admission-v1", "scanner": "synthetic",
        "scannerVersion": "fixture", "result": "passed", "criticalFindings": 0,
        "highFindings": 0, "scannedAtUtc": NOW.isoformat(),
    })
    ledger.image_scan_evidence_sha256 = file_hash(scan_path)
    patch_path = tmp_path / "reviewed.patch"
    patch_path.write_text("synthetic reviewed optional-field correction\n", encoding="utf-8")
    patch_sha = file_hash(patch_path)
    monkeypatch.setattr(bootstrap_transition, "REVIEWED_PATCH_SHA256", patch_sha)
    def synthetic_source(old: str, new: str) -> dict[str, str]:
        if (old, new) != (ORIGINAL, CORRECTED):
            raise CampaignError("corrected source boundary differs")
        return {
            "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
            "cleanupScriptSha256": runtime["cleanupScriptSha256"],
            "protectedStashesSha256": "e" * 64,
        }

    monkeypatch.setattr(bootstrap_transition, "inspect_transition_source", synthetic_source)
    validation_path = write(tmp_path / "validation.json", {
        "status": "passed", "originalSourceHead": ORIGINAL, "patchSha256": patch_sha,
        "operatorSourceHead": CORRECTED,
        "completedAtUtc": (NOW + timedelta(minutes=19, seconds=59)).isoformat(),
        "checks": [{"name": "normal-operator-regression", "status": "passed"}],
    })
    approval_path = write(tmp_path / "explicit-approval.json", {
        "approved": True, "originalSourceHead": ORIGINAL, "patchSha256": patch_sha,
        "maximumRecoveryMinutes": 15, "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "allowedOperations": ["bootstrap-retry", "post-retry-campaign", "cleanup"],
    })
    transition_path = tmp_path / "bootstrap-source-transition.json"
    document = bootstrap_transition.build_transition(
        runtime_path=tmp_path / "runtime", config_path=tmp_path / "config",
        attempt_path=tmp_path / "bootstrap-stage-attempt.json",
        pause_path=tmp_path / "bootstrap-stage-pause.json",
        original_authorization_path=tmp_path / "authorization",
        image_admission_path=image_path, scan_path=scan_path,
        validation_receipt_path=validation_path, explicit_approval_path=approval_path,
        patch_path=patch_path, corrected_source_head=CORRECTED,
        issued_at=(NOW + timedelta(minutes=20)).isoformat(),
        expires_at=(NOW + timedelta(minutes=35)).isoformat(),
    )
    write(transition_path, document)
    originals = {path: path.read_bytes() for path in (
        tmp_path / "runtime", tmp_path / "config", tmp_path / "authorization",
        tmp_path / "bootstrap-stage-attempt.json", tmp_path / "bootstrap-stage-pause.json",
        image_path, scan_path,
    )}
    return Case(tmp_path, runtime, config, provider, ledger, transition_path, originals)


def test_normal_operator_transition_retries_once_and_preserves_originals(case: Case) -> None:
    status, provider, ledger, errors = case.invoke()
    assert status == 0, errors
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert provider.events.count("retry-start") == 1
    assert provider.events.index("db-inspection") < provider.events.index("db-mutation")
    assert "cleanup" not in provider.events
    completed = json.loads((case.directory / "bootstrap-stage-recovery-completed.json").read_text())
    assert completed["operatorSourceHead"] == CORRECTED
    assert completed["sourceHead"] == ORIGINAL
    assert completed["bootstrapSourceTransitionSha256"]
    assert all(path.read_bytes() == value for path, value in case.originals.items())
    status, _, _, _ = case.invoke()
    assert status == 2 and provider.events.count("retry-start") == 1
    provider.failure = "normal-success"
    provider.retry_execution = None
    provider.template = {}
    provider.execution = "migration-execution"
    status, _, _, errors = case.invoke(operation="migrate", resume=False)
    assert status == 0, errors
    assert ledger.phase == Phase.MIGRATED.value
    before = len(provider.commands)
    status, _, _, errors = case.invoke(operation="evidence", resume=False, execute=False)
    assert status == 0, errors
    assert len(provider.commands) == before
    assert all(path.read_bytes() == value for path, value in case.originals.items())


@pytest.mark.parametrize("operation", ["migrate", "evidence"])
def test_missing_retry_completion_blocks_downstream(case: Case, operation: str) -> None:
    before = len(case.provider.commands)
    status, _, _, _ = case.invoke(operation=operation, resume=False)
    assert status == 2
    assert len(case.provider.commands) == before
    assert case.provider.events.count("retry-start") == 0


def test_expired_new_dispatch_window_cannot_start_retry(case: Case) -> None:
    case.provider.clock_advance = 36 * 60
    status, _, _, _ = case.invoke()
    assert status == 2 and case.provider.events.count("retry-start") == 0
    assert not (case.directory / "bootstrap-stage-retry-intent.json").exists()


def test_later_read_only_completion_does_not_restart_expired_transition(case: Case) -> None:
    case.provider.failure = "missing-marker"
    status, _, _, _ = case.invoke()
    assert status == 2 and case.provider.events.count("retry-start") == 1
    mutations = list(case.provider.db_mutations)
    case.provider.failure = ""
    case.provider.retry_marker = case.provider.actual_retry_marker
    case.provider.clock_advance = 36 * 60
    status, _, ledger, errors = case.invoke()
    assert status == 0, errors
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert case.provider.events.count("retry-start") == 1
    assert case.provider.db_mutations == mutations
    assert "cleanup" not in case.provider.events


@pytest.mark.parametrize("corruption", ["missing", "wrong-transition"])
def test_lost_or_mismatched_transition_completion_blocks_next_phase(
    case: Case, corruption: str,
) -> None:
    assert case.invoke()[0] == 0
    path = case.directory / "bootstrap-stage-recovery-completed.json"
    if corruption == "missing":
        path.unlink()
    else:
        record = json.loads(path.read_text())
        record["bootstrapSourceTransitionSha256"] = "1" * 64
        record["recordSha256"] = operator._stage_hash(
            "stage-recovery-completed",
            {key: value for key, value in record.items() if key != "recordSha256"},
        )
        write(path, record)
    before = len(case.provider.commands)
    status, _, _, _ = case.invoke(operation="migrate", resume=False)
    assert status == 2 and len(case.provider.commands) == before
    assert case.provider.events.count("retry-start") == 1


@pytest.mark.parametrize("filename", [
    "runtime", "config", "authorization", "bootstrap-stage-attempt.json",
    "bootstrap-stage-pause.json", "image-admission.json", "scan.json", "reviewed.patch",
    "validation.json", "explicit-approval.json",
])
def test_altered_bound_artifact_cannot_reach_provider(case: Case, filename: str) -> None:
    path = case.directory / filename
    path.write_bytes(path.read_bytes() + b"\n")
    before = len(case.provider.commands)
    status, _, _, _ = case.invoke()
    assert status == 2
    assert len(case.provider.commands) == before
    assert case.provider.events.count("retry-start") == 0


def test_changed_source_observation_cannot_reach_provider(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def changed_source(_old: str, _new: str) -> dict[str, str]:
        raise CampaignError("corrected source boundary differs")

    monkeypatch.setattr(bootstrap_transition, "inspect_transition_source", changed_source)
    before = len(case.provider.commands)
    status, _, _, _ = case.invoke()
    assert status == 2 and len(case.provider.commands) == before


def test_direct_original_bootstrap_remains_compatible(tmp_path: Path) -> None:
    status, provider, ledger, errors = run_operator(tmp_path, failure="normal-success")
    assert status == 0, errors
    assert ledger.phase == Phase.DATABASE_BOOTSTRAPPED.value
    assert provider.events.count("start") == 1 and "retry-start" not in provider.events


def rebuild(case: Case) -> dict[str, object]:
    document = json.loads(case.transition.read_text())
    directory = case.directory
    return bootstrap_transition.build_transition(
        runtime_path=directory / "runtime", config_path=directory / "config",
        attempt_path=directory / "bootstrap-stage-attempt.json",
        pause_path=directory / "bootstrap-stage-pause.json",
        original_authorization_path=directory / "authorization",
        image_admission_path=directory / "image-admission.json", scan_path=directory / "scan.json",
        validation_receipt_path=directory / "validation.json",
        explicit_approval_path=directory / "explicit-approval.json",
        patch_path=directory / "reviewed.patch", corrected_source_head=CORRECTED,
        issued_at=document["issuedAtUtc"], expires_at=document["expiresAtUtc"],
    )


@pytest.mark.parametrize(("filename", "field", "value"), [
    ("explicit-approval.json", "approved", False),
    ("explicit-approval.json", "maximumRecoveryMinutes", 16),
    ("explicit-approval.json", "allowedOperations", ["bootstrap-retry", "deploy", "cleanup"]),
    ("validation.json", "operatorSourceHead", "1" * 40),
    ("validation.json", "completedAtUtc", "2030-01-01T00:21:00Z"),
    ("validation.json", "checks", [{"name": "regression", "status": "failed"}]),
    ("image-admission.json", "imageDigest", "sha256:" + "1" * 64),
    ("scan.json", "highFindings", 1),
])
def test_builder_rejects_semantically_wrong_approval_or_proof(
    case: Case, filename: str, field: str, value: object,
) -> None:
    path = case.directory / filename
    document = json.loads(path.read_text())
    document[field] = value
    write(path, document)
    with pytest.raises(CampaignError):
        rebuild(case)


@pytest.mark.parametrize("field", [
    "operatorSourceHead", "originalAttemptSha256", "imageDigest", "canonicalBuildInputSha256",
    "cleanupScriptSha256", "protectedStashesSha256", "explicitApprovalSha256",
])
def test_self_consistent_transition_hash_cannot_override_bound_history(
    case: Case, field: str,
) -> None:
    document = json.loads(case.transition.read_text())
    document[field] = (
        "1" * 40 if field == "operatorSourceHead"
        else "sha256:" + "1" * 64 if field == "imageDigest" else "1" * 64
    )
    document["transitionSha256"] = bootstrap_transition._hash(
        bootstrap_transition.DOMAIN,
        {key: value for key, value in document.items() if key != "transitionSha256"},
    )
    write(case.transition, document)
    before = len(case.provider.commands)
    status, _, _, _ = case.invoke()
    assert status == 2 and len(case.provider.commands) == before


@pytest.mark.parametrize("record", [
    "bootstrap-stage-retry-intent.json", "bootstrap-stage-retry-start.json",
    "bootstrap-stage-recovery-completed.json",
])
def test_new_transition_cannot_reset_an_existing_retry(case: Case, record: str) -> None:
    write(case.directory / record, {"recorded": "earlier-dispatch"})
    with pytest.raises(CampaignError):
        rebuild(case)


@pytest.mark.parametrize("fault", [
    "", "wrong-head", "wrong-parent", "unreviewed-path", "image-inputs", "cleanup-script",
    "stash-count",
])
def test_actual_source_inspector_enforces_exact_operator_only_child(
    monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    script = b"cleanup-content"
    monkeypatch.setattr(bootstrap_transition, "local_source_binding", lambda: (
        "1" * 40 if fault == "wrong-head" else CORRECTED,
        hashlib.sha256(script).hexdigest(),
    ))

    def git(*arguments: str, binary: bool = False) -> str | bytes:
        if arguments[:1] == ("rev-list",):
            return CORRECTED + " " + ("1" * 40 if fault == "wrong-parent" else ORIGINAL)
        if arguments[:1] == ("diff",):
            return ("apps/api/Dockerfile" if fault == "unreviewed-path"
                    else "infra/milestone_7_8/operator.py")
        if arguments[:1] == ("show",):
            assert binary
            return b"changed-script" if fault == "cleanup-script" else script
        assert arguments == ("stash", "list", "--format=%H")
        return "\n".join(str(index) * 40 for index in range(4 if fault == "stash-count" else 5))

    monkeypatch.setattr(bootstrap_transition, "_git", git)
    monkeypatch.setattr(bootstrap_transition, "canonical_snapshot", lambda head: {
        "buildInputSha256": "1" * 64 if fault == "image-inputs" and head == CORRECTED else "b" * 64,
    })
    if fault:
        with pytest.raises(CampaignError):
            bootstrap_transition.inspect_transition_source(ORIGINAL, CORRECTED)
    else:
        result = bootstrap_transition.inspect_transition_source(ORIGINAL, CORRECTED)
        assert result["canonicalBuildInputSha256"] == "b" * 64
        assert result["cleanupScriptSha256"] == hashlib.sha256(script).hexdigest()

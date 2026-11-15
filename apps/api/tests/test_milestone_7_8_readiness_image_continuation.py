from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from test_milestone_7_8_campaign_enablement import _runtime
from test_milestone_7_8_image_continuation import Clock, document, write
from test_milestone_7_8_image_replacement_ledger import image_decided
from test_milestone_7_8_workload_image_update import NEW, NOW, OLD, Provider, fixture

from infra.milestone_7_8 import campaign, local_image, operator, workload_image_update
from infra.milestone_7_8 import image_continuation as continuation
from infra.milestone_7_8.campaign import CampaignError, Phase, load_ledger, save_ledger
from infra.milestone_7_8.cleanup_controller import ARCHITECTURE

HEAD = "e" * 40


@pytest.fixture
def case(tmp_path, monkeypatch):
    folder = tmp_path / ".runtime/milestone_7_8/readiness"
    folder.mkdir(parents=True)
    monkeypatch.setattr(continuation, "ROOT", tmp_path)
    partial, config, _ = fixture(folder)
    runtime = {**_runtime(), **partial, "sourceHead": "a" * 40}
    runtime_path = write(folder / "runtime.json", runtime)
    config_path = write(folder / "config.json", document(config))
    ledger = image_decided(config)
    ledger.transition(Phase.DATABASE_BOOTSTRAPPED, NOW)
    ledger.transition(Phase.MIGRATED, NOW)
    ledger_path = folder / "ledger.json"
    save_ledger(ledger_path, ledger)
    commands = tuple(
        (*cmd, "--subscription", runtime["subscriptionId"])
        for cmd in operator.command_plan(
            "evidence",
            config,
            runtime,
            control_plane_evidence="<derived-after-successful-managed-probes>",
        )
    )
    bindings = operator._stage_bindings(replace(config, image_digest=OLD), runtime, ledger)
    attempt = operator._stage_record(
        folder / "evidence-stage-attempt.json",
        "stage-attempt",
        {
            "version": "m7.8-protected-stage-attempt-v1",
            "operation": "evidence",
            "bindings": bindings,
            "commandSha256": operator._stage_hash("stage-command", commands),
            "authorizationSha256": "d" * 64,
            "startedAtUtc": NOW.isoformat(),
        },
    )
    operator._stage_record(
        folder / "evidence-stage-pause.json",
        "stage-pause",
        {
            "version": "m7.8-protected-stage-pause-v1",
            "operation": "evidence",
            "bindings": bindings,
            "attemptSha256": attempt["recordSha256"],
            "authorizationSha256": "d" * 64,
            "failedExecution": None,
            "failedAtUtc": NOW.isoformat(),
            "recoveryUntilUtc": NOW.isoformat(),
            "maximumRetryDispatches": 1,
        },
    )
    for name in (
        "managed-evidence-attempt.json",
        "local-image/completed.json",
        "local-image/image-scan.json",
    ):
        write(folder / name, {"original": True})
    for index, field in enumerate(("workerJobName", "evidenceJobName"), 1):
        job, execution = runtime[field], runtime[field] + "-execution"
        resource_id = (
            f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
            f"{config.target_resource_group}/providers/Microsoft.App/jobs/{job}"
            f"/executions/{execution}"
        )
        scope_args = [
            "--name",
            job,
            "--resource-group",
            config.target_resource_group,
            "--subscription",
            runtime["subscriptionId"],
        ]
        write(
            folder / f"phases/evidence-first/{index:03}-intent.json",
            {
                "command": ["az", "containerapp", "job", "start", *scope_args],
            },
        )
        write(
            folder / f"phases/evidence-first/{index:03}-result.json",
            {
                "exitCode": 0,
                "stdout": json.dumps({"id": resource_id, "name": execution}),
            },
        )
        write(
            folder
            / f"measurement-failure-diagnosis/terminal-reconciliation/{index:02}-intent.json",
            {
                "command": [
                    "az",
                    "containerapp",
                    "job",
                    "execution",
                    "show",
                    *scope_args,
                    "--job-execution-name",
                    execution,
                ],
            },
        )
        write(
            folder
            / f"measurement-failure-diagnosis/terminal-reconciliation/{index:02}-result.json",
            {
                "exitCode": 0,
                "stdout": json.dumps(
                    {
                        "id": resource_id,
                        "name": execution,
                        "properties": {
                            "status": "Stopped" if field == "workerJobName" else "Failed",
                            "template": {
                                "containers": [
                                    {
                                        "image": (
                                            f"{runtime['registryName']}.azurecr.io/mobius-api@{OLD}"
                                        ),
                                        "args": []
                                        if field == "workerJobName"
                                        else ["--phase=measurement-sample"],
                                    }
                                ]
                            },
                        },
                    }
                ),
            },
        )
    retained_path = write(folder / "retained-image.json", {"syntheticArchiveFixture": True})
    budget = write(
        folder / "budget.json",
        {
            "approvedFreshBundleCeilingUsd": config.authorized_ceiling_usd,
            "activeExecutionHours": config.maximum_hours,
            "priorForecastPreservedUsd": "100.00",
            "approvedAggregateCeilingUsd": "164.38",
        },
    )
    authority = {
        "version": "m7.8-readiness-image-source-authority-v1",
        "originalRuntimeSourceHead": runtime["sourceHead"],
        "parentSourceHead": "f" * 40,
        "sourceHead": HEAD,
        "canonicalBuildInputSha256": "b" * 64,
        "cleanupScriptSha256": runtime["cleanupScriptSha256"],
        "allowedChangedPaths": ["apps/api/app/db/runtime.py"],
        "budgetApprovalFile": str(budget),
        "budgetApprovalSha256": continuation._file_hash(budget),
        "replacementCoveredByApprovedBudget": True,
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "authorizedCeilingUsd": config.authorized_ceiling_usd,
        "maximumHours": config.maximum_hours,
        "allowedOperations": sorted(continuation.READINESS_OPERATIONS),
        "issuedAtUtc": NOW.isoformat(),
        "expiresAtUtc": config.cleanup_deadline_utc,
    }
    authority["authoritySha256"] = hashlib.sha256(
        b"m7.8/readiness-image-source-authority/v1\0"
        + json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    authority_path = write(folder / "source-authority.json", authority)
    monkeypatch.setattr(continuation, "_readiness_source", lambda plan: HEAD)
    monkeypatch.setattr(
        continuation,
        "load_retained_image",
        lambda *a, **k: {
            "imageId": NEW,
            "imageBuildSourceHead": HEAD,
        },
    )
    monkeypatch.setattr(operator, "load_runtime", lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *a: None)
    monkeypatch.setattr(operator, "_verify_retry_protection", lambda *a: [])
    monkeypatch.setattr(continuation, "datetime", Clock)
    monkeypatch.setattr(operator, "datetime", Clock)
    plan = continuation.build_readiness_plan(
        runtime_path,
        config_path,
        ledger_path,
        retained_image=retained_path,
        source_authority=authority_path,
    )
    plan_path = write(folder / "readiness-correction/plan.json", plan)
    scope = workload_image_update._scope(runtime, config, OLD, NEW)
    provider = Provider(runtime, config, scope)
    monkeypatch.setattr(campaign, "SubprocessRunner", lambda **k: provider)

    def local_completion(path, image_runtime, image_config, **kwargs):
        assert image_runtime["sourceHead"] == HEAD
        assert image_runtime["canonicalBuildInputSha256"] == "b" * 64
        assert runtime["sourceHead"] == "a" * 40
        return 0

    monkeypatch.setattr(local_image, "validate_completion", local_completion)
    scan = write(
        plan_path.parent / "local-image/image-scan.json",
        {
            "version": "m7.8-image-admission-v1",
            "sourceHead": HEAD,
            "canonicalBuildInputSha256": "b" * 64,
            "imageDigest": NEW,
            "scanner": "Docker Scout",
            "scannerVersion": "v1",
            "scannedAtUtc": NOW.isoformat(),
            "result": "passed",
            "criticalFindings": 0,
            "highFindings": 0,
        },
    )
    unsigned = {
        "version": "m7.8-execution-authorization-v6",
        "authorizedCeilingUsd": config.authorized_ceiling_usd,
        "maximumHours": config.maximum_hours,
        "disposition": "separately-authorized-azure-execution",
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": runtime["sourceHead"],
        "controllerArchitecture": ARCHITECTURE,
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "controllerAuthorityEvidenceSha256": runtime["controllerAuthorityEvidenceSha256"],
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "freshControllerAdmissionEvidenceVersion": runtime[
            "freshControllerAdmissionEvidenceVersion"
        ],
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "expiresAtUtc": runtime["cleanupAuthorityExpiresUtc"],
        "allowedOperations": ["image-decision", "cleanup"],
    }
    authorization = write(
        folder / "authorization.json",
        {
            **unsigned,
            "authorizationSha256": hashlib.sha256(
                b"m7.8/execution-authorization/v6\0"
                + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
    )
    return folder, runtime, config, ledger, plan_path, scan, authorization, provider


def test_readiness_admission_preserves_migrated_database_history_and_frozen_runtime(case):
    folder, runtime, config, ledger, plan, scan, auth, provider = case
    original = {
        name: (folder / name).read_bytes()
        for name in (
            "runtime.json",
            "config.json",
            "evidence-stage-attempt.json",
            "evidence-stage-pause.json",
        )
    }
    transitions = list(ledger.transitions)
    assert (
        continuation.execute_admission(
            plan,
            runtime,
            config,
            ledger,
            digest=NEW,
            scan_path=scan,
            authorization=auth,
            execute=True,
        )
        == 0
    )
    actual = load_ledger(folder / "ledger.json", config)
    assert actual.phase == Phase.MIGRATED and actual.transitions == transitions
    assert actual.image_digest == NEW and actual.image_scan_count == 2
    assert actual.image_replacement["replacementPhase"] == Phase.MIGRATED.value
    assert actual.resource_generation_count == 1 and actual.image_generation_count == 0
    assert provider.patches == 10
    assert all(command[3] in {"get", "patch"} for command in provider.commands)
    assert all((folder / name).read_bytes() == value for name, value in original.items())
    link = continuation.validate_readiness_evidence_origin(
        folder,
        replace(config, image_digest=NEW),
        runtime,
        actual,
    )
    assert link["originalBindings"]["imageDigest"] == OLD
    assert link["continuationSha256"] == actual.image_replacement["continuationSha256"]
    actual.transition(Phase.EVIDENCE_EXECUTED, NOW + timedelta(minutes=3))
    assert (
        continuation.validate_readiness_evidence_origin(
            folder,
            replace(config, image_digest=NEW),
            runtime,
            actual,
        )
        == link
    )


def test_readiness_image_context_changes_only_explicit_source_and_canonical(case):
    folder, runtime, config, ledger, path, *_ = case
    loaded = continuation.load_plan(path)
    assert continuation._effective(loaded) == (runtime, config)
    _, image_runtime, image_config = continuation.image_evidence_context(path)
    assert image_config == config
    assert {key for key in runtime if runtime[key] != image_runtime[key]} == {
        "sourceHead",
        "canonicalBuildInputSha256",
    }
    image_plan = {
        "continuationFile": str(path),
        "continuationPlanSha256": loaded["planSha256"],
        "retainedImage": {
            "imageId": NEW,
            "imageBuildSourceHead": HEAD,
            "provenanceFile": str(folder / "retained-image.json"),
        },
    }
    continuation.validate_image_request(
        image_runtime,
        config,
        ledger,
        image_plan,
        {"expiresAtUtc": config.cleanup_deadline_utc},
        NOW,
    )
    with pytest.raises(CampaignError, match="context differs"):
        continuation.validate_image_request(
            runtime, config, ledger, image_plan, {"expiresAtUtc": config.cleanup_deadline_utc}, NOW
        )


@pytest.mark.parametrize("operation", ["bootstrap", "migrate", "startup"])
def test_readiness_continuation_never_replays_completed_database_setup(case, operation):
    folder, _, _, _, plan, *_ = case
    with pytest.raises(CampaignError, match="operation, files"):
        continuation.load_context(
            plan,
            folder / "runtime.json",
            folder / "config.json",
            folder / "ledger.json",
            operation=operation,
        )


def test_readiness_history_tampering_fails_closed(case):
    folder, _, _, _, path, *_ = case
    target = folder / "evidence-stage-pause.json"
    target.write_text(target.read_text() + " ")
    with pytest.raises(CampaignError, match="original evidence changed"):
        continuation.load_plan(path)


@pytest.mark.parametrize(
    "change", ["acceptance-phase", "running-worker", "wrong-start", "unknown-start"]
)
def test_readiness_rejects_nonmeasurement_or_unreconciled_dispatch(case, change):
    folder, _, _, _, path, *_ = case
    plan = json.loads(path.read_text())
    if change in {"wrong-start", "unknown-start"}:
        captured = folder / "phases/evidence-first/002-result.json"
    else:
        stem = "02" if change == "acceptance-phase" else "01"
        captured = (
            folder / f"measurement-failure-diagnosis/terminal-reconciliation/{stem}-result.json"
        )
    envelope = json.loads(captured.read_text())
    value = json.loads(envelope["stdout"])
    if change == "acceptance-phase":
        value["properties"]["template"]["containers"][0]["args"] = ["--phase=application"]
    elif change == "running-worker":
        value["properties"]["status"] = "Running"
    elif change == "wrong-start":
        value["name"] += "-other"
        value["id"] += "-other"
    else:
        envelope["exitCode"] = 1
    envelope["stdout"] = json.dumps(value)
    write(captured, envelope)
    plan["boundFilesSha256"][str(captured)] = continuation._file_hash(captured)
    plan["planSha256"] = continuation._hash({k: v for k, v in plan.items() if k != "planSha256"})
    write(path, plan)
    with pytest.raises(CampaignError):
        continuation.load_plan(path)


def test_readiness_plan_cannot_omit_original_evidence(case):
    folder, _, _, _, path, *_ = case
    plan = json.loads(path.read_text())
    del plan["boundFilesSha256"][str(folder / "local-image/completed.json")]
    plan["planSha256"] = continuation._hash({k: v for k, v in plan.items() if k != "planSha256"})
    write(path, plan)
    with pytest.raises(CampaignError, match="omitted original evidence"):
        continuation.load_plan(path)


def test_updater_retains_original_tags_but_uses_current_renewed_deadline(tmp_path, monkeypatch):
    from infra.milestone_7_8 import campaign_deadline_renewal

    runtime, original, _ = fixture(tmp_path)
    current = replace(original, cleanup_deadline_utc="2030-01-01T05:00:00Z")
    monkeypatch.setattr(campaign_deadline_renewal, "origin_context", lambda *a: (runtime, original))
    scope = workload_image_update._scope(runtime, current, OLD, NEW)
    assert scope["cleanupDeadlineUtc"] == current.cleanup_deadline_utc
    assert scope["configSha256"] == workload_image_update._hash(current.binding_document())
    provider = Provider(runtime, original, scope)
    for target in scope["targets"]:
        workload_image_update._validate_resource(
            provider.states[target["id"]], target, scope, runtime, current, OLD
        )


def test_standard_saved_ledger_loads_image_context_with_omitted_optional_fields(case):
    folder, _, config, ledger, path, *_ = case
    raw = json.loads((folder / "ledger.json").read_text())
    assert "image_replacement" not in raw
    loaded_runtime, loaded_config, loaded_ledger = continuation.load_context(
        path,
        folder / "runtime.json",
        folder / "config.json",
        folder / "ledger.json",
        operation="image",
    )
    assert loaded_runtime["sourceHead"] == HEAD
    assert loaded_config == config and loaded_ledger == ledger


def _successor(case, monkeypatch, previous, digest, head):
    folder = case[0]
    previous_plan = continuation.load_plan(previous)
    number = int(previous_plan.get("readinessSequence", 1)) + 1
    target = folder / f"rc{number:02d}"
    authority = continuation._read(Path(previous_plan["sourceAuthorityFile"]))
    authority.update(parentSourceHead=previous_plan["sourceHead"], sourceHead=head)
    authority.pop("authoritySha256")
    authority["authoritySha256"] = hashlib.sha256(
        b"m7.8/readiness-image-source-authority/v1\0"
        + json.dumps(authority, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source_authority = write(target / "source-authority.json", authority)
    retained = write(target / "retained.json", {"fixture": head})
    monkeypatch.setattr(continuation, "_readiness_source", lambda plan: plan["sourceHead"])
    monkeypatch.setattr(
        continuation,
        "load_retained_image",
        lambda *a, **k: {
            "imageId": digest,
            "imageBuildSourceHead": head,
        },
    )
    monkeypatch.setattr(local_image, "validate_completion", lambda *a, **k: 0)
    plan = continuation.build_readiness_plan(
        folder / "runtime.json",
        folder / "config.json",
        folder / "ledger.json",
        retained_image=retained,
        source_authority=source_authority,
        previous_plan=previous,
    )
    path = write(target / "plan.json", plan)
    scan = write(
        target / "local-image/image-scan.json",
        {
            "version": "m7.8-image-admission-v1",
            "sourceHead": head,
            "canonicalBuildInputSha256": "b" * 64,
            "imageDigest": digest,
            "scanner": "Docker Scout",
            "scannerVersion": "v1",
            "scannedAtUtc": NOW.isoformat(),
            "result": "passed",
            "criticalFindings": 0,
            "highFindings": 0,
        },
    )
    return path, scan


def test_successive_readiness_corrections_preserve_chain_and_original_pause(case, monkeypatch):
    from dataclasses import asdict

    folder, runtime, config, ledger, first, scan, auth, provider = case
    continuation.execute_admission(
        first, runtime, config, ledger, digest=NEW, scan_path=scan, authorization=auth, execute=True
    )
    first_files = {p: p.read_bytes() for p in first.parent.rglob("*") if p.is_file()}
    transitions = list(ledger.transitions)
    previous = first
    for index, character in enumerate(("c", "d"), 2):
        digest = "sha256:" + character * 64
        before = asdict(ledger)
        path, scan = _successor(case, monkeypatch, previous, digest, character * 40)
        loaded_runtime, _, loaded_ledger = continuation.load_context(
            path,
            folder / "runtime.json",
            folder / "config.json",
            folder / "ledger.json",
            operation="image",
        )
        assert loaded_runtime["sourceHead"] == character * 40
        assert asdict(loaded_ledger) == before
        assert continuation.readiness_plan_for_ledger(folder, ledger) == previous
        continuation.execute_admission(
            path,
            runtime,
            config,
            ledger,
            digest=digest,
            scan_path=scan,
            authorization=auth,
            execute=True,
        )
        assert ledger.phase == Phase.MIGRATED and ledger.transitions == transitions
        assert ledger.image_scan_count == index + 1
        assert ledger.readiness_image_replacements[-1] == before["image_replacement"]
        assert ledger.resource_generation_count == 1 and ledger.image_generation_count == 0
        assert continuation.readiness_plan_for_ledger(folder, ledger) == path
        link = continuation.validate_readiness_evidence_origin(
            folder,
            replace(config, image_digest=digest),
            runtime,
            ledger,
        )
        assert link["originalBindings"]["imageDigest"] == OLD
        assert link["continuationSha256"] == ledger.image_replacement["continuationSha256"]
        assert load_ledger(folder / "ledger.json", config) == ledger
        previous = path
    assert provider.patches == 30
    assert all(p.read_bytes() == value for p, value in first_files.items())
    ledger.readiness_image_replacements[0]["replacementImageDigest"] = "sha256:" + "f" * 64
    with pytest.raises(CampaignError, match="predecessor differs"):
        ledger.validate_resume(config)


@pytest.mark.parametrize(
    "field,value",
    [
        ("previousPlanSha256", "0" * 64),
        ("previousAdmissionSha256", "0" * 64),
        ("originalImageDigest", OLD),
        ("readinessSequence", 3),
    ],
)
def test_successor_rejects_changed_predecessor_binding(case, monkeypatch, field, value):
    _, runtime, config, ledger, first, scan, auth, _ = case
    continuation.execute_admission(
        first, runtime, config, ledger, digest=NEW, scan_path=scan, authorization=auth, execute=True
    )
    path, _ = _successor(case, monkeypatch, first, "sha256:" + "c" * 64, "c" * 40)
    plan = continuation._read(path)
    plan[field] = value
    plan["planSha256"] = continuation._hash({k: v for k, v in plan.items() if k != "planSha256"})
    write(path, plan)
    with pytest.raises(CampaignError):
        continuation.load_plan(path)

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, tzinfo
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import ClassVar, cast

import pytest
from test_milestone_7_8_bootstrap_transition import camel
from test_milestone_7_8_campaign_enablement import _runtime
from test_milestone_7_8_image_replacement_ledger import image_decided
from test_milestone_7_8_workload_image_update import NOW, Provider, fixture

from infra.milestone_7_8 import campaign, local_image, operator, workload_image_update
from infra.milestone_7_8 import image_continuation as continuation
from infra.milestone_7_8.campaign import CampaignConfig, CampaignError, Ledger, save_ledger
from infra.milestone_7_8.cleanup_controller import ARCHITECTURE

HEAD = "e" * 40
OLD_SCAN = "c" * 64


def write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def document(config: CampaignConfig) -> dict[str, object]:
    result = {camel(key): value for key, value in asdict(config).items()}
    result["resourceItems"] = [
        {camel(key): value for key, value in asdict(item).items()}
        for item in config.resource_items
    ]
    return result


class Clock(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Clock:
        return cls.fromtimestamp((NOW + timedelta(minutes=2)).timestamp(), tz)


@dataclass
class Case:
    folder: Path
    runtime: dict[str, str]
    config: CampaignConfig
    plan: Path
    provider: Provider
    originals: dict[Path, bytes]
    authorization: Path

    def invoke(self, monkeypatch: pytest.MonkeyPatch, operation: str = "image-decision") -> int:
        args = ["operator", operation, "--runtime", str(self.folder / "runtime.json"),
                "--config", str(self.folder / "cost.json"),
                "--ledger", str(self.folder / "ledger.json"),
                "--image-continuation", str(self.plan), "--execute",
                "--authorization", str(self.authorization)]
        if operation == "image-decision":
            args += ["--image-digest", continuation.IMAGE, "--image-scan-evidence",
                     str(self.folder / "image-continuation/local-image/image-scan.json")]
        monkeypatch.setattr(sys, "argv", args)
        return operator.main()


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Case:
    folder = tmp_path / ".runtime/milestone_7_8/campaign"
    folder.mkdir(parents=True)
    monkeypatch.setattr(continuation, "ROOT", tmp_path)
    partial, config, _ = fixture(folder)
    runtime = {**_runtime(), **partial, "sourceHead": continuation.ORIGINAL_HEAD,
               "canonicalBuildInputSha256": "b" * 64}
    runtime["cleanupAuthorityExpiresUtc"] = "2030-01-01T06:00:00Z"
    runtime_path = write(folder / "runtime.json", runtime)
    config_path = write(folder / "cost.json", document(config))
    ledger = image_decided(config)
    ledger.image_digest = continuation.ORIGINAL_IMAGE
    save_ledger(folder / "ledger.json", ledger)
    operator._stage_record(folder / "bootstrap-prerequisite-intent.json",
                           "database-prerequisite-intent", {
                               "operation": "bootstrap",
                               "bindings": operator._stage_bindings(config, runtime, ledger),
                           })
    for name in ("prerequisite-diagnosis-r1", "create-signature-diagnostic"):
        write(folder / name / "diagnostic-only-result.json", {"diagnostic": True})
    old_scan = write(folder / "local-image/image-scan.json", {"old": True})
    write(folder / "local-image/completed.json", {"filesSha256": {
        old_scan.name: hashlib.sha256(old_scan.read_bytes()).hexdigest(),
    }})
    write(folder / "budget-continuity.json", {"historicalSubtotalUsd": "35.202905", "inputs": {}})
    replacement = document(config)
    items = cast(list[dict[str, object]], replacement["resourceItems"])
    for name in ("completed-extra-prerequisite-diagnostic", "completed-create-signature-diagnostic",
                 "proposed-corrected-bootstrap-prerequisite"):
        items.append({"name": name, "hourlyUsd": "0", "hours": 1, "fixedUsd": "0.0189",
                      "pricedAtUtc": "2030-01-01T00:00:00Z"})
    subtotal = sum(Decimal(str(item["hourlyUsd"])) * Decimal(str(item["hours"]))
                   + Decimal(str(item["fixedUsd"])) for item in items)
    replacement["conservativeEstimateUsd"] = str(
        (subtotal * Decimal("1.25")).quantize(Decimal(".0001"), rounding=ROUND_CEILING)
    )
    cost_path = write(folder / "replacement-cost.json", replacement)
    retained = write(folder / "retained-image.json", {"synthetic": True})
    monkeypatch.setattr(continuation, "_source", lambda: HEAD)
    monkeypatch.setattr(continuation, "load_retained_image", lambda *_, **__: {
        "imageId": continuation.IMAGE, "imageBuildSourceHead": continuation.IMAGE_BUILD_HEAD,
    })
    # Source/archive and registry proof replay are tested by the actual engine
    # suites; this integration keeps the real continuation and workload validators.
    monkeypatch.setattr(local_image, "validate_completion", lambda *_, **__: 0)
    monkeypatch.setattr(operator, "load_runtime", lambda path: json.loads(path.read_text()))
    monkeypatch.setattr(operator, "validate_prepared_bundle", lambda *_: None)
    monkeypatch.setattr(operator, "load_bound_fresh_controller_admission", lambda *_: None)
    monkeypatch.setattr(operator, "_verify_retry_protection", lambda *_: [])
    monkeypatch.setattr(continuation, "datetime", Clock)
    monkeypatch.setattr(operator, "datetime", Clock)
    plan = continuation.build_plan(runtime_path, config_path, folder / "ledger.json",
                                   cost_path=cost_path, retained_image=retained)
    plan_path = write(folder / "image-continuation/plan.json", plan)
    effective_runtime, effective_config = continuation._effective(plan)
    scope = workload_image_update._scope(
        effective_runtime, effective_config, continuation.ORIGINAL_IMAGE, continuation.IMAGE,
    )
    provider = Provider(effective_runtime, effective_config, scope)
    for state in provider.states.values():
        container = cast(dict[str, object], workload_image_update._containers(state)[0])
        container["image"] = provider.image(continuation.ORIGINAL_IMAGE)
    monkeypatch.setattr(campaign, "SubprocessRunner", lambda **_: provider)
    scan_path = write(folder / "image-continuation/local-image/image-scan.json", {
        "version": "m7.8-image-admission-v1", "sourceHead": HEAD,
        "canonicalBuildInputSha256": continuation.CANONICAL,
        "imageDigest": continuation.IMAGE, "scanner": "Docker Scout", "scannerVersion": "v1",
        "scannedAtUtc": NOW.isoformat(), "result": "passed", "criticalFindings": 0,
        "highFindings": 0,
    })
    assert scan_path.exists()
    unsigned = {
        "version": "m7.8-execution-authorization-v5",
        "disposition": "separately-authorized-azure-execution",
        "campaignId": config.campaign_id, "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation, "sourceHead": HEAD,
        "controllerArchitecture": ARCHITECTURE,
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "controllerAuthorityEvidenceSha256": runtime["controllerAuthorityEvidenceSha256"],
        "freshControllerAdmissionEvidenceSha256": config.fresh_controller_admission_evidence_sha256,
        "freshControllerAdmissionEvidenceVersion": (
            runtime["freshControllerAdmissionEvidenceVersion"]
        ),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "expiresAtUtc": runtime["cleanupAuthorityExpiresUtc"],
        "allowedOperations": ["image-decision", "bootstrap", "migrate", "cleanup"],
    }
    auth = write(folder / "authorization.json", {**unsigned, "authorizationSha256": hashlib.sha256(
        b"m7.8/execution-authorization/v5\0"
        + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()})
    originals = {path: path.read_bytes() for path in (
        runtime_path, config_path, folder / "bootstrap-prerequisite-intent.json",
        old_scan, folder / "local-image/completed.json",
    )}
    return Case(folder, effective_runtime, effective_config, plan_path, provider, originals, auth)


def test_normal_operator_image_replacement_replays_preservation_without_base_writes(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert case.invoke(monkeypatch) == 0
    assert case.provider.patches == 10
    ledger = campaign.load_ledger(case.folder / "ledger.json", case.config)
    assert ledger.image_digest == continuation.IMAGE
    assert ledger.image_scan_count == ledger.required_scan_count == 2
    assert ledger.resource_generation_count == 1 and ledger.image_generation_count == 0
    continuation.validate_admission(case.plan, case.runtime, case.config, ledger)
    assert all(path.read_bytes() == content for path, content in case.originals.items())
    assert case.invoke(monkeypatch) == 2
    assert case.provider.patches == 10


@pytest.mark.parametrize("failure,lost", [(1, False), (5, False), (10, True)])
def test_incomplete_update_pauses_without_admission_or_deletion(
    case: Case, monkeypatch: pytest.MonkeyPatch, failure: int, lost: bool,
) -> None:
    case.provider.failure, case.provider.lost = failure, lost
    before = (case.folder / "ledger.json").read_bytes()
    assert case.invoke(monkeypatch) == 2
    assert case.provider.patches == failure
    assert (case.folder / "ledger.json").read_bytes() == before
    assert not (case.folder / "image-continuation/completed.json").exists()
    assert case.invoke(monkeypatch, "bootstrap") == 2
    assert case.invoke(monkeypatch) == 2
    assert case.provider.patches == failure
    assert all(command[3] in {"get", "patch"} for command in case.provider.commands)


def test_altered_history_and_missing_receipt_cannot_unlock_bootstrap(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert case.invoke(monkeypatch) == 0
    receipt = case.folder / "image-continuation/completed.json"
    receipt.unlink()
    assert case.invoke(monkeypatch, "bootstrap") == 2
    assert case.provider.patches == 10


def test_original_raw_image_record_changes_are_rejected_before_update(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(case.folder / "local-image/image-scan.json", {"tampered": True})
    assert case.invoke(monkeypatch) == 2
    assert not case.provider.commands


def test_later_stages_and_cleanup_use_exact_continuation_cost_and_source(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert case.invoke(monkeypatch) == 0
    runtime, config, ledger = continuation.load_context(
        case.plan, case.folder / "runtime.json", case.folder / "cost.json",
        case.folder / "ledger.json", operation="bootstrap",
    )
    assert runtime["sourceHead"] == HEAD
    assert runtime["canonicalBuildInputSha256"] == continuation.CANONICAL
    assert config == case.config
    assert ledger.conservative_estimate_usd == config.conservative_estimate_usd
    with pytest.raises(CampaignError):
        campaign.load_ledger(
            case.folder / "ledger.json", CampaignConfig.from_json(case.folder / "cost.json"),
        )
    for operation in ("deploy", "scope-create", "evidence"):
        with pytest.raises(CampaignError, match="operation"):
            continuation.load_context(
                case.plan, case.folder / "runtime.json", case.folder / "cost.json",
                case.folder / "ledger.json", operation=operation,
            )
    assert isinstance(ledger, Ledger)


@pytest.mark.parametrize("defect", ["source", "canonical", "missing-history", "old-intent"])
def test_rehashed_but_wrong_transition_is_rejected(
    case: Case, monkeypatch: pytest.MonkeyPatch, defect: str,
) -> None:
    plan = json.loads(case.plan.read_text())
    if defect == "source":
        plan["sourceHead"] = "a" * 40
    elif defect == "canonical":
        plan["canonicalBuildInputSha256"] = "a" * 64
    elif defect == "missing-history":
        del plan["boundFilesSha256"][str(case.folder / "bootstrap-prerequisite-intent.json")]
    else:
        write(case.folder / "bootstrap-prerequisite-intent.json", {"forged": True})
    plan["planSha256"] = continuation._hash({
        key: value for key, value in plan.items() if key != "planSha256"
    })
    write(case.plan, plan)
    assert case.invoke(monkeypatch) == 2
    assert not case.provider.commands


def test_replacement_scan_binding_is_required_before_workload_mutation(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = case.folder / "image-continuation/local-image/image-scan.json"
    scan = json.loads(path.read_text())
    scan["sourceHead"] = continuation.ORIGINAL_HEAD
    write(path, scan)
    assert case.invoke(monkeypatch) == 2
    assert not case.provider.commands


def test_cleanup_context_remains_available_if_new_admission_evidence_is_lost(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert case.invoke(monkeypatch) == 0
    (case.folder / "image-continuation/completed.json").unlink()
    runtime, config, ledger = continuation.load_context(
        case.plan, case.folder / "runtime.json", case.folder / "cost.json",
        case.folder / "ledger.json", operation="cleanup",
    )
    assert runtime == case.runtime and config == case.config
    assert ledger.image_replacement is not None


@pytest.mark.parametrize("during_readback", [False, True])
def test_expiry_reaches_existing_cleanup_before_image_mutation(
    case: Case, monkeypatch: pytest.MonkeyPatch, during_readback: bool,
) -> None:
    class Expired(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Expired:
            instant = campaign.parse_utc(case.config.cleanup_deadline_utc) + timedelta(seconds=1)
            return cls.fromtimestamp(instant.timestamp(), tz)

    cleanup: list[bool] = []
    monkeypatch.setattr(operator, "start_failure_cleanup", lambda *_: cleanup.append(True))
    if during_readback:
        def expire(*_: object) -> list[object]:
            monkeypatch.setattr(operator, "datetime", Expired)
            return []
        monkeypatch.setattr(operator, "_verify_retry_protection", expire)
    else:
        monkeypatch.setattr(operator, "datetime", Expired)
        monkeypatch.setattr(continuation, "datetime", Expired)
    assert case.invoke(monkeypatch) == 2
    assert cleanup == [True]
    assert case.provider.patches == 0
    assert json.loads((case.folder / "ledger.json").read_text())["phase"] == "cleaning"


def test_incomplete_protection_readback_pauses_without_updates_or_deletion(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def incomplete(*_: object) -> None:
        raise CampaignError("cleanup readback incomplete")

    monkeypatch.setattr(operator, "_verify_retry_protection", incomplete)
    assert case.invoke(monkeypatch) == 2
    assert case.provider.commands == []
    assert not (case.folder / "image-continuation/admission-intent.json").exists()


def test_admission_replay_checks_authorization_at_each_retained_dispatch(
    case: Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ticking(datetime):
        seconds: ClassVar[int] = 120

        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Ticking:
            cls.seconds += 1
            return cls.fromtimestamp((NOW + timedelta(seconds=cls.seconds)).timestamp(), tz)

    monkeypatch.setattr(continuation, "datetime", Ticking)
    assert case.invoke(monkeypatch) == 0
    folder = case.folder / "image-continuation"
    intent = json.loads((folder / "admission-intent.json").read_text())
    authorization = json.loads((folder / "authorization.json").read_text())
    # A rehashed approval covers admission start but expires before later PATCHes.
    authorization["expiresAtUtc"] = (
        campaign.parse_utc(intent["startedAtUtc"]) + timedelta(seconds=2)
    ).isoformat()
    unsigned = {key: value for key, value in authorization.items() if key != "authorizationSha256"}
    authorization["authorizationSha256"] = hashlib.sha256(
        b"m7.8/execution-authorization/v5\0"
        + json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    write(folder / "authorization.json", authorization)
    intent["authorizationSha256"] = continuation._file_hash(folder / "authorization.json")
    write(folder / "admission-intent.json", intent)
    receipt = json.loads((folder / "completed.json").read_text())
    receipt["admissionIntentSha256"] = continuation._file_hash(folder / "admission-intent.json")
    receipt["continuationSha256"] = continuation._hash({
        key: value for key, value in receipt.items() if key != "continuationSha256"
    })
    write(folder / "completed.json", receipt)
    ledger = campaign.load_ledger(case.folder / "ledger.json", case.config)
    assert ledger.image_replacement is not None
    ledger.image_replacement["continuationSha256"] = receipt["continuationSha256"]
    with pytest.raises(CampaignError, match="authorization is expired"):
        continuation.validate_admission(case.plan, case.runtime, case.config, ledger)

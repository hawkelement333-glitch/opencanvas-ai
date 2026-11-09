from __future__ import annotations

import asyncio
import hashlib

# The API test root is normally the import root; this focused infrastructure contract
# also imports the repository-level campaign package after adding that explicit root.
# ruff: noqa: E402
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from infra.milestone_7_8 import controller as controller_operator
from infra.milestone_7_8 import operator as campaign_operator
from infra.milestone_7_8 import predeployment, prepare, retention, retention_v3
from infra.milestone_7_8.automation_region import (
    CLEANUP_CANDIDATE_REGIONS_BINDING,
    CLEANUP_REGION_CANDIDATES,
    OFFER_ELIGIBILITY_SOURCE,
    OFFER_ELIGIBLE_REGIONS_BINDING,
    RESTRICTED_OFFER_ELIGIBLE_REGIONS,
    AutomationRegionSelection,
    CandidateEvidence,
)
from infra.milestone_7_8.campaign import (
    HARD_CEILING,
    ORDER,
    RESIDUE_KEYS,
    CampaignConfig,
    CampaignError,
    CleanupBinding,
    CostItem,
    Ledger,
    Lifecycle,
    Phase,
    SimulatedRunner,
    terminal_receipt,
)
from infra.milestone_7_8.cleanup_controller import load_execution_authorization
from infra.milestone_7_8.controller import (
    ControllerConfig,
    controller_command_plan,
    load_controller_authorization,
    validate_controller_results,
)
from infra.milestone_7_8.operator import (
    OPERATION_PHASE,
    command_plan,
    execute_cleanup_arm_commands,
    execute_cleanup_deploy_commands,
    execute_cleanup_disarm_commands,
    execute_commands,
    execute_residue_commands,
    observe_residue,
    required_execution_authorizations,
    validate_cleanup_deployment,
    validate_cleanup_readback,
    validate_operation_results,
    verify_zero_residue,
)

from opencanvas_api.db.principal_manifest import (
    CAMPAIGN_ENV,
    CURRENT_PRINCIPAL_ID_ENV,
    GENERATION_ENV,
    MANIFEST_ENV,
    PrincipalManifestError,
    PrincipalSlot,
    load_principal_manifest,
)
from scripts import bootstrap_postgres, managed_postgres_evidence, migrate_and_grant

NOW = datetime(2030, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("upstream", "branch", "status", "stash_count", "accepted"),
    [
        (
            "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
            "milestone-7-8-production-readiness-audit-local",
            "",
            5,
            True,
        ),
        ("", "milestone-7-8-production-readiness-audit-local", "", 5, False),
        (
            "refs/remotes/origin/other",
            "milestone-7-8-production-readiness-audit-local",
            "",
            5,
            False,
        ),
        (
            "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
            "other",
            "",
            5,
            False,
        ),
        (
            "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
            "milestone-7-8-production-readiness-audit-local",
            " M tracked",
            5,
            False,
        ),
        (
            "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
            "milestone-7-8-production-readiness-audit-local",
            "",
            4,
            False,
        ),
    ],
)
def test_controller_source_boundary(
    monkeypatch: pytest.MonkeyPatch,
    upstream: str,
    branch: str,
    status: str,
    stash_count: int,
    accepted: bool,
) -> None:
    def fake_run(args: tuple[str, ...], **_kwargs: object) -> object:
        from types import SimpleNamespace

        command = args[1:]
        values = {
            ("rev-parse", "HEAD"): "a" * 40,
            ("status", "--porcelain=v1"): status,
            ("branch", "--show-current"): branch,
            (
                "for-each-ref",
                "--format=%(upstream)",
                "refs/heads/milestone-7-8-production-readiness-audit-local",
            ): upstream,
            ("stash", "list", "--format=%H"): "\n".join(str(i) for i in range(stash_count)),
        }
        return SimpleNamespace(returncode=0, stdout=values[command])

    monkeypatch.setattr(controller_operator.subprocess, "run", fake_run)
    if accepted:
        head, digest = controller_operator.local_source_binding()
        assert head == "a" * 40
        assert len(digest) == 64
    else:
        with pytest.raises(CampaignError, match="source boundary differs"):
            controller_operator.local_source_binding()


def test_controller_execution_rechecks_head_and_script(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _controller_config()
    for source_head, script_hash in (
        ("0" * 40, config.cleanup_script_sha256),
        (config.source_head, "0" * 64),
    ):
        monkeypatch.setattr(
            controller_operator,
            "local_source_binding",
            lambda source_head=source_head, script_hash=script_hash: (source_head, script_hash),
        )
        with pytest.raises(CampaignError, match="source boundary differs"):
            controller_operator.validate_local_boundary(config)


def _object_id(value: int) -> str:
    return f"00000000-0000-4000-8000-{value:012d}"


def _retention_absence_document(
    subscription_id: str,
    *,
    evidence_class: str = "synthetic-test-fixture",
) -> dict[str, object]:
    endpoint = retention_v3.endpoint(subscription_id)
    return retention_v3.build_document(
        subscription_id=subscription_id,
        observed_at=datetime(2026, 9, 14, 1, 9, 46, 308000, tzinfo=UTC),
        pages=[
            {
                "requestSha256": retention_v3.request_sha256(endpoint),
                "recordIdentitySha256": list(retention.RETENTION_UNRELATED_IDENTITY_SHA256),
                "nextRequestSha256": None,
            }
        ],
        evidence_class=evidence_class,
    )


def _manifest(
    *,
    campaign: str = "mobius78-pg-proof",
    generation: str = "g1-aabbccddeeff",
    names: dict[str, str] | None = None,
) -> dict[str, object]:
    labels = names or {slot.value: f"id-m78-proof-{slot.value}" for slot in PrincipalSlot}
    return {
        "version": "m7.8-principal-manifest-v1",
        "campaignId": campaign,
        "generationId": generation,
        "subscriptionCorrelation": "a" * 16,
        "principals": {
            slot.value: {
                "role": slot.value,
                "name": labels[slot.value],
                "objectId": _object_id(index + 1),
            }
            for index, slot in enumerate(PrincipalSlot)
        },
    }


def _set_manifest(monkeypatch: pytest.MonkeyPatch, value: dict[str, object]) -> None:
    monkeypatch.setenv(MANIFEST_ENV, json.dumps(value))
    monkeypatch.setenv(CAMPAIGN_ENV, str(value["campaignId"]))
    monkeypatch.setenv(GENERATION_ENV, str(value["generationId"]))


def _config(**changes: object) -> CampaignConfig:
    values: dict[str, object] = {
        "campaign_id": "mobius78-pg-proof",
        "generation_id": "g1-aabbccddeeff",
        "subscription_correlation": "a" * 16,
        "tenant_correlation": "b" * 16,
        "target_resource_group": "rg-m78-aabbccddee-target",
        "cleanup_resource_group": "rg-m78-controller-aaaaaaaaaa",
        "target_region": "centralus",
        "cleanup_region": "eastus2",
        "postgres_region": "centralus",
        "cleanup_deadline_utc": "2030-01-01T04:00:00Z",
        "conservative_estimate_usd": "25.6832",
        "contingency_percent": "25",
        "resource_items": (CostItem("bounded-campaign", "5.13664", 4),),
        "principal_manifest_sha256": "c" * 64,
        "cleanup_region_selection_sha256": "f" * 64,
        "cleanup_candidate_regions": CLEANUP_CANDIDATE_REGIONS_BINDING,
        "cleanup_offer_classification": "restricted-public-offer",
        "cleanup_offer_eligibility_disposition": ("restricted-offer-metadata-confirmed"),
        "cleanup_offer_eligible_regions": OFFER_ELIGIBLE_REGIONS_BINDING,
        "cleanup_offer_eligibility_source": OFFER_ELIGIBILITY_SOURCE,
        "cleanup_offer_eligibility_sha256": "e" * 64,
        "fresh_controller_admission_evidence_sha256": "0" * 64,
        "image_digest": None,
    }
    values.update(changes)
    return CampaignConfig(**values)  # type: ignore[arg-type]


def test_campaign_derived_principals_and_alternative_generation_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _manifest()
    _set_manifest(monkeypatch, first)
    assert (
        load_principal_manifest().principals[PrincipalSlot.MIGRATION].name
        == "id-m78-proof-migration"
    )
    second = _manifest(campaign="mobius78-pg-other", generation="g2-112233aabbcc")
    _set_manifest(monkeypatch, second)
    assert load_principal_manifest().generation_id == "g2-112233aabbcc"


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "swapped", "malformed", "stale", "unknown"]
)
def test_invalid_principal_manifests_fail_closed(
    monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    value = _manifest()
    principals = value["principals"]
    assert isinstance(principals, dict)
    if defect == "missing":
        principals.pop("worker")
    elif defect == "duplicate":
        principals["worker"]["objectId"] = principals["api"]["objectId"]  # type: ignore[index]
    elif defect == "swapped":
        principals["worker"]["role"] = "api"  # type: ignore[index]
    elif defect == "malformed":
        principals["api"]["name"] = 'bad"role'  # type: ignore[index]
    elif defect == "stale":
        value["generationId"] = "g2-112233aabbcc"
    else:
        value["unexpected"] = True
    _set_manifest(monkeypatch, value)
    if defect == "stale":
        monkeypatch.setenv(GENERATION_ENV, "g1-aabbccddeeff")
    with pytest.raises(PrincipalManifestError):
        load_principal_manifest()


def test_retained_labels_have_no_special_case(monkeypatch: pytest.MonkeyPatch) -> None:
    labels = {
        "bootstrap": "id-mobius77-db-admin",
        "migration": "id-mobius77-db-migration",
        "api": "id-mobius77-api",
        "worker": "id-mobius77-worker",
        "evidence": "id-mobius77-evidence",
        "cleanup": "id-mobius77-cleanup",
    }
    _set_manifest(monkeypatch, _manifest(names=labels))
    manifest = load_principal_manifest()
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(2))
    manifest.require_current(PrincipalSlot.MIGRATION, current_name=labels["migration"])
    monkeypatch.setenv(CURRENT_PRINCIPAL_ID_ENV, _object_id(3))
    with pytest.raises(PrincipalManifestError):
        manifest.require_current(PrincipalSlot.MIGRATION, current_name=labels["migration"])


def test_bootstrap_and_migration_consume_same_semantic_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_manifest(monkeypatch, _manifest())
    contracts = bootstrap_postgres._principal_contracts()
    assert [item.name for item in contracts] == [
        "id-m78-proof-migration",
        "id-m78-proof-api",
        "id-m78-proof-worker",
        "id-m78-proof-evidence",
    ]
    assert migrate_and_grant._principals() == (
        "id-m78-proof-migration",
        "id-m78-proof-api",
        "id-m78-proof-worker",
    )


@pytest.mark.parametrize(
    ("estimate", "accepted"),
    [("49.99", True), ("50.00", True), ("50.01", False)],
)
def test_cost_ceiling_boundaries(estimate: str, accepted: bool) -> None:
    config = _config(
        conservative_estimate_usd=estimate,
        resource_items=(CostItem("bounded", "9.998", 4),),
    )
    if accepted:
        config.validate()
        assert Decimal(estimate) <= HARD_CEILING
    else:
        with pytest.raises(CampaignError, match="ceiling"):
            config.validate()


def test_contingency_deadline_and_generation_limits() -> None:
    with pytest.raises(CampaignError, match="contingency"):
        _config(contingency_percent="24.99").validate()
    with pytest.raises(CampaignError, match="resource-group scope"):
        _config(target_resource_group="production").validate()
    with pytest.raises(CampaignError, match="expired"):
        _config(cleanup_deadline_utc="2020-01-01T00:00:00Z").validate()
    ledger = Ledger("mobius78-pg-proof", "g1-aabbccddeeff")
    ledger.bind_deadline("2030-01-01T04:00:00Z")
    with pytest.raises(CampaignError, match="extension"):
        ledger.bind_deadline("2030-01-01T04:01:00Z")
    for phase in ORDER[1 : ORDER.index(Phase.BILLABLE_STARTED) + 1]:
        if phase is Phase.CLEANUP_ARMED:
            ledger.record_cleanup_arm_evidence("e" * 64)
        ledger.transition(phase, NOW)
    with pytest.raises(CampaignError, match="generation"):
        ledger.resource_generation_count = 1
        ledger.phase = Phase.CLEANUP_VERIFIED.value
        ledger.transition(Phase.BILLABLE_STARTED, NOW)
    ledger.record_image("sha256:" + "a" * 64, built=True)
    ledger.record_image_scan("sha256:" + "a" * 64, "c" * 64)
    with pytest.raises(CampaignError, match="second image"):
        ledger.record_image("sha256:" + "b" * 64, built=True)
    with pytest.raises(CampaignError, match="second image admission"):
        ledger.record_image_scan("sha256:" + "a" * 64, "d" * 64)


def test_full_lifecycle_reaches_sanitized_zero_residue() -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, ledger, SimulatedRunner()).run_simulation(now=NOW)
    receipt = terminal_receipt(result)
    assert result.phase == Phase.FINALIZED
    assert result.resource_generation_count == result.image_generation_count == 1
    assert set(result.residue) == set(RESIDUE_KEYS)
    assert set(result.residue.values()) == {0}
    assert receipt["status"] == "zero-residue"
    assert config.campaign_id not in json.dumps(receipt)


@pytest.mark.parametrize("failed_at", ORDER[1:-1])
def test_every_lifecycle_phase_failure_is_bounded(failed_at: Phase) -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    result = Lifecycle(config, ledger, SimulatedRunner()).fail_and_cleanup(failed_at, now=NOW)
    if ORDER.index(failed_at) < ORDER.index(Phase.SCOPE_CREATED):
        assert result.cleanup_started_utc is None
    else:
        assert result.phase == Phase.FINALIZED
        assert set(result.residue.values()) == {0}


def test_resume_and_cleanup_binding_reject_substitution() -> None:
    config = _config()
    with pytest.raises(CampaignError, match="resume"):
        Lifecycle(config, Ledger(config.campaign_id, "g2-112233aabbcc"), SimulatedRunner())
    valid = CleanupBinding(
        campaign_id=config.campaign_id,
        generation_id=config.generation_id,
        subscription_correlation=config.subscription_correlation,
        target_resource_group=config.target_resource_group,
        cleanup_resource_group=config.cleanup_resource_group,
        cleanup_principal_sha256="d" * 64,
        deadline_utc=config.cleanup_deadline_utc,
        ceiling_usd="50.00",
        schedule_count=0,
        binding_count=0,
        cleanup_region=config.cleanup_region,
        cleanup_region_selection_sha256=config.cleanup_region_selection_sha256,
        cleanup_candidate_regions=config.cleanup_candidate_regions,
        cleanup_offer_classification=config.cleanup_offer_classification,
        cleanup_offer_eligibility_disposition=(config.cleanup_offer_eligibility_disposition),
        cleanup_offer_eligible_regions=config.cleanup_offer_eligible_regions,
        cleanup_offer_eligibility_source=config.cleanup_offer_eligibility_source,
        cleanup_offer_eligibility_sha256=config.cleanup_offer_eligibility_sha256,
        fresh_controller_admission_evidence_sha256=(
            config.fresh_controller_admission_evidence_sha256
        ),
    )
    valid.validate(config)
    with pytest.raises(CampaignError, match="cleanup binding"):
        replace(valid, schedule_count=1).validate(config)


def test_evidence_contract_is_complete_and_redacted() -> None:
    required = managed_postgres_evidence.REQUIRED_PROOFS
    assert {
        "catalog.runtime-grants",
        "recovery.failover",
        "idempotency.canvas",
        "idempotency.edge",
        "tenant.post-failover",
        "tenant.forged-evidence-bundle",
        "operations.backup",
    } < required
    source = (REPOSITORY_ROOT / "apps/api/scripts/managed_postgres_evidence.py").read_text()
    assert "password" not in managed_postgres_evidence._digest({"password": "do-not-print"})
    assert "TODO" not in source and "NotImplemented" not in source


def _control_plane_evidence() -> dict[str, object]:
    return {
        "primaryZone": "1",
        "standbyZone": "2",
        "haMode": "ZoneRedundant",
        "maintenanceDay": 0,
        "maintenanceHour": 7,
        "storageGiB": 64,
        "storageTier": "P6",
        "backupRetentionDays": 7,
        "geoBackup": False,
        "latencyP95Ms": 12.5,
        "recoverySeconds": 42.0,
        "failoverObserved": True,
        "credentialRecoveryObserved": True,
        "postFailoverTenantIsolationObserved": True,
        "azureReservedConnections": 5,
        "poolCeilings": 50,
        "rolloutOverlap": 10,
        "operatorConsumers": 5,
        "observedPeak": 40,
        "safetyReserve": 20,
        "maxConnections": 100,
    }


def _operator_control_plane_evidence() -> dict[str, object]:
    return {
        key: value
        for key, value in _control_plane_evidence().items()
        if key
        not in {
            "recoverySeconds",
            "failoverObserved",
            "credentialRecoveryObserved",
            "postFailoverTenantIsolationObserved",
        }
    }


def test_control_plane_evidence_capacity_and_types_fail_closed() -> None:
    evidence = _control_plane_evidence()
    assertions = managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))
    assert assertions and all(item.passed for item in assertions)
    evidence["maxConnections"] = 89
    with pytest.raises(managed_postgres_evidence.EvidenceError):
        managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))
    evidence = _control_plane_evidence()
    evidence["maintenanceDay"] = True
    with pytest.raises(managed_postgres_evidence.EvidenceError):
        managed_postgres_evidence.validate_control_plane_evidence(json.dumps(evidence))


def test_image_scan_receipt_is_bound_before_workload_deployment(tmp_path: Path) -> None:
    runtime = _runtime()
    digest = "sha256:" + "e" * 64
    receipt = {
        "version": "m7.8-image-admission-v1",
        "sourceHead": runtime["sourceHead"],
        "canonicalBuildInputSha256": runtime["canonicalBuildInputSha256"],
        "imageDigest": digest,
        "scanner": "approved-image-admission-scanner",
        "scannerVersion": "1.0",
        "scannedAtUtc": "2030-01-01T01:00:00Z",
        "result": "passed",
        "criticalFindings": 0,
        "highFindings": 0,
    }
    path = tmp_path / "image-scan.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert (
        campaign_operator.load_image_scan_evidence(path, digest=digest, runtime=runtime)
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    receipt["highFindings"] = 1
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(CampaignError, match="policy"):
        campaign_operator.load_image_scan_evidence(path, digest=digest, runtime=runtime)


def test_deployed_principal_manifest_matches_prepared_semantic_plan() -> None:
    names = {
        "bootstrap": "id-m78-proof-bootstrap",
        "migration": "id-m78-proof-migration",
        "api": "id-m78-proof-api",
        "worker": "id-m78-proof-worker",
        "evidence": "id-m78-proof-evidence",
        "cleanup": "cleanup-proof",
    }
    planned = {
        "campaignId": "mobius78-pg-proof",
        "generationId": "g1-aabbccddeeff",
        "principals": {
            key: names[key] for key in ("bootstrap", "migration", "api", "worker", "evidence")
        },
        "cleanup": names["cleanup"],
    }
    config = _config(
        principal_manifest_sha256=hashlib.sha256(
            json.dumps(planned, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )
    manifest = {
        "version": "m7.8-principal-manifest-v1",
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "principals": {
            slot: {"role": slot, "name": name, "objectId": _object_id(index)}
            for index, (slot, name) in enumerate(names.items(), 1)
        },
    }
    outputs: dict[str, object] = {
        "campaignBinding": {
            "campaignId": config.campaign_id,
            "generationId": config.generation_id,
            "subscriptionCorrelation": config.subscription_correlation,
            "cleanupDeadlineUtc": config.cleanup_deadline_utc,
            "maximumHours": 4,
            "costCeilingCents": 5000,
            "cleanupResourceGroupName": config.cleanup_resource_group,
            "cleanupLocation": config.cleanup_region,
            "cleanupRegionSelectionSha256": config.cleanup_region_selection_sha256,
            "cleanupCandidateRegions": config.cleanup_candidate_regions,
            "cleanupOfferClassification": config.cleanup_offer_classification,
            "cleanupOfferEligibilityDisposition": (config.cleanup_offer_eligibility_disposition),
            "cleanupOfferEligibleRegions": config.cleanup_offer_eligible_regions,
            "cleanupOfferEligibilitySource": config.cleanup_offer_eligibility_source,
            "cleanupOfferEligibilitySha256": config.cleanup_offer_eligibility_sha256,
            "freshControllerAdmissionEvidenceSha256": (
                config.fresh_controller_admission_evidence_sha256
            ),
            "principalManifest": json.dumps(manifest),
        }
    }
    campaign_operator.validate_deployed_principal_manifest(outputs, config)
    manifest["principals"]["worker"]["objectId"] = _object_id(3)  # type: ignore[index]
    outputs["campaignBinding"]["principalManifest"] = json.dumps(manifest)  # type: ignore[index]
    with pytest.raises(CampaignError, match="not distinct"):
        campaign_operator.validate_deployed_principal_manifest(outputs, config)


def test_fake_postgres_adapter_proves_campaign_login_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSettings:
        def require_database_role(self, _role: object) -> None:
            return None

    class DeniedContext:
        async def __aenter__(self) -> None:
            raise ConnectionError("synthetic login denied")

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeEngine:
        def connect(self) -> DeniedContext:
            return DeniedContext()

    class FakeDatabase:
        engine = FakeEngine()

        @classmethod
        def from_settings(cls, *_args: object, **_kwargs: object) -> FakeDatabase:
            return cls()

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(managed_postgres_evidence, "get_settings", FakeSettings)
    monkeypatch.setattr(managed_postgres_evidence, "Database", FakeDatabase)
    assertions = asyncio.run(managed_postgres_evidence.credential_denial_assertion())
    assert [item.code for item in assertions] == ["recovery.credential-revocation"]


def test_new_bicep_has_no_executable_milestone_7_7_coupling() -> None:
    root = REPOSITORY_ROOT / "infra/milestone_7_8"
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in root.rglob("*.*")
        if path.suffix in {".bicep", ".json", ".ps1", ".py"}
    )
    assert "id-mobius77" not in combined
    assert "milestone_7_7" not in combined
    assert "2026-08-09" not in combined
    assert "TODO" not in combined
    assert (root / "main.bicep").is_file()
    assert (root / "cleanup.bicep").is_file()
    assert (root / "controller.bicep").is_file()
    cleanup = (root / "cleanup.bicep").read_text(encoding="utf-8")
    assert cleanup.count("./modules/cleanup-rbac.bicep") == 2
    assert "Microsoft.Automation/automationAccounts@" in cleanup
    assert "existing =" in cleanup
    assert "resource controllerAccount" in cleanup
    assert "resource cleanupResourceGroup" not in cleanup
    assert "b24988ac-6180-42a0-ab88-20f7382dd24c" in cleanup
    assert "f58310d9-a9f6-439a-9e8d-f62e7b41a168" in cleanup


def _controller_config() -> ControllerConfig:
    subscription_id = _object_id(100)
    correlation = campaign_operator.sanitize(subscription_id, domain="subscription")
    return ControllerConfig(
        subscription_id=subscription_id,
        tenant_id=_object_id(101),
        campaign_id="mobius78-pg-proof",
        generation_id="g1-aabbccddeeff",
        subscription_correlation=correlation,
        source_head="b" * 40,
        controller_location="eastus2",
        controller_resource_group_name=f"rg-m78-controller-{correlation[:10]}",
        automation_account_name=f"aa-m78-controller-{correlation[:10]}",
        runbook_name="Remove-M78Campaign",
        controller_authorized_until_utc="2030-01-02T00:00:00Z",
        cleanup_script_sha256=hashlib.sha256(b"cleanup-content").hexdigest(),
        fresh_controller_admission_evidence_sha256="0" * 64,
        fresh_controller_admission_evidence_version=(
            "m7.8-fresh-subscription-predeployment-absence-evidence-v1"
        ),
        deployment_name=f"m78-controller-{correlation[:10]}",
    )


def test_separate_controller_bootstrap_is_one_time_and_authorization_gated(
    tmp_path: Path,
) -> None:
    config = _controller_config()
    bootstrap = controller_command_plan("controller-bootstrap", config)
    verify = controller_command_plan("controller-verify", config)
    rendered = [" ".join(command).casefold() for command in bootstrap]
    assert sum("deployment sub create" in item for item in rendered) == 1
    assert sum("replace-content" in item for item in rendered) == 1
    assert sum("runbook publish" in item for item in rendered) == 1
    assert not any("automation account delete" in item for item in rendered)
    assert all(
        "--method get" in " ".join(item)
        or item[1:3] in {("group", "show"), ("automation", "account"), ("role", "assignment")}
        for item in verify
    )

    authorization_path = tmp_path / "controller-authorization.json"
    value: dict[str, object] = {
        "version": "m7.8-controller-execution-authorization-v4",
        "disposition": "separately-authorized-controller-execution",
        "operation": "controller-bootstrap",
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": config.source_head,
        "controllerArchitecture": "reusable-automation-controller-v1",
        "controllerLocation": config.controller_location,
        "controllerResourceGroupName": config.controller_resource_group_name,
        "automationAccountName": config.automation_account_name,
        "controllerAuthorizedUntilUtc": config.controller_authorized_until_utc,
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "freshControllerAdmissionEvidenceVersion": (
            config.fresh_controller_admission_evidence_version
        ),
        "expiresAtUtc": "2030-01-01T01:00:00Z",
    }
    value["authorizationSha256"] = hashlib.sha256(
        b"m7.8/controller-execution-authorization/v4\0"
        + json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    authorization_path.write_text(json.dumps(value), encoding="utf-8")
    assert (
        len(
            load_controller_authorization(
                authorization_path,
                config=config,
                operation="controller-bootstrap",
                now=NOW,
            )
        )
        == 64
    )
    with pytest.raises(CampaignError, match="not exact"):
        load_controller_authorization(
            authorization_path,
            config=config,
            operation="controller-verify",
            now=NOW,
        )
    with pytest.raises(CampaignError, match="not exact"):
        load_controller_authorization(
            authorization_path,
            config=replace(config, fresh_controller_admission_evidence_sha256="1" * 64),
            operation="controller-bootstrap",
            now=NOW,
        )


def test_controller_execute_rejects_missing_fresh_admission_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _controller_config()
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "subscriptionId": config.subscription_id,
                "tenantId": config.tenant_id,
                "campaignId": config.campaign_id,
                "generationId": config.generation_id,
                "subscriptionCorrelation": config.subscription_correlation,
                "sourceHead": config.source_head,
                "controllerLocation": config.controller_location,
                "controllerResourceGroupName": config.controller_resource_group_name,
                "automationAccountName": config.automation_account_name,
                "runbookName": config.runbook_name,
                "controllerAuthorizedUntilUtc": config.controller_authorized_until_utc,
                "cleanupScriptSha256": config.cleanup_script_sha256,
                "freshControllerAdmissionEvidenceSha256": (
                    config.fresh_controller_admission_evidence_sha256
                ),
                "freshControllerAdmissionEvidenceVersion": (
                    config.fresh_controller_admission_evidence_version
                ),
                "deploymentName": config.deployment_name,
            }
        ),
        encoding="utf-8",
    )
    authorization_path = tmp_path / "authorization.json"

    def unexpected_runner() -> object:
        raise AssertionError("Azure runner must not be created")

    monkeypatch.setattr(controller_operator, "SubprocessRunner", unexpected_runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controller",
            "controller-bootstrap",
            "--config",
            str(config_path),
            "--authorization",
            str(authorization_path),
            "--execute",
        ],
    )
    assert controller_operator.main() == 2
    assert "requires fresh controller admission evidence" in capsys.readouterr().out


def test_controller_baseline_readback_requires_publication_and_empty_bindings() -> None:
    config = _controller_config()
    tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": "reusable-automation-controller-v1",
        "mobius.subscription-correlation": config.subscription_correlation,
        "mobius.controller-authorized-until-utc": (config.controller_authorized_until_utc),
        "mobius.cleanup-script-sha256": config.cleanup_script_sha256,
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "mobius.fresh-controller-admission-version": (
            config.fresh_controller_admission_evidence_version
        ),
    }
    results = [
        _command_result(
            {
                "name": config.controller_resource_group_name,
                "location": "East US 2",
                "tags": tags,
            }
        ),
        _command_result(
            {
                "name": config.automation_account_name,
                "location": "East US 2",
                "tags": tags,
                "identity": {"principalId": _object_id(201)},
                "properties": {"disableLocalAuth": True},
            }
        ),
        _command_result(
            [
                {
                    "principalId": _object_id(201),
                    "roleDefinitionId": (
                        f"/subscriptions/{config.subscription_id}/providers/"
                        "Microsoft.Authorization/roleDefinitions/"
                        "acdd72a7-3385-48ef-bd42-f606fba81ae7"
                    ),
                    "scope": (
                        f"/subscriptions/{config.subscription_id}/resourceGroups/"
                        f"{config.controller_resource_group_name}"
                    ),
                }
            ]
        ),
        _command_result(
            {
                "name": config.runbook_name,
                "properties": {
                    "state": "Published",
                    "lastModifiedTime": "2030-01-01T00:01:00Z",
                },
            }
        ),
        {"exitCode": 0, "stdout": "cleanup-content", "stderr": ""},
        _command_result({"value": []}),
        _command_result({"value": []}),
    ]
    assert len(validate_controller_results(results, config)) == 64
    results[-1] = _command_result({"value": [{"name": "unexpected"}]})
    with pytest.raises(CampaignError, match="inventory is not empty"):
        validate_controller_results(results, config)


def _runtime() -> dict[str, str]:
    subscription_id = _object_id(100)
    cleanup_resource_group = "rg-m78-controller-aaaaaaaaaa"
    account = "aa-m78-controller-aaaaaaaaaa"
    return {
        "subscriptionId": subscription_id,
        "sourceHead": "a" * 40,
        "canonicalBuildInputSha256": "b" * 64,
        "dockerfileSha256": "c" * 64,
        "cleanupScriptSha256": "d" * 64,
        "automationApiVersion": "2024-10-23",
        "cleanupControllerArchitecture": "reusable-automation-controller-v1",
        "cleanupControllerArmability": "architecture-corrected-live-execution-not-authorized",
        "controllerBindingSha256": campaign_operator.controller_binding_sha256(
            subscription_id,
            resource_group=cleanup_resource_group,
            account=account,
            runbook="Remove-M78Campaign",
        ),
        "cleanupAuthorityExpiresUtc": "2030-01-01T05:00:00Z",
        "cleanupRegion": "eastus2",
        "cleanupRegionSelectionSha256": "f" * 64,
        "cleanupCandidateRegions": CLEANUP_CANDIDATE_REGIONS_BINDING,
        "cleanupOfferClassification": "restricted-public-offer",
        "cleanupOfferEligibilityDisposition": ("restricted-offer-metadata-confirmed"),
        "cleanupOfferEligibleRegions": OFFER_ELIGIBLE_REGIONS_BINDING,
        "cleanupOfferEligibilitySource": OFFER_ELIGIBILITY_SOURCE,
        "cleanupOfferEligibilitySha256": "e" * 64,
        "freshControllerAdmissionEvidenceSha256": "0" * 64,
        "freshControllerAdmissionEvidenceVersion": (
            "m7.8-fresh-subscription-predeployment-absence-evidence-v1"
        ),
        "freshControllerAdmissionEvidenceClass": "managed-provider-predeployment-get-only",
        "freshControllerAdmissionEvidenceObservedAtUtc": "2030-01-01T00:00:00Z",
        "freshControllerAdmissionRuntimeFile": "runtime/fresh-subscription-runtime.json",
        "freshControllerAdmissionAuthorizationFile": (
            "runtime/predeployment-read-authorization.json"
        ),
        "freshControllerAdmissionEvidenceFile": "runtime/predeployment-absence-evidence.json",
        "cleanupRegionSelectionFile": "runtime/cleanup-region-selection.json",
        "cleanupDeploymentName": "m78-cleanup",
        "campaignDeploymentName": "m78-campaign",
        "automationAccountName": account,
        "runbookName": "Remove-M78Campaign",
        "scheduleName": "m78-deadline-proof",
        "bindingName": "11111111-1111-4111-8111-111111111111",
        "bootstrapJobName": "job-proof-bootstrap",
        "migrationJobName": "job-proof-migration",
        "workerJobName": "job-proof-worker",
        "evidenceJobName": "job-proof-evidence",
        "apiProbeJobName": "job-proof-probe-api",
        "workerProbeJobName": "job-proof-probe-worker",
        "migrationProbeJobName": "job-proof-probe-migration",
        "recoveryJobName": "job-proof-credential-recovery",
        "recoveryRestoreJobName": "job-proof-credential-restore",
        "postgresServerName": "pg-m78-proof",
        "registryName": "acrm78proof",
        "logAnalyticsWorkspaceName": "law-m78-proof",
        "resourceGroupName": "rg-m78-aabbccddee-target",
        "cleanupResourceGroupName": cleanup_resource_group,
        "cleanupParametersFile": "runtime/m78.cleanup.parameters.json",
        "campaignParametersFile": "runtime/m78.campaign.parameters.json",
    }


def test_operator_runbook_maps_every_phase_to_implemented_commands() -> None:
    runtime = _runtime()
    config = _config()
    for operation in OPERATION_PHASE:
        commands = command_plan(operation, config, runtime)
        assert isinstance(commands, tuple)
        assert all(command and all(part for part in command) for command in commands)
    evidence = command_plan("evidence", config, runtime)
    rendered = "\n".join(" ".join(command) for command in evidence)
    assert "--failover Forced" in rendered
    assert "--phase application" in rendered
    assert "--phase operations" in rendered
    scope = " ".join(command_plan("scope-create", config, runtime)[0])
    assert "mobius.milestone=7.8" in scope
    assert f"mobius.cleanup-deadline-utc={config.cleanup_deadline_utc}" in scope
    assert "mobius.cost-ceiling-cents=5000" in scope
    assert f"mobius.cleanup-offer-classification={config.cleanup_offer_classification}" in scope
    assert (
        f"mobius.cleanup-offer-eligibility-sha256={config.cleanup_offer_eligibility_sha256}"
    ) in scope


def _command_result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


def _controller_tags(config: CampaignConfig, runtime: dict[str, str]) -> dict[str, str]:
    return {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": "reusable-automation-controller-v1",
        "mobius.subscription-correlation": config.subscription_correlation,
        "mobius.controller-authorized-until-utc": "2030-01-02T00:00:00Z",
        "mobius.cleanup-script-sha256": runtime["cleanupScriptSha256"],
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }


def _controller_account_record(
    config: CampaignConfig, runtime: dict[str, str]
) -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
            f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
            f"automationAccounts/{runtime['automationAccountName']}"
        ),
        "name": runtime["automationAccountName"],
        "location": config.cleanup_region,
        "tags": _controller_tags(config, runtime),
        "identity": {"principalId": _object_id(201)},
        "properties": {"disableLocalAuth": True},
    }


def _controller_reader_assignments(
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    principal_id: str = _object_id(201),
) -> dict[str, object]:
    scope = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.cleanup_resource_group}"
    )
    return _command_result(
        [
            {
                "id": (
                    f"{scope}/providers/Microsoft.Authorization/roleAssignments/{_object_id(203)}"
                ),
                "principalId": principal_id,
                "roleDefinitionId": (
                    f"/subscriptions/{runtime['subscriptionId']}/providers/"
                    "Microsoft.Authorization/roleDefinitions/"
                    "acdd72a7-3385-48ef-bd42-f606fba81ae7"
                ),
                "scope": scope,
            }
        ]
    )


def _cleanup_deployment_result(
    config: CampaignConfig, runtime: dict[str, str] | None = None
) -> dict[str, object]:
    runtime = runtime or _runtime()
    subscription_id = runtime["subscriptionId"]
    target_scope = f"/subscriptions/{subscription_id}/resourceGroups/{config.target_resource_group}"
    contributor = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        "roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
    )
    rbac = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        "roleDefinitions/f58310d9-a9f6-439a-9e8d-f62e7b41a168"
    )
    values = {
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "targetResourceGroupName": config.target_resource_group,
        "cleanupResourceGroupName": config.cleanup_resource_group,
        "cleanupPrincipalId": _object_id(201),
        "cleanupLocation": config.cleanup_region,
        "cleanupRegionSelectionSha256": config.cleanup_region_selection_sha256,
        "cleanupCandidateRegions": config.cleanup_candidate_regions,
        "cleanupOfferClassification": config.cleanup_offer_classification,
        "cleanupOfferEligibilityDisposition": (config.cleanup_offer_eligibility_disposition),
        "cleanupOfferEligibleRegions": config.cleanup_offer_eligible_regions,
        "cleanupOfferEligibilitySource": config.cleanup_offer_eligibility_source,
        "cleanupOfferEligibilitySha256": config.cleanup_offer_eligibility_sha256,
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "cleanupAuthorityExpiresUtc": runtime["cleanupAuthorityExpiresUtc"],
        "automationAccountName": runtime["automationAccountName"],
        "runbookName": runtime["runbookName"],
        "costCeilingCents": 5000,
        "scheduleName": runtime["scheduleName"],
        "bindingName": runtime["bindingName"],
        "scheduleCount": 0,
        "bindingCount": 0,
        "cleanupRoleDefinitionIds": {
            "contributor": contributor,
            "rbacAdministrator": rbac,
        },
        "targetRoleAssignmentIds": [
            f"{target_scope}/providers/Microsoft.Authorization/roleAssignments/{_object_id(301)}",
            f"{target_scope}/providers/Microsoft.Authorization/roleAssignments/{_object_id(302)}",
        ],
    }
    return _command_result(
        {"properties": {"outputs": {key: {"value": value} for key, value in values.items()}}}
    )


def test_cleanup_binding_and_readback_reject_substitution() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    deployment = _cleanup_deployment_result(config, runtime)
    validate_cleanup_deployment(deployment, config)
    tampered = _cleanup_deployment_result(config, runtime)
    tampered_payload = json.loads(str(tampered["stdout"]))
    tampered_payload["properties"]["outputs"]["cleanupOfferEligibilitySha256"]["value"] = "0" * 64
    tampered["stdout"] = json.dumps(tampered_payload)
    with pytest.raises(CampaignError, match="cleanup binding"):
        validate_cleanup_deployment(tampered, config)
    outputs = campaign_operator._deployment_outputs(deployment)
    principal_id = _object_id(201)
    role_definitions = list(outputs["cleanupRoleDefinitionIds"].values())

    def assignments(scope: str, ids: list[str]) -> dict[str, object]:
        return _command_result(
            [
                {
                    "id": assignment_id,
                    "principalId": principal_id,
                    "roleDefinitionId": role_definition_id,
                    "scope": scope,
                }
                for assignment_id, role_definition_id in zip(ids, role_definitions, strict=True)
            ]
        )

    target_scope = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.target_resource_group}"
    )
    controller_tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": "reusable-automation-controller-v1",
        "mobius.subscription-correlation": config.subscription_correlation,
        "mobius.controller-authorized-until-utc": "2030-01-02T00:00:00Z",
        "mobius.cleanup-script-sha256": runtime["cleanupScriptSha256"],
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }
    results = [
        deployment,
        _command_result(
            {
                "name": runtime["automationAccountName"],
                "identity": {"principalId": principal_id},
                "location": "East US 2",
                "tags": controller_tags,
            }
        ),
        assignments(target_scope, outputs["targetRoleAssignmentIds"]),
        _controller_reader_assignments(config, runtime, principal_id=principal_id),
        _command_result(
            {
                "name": runtime["runbookName"],
                "properties": {
                    "state": "Published",
                    "lastModifiedTime": "2030-01-01T00:01:00Z",
                },
            }
        ),
        {
            "exitCode": 0,
            "stdout": "cleanup-content",
            "stderr": "",
        },
        _command_result(
            {
                "name": runtime["scheduleName"],
                "properties": {
                    "frequency": "OneTime",
                    "interval": 1,
                    "isEnabled": True,
                    "startTime": config.cleanup_deadline_utc,
                    "timeZone": "Etc/UTC",
                },
            }
        ),
        _command_result(
            {
                "value": [
                    {
                        "name": runtime["bindingName"],
                        "properties": {
                            "parameters": campaign_operator.cleanup_job_parameters(config, runtime),
                            "runbook": {"name": runtime["runbookName"]},
                            "schedule": {"name": runtime["scheduleName"]},
                        },
                    }
                ]
            }
        ),
    ]
    validate_cleanup_readback(results, config, runtime)
    results[6] = _command_result(
        {
            "name": runtime["scheduleName"],
            "properties": {
                "frequency": "OneTime",
                "interval": 1,
                "startTime": "2030-01-01T04:01:00Z",
                "timeZone": "Etc/UTC",
            },
        }
    )
    with pytest.raises(CampaignError, match="readback drifted"):
        validate_cleanup_readback(results, config, runtime)


def test_scope_readback_binds_offer_eligibility_tags() -> None:
    config = _config()
    runtime = _runtime()
    tags = {
        "mobius.campaign": config.campaign_id,
        "mobius.generation": config.generation_id,
        "mobius.milestone": "7.8",
        "mobius.cleanup-deadline-utc": config.cleanup_deadline_utc,
        "mobius.cost-ceiling-cents": "5000",
        "mobius.cleanup-region-selection-sha256": (config.cleanup_region_selection_sha256),
        "mobius.cleanup-candidate-regions": config.cleanup_candidate_regions,
        "mobius.cleanup-offer-classification": config.cleanup_offer_classification,
        "mobius.cleanup-offer-disposition": (config.cleanup_offer_eligibility_disposition),
        "mobius.cleanup-offer-regions": config.cleanup_offer_eligible_regions,
        "mobius.cleanup-offer-source": config.cleanup_offer_eligibility_source,
        "mobius.cleanup-offer-eligibility-sha256": (config.cleanup_offer_eligibility_sha256),
        "mobius.fresh-controller-admission-sha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
    }
    result = _command_result({"name": config.target_resource_group, "tags": tags})
    validate_operation_results("scope-create", [result], config, runtime)

    tags["mobius.cleanup-offer-eligibility-sha256"] = "0" * 64
    with pytest.raises(CampaignError, match="scope readback differs"):
        validate_operation_results(
            "scope-create",
            [_command_result({"name": config.target_resource_group, "tags": tags})],
            config,
            runtime,
        )


def test_fake_azure_job_adapter_waits_for_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAzureRunner:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            self.commands.append(command)
            if "execution" in command and "show" in command:
                return _command_result(
                    {"name": "execution-one", "properties": {"status": "Succeeded"}}
                )
            return _command_result({"name": "execution-one", "properties": {"status": "Running"}})

    monkeypatch.setattr(campaign_operator.time, "sleep", lambda _seconds: None)
    runner = FakeAzureRunner()
    command = (
        "az",
        "containerapp",
        "job",
        "start",
        "--resource-group",
        "rg-proof",
        "--name",
        "job-proof",
        "--output",
        "json",
    )
    result = execute_commands(runner, (command,))  # type: ignore[arg-type]
    assert result[0]["terminalStatus"] == "Succeeded"
    assert len(runner.commands) == 2


def test_managed_evidence_sequence_derives_recovery_and_persists_receipt(
    tmp_path: Path,
) -> None:
    class FakeEvidenceRunner:
        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            if command[:4] == ("az", "containerapp", "job", "start"):
                return _command_result(
                    {
                        "name": "execution-"
                        + hashlib.sha256(" ".join(command).encode()).hexdigest()[:8],
                        "status": "Succeeded",
                    }
                )
            return _command_result({"status": "Succeeded"})

    runtime = _runtime()
    config = _config(image_digest="sha256:" + "e" * 64)
    control = _operator_control_plane_evidence()
    commands = command_plan(
        "evidence",
        config,
        runtime,
        control_plane_evidence="<derived-after-successful-managed-probes>",
    )
    results = campaign_operator.execute_evidence_commands(
        FakeEvidenceRunner(),
        commands,
        control,  # type: ignore[arg-type]
    )
    assert len(results) == 12
    path = tmp_path / "managed-evidence-execution.json"
    campaign_operator.persist_evidence_execution_receipt(
        path,
        config=config,
        runtime=runtime,
        commands=commands,
        results=results,
        control_plane_evidence=control,
    )
    campaign_operator.validate_evidence_execution_receipt(
        path,
        config=config,
        runtime=runtime,
        control_plane_evidence=control,
    )
    assert "<derived-after" not in path.read_text(encoding="utf-8")


def test_zero_residue_requires_all_control_plane_reads_to_be_empty() -> None:
    config = _config()
    runtime = _runtime()
    results = [
        _command_result(False),
        _command_result([]),
        _command_result([]),
        _command_result(
            {
                "name": config.cleanup_resource_group,
                "location": config.cleanup_region,
                "tags": _controller_tags(config, runtime),
            }
        ),
        _command_result(_controller_account_record(config, runtime)),
        _command_result({"value": []}),
        _command_result({"value": []}),
        _command_result(
            {
                "complete": True,
                "pageCount": 1,
                "value": [_controller_account_record(config, runtime)],
            }
        ),
        _command_result({"complete": True, "pageCount": 1, "value": []}),
    ]
    assert set(verify_zero_residue(results, config, runtime).values()) == {0}
    results[8] = _command_result(
        {
            "complete": True,
            "pageCount": 1,
            "value": [
                {
                    "name": runtime["automationAccountName"],
                    "location": config.cleanup_region,
                    "properties": {
                        "automationAccountResourceId": (
                            f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/"
                            f"{config.cleanup_resource_group}/providers/Microsoft.Automation/"
                            f"automationAccounts/{runtime['automationAccountName']}"
                        )
                    },
                }
            ],
        }
    )
    with pytest.raises(CampaignError, match="retained exactly once"):
        verify_zero_residue(results, config, runtime)
    with pytest.raises(CampaignError, match="retained exactly once"):
        observe_residue(results, config, runtime)


def test_resume_ledger_rejects_substituted_phase() -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_cleanup_region(config)
    ledger.phase = Phase.CORRELATED.value
    with pytest.raises(CampaignError, match="transition chain"):
        ledger.validate_resume(config)


@pytest.mark.parametrize(
    "failure", ["dirty", "branch", "no-upstream", "other-upstream", "stashes", "output"]
)
def test_prepare_rejects_invalid_local_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    output = tmp_path / "existing" if failure == "output" else tmp_path / "new"
    if failure == "output":
        output.mkdir()
        (output / "sentinel").write_text("preserved", encoding="utf-8")
    values = {
        ("status", "--porcelain=v1"): " M tracked" if failure == "dirty" else "",
        ("branch", "--show-current"): (
            "wrong" if failure == "branch" else "milestone-7-8-production-readiness-audit-local"
        ),
        (
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        ): {
            "no-upstream": "",
            "other-upstream": "refs/remotes/origin/other",
        }.get(failure, "refs/remotes/origin/milestone-7-8-production-readiness-audit-local"),
        ("stash", "list", "--format=%H"): "\n".join(
            str(i) for i in range(4 if failure == "stashes" else 5)
        ),
    }
    monkeypatch.setattr(prepare, "_git", lambda *args: values[args])
    monkeypatch.setattr(
        prepare,
        "discover_automation_region",
        lambda *_args, **_kwargs: pytest.fail("invalid boundary reached provider discovery"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare",
            "--campaign-id",
            "mobius78-managed-proof",
            "--generation-id",
            "g1-aabbccddeeff",
            "--output",
            str(output),
            "--controller-region",
            "eastus",
            "--fresh-subscription-runtime",
            "unused",
            "--fresh-subscription-authorization",
            "unused",
            "--fresh-subscription-evidence",
            "unused",
        ],
    )
    assert prepare.main() != 0
    if failure == "output":
        assert (output / "sentinel").read_text(encoding="utf-8") == "preserved"
    else:
        assert not output.exists()


def test_prepare_creates_one_private_restart_safe_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subscription = _object_id(101)
    tenant = _object_id(102)
    parent = tmp_path / "runtime"
    parent.mkdir()
    existing_evidence = parent / "existing-private-evidence.json"
    existing_evidence.write_text('{"preserved":true}', encoding="utf-8")
    output = parent / "new-campaign"
    monkeypatch.setenv("M78_SUBSCRIPTION_ID", subscription)
    monkeypatch.setenv("M78_TENANT_ID", tenant)
    fresh_scope_document = predeployment.build_runtime_document(
        subscription_id=subscription,
        tenant_id=tenant,
        campaign_id="mobius78-managed-proof",
        generation_id="g1-aabbccddeeff",
        region="eastus2",
    )
    fresh_scope_path = tmp_path / "fresh-subscription-runtime.json"
    fresh_scope_path.write_text(json.dumps(fresh_scope_document), encoding="utf-8")
    fresh_scope = predeployment.load_runtime(fresh_scope_path)
    fresh_authorization = predeployment.build_read_authorization(
        fresh_scope,
        issued_at=NOW,
        expires_at=NOW.replace(minute=30),
    )
    fresh_authorization_path = tmp_path / "predeployment-read-authorization.json"
    fresh_authorization_path.write_text(json.dumps(fresh_authorization), encoding="utf-8")
    fresh_evidence = predeployment.build_evidence_document(
        fresh_scope,
        authorization=fresh_authorization,
        observed_at=NOW,
        pages=[
            {
                "requestSha256": predeployment.request_sha256(predeployment.endpoint(subscription)),
                "recordIdentitySha256": [],
                "nextRequestSha256": None,
            }
        ],
    )
    fresh_evidence_path = tmp_path / "predeployment-absence-evidence.json"
    fresh_evidence_path.write_text(json.dumps(fresh_evidence), encoding="utf-8")
    fresh_evidence_sha256 = predeployment.evidence_sha256(fresh_evidence)
    git_values = {
        ("status", "--porcelain=v1"): "",
        ("branch", "--show-current"): "milestone-7-8-production-readiness-audit-local",
        (
            "for-each-ref",
            "--format=%(upstream)",
            "refs/heads/milestone-7-8-production-readiness-audit-local",
        ): "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
        ("stash", "list", "--format=%H"): "\n".join(str(index) for index in range(5)),
        ("rev-parse", "HEAD"): "a" * 40,
    }
    monkeypatch.setattr(prepare, "_git", lambda *args: git_values[args])
    monkeypatch.setattr(
        prepare,
        "canonical_snapshot",
        lambda _treeish: {
            "buildInputSha256": "b" * 64,
            "dockerfileSha256": "c" * 64,
        },
    )
    selection = AutomationRegionSelection(
        version="m7.8-cleanup-region-selection-v5",
        candidate_order=CLEANUP_REGION_CANDIDATES,
        selected_region="eastus2",
        provider_registration_state="Registered",
        capacity_basis=("provider-offer-policy-exact-controller-or-zero-occupancy"),
        controller_disposition="exact-controller-adoptable",
        controller_region="eastus2",
        policy_assignment_count=0,
        policy_definition_count=0,
        provider_locations_sha256="1" * 64,
        offer_classification="restricted-public-offer",
        offer_eligibility_disposition="restricted-offer-metadata-confirmed",
        offer_eligible_regions=RESTRICTED_OFFER_ELIGIBLE_REGIONS,
        offer_eligibility_source=OFFER_ELIGIBILITY_SOURCE,
        offer_eligibility_sha256="5" * 64,
        active_occupancy_sha256="2" * 64,
        soft_deleted_occupancy_sha256="3" * 64,
        policy_evidence_sha256="4" * 64,
        fresh_controller_admission_evidence_sha256=fresh_evidence_sha256,
        observed_at_utc="2030-01-01T00:00:00Z",
        candidates=tuple(
            CandidateEvidence(
                region,
                True,
                region in RESTRICTED_OFFER_ELIGIBLE_REGIONS,
                True,
                int(region == "eastus2"),
                int(region == "eastus2"),
                0,
                (
                    "viable"
                    if region == "eastus2"
                    else "offer-ineligible"
                    if region not in RESTRICTED_OFFER_ELIGIBLE_REGIONS
                    else "controller-region-mismatch"
                ),
            )
            for region in CLEANUP_REGION_CANDIDATES
        ),
    )
    monkeypatch.setattr(prepare, "discover_automation_region", lambda *_args, **_kwargs: selection)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare",
            "--campaign-id",
            "mobius78-managed-proof",
            "--generation-id",
            "g1-aabbccddeeff",
            "--output",
            str(output),
            "--target-region",
            "eastus2",
            "--postgres-region",
            "eastus2",
            "--controller-region",
            "eastus2",
            "--fresh-subscription-runtime",
            str(fresh_scope_path),
            "--fresh-subscription-authorization",
            str(fresh_authorization_path),
            "--fresh-subscription-evidence",
            str(fresh_evidence_path),
        ],
    )
    assert prepare.main() == 0
    assert existing_evidence.read_text(encoding="utf-8") == '{"preserved":true}'
    stdout = capsys.readouterr().out
    assert subscription not in stdout and tenant not in stdout
    config = CampaignConfig.from_json(output / "campaign.json")
    assert config.campaign_id == "mobius78-managed-proof"
    assert config.cleanup_candidate_regions == CLEANUP_CANDIDATE_REGIONS_BINDING
    assert config.cleanup_offer_classification == selection.offer_classification
    assert config.cleanup_offer_eligible_regions == OFFER_ELIGIBLE_REGIONS_BINDING
    assert config.cleanup_offer_eligibility_sha256 == selection.offer_eligibility_sha256
    runtime_path = output / "runtime.json"
    runtime = campaign_operator.load_runtime(runtime_path)
    campaign_operator.validate_prepared_bundle(runtime_path, runtime, config)
    assert runtime["cleanupControllerArmability"] == (
        "architecture-corrected-live-execution-not-authorized"
    )
    assert set(json.loads(runtime_path.read_text())) == {
        *{
            "subscriptionId",
            "sourceHead",
            "canonicalBuildInputSha256",
            "dockerfileSha256",
            "cleanupScriptSha256",
            "automationApiVersion",
            "cleanupControllerArchitecture",
            "cleanupControllerArmability",
            "controllerBindingSha256",
            "cleanupAuthorityExpiresUtc",
            "cleanupRegion",
            "cleanupRegionSelectionSha256",
            "cleanupCandidateRegions",
            "cleanupOfferClassification",
            "cleanupOfferEligibilityDisposition",
            "cleanupOfferEligibleRegions",
            "cleanupOfferEligibilitySource",
            "cleanupOfferEligibilitySha256",
            "freshControllerAdmissionEvidenceSha256",
            "freshControllerAdmissionEvidenceVersion",
            "freshControllerAdmissionEvidenceClass",
            "freshControllerAdmissionEvidenceObservedAtUtc",
            "freshControllerAdmissionRuntimeFile",
            "freshControllerAdmissionAuthorizationFile",
            "freshControllerAdmissionEvidenceFile",
            "cleanupRegionSelectionFile",
            "cleanupDeploymentName",
            "campaignDeploymentName",
            "automationAccountName",
            "runbookName",
            "scheduleName",
            "bindingName",
            "bootstrapJobName",
            "migrationJobName",
            "workerJobName",
            "evidenceJobName",
            "apiProbeJobName",
            "workerProbeJobName",
            "migrationProbeJobName",
            "recoveryJobName",
            "recoveryRestoreJobName",
            "postgresServerName",
            "registryName",
            "logAnalyticsWorkspaceName",
            "resourceGroupName",
            "cleanupResourceGroupName",
            "cleanupParametersFile",
            "campaignParametersFile",
        }
    }
    cleanup_path = output / "cleanup.parameters.json"
    cleanup = json.loads(cleanup_path.read_text())
    cleanup["parameters"]["targetResourceGroupName"]["value"] = "rg-m78-0000000000-target"
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(CampaignError, match="campaign binding differs"):
        campaign_operator.validate_prepared_bundle(runtime_path, runtime, config)
    with pytest.raises(FileExistsError):
        output.mkdir()


def _cleanup_arm_success_results(
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    runbook_state: str = "Published",
    runbook_name: str | None = None,
    modified: str | None = "2030-01-01T00:01:00Z",
    content: str = "cleanup-content",
    bindings: int = 1,
    existing_schedule: bool = False,
    existing_binding: bool = False,
) -> list[dict[str, object]]:
    deployment = _cleanup_deployment_result(config, runtime)
    outputs = campaign_operator._deployment_outputs(deployment)
    principal_id = _object_id(201)
    role_definitions = list(outputs["cleanupRoleDefinitionIds"].values())

    def assignments(scope: str, ids: object) -> dict[str, object]:
        assert isinstance(ids, list)
        return _command_result(
            [
                {
                    "id": assignment_id,
                    "principalId": principal_id,
                    "roleDefinitionId": role_definition_id,
                    "scope": scope,
                }
                for assignment_id, role_definition_id in zip(ids, role_definitions, strict=True)
            ]
        )

    runbook_properties: dict[str, object] = {"state": runbook_state}
    if modified is not None:
        runbook_properties["lastModifiedTime"] = modified
    binding_values = [
        {
            "name": runtime["bindingName"],
            "properties": {
                "parameters": {
                    "CampaignId": config.campaign_id,
                    "GenerationId": config.generation_id,
                    "SubscriptionCorrelation": config.subscription_correlation,
                    "TargetResourceGroupName": config.target_resource_group,
                    **campaign_operator.cleanup_job_parameters(config, runtime),
                },
                "runbook": {"name": runtime["runbookName"]},
                "schedule": {"name": runtime["scheduleName"]},
            },
        }
        for _ in range(bindings)
    ]
    target_scope = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/{config.target_resource_group}"
    )
    schedule_value = {
        "name": runtime["scheduleName"],
        "properties": {
            "frequency": "OneTime",
            "interval": 1,
            "isEnabled": True,
            "startTime": config.cleanup_deadline_utc,
            "timeZone": "Etc/UTC",
        },
    }
    return [
        deployment,
        _command_result(
            {
                **_controller_account_record(config, runtime),
                "identity": {"principalId": principal_id},
                "location": "East US 2",
            }
        ),
        assignments(target_scope, outputs["targetRoleAssignmentIds"]),
        _controller_reader_assignments(config, runtime, principal_id=principal_id),
        _command_result(
            {
                "name": runbook_name or runtime["runbookName"],
                "properties": runbook_properties,
            }
        ),
        {"exitCode": 0, "stdout": content, "stderr": ""},
        _command_result({"value": [schedule_value] if existing_schedule else []}),
        _command_result({"value": binding_values if existing_binding else []}),
        _command_result({"status": "accepted"}),
        _command_result(schedule_value),
        _command_result({"status": "accepted"}),
        _command_result({"value": binding_values}),
    ]


class _OrderedCleanupRunner:
    def __init__(self, results: list[dict[str, object]], *, fail_at: int | None = None) -> None:
        self.results = results
        self.fail_at = fail_at
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        index = len(self.commands)
        self.commands.append(command)
        if index == self.fail_at:
            return {"exitCode": 1, "stdout": "", "stderr": "safe failure"}
        return self.results[index]


def _controller_baseline_results(
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    schedules: list[object] | None = None,
    bindings: list[object] | None = None,
) -> list[dict[str, object]]:
    return [
        _command_result(
            {
                "name": config.cleanup_resource_group,
                "location": config.cleanup_region,
                "tags": _controller_tags(config, runtime),
            }
        ),
        _command_result(_controller_account_record(config, runtime)),
        _controller_reader_assignments(config, runtime),
        _command_result(
            {
                "name": runtime["runbookName"],
                "properties": {
                    "state": "Published",
                    "lastModifiedTime": "2030-01-01T00:01:00Z",
                },
            }
        ),
        {"exitCode": 0, "stdout": "cleanup-content", "stderr": ""},
        _command_result({"value": schedules or []}),
        _command_result({"value": bindings or []}),
        _cleanup_deployment_result(config, runtime),
    ]


def test_campaign_path_cannot_create_or_delete_reusable_controller() -> None:
    config = _config()
    runtime = _runtime()
    for operation in OPERATION_PHASE:
        for command in command_plan(operation, config, runtime):
            rendered = " ".join(command).casefold()
            assert "automation account create" not in rendered
            assert "automation account delete" not in rendered
            if "--method delete" in rendered and "/automationaccounts/" in rendered:
                assert "/jobschedules/" in rendered or "/schedules/" in rendered
    cleanup = (REPOSITORY_ROOT / "infra/milestone_7_8/cleanup.bicep").read_text()
    assert "automationAccounts@2024-10-23' existing" in cleanup
    assert "resource controllerResourceGroup" in cleanup
    assert (
        "resource controllerResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' ="
        not in cleanup
    )


def test_cleanup_deploy_rejects_busy_controller_before_target_rbac_mutation() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    live_schedule = {
        "name": "another-schedule",
        "properties": {"frequency": "OneTime"},
    }
    runner = _OrderedCleanupRunner(
        _controller_baseline_results(config, runtime, schedules=[live_schedule])
    )
    with pytest.raises(CampaignError, match="exclusively adoptable"):
        execute_cleanup_deploy_commands(
            runner,
            command_plan("cleanup-deploy", config, runtime),
            config,
            runtime,  # type: ignore[arg-type]
        )
    assert len(runner.commands) == 7
    assert not any("deployment sub create" in " ".join(item) for item in runner.commands)


def test_initial_cleanup_deployment_has_no_schedule_or_binding() -> None:
    controller = (
        REPOSITORY_ROOT / "infra/milestone_7_8/modules/cleanup-controller.bicep"
    ).read_text(encoding="utf-8")
    cleanup = (REPOSITORY_ROOT / "infra/milestone_7_8/cleanup.bicep").read_text(encoding="utf-8")
    assert "automationAccounts/schedules@" not in controller
    assert "automationAccounts/jobSchedules@" not in controller
    assert "output scheduleCount int = 0" in cleanup
    assert "output bindingCount int = 0" in cleanup


def test_cleanup_arming_adopts_published_controller_and_is_restart_deterministic() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    commands = command_plan("cleanup-arm", config, runtime)
    rendered = [" ".join(command) for command in commands]
    runbook_read_index = next(
        index for index, value in enumerate(rendered) if "/runbooks/" in value
    )
    schedule_index = next(
        index
        for index, value in enumerate(rendered)
        if "/schedules/" in value and "--method put" in value
    )
    binding_index = next(
        index
        for index, value in enumerate(rendered)
        if "/jobSchedules/" in value and "--method put" in value
    )
    assert not any("runbook publish" in value or "replace-content" in value for value in rendered)
    assert runbook_read_index < schedule_index < binding_index
    first = _OrderedCleanupRunner(_cleanup_arm_success_results(config, runtime))
    _, first_hash = execute_cleanup_arm_commands(first, commands, config, runtime)  # type: ignore[arg-type]
    second = _OrderedCleanupRunner(_cleanup_arm_success_results(config, runtime))
    _, second_hash = execute_cleanup_arm_commands(second, commands, config, runtime)  # type: ignore[arg-type]
    assert first.commands == second.commands == list(commands)
    assert first_hash == second_hash


def test_cleanup_arming_adopts_exact_existing_schedule_and_binding_without_put() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    all_results = _cleanup_arm_success_results(
        config, runtime, existing_schedule=True, existing_binding=True
    )
    runner = _OrderedCleanupRunner(all_results[:8])
    _, proof = execute_cleanup_arm_commands(
        runner,
        command_plan("cleanup-arm", config, runtime),
        config,
        runtime,  # type: ignore[arg-type]
    )
    assert len(proof) == 64
    assert len(runner.commands) == 8
    assert not any("--method put" in " ".join(item) for item in runner.commands)


def test_cleanup_arming_retries_partial_schedule_by_creating_only_binding() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    all_results = _cleanup_arm_success_results(config, runtime, existing_schedule=True)
    runner = _OrderedCleanupRunner([*all_results[:8], all_results[10], all_results[11]])
    _, proof = execute_cleanup_arm_commands(
        runner,
        command_plan("cleanup-arm", config, runtime),
        config,
        runtime,  # type: ignore[arg-type]
    )
    rendered = [" ".join(item).casefold() for item in runner.commands]
    assert len(proof) == 64
    assert len(rendered) == 10
    assert not any("/schedules/" in item and "--method put" in item for item in rendered)
    assert sum("/jobschedules/" in item and "--method put" in item for item in rendered) == 1


def test_controller_read_failure_and_draft_readback_stop_before_schedule() -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    commands = command_plan("cleanup-arm", config, runtime)
    publication_failure = _OrderedCleanupRunner(
        _cleanup_arm_success_results(config, runtime), fail_at=5
    )
    with pytest.raises(CampaignError, match="failed safely"):
        execute_cleanup_arm_commands(publication_failure, commands, config, runtime)  # type: ignore[arg-type]
    assert len(publication_failure.commands) == 6
    assert not any("--method put" in " ".join(item) for item in publication_failure.commands)

    draft = _OrderedCleanupRunner(
        _cleanup_arm_success_results(config, runtime, runbook_state="Edit")
    )
    with pytest.raises(CampaignError, match="not published"):
        execute_cleanup_arm_commands(draft, commands, config, runtime)  # type: ignore[arg-type]
    assert len(draft.commands) == 8
    assert not any("--method put" in " ".join(item) for item in draft.commands)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"modified": None}, "stale or missing"),
        ({"runbook_name": "wrong-runbook"}, "identity differs"),
        ({"content": "wrong-content"}, "content differs"),
        ({"bindings": 0}, "exactly one"),
        ({"bindings": 2}, "exactly one"),
    ],
)
def test_cleanup_arming_rejects_missing_stale_mismatched_or_duplicate_proof(
    changes: dict[str, object], message: str
) -> None:
    config = _config()
    runtime = _runtime()
    runtime["cleanupScriptSha256"] = hashlib.sha256(b"cleanup-content").hexdigest()
    runner = _OrderedCleanupRunner(
        _cleanup_arm_success_results(config, runtime, **changes)  # type: ignore[arg-type]
    )
    with pytest.raises(CampaignError, match=message):
        execute_cleanup_arm_commands(
            runner,
            command_plan("cleanup-arm", config, runtime),
            config,
            runtime,  # type: ignore[arg-type]
        )


def test_cleanup_disarm_reconciles_ambiguous_delete_and_requires_absence() -> None:
    config = _config()
    runtime = _runtime()
    commands = command_plan("cleanup-disarm", config, runtime)
    ambiguous = _OrderedCleanupRunner(
        [
            {"exitCode": 1, "stdout": "", "stderr": "ambiguous timeout"},
            {"exitCode": 1, "stdout": "", "stderr": "not found"},
            _command_result({"value": []}),
            _command_result({"value": []}),
        ]
    )
    _, proof = execute_cleanup_disarm_commands(
        ambiguous,
        commands,
        config,
        runtime,  # type: ignore[arg-type]
    )
    assert len(proof) == 64

    residual = _OrderedCleanupRunner(
        [
            _command_result({}),
            _command_result({}),
            _command_result({"value": [{"name": runtime["scheduleName"]}]}),
            _command_result({"value": []}),
        ]
    )
    with pytest.raises(CampaignError, match="revocation failed"):
        execute_cleanup_disarm_commands(
            residual,
            commands,
            config,
            runtime,  # type: ignore[arg-type]
        )


def _write_execution_authorization(
    path: Path,
    config: CampaignConfig,
    runtime: dict[str, str],
    *,
    expires_at: str,
    operations: list[str],
) -> None:
    value: dict[str, object] = {
        "version": "m7.8-execution-authorization-v4",
        "disposition": "separately-authorized-azure-execution",
        "campaignId": config.campaign_id,
        "generationId": config.generation_id,
        "subscriptionCorrelation": config.subscription_correlation,
        "sourceHead": runtime["sourceHead"],
        "controllerArchitecture": "reusable-automation-controller-v1",
        "controllerBindingSha256": runtime["controllerBindingSha256"],
        "freshControllerAdmissionEvidenceSha256": (
            config.fresh_controller_admission_evidence_sha256
        ),
        "freshControllerAdmissionEvidenceVersion": runtime[
            "freshControllerAdmissionEvidenceVersion"
        ],
        "cleanupDeadlineUtc": config.cleanup_deadline_utc,
        "expiresAtUtc": expires_at,
        "allowedOperations": operations,
    }
    value["authorizationSha256"] = hashlib.sha256(
        b"m7.8/execution-authorization/v4\0"
        + json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    path.write_text(json.dumps(value), encoding="utf-8")


def test_execution_authorization_is_exact_expiring_and_operation_scoped(
    tmp_path: Path,
) -> None:
    config = _config()
    runtime = _runtime()
    path = tmp_path / "authorization.json"
    _write_execution_authorization(
        path,
        config,
        runtime,
        expires_at="2030-01-01T04:30:00Z",
        operations=["cleanup-deploy"],
    )
    authorization = load_execution_authorization(
        path,
        config=config,
        runtime=runtime,
        operation="cleanup-deploy",
        now=datetime(2030, 1, 1, 4, tzinfo=UTC),
    )
    assert authorization.allowed_operations == frozenset({"cleanup-deploy"})
    with pytest.raises(CampaignError, match="not exact"):
        load_execution_authorization(
            path,
            config=replace(config, fresh_controller_admission_evidence_sha256="1" * 64),
            runtime=runtime,
            operation="cleanup-deploy",
            now=datetime(2030, 1, 1, 4, tzinfo=UTC),
        )

    _write_execution_authorization(
        path,
        config,
        runtime,
        expires_at="2030-01-01T04:30:00Z",
        operations=["preflight"],
    )
    authorization = load_execution_authorization(
        path,
        config=config,
        runtime=runtime,
        operation="preflight",
        now=datetime(2030, 1, 1, 4, tzinfo=UTC),
    )
    assert authorization.allowed_operations == frozenset({"preflight"})

    _write_execution_authorization(
        path,
        config,
        runtime,
        expires_at="2030-01-01T04:30:00Z",
        operations=["cleanup-deploy"],
    )
    with pytest.raises(CampaignError, match="not exact"):
        load_execution_authorization(
            path,
            config=config,
            runtime=runtime,
            operation="cleanup-arm",
            now=datetime(2030, 1, 1, 4, tzinfo=UTC),
        )
    with pytest.raises(CampaignError, match="expired or overbroad"):
        load_execution_authorization(
            path,
            config=config,
            runtime=runtime,
            operation="cleanup-deploy",
            now=datetime(2030, 1, 1, 4, 30, tzinfo=UTC),
        )

    _write_execution_authorization(
        path,
        config,
        runtime,
        expires_at="2030-01-01T05:01:00Z",
        operations=["cleanup-deploy"],
    )
    with pytest.raises(CampaignError, match="expired or overbroad"):
        load_execution_authorization(
            path,
            config=config,
            runtime=runtime,
            operation="cleanup-deploy",
            now=datetime(2030, 1, 1, 4, tzinfo=UTC),
        )


def test_fresh_controller_admission_blocks_missing_or_mismatched_bundle(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    campaign_id = "mobius78-pg-proof"
    generation_id = "g1-aabbccddeeff"
    fresh_runtime_document = predeployment.build_runtime_document(
        subscription_id=runtime["subscriptionId"],
        tenant_id=_object_id(102),
        campaign_id=campaign_id,
        generation_id=generation_id,
        region="eastus2",
    )
    scope_path = tmp_path / "fresh-subscription-runtime.json"
    scope_path.write_text(json.dumps(fresh_runtime_document), encoding="utf-8")
    scope = predeployment.load_runtime(scope_path)
    runtime["cleanupResourceGroupName"] = scope.controller_resource_group_name
    runtime["automationAccountName"] = scope.automation_account_name
    runtime["controllerBindingSha256"] = campaign_operator.controller_binding_sha256(
        scope.subscription_id,
        resource_group=scope.controller_resource_group_name,
        account=scope.automation_account_name,
        runbook="Remove-M78Campaign",
    )
    authorization = predeployment.build_read_authorization(
        scope,
        issued_at=NOW,
        expires_at=NOW.replace(minute=30),
    )
    authorization_path = tmp_path / "predeployment-read-authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    value = predeployment.build_evidence_document(
        scope,
        authorization=authorization,
        observed_at=NOW,
        pages=[
            {
                "requestSha256": predeployment.request_sha256(
                    predeployment.endpoint(scope.subscription_id)
                ),
                "recordIdentitySha256": [],
                "nextRequestSha256": None,
            }
        ],
    )
    evidence_path = tmp_path / "predeployment-absence-evidence.json"
    evidence_path.write_text(json.dumps(value), encoding="utf-8")
    evidence_sha256 = predeployment.evidence_sha256(value)
    config = replace(
        _config(),
        subscription_correlation=campaign_operator.sanitize(
            runtime["subscriptionId"], domain="subscription"
        ),
        cleanup_resource_group=scope.controller_resource_group_name,
        fresh_controller_admission_evidence_sha256=evidence_sha256,
    )
    runtime.update(
        {
            "freshControllerAdmissionEvidenceSha256": evidence_sha256,
            "freshControllerAdmissionEvidenceVersion": predeployment.EVIDENCE_VERSION,
            "freshControllerAdmissionEvidenceClass": predeployment.EVIDENCE_CLASS,
            "freshControllerAdmissionEvidenceObservedAtUtc": str(value["observedAtUtc"]),
            "freshControllerAdmissionRuntimeFile": str(scope_path),
            "freshControllerAdmissionAuthorizationFile": str(authorization_path),
            "freshControllerAdmissionEvidenceFile": str(evidence_path),
        }
    )
    runtime_path = tmp_path / "runtime.json"

    campaign_operator.load_bound_fresh_controller_admission(
        runtime_path,
        runtime,
        config,
    )
    with pytest.raises(CampaignError, match="binding differs"):
        campaign_operator.load_bound_fresh_controller_admission(
            runtime_path,
            runtime,
            replace(config, fresh_controller_admission_evidence_sha256="1" * 64),
        )
    assert campaign_operator.cleanup_authority_sha256(
        config, runtime
    ) != campaign_operator.cleanup_authority_sha256(
        replace(config, fresh_controller_admission_evidence_sha256="1" * 64), runtime
    )


def test_fresh_controller_lifecycle_never_requires_post_delete_absence() -> None:
    """Fresh admission proves planned-controller non-occupancy, not retention.

    This regression guard deliberately covers the executable fresh path rather
    than the historical v3 parser.  A retained controller is required to stay
    active during campaign finalization, and an unrelated deleted record is
    observation-only (covered by the paginated residue test immediately below).
    """

    fresh_paths = (
        REPOSITORY_ROOT / "infra/milestone_7_8/prepare.py",
        REPOSITORY_ROOT / "infra/milestone_7_8/controller.py",
        REPOSITORY_ROOT / "infra/milestone_7_8/operator.py",
        REPOSITORY_ROOT / "infra/milestone_7_8/campaign.py",
        REPOSITORY_ROOT / "infra/milestone_7_8/cleanup_controller.py",
        REPOSITORY_ROOT / "infra/milestone_7_8/controller.bicep",
        REPOSITORY_ROOT / "infra/milestone_7_8/cleanup.bicep",
        REPOSITORY_ROOT / "infra/milestone_7_8/main.bicep",
        REPOSITORY_ROOT / "infra/milestone_7_8/modules/campaign-resources.bicep",
        REPOSITORY_ROOT / "infra/milestone_7_8/schemas/campaign.schema.json",
        REPOSITORY_ROOT / "infra/milestone_7_8/schemas/runtime.schema.json",
        REPOSITORY_ROOT / "infra/milestone_7_8/schemas/ledger.schema.json",
        REPOSITORY_ROOT / "infra/milestone_7_8/schemas/terminal-receipt.schema.json",
    )
    fresh_contract = "\n".join(path.read_text(encoding="utf-8") for path in fresh_paths)

    assert "freshControllerAdmissionEvidenceSha256" in fresh_contract
    assert "retentionAbsenceEvidence" not in fresh_contract
    assert "retained-account-absent" not in fresh_contract
    assert "blocked-provider-retention" not in fresh_contract
    assert "provider-retained" not in fresh_contract
    assert "30-day" not in fresh_contract
    assert "softDeletedAutomationAccounts" not in fresh_contract
    assert "automationAccounts" not in RESIDUE_KEYS
    assert "softDeletedAutomationAccounts" not in RESIDUE_KEYS


def test_failure_cleanup_requires_authority_even_for_readback_failure() -> None:
    assert required_execution_authorizations("preflight", Phase.NEW) == frozenset({"preflight"})
    assert required_execution_authorizations("scope-create", Phase.COST_GATED) == frozenset(
        {"scope-create", "cleanup"}
    )
    assert required_execution_authorizations("cleanup-verify", Phase.CLEANUP_ARMED) == frozenset(
        {"cleanup-verify", "cleanup"}
    )
    assert required_execution_authorizations("cleanup-wait", Phase.CLEANING) == frozenset(
        {"cleanup-wait", "cleanup"}
    )
    assert required_execution_authorizations("residue", Phase.CLEANUP_DISARMED) == frozenset(
        {"residue"}
    )


def test_ledger_cannot_record_armed_or_finalized_early() -> None:
    config = _config()
    ledger = Ledger(config.campaign_id, config.generation_id)
    ledger.bind_deadline(config.cleanup_deadline_utc)
    for phase in ORDER[1 : ORDER.index(Phase.CLEANUP_DEPLOYED) + 1]:
        ledger.transition(phase, NOW)
    with pytest.raises(CampaignError, match="arming evidence"):
        ledger.transition(Phase.CLEANUP_ARMED, NOW)
    ledger.record_cleanup_arm_evidence("a" * 64)
    ledger.transition(Phase.CLEANUP_ARMED, NOW)
    ledger.phase = Phase.RESIDUE_VERIFIED.value
    with pytest.raises(CampaignError, match="terminal receipt"):
        terminal_receipt(ledger)


def test_residue_inventory_paginates_and_preserves_unrelated_deleted_accounts() -> None:
    config = _config()
    runtime = _runtime()
    commands = command_plan("residue", config, runtime)
    unrelated_id = (
        f"/subscriptions/{runtime['subscriptionId']}/resourceGroups/unrelated/"
        "providers/Microsoft.Automation/automationAccounts/unrelated-account"
    )

    class PaginatedRunner:
        def __init__(self) -> None:
            self.commands: list[tuple[str, ...]] = []

        def run(self, command: tuple[str, ...]) -> dict[str, object]:
            self.commands.append(command)
            rendered = " ".join(command)
            if command[:3] == ("az", "group", "exists"):
                return _command_result(False)
            if command[:3] == ("az", "resource", "list"):
                return _command_result([])
            if command[:3] == ("az", "role", "assignment"):
                return _command_result([])
            if command[:3] == ("az", "group", "show"):
                return _command_result(
                    {
                        "name": config.cleanup_resource_group,
                        "location": config.cleanup_region,
                        "tags": _controller_tags(config, runtime),
                    }
                )
            if command[:3] == ("az", "automation", "account"):
                return _command_result(_controller_account_record(config, runtime))
            if "/schedules?" in rendered or "/jobSchedules?" in rendered:
                return _command_result({"value": []})
            if "active-continuation" in rendered:
                return _command_result({"value": []})
            if "/automationAccounts?" in rendered:
                return _command_result(
                    {
                        "value": [_controller_account_record(config, runtime)],
                        "nextLink": "https://management.azure.com/active-continuation",
                    }
                )
            if "/deletedAutomationAccounts?" in rendered:
                return _command_result(
                    {
                        "value": [
                            {
                                "name": "unrelated-account",
                                "location": "eastus",
                                "properties": {"automationAccountResourceId": unrelated_id},
                            },
                        ]
                    }
                )
            raise AssertionError(rendered)

    runner = PaginatedRunner()
    results = execute_residue_commands(runner, commands)  # type: ignore[arg-type]
    observation = observe_residue(results, config, runtime)
    assert observation.active_inventory_pages == 2
    assert observation.deleted_inventory_pages == 1
    assert set(observation.counters.values()) == {0}
    assert len(observation.unrelated_deleted_identity_sha256) == 1
    assert len(runner.commands) == 10
    ledger = Ledger(config.campaign_id, config.generation_id)
    disposition = ledger.record_residue(
        observation.counters, evidence_sha256=observation.evidence_sha256
    )
    assert disposition == "zero-residue"


def test_malformed_deleted_attribution_fails_closed_and_no_purge_is_planned() -> None:
    config = _config()
    runtime = _runtime()
    malformed_results = [
        _command_result(False),
        _command_result([]),
        _command_result([]),
        _command_result(
            {
                "name": config.cleanup_resource_group,
                "location": config.cleanup_region,
                "tags": _controller_tags(config, runtime),
            }
        ),
        _command_result(_controller_account_record(config, runtime)),
        _command_result({"value": []}),
        _command_result({"value": []}),
        _command_result(
            {
                "complete": True,
                "pageCount": 1,
                "value": [_controller_account_record(config, runtime)],
            }
        ),
        _command_result(
            {
                "complete": True,
                "pageCount": 1,
                "value": [
                    {
                        "name": runtime["automationAccountName"],
                        "location": config.cleanup_region,
                        "properties": {},
                    }
                ],
            }
        ),
    ]
    with pytest.raises(CampaignError, match="attribution is malformed"):
        observe_residue(malformed_results, config, runtime)
    for operation in OPERATION_PHASE:
        for command in command_plan(operation, config, runtime):
            rendered = " ".join(command)
            if "deletedAutomationAccounts" in rendered:
                assert command[command.index("--method") + 1] == "get"


def test_retention_receipt_and_terminal_schema_are_closed_and_sanitized() -> None:
    schema_root = REPOSITORY_ROOT / "infra/milestone_7_8/schemas"
    for path in schema_root.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert value.get("additionalProperties") is False
    terminal_schema = json.loads(
        (schema_root / "terminal-receipt.schema.json").read_text(encoding="utf-8")
    )
    assert (
        "softDeletedAutomationAccounts" not in terminal_schema["properties"]["residue"]["required"]
    )
    receipt = json.loads(
        (
            REPOSITORY_ROOT / "evidence/milestone_7_8/automation-retention-cleanup-remediation.json"
        ).read_text(encoding="utf-8")
    )
    encoded = json.dumps(receipt, sort_keys=True)
    assert receipt["azureMutationCount"] == 0
    assert receipt["residueAfter"]["softDeletedAutomationAccounts"] == 1
    assert receipt["supportRequestSubmitted"] is False
    assert "C:\\Users" not in encoded
    assert "/subscriptions/" not in encoded


def test_historical_subscription_retirement_schema_is_closed_and_non_authorizing() -> None:
    schema = json.loads(
        (
            REPOSITORY_ROOT
            / "infra/milestone_7_8/schemas/historical-subscription-retirement-evidence.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert schema["$id"] == (
        "urn:solarplexus:mobius:milestone-7.8:historical-subscription-retirement-evidence:v1"
    )
    assert schema["properties"]["status"] == {"const": "historical-subscription-retired"}
    assert schema["properties"]["sourceClass"]["enum"] == [
        "authenticated-microsoft-notice",
        "authoritative-account-record",
    ]
    assert schema["properties"]["bindingEvidenceClass"]["enum"] == [
        "retained-private-runtime",
        "retained-authorization-evidence",
    ]
    for field in (
        "providerInventoryReadCompleted",
        "v3AbsenceEvidenceProduced",
        "liveSubscriptionAdmissionAuthorized",
        "controllerBootstrapAuthorized",
        "campaignExecutionAuthorized",
    ):
        assert schema["properties"][field] == {"const": False}
    assert schema["properties"]["replacementSubscriptionRequired"] == {"const": True}
    for field in (
        "azureGetOperations",
        "azureMutationCount",
        "repositoryMutationCount",
        "supportTicketOperationCount",
        "controllerMutationCount",
        "campaignMutationCount",
        "remoteGitMutationCount",
        "milestone8MutationCount",
    ):
        assert schema["properties"][field] == {"const": 0}
    serialized = json.dumps(schema, sort_keys=True)
    assert "retained-account-absent" not in serialized
    assert "subscriptionId" not in serialized
    assert "/subscriptions/" not in serialized

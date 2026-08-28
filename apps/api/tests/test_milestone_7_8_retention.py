from __future__ import annotations

import ast
import json
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infra.milestone_7_8 import retention

SUBSCRIPTION = "11111111-2222-3333-4444-555555555555"
ACCOUNT = "aa-m78-0123456789"
REGION = "southeastasia"
DELETION_TIME = "2026-08-15T01:09:46.307Z"
BOUNDARY = datetime(2026, 9, 14, 1, 9, 46, 307000, tzinfo=UTC)


def _original_id(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-{name}/providers/"
        f"Microsoft.Automation/automationAccounts/{name}"
    )


def _deleted_id(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Automation/"
        f"deletedAutomationAccounts/{name}"
    )


def _record(
    name: str,
    *,
    location: str = REGION,
    deletion_time: str = DELETION_TIME,
) -> dict[str, object]:
    return {
        "id": _deleted_id(name),
        "name": name,
        "properties": {
            "automationAccountResourceId": _original_id(name),
            "deletionTime": deletion_time,
            "location": location,
        },
    }


def _contract_files(tmp_path: Path) -> tuple[Path, Path, list[dict[str, object]]]:
    target = _record(ACCOUNT)
    unrelated = [_record(f"unrelated-{index}", location="eastus") for index in range(4)]
    runtime_path = tmp_path / "runtime.json"
    evidence_path = tmp_path / "evidence.json"
    runtime_path.write_text(
        json.dumps(
            {
                "subscriptionId": SUBSCRIPTION,
                "automationAccountName": ACCOUNT,
                "cleanupRegion": REGION,
            }
        ),
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps(
            {
                "version": "m7.8-automation-retention-remediation-v1",
                "campaignCorrelation": "0123456789abcdef",
                "generationCorrelation": "fedcba9876543210",
                "region": REGION,
                "campaignDeletedIdentitySha256": retention._target_hash(
                    _original_id(ACCOUNT).casefold()
                ),
                "unrelatedDeletedIdentitySha256": sorted(
                    retention._unrelated_hash(_original_id(str(item["name"])).casefold())
                    for item in unrelated
                ),
                "inventories": {
                    "deleted": {
                        "afterTotalCount": 5,
                        "afterCampaignCount": 1,
                        "unrelatedCount": 4,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return runtime_path, evidence_path, [target, *unrelated]


class FakeRunner:
    def __init__(
        self,
        *,
        pages: dict[str, dict[str, object]],
        subscription: str = SUBSCRIPTION,
    ) -> None:
        self.pages = pages
        self.subscription = subscription
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: tuple[str, ...] | list[str],
        *,
        timeout: int | float = 900,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        encoding: str = "utf-8",
    ) -> subprocess.CompletedProcess[str]:
        del timeout, cwd, env, encoding
        command = tuple(arguments)
        self.calls.append(command)
        if command[:2] == ("account", "show"):
            return subprocess.CompletedProcess(command, 0, self.subscription + "\n", "")
        assert command[:3] == ("rest", "--method", "get")
        url = command[command.index("--url") + 1]
        return subprocess.CompletedProcess(command, 0, json.dumps(self.pages[url]), "")


def _contract(tmp_path: Path) -> tuple[retention.RetentionContract, list[dict[str, object]]]:
    runtime_path, evidence_path, records = _contract_files(tmp_path)
    return (
        retention.load_contract(
            runtime_path,
            evidence_path,
            authoritative_deletion_time=DELETION_TIME,
        ),
        records,
    )


def _absence_document(
    *,
    subscription_correlation: str = "a" * 16,
    evidence_class: str = retention.MANAGED_EVIDENCE_CLASS,
) -> dict[str, object]:
    return {
        "version": retention.ABSENCE_EVIDENCE_VERSION,
        "evidenceClass": evidence_class,
        "status": "retained-account-absent",
        "subscriptionCorrelation": subscription_correlation,
        "campaignCorrelation": retention.RETENTION_CAMPAIGN_CORRELATION,
        "generationCorrelation": retention.RETENTION_GENERATION_CORRELATION,
        "region": retention.RETENTION_REGION,
        "observedAtUtc": retention.EXPECTED_REMOVAL_BOUNDARY_UTC,
        "authoritativeDeletionTimeUtc": (retention.AUTHORITATIVE_DELETION_TIME_UTC),
        "expectedRemovalBoundaryUtc": retention.EXPECTED_REMOVAL_BOUNDARY_UTC,
        "providerReportedDeletionTime": None,
        "deletionTimeInterpretation": None,
        "paginationComplete": True,
        "deletedInventoryPages": 1,
        "deletedAccountCount": 4,
        "targetCandidates": 0,
        "unrelatedDeletedAccountCount": 4,
        "campaignDeletedIdentitySha256": (retention.RETENTION_TARGET_IDENTITY_SHA256),
        "legacyCampaignIdentityHashMatch": True,
        "unrelatedDeletedIdentitySha256": list(retention.RETENTION_UNRELATED_IDENTITY_SHA256),
        "legacyUnrelatedIdentityHashMatch": True,
        "azureGetOperations": 2,
        "azureMutationCount": 0,
        "repositoryMutationCount": 0,
        "supportTicketOperationCount": 0,
    }


def _first_url() -> str:
    return (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}/providers/"
        "Microsoft.Automation/deletedAutomationAccounts?api-version=2024-10-23"
    )


def test_presence_reconciliation_follows_pagination_and_returns_only_sanitized_counts(
    tmp_path: Path,
) -> None:
    contract, records = _contract(tmp_path)
    next_link = _first_url() + "&$skiptoken=opaque"
    runner = FakeRunner(
        pages={
            _first_url(): {"value": records[:2], "nextLink": next_link},
            next_link: {"value": records[2:]},
        }
    )
    verifier = retention.RetentionVerifier(
        runner,
        clock=lambda: datetime(2026, 8, 18, tzinfo=UTC),
    )

    result = verifier.verify(contract, expect="present")

    assert result == {
        "version": "m7.8-retained-automation-absence-verification-v2",
        "evidenceClass": "managed-provider-get-only",
        "status": "provider-retained",
        "subscriptionCorrelation": retention._correlation(SUBSCRIPTION, domain="subscription"),
        "campaignCorrelation": "0123456789abcdef",
        "generationCorrelation": "fedcba9876543210",
        "region": REGION,
        "observedAtUtc": "2026-08-18T00:00:00.000Z",
        "authoritativeDeletionTimeUtc": DELETION_TIME,
        "expectedRemovalBoundaryUtc": "2026-09-14T01:09:46.307Z",
        "providerReportedDeletionTime": DELETION_TIME,
        "deletionTimeInterpretation": "provider-rfc3339-instant",
        "paginationComplete": True,
        "deletedInventoryPages": 2,
        "deletedAccountCount": 5,
        "targetCandidates": 1,
        "unrelatedDeletedAccountCount": 4,
        "campaignDeletedIdentitySha256": retention._target_hash(_original_id(ACCOUNT).casefold()),
        "legacyCampaignIdentityHashMatch": True,
        "unrelatedDeletedIdentitySha256": sorted(
            retention._unrelated_hash(_original_id(f"unrelated-{index}").casefold())
            for index in range(4)
        ),
        "legacyUnrelatedIdentityHashMatch": True,
        "azureGetOperations": 3,
        "azureMutationCount": 0,
        "repositoryMutationCount": 0,
        "supportTicketOperationCount": 0,
    }
    serialized = json.dumps(result)
    assert SUBSCRIPTION not in serialized
    assert ACCOUNT not in serialized
    assert "/subscriptions/" not in serialized
    assert all(call[:1] in {("account",), ("rest",)} for call in runner.calls)
    assert all("get" in call for call in runner.calls if call[:1] == ("rest",))


def test_post_boundary_absence_accepts_only_the_same_four_unrelated_records(
    tmp_path: Path,
) -> None:
    contract, records = _contract(tmp_path)
    runner = FakeRunner(pages={_first_url(): {"value": records[1:]}})
    verifier = retention.RetentionVerifier(
        runner,
        clock=lambda: datetime(2026, 9, 14, 1, 9, 46, 307000, tzinfo=UTC),
    )

    result = verifier.verify(contract, expect="absent")

    assert result["status"] == "retained-account-absent"
    assert result["deletedAccountCount"] == 4
    assert result["targetCandidates"] == 0
    assert result["azureGetOperations"] == 2


def test_exact_absence_artifact_is_canonical_and_live_admissible(tmp_path: Path) -> None:
    value = _absence_document()
    path = tmp_path / "retention-absence.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    first = retention.validate_retention_absence_evidence(
        path,
        subscription_correlation="a" * 16,
        allow_synthetic=False,
    )
    second = retention.validate_retention_absence_evidence(
        path,
        subscription_correlation="a" * 16,
        allow_synthetic=False,
    )

    assert first.evidence_sha256 == second.evidence_sha256
    assert first.document == value
    assert first.evidence_class == retention.MANAGED_EVIDENCE_CLASS


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda value: value.pop("status"), "not-exact"),
        (lambda value: value.update(status="provider-retained"), "not-exact"),
        (
            lambda value: value.update(observedAtUtc="2026-09-14T01:09:46.306Z"),
            "observed-before-boundary",
        ),
        (lambda value: value.update(subscriptionCorrelation="b" * 16), "not-exact"),
        (lambda value: value.update(campaignCorrelation="b" * 16), "not-exact"),
        (lambda value: value.update(generationCorrelation="b" * 16), "not-exact"),
        (lambda value: value.update(region="westus"), "not-exact"),
        (lambda value: value.update(paginationComplete=False), "not-exact"),
        (lambda value: value.update(targetCandidates=1), "not-exact"),
        (lambda value: value.update(azureMutationCount=1), "not-exact"),
        (
            lambda value: value.update(campaignDeletedIdentitySha256="0" * 64),
            "not-exact",
        ),
        (
            lambda value: value.update(unrelatedDeletedIdentitySha256=[]),
            "not-exact",
        ),
        (lambda value: value.update(unexpected=True), "not-exact"),
    ],
)
def test_absence_admission_rejects_incomplete_drifted_or_unsafe_evidence(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], object],
    error: str,
) -> None:
    value = _absence_document()
    mutation(value)
    path = tmp_path / "retention-absence.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(retention.RetentionVerificationError, match=error):
        retention.validate_retention_absence_evidence(
            path,
            subscription_correlation="a" * 16,
            allow_synthetic=False,
        )


def test_synthetic_absence_can_prepare_but_cannot_authorize_live_execution(
    tmp_path: Path,
) -> None:
    value = _absence_document(evidence_class=retention.SYNTHETIC_EVIDENCE_CLASS)
    path = tmp_path / "retention-absence.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    retention.validate_retention_absence_evidence(
        path,
        subscription_correlation="a" * 16,
        allow_synthetic=True,
    )
    with pytest.raises(retention.RetentionVerificationError, match="not-exact"):
        retention.validate_retention_absence_evidence(
            path,
            subscription_correlation="a" * 16,
            allow_synthetic=False,
        )


def test_provider_deleted_time_alias_is_normalized_for_the_target(tmp_path: Path) -> None:
    contract, records = _contract(tmp_path)
    target_properties = records[0]["properties"]
    assert isinstance(target_properties, dict)
    target_properties["DeletedTime"] = target_properties.pop("deletionTime")
    runner = FakeRunner(pages={_first_url(): {"value": records}})

    result = retention.RetentionVerifier(runner).verify(contract, expect="present")

    assert result["status"] == "provider-retained"


def test_provider_naive_central_clock_must_equal_authoritative_utc_instant(
    tmp_path: Path,
) -> None:
    contract, records = _contract(tmp_path)
    target_properties = records[0]["properties"]
    assert isinstance(target_properties, dict)
    target_properties["DeletedTime"] = "2026-08-14T20:09:46.307"
    target_properties.pop("deletionTime")
    runner = FakeRunner(pages={_first_url(): {"value": records}})

    result = retention.RetentionVerifier(runner).verify(contract, expect="present")

    assert result["providerReportedDeletionTime"] == "2026-08-14T20:09:46.307"
    assert (
        result["deletionTimeInterpretation"] == "provider-naive-central-daylight-time-utc-minus-05"
    )


def test_explicit_legacy_reconciliation_emits_corrected_hash_only_after_other_checks(
    tmp_path: Path,
) -> None:
    runtime_path, evidence_path, records = _contract_files(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["campaignDeletedIdentitySha256"] = "f" * 64
    evidence["unrelatedDeletedIdentitySha256"] = [str(index) * 64 for index in range(1, 5)]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    contract = retention.load_contract(
        runtime_path,
        evidence_path,
        authoritative_deletion_time=DELETION_TIME,
    )
    runner = FakeRunner(pages={_first_url(): {"value": records}})

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-target-attribution-conflict$",
    ):
        retention.RetentionVerifier(runner).verify(contract, expect="present")

    reconciled = retention.RetentionVerifier(
        FakeRunner(pages={_first_url(): {"value": records}})
    ).verify(
        contract,
        expect="present",
        reconcile_legacy_binding=True,
    )
    assert reconciled["legacyCampaignIdentityHashMatch"] is False
    assert reconciled["legacyUnrelatedIdentityHashMatch"] is False
    assert reconciled["campaignDeletedIdentitySha256"] == retention._target_hash(
        _original_id(ACCOUNT).casefold()
    )


def test_legacy_reconciliation_cannot_be_used_for_absence(tmp_path: Path) -> None:
    contract, _ = _contract(tmp_path)

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-reconciliation-mode-invalid$",
    ):
        retention.RetentionVerifier(FakeRunner(pages={})).verify(
            contract,
            expect="absent",
            reconcile_legacy_binding=True,
        )


def test_reconciled_receipt_is_the_strict_normal_verification_authority(
    tmp_path: Path,
) -> None:
    runtime_path, evidence_path, records = _contract_files(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence.update(
        {
            "version": "m7.8-automation-retention-live-reconciliation-v1",
            "authoritativeDeletionTimeUtc": DELETION_TIME,
            "expectedRemovalBoundaryUtc": "2026-09-14T01:09:46.307Z",
            "status": "provider-retained",
            "azureMutationCount": 0,
        }
    )
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    contract = retention.load_contract(
        runtime_path,
        evidence_path,
        authoritative_deletion_time=DELETION_TIME,
    )

    result = retention.RetentionVerifier(
        FakeRunner(pages={_first_url(): {"value": records}})
    ).verify(contract, expect="present")

    assert result["legacyCampaignIdentityHashMatch"] is True
    assert result["legacyUnrelatedIdentityHashMatch"] is True


def test_absence_verification_fails_before_boundary_without_azure_call(tmp_path: Path) -> None:
    contract, records = _contract(tmp_path)
    runner = FakeRunner(pages={_first_url(): {"value": records[1:]}})
    verifier = retention.RetentionVerifier(
        runner,
        clock=lambda: BOUNDARY.replace(microsecond=306999),
    )

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-boundary-not-reached$",
    ):
        verifier.verify(contract, expect="absent")

    assert runner.calls == []


@pytest.mark.parametrize(
    ("records_transform", "error"),
    [
        (
            lambda records: [records[0], records[0], *records[2:]],
            "retention-deleted-inventory-duplicate",
        ),
        (
            lambda records: [
                _record(ACCOUNT, deletion_time="2026-08-15T01:09:47.000Z"),
                *records[1:],
            ],
            "retention-target-deletion-time-mismatch",
        ),
        (
            lambda records: [_record(ACCOUNT, location="westus"), *records[1:]],
            "retention-target-location-mismatch",
        ),
        (
            lambda records: [*records[:-1], _record("unexpected-fifth", location="eastus")],
            "retention-unrelated-inventory-drift",
        ),
    ],
)
def test_presence_rejects_ambiguous_or_drifted_identity(
    tmp_path: Path,
    records_transform: Callable[[list[dict[str, object]]], list[dict[str, object]]],
    error: str,
) -> None:
    contract, records = _contract(tmp_path)
    transformed = records_transform(records)
    runner = FakeRunner(pages={_first_url(): {"value": transformed}})
    verifier = retention.RetentionVerifier(runner)

    with pytest.raises(retention.RetentionVerificationError, match=rf"^{re.escape(error)}$"):
        verifier.verify(contract, expect="present")


def test_subscription_mismatch_stops_before_inventory(tmp_path: Path) -> None:
    contract, records = _contract(tmp_path)
    runner = FakeRunner(
        pages={_first_url(): {"value": records}},
        subscription="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-subscription-mismatch$",
    ):
        retention.RetentionVerifier(runner).verify(contract, expect="present")

    assert len(runner.calls) == 1


def test_untrusted_next_link_is_rejected_without_following_it(tmp_path: Path) -> None:
    contract, records = _contract(tmp_path)
    runner = FakeRunner(
        pages={
            _first_url(): {
                "value": records,
                "nextLink": "https://example.invalid/private?api-version=2024-10-23",
            }
        }
    )

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-next-link-invalid$",
    ):
        retention.RetentionVerifier(runner).verify(contract, expect="present")

    assert len(runner.calls) == 2


def test_contract_loader_rejects_incomplete_retained_inventory(tmp_path: Path) -> None:
    runtime_path, evidence_path, _ = _contract_files(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["inventories"]["deleted"]["afterTotalCount"] = 4
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(
        retention.RetentionVerificationError,
        match=r"^retention-evidence-inventory-invalid$",
    ):
        retention.load_contract(
            runtime_path,
            evidence_path,
            authoritative_deletion_time=DELETION_TIME,
        )


def test_production_module_contains_no_azure_mutation_verb() -> None:
    source = Path(retention.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    rest_methods: list[tuple[object, ...]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_run"
            and node.args
            and isinstance(node.args[0], ast.Tuple)
            and len(node.args[0].elts) >= 3
        ):
            prefix = tuple(
                item.value if isinstance(item, ast.Constant) else None
                for item in node.args[0].elts[:3]
            )
            if prefix[:1] == ("rest",):
                rest_methods.append(prefix)

    assert rest_methods
    assert all(method == ("rest", "--method", "get") for method in rest_methods)
    tokens = {
        node.value.casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {"put", "patch", "post", "delete"}.isdisjoint(tokens)

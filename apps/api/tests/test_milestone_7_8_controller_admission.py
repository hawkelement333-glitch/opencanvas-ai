"""Offline integration tests runnable with unittest or pytest; no Azure client."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from infra.milestone_7_8 import controller_admission as admission
from infra.milestone_7_8 import (
    controller_publication,
    controller_renewal,
    operator,
    predeployment,
    prepare,
)
from infra.milestone_7_8.automation_region import (
    CLEANUP_REGION_CANDIDATES,
    automation_region_discovery_commands,
    select_automation_region_from_results,
)
from infra.milestone_7_8.campaign import (
    CampaignConfig,
    CampaignError,
    CostItem,
    sanitize,
)
from infra.milestone_7_8.cleanup_controller import (
    ARCHITECTURE,
    controller_binding_sha256,
    controller_names,
    load_execution_authorization,
)
from infra.milestone_7_8.controller import (
    ControllerConfig,
    controller_config_document,
    controller_config_sha256,
    validate_controller_results,
)
from infra.milestone_7_8.predeployment import EVIDENCE_VERSION

SUBSCRIPTION = "00000000-0000-4000-8000-000000000100"
TENANT = "00000000-0000-4000-8000-000000000101"
OLD = "2030-01-02T00:00:00Z"
NEW = "2030-01-03T00:00:00Z"
NOW = datetime(2030, 1, 1, tzinfo=UTC)


def result(value: object) -> dict[str, object]:
    return {"exitCode": 0, "stdout": json.dumps(value), "stderr": ""}


def authority_fixture(
    *,
    subscription: str = SUBSCRIPTION,
    tenant: str = TENANT,
    campaign: str = "mobius78-region-proof",
    generation: str = "g1-aabbccddeeff",
    region: str = "eastus2",
    evidence_hash: str = "0" * 64,
    cleanup_hash: str | None = None,
) -> dict[str, object]:
    correlation = sanitize(subscription, domain="subscription")
    names = controller_names(correlation)
    config = ControllerConfig(
        subscription,
        tenant,
        campaign,
        generation,
        correlation,
        "a" * 40,
        region,
        names.resource_group,
        names.account,
        names.runbook,
        OLD,
        cleanup_hash or hashlib.sha256(b"cleanup-content").hexdigest(),
        evidence_hash,
        EVIDENCE_VERSION,
        f"m78-controller-{correlation[:10]}",
    )
    scope = f"/subscriptions/{subscription}/resourceGroups/{names.resource_group}"
    account_id = f"{scope}/providers/Microsoft.Automation/automationAccounts/{names.account}"
    tags = {
        "mobius.milestone": "7.8",
        "mobius.owner": "managed-postgresql-evidence",
        "mobius.cleanup-controller": ARCHITECTURE,
        "mobius.subscription-correlation": correlation,
        admission.DEADLINE_TAG: OLD,
        "mobius.cleanup-script-sha256": config.cleanup_script_sha256,
        "mobius.fresh-controller-admission-sha256": evidence_hash,
        "mobius.fresh-controller-admission-version": EVIDENCE_VERSION,
    }
    principal = "00000000-0000-4000-8000-000000000201"
    responses = [
        result({"id": scope, "name": names.resource_group, "location": region, "tags": tags}),
        result(
            {
                "id": account_id,
                "name": names.account,
                "location": region,
                "tags": tags,
                "identity": {"principalId": principal},
                "disableLocalAuth": True,
            }
        ),
        result(
            [
                {
                    "principalId": principal,
                    "scope": scope,
                    "roleDefinitionId": "/roles/acdd72a7-3385-48ef-bd42-f606fba81ae7",
                }
            ]
        ),
        result(
            {
                "id": f"{account_id}/runbooks/{names.runbook}",
                "name": names.runbook,
                "tags": tags,
                "properties": {"state": "Published", "lastModifiedTime": "2030-01-01T00:00:00Z"},
            }
        ),
        {"exitCode": 0, "stdout": "cleanup-content", "stderr": ""},
        result({"value": []}),
        result({"value": []}),
    ]
    # Content hashes in production always bind the actual returned content.
    if cleanup_hash is not None:
        # Used only by preparation tests, which supply the actual committed script.
        content = (
            Path(__file__).resolve().parents[3]
            / "infra/milestone_7_8/scripts/Remove-M78Campaign.ps1"
        ).read_text()
        if hashlib.sha256(content.encode()).hexdigest() != cleanup_hash:
            raise AssertionError("fixture content does not match supplied cleanup hash")
        responses[4]["stdout"] = content
    authorization = {
        "version": "m7.8-controller-execution-authorization-v4",
        "disposition": "separately-authorized-controller-execution",
        "operation": "controller-verify",
        "subscriptionCorrelation": correlation,
        "sourceHead": config.source_head,
        "controllerArchitecture": ARCHITECTURE,
        "controllerLocation": region,
        "controllerResourceGroupName": names.resource_group,
        "automationAccountName": names.account,
        "controllerAuthorizedUntilUtc": OLD,
        "freshControllerAdmissionEvidenceSha256": evidence_hash,
        "freshControllerAdmissionEvidenceVersion": EVIDENCE_VERSION,
        "expiresAtUtc": OLD,
    }
    authorization_hash = admission.digest(
        "m7.8/controller-execution-authorization/v4", authorization
    )
    authorization["authorizationSha256"] = authorization_hash
    return {
        "version": admission.VERSION,
        "verifiedConfig": controller_config_document(config),
        "verificationAuthorization": authorization,
        "verificationResult": {
            "status": "controller-baseline-verified",
            "operation": "controller-verify",
            "commandCount": 7,
            "authorizationSha256": authorization_hash,
            "controllerProofSha256": validate_controller_results(responses, config),
        },
        "baselineReadback": responses,
        "renewal": None,
    }


def renewed_fixture() -> dict[str, object]:
    evidence = authority_fixture()
    original = ControllerConfig.from_document(evidence["verifiedConfig"])
    renewed = replace(original, source_head="b" * 40, controller_authorized_until_utc=NEW)
    before = copy.deepcopy(evidence["baselineReadback"])
    after = copy.deepcopy(before)
    for index in (0, 1, 3):
        resource = json.loads(after[index]["stdout"])
        resource["tags"][admission.DEADLINE_TAG] = NEW
        after[index] = result(resource)
    binding = controller_binding_sha256(
        original.subscription_id,
        resource_group=original.controller_resource_group_name,
        account=original.automation_account_name,
        runbook=original.runbook_name,
    )
    approval = {
        "version": "m7.8-controller-renewal-approval-v1",
        "operation": "controller-renew-deadline-tags",
        "controllerBindingSha256": binding,
        "originalConfigSha256": controller_config_sha256(original),
        "renewedConfigSha256": controller_config_sha256(renewed),
        "originalDeadlineUtc": OLD,
        "renewedDeadlineUtc": NEW,
        "baselineReadbackSha256": admission.digest(
            "m7.8/controller-renewal-before/v1", admission._snapshot_values(before)
        ),
        "issuedAtUtc": "2030-01-02T01:00:00Z",
        "expiresAtUtc": "2030-01-02T02:00:00Z",
    }
    approval_hash = admission.digest("m7.8/controller-renewal-approval/v1", approval)
    approval["authorizationSha256"] = approval_hash
    completion = {
        "version": "m7.8-controller-renewal-completion-v1",
        "status": "complete",
        "controllerBindingSha256": binding,
        "originalConfigSha256": controller_config_sha256(original),
        "renewedConfigSha256": controller_config_sha256(renewed),
        "renewalApprovalSha256": approval_hash,
        "baselinePreservationSha256": admission._preservation(before, after),
        "originalDeadlineUtc": OLD,
        "observedDeadlineUtc": NEW,
        "allResourcesReadBack": True,
        "otherTagsAndPropertiesPreserved": True,
    }
    completion["receiptSha256"] = admission.digest(
        "m7.8/controller-renewal-completion/v1", completion
    )
    evidence["renewal"] = {
        "renewedConfig": controller_config_document(renewed),
        "approval": approval,
        "beforeReadback": before,
        "afterReadback": after,
        "completion": completion,
        "startedAtUtc": "2030-01-02T01:01:00Z",
        "completedAtUtc": "2030-01-02T01:02:00Z",
    }
    return evidence


def test_renewal_plan_limits_each_request_to_one_deadline_tag():
    evidence = authority_fixture()
    plan = controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=NEW)
    requests = plan["requests"]
    assert len(requests) == 3
    assert len({item["url"] for item in requests}) == 3
    for item in requests:
        assert item["method"] == "PATCH"
        assert item["url"].startswith("https://management.azure.com/subscriptions/")
        assert item["url"].endswith(
            "/providers/Microsoft.Resources/tags/default?api-version=2021-04-01"
        )
        assert item["body"] == {
            "operation": "Merge",
            "properties": {"tags": {admission.DEADLINE_TAG: NEW}},
        }
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=OLD)


def test_renewal_approval_binds_fresh_readback_and_exact_plan():
    evidence = authority_fixture()
    plan = controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=NEW)
    now = datetime(2030, 1, 2, 1, 1, tzinfo=UTC)
    kwargs = {"issued_at": "2030-01-02T01:00:00Z", "expires_at": "2030-01-02T02:00:00Z", "now": now}
    approval = controller_renewal.build_approval(
        evidence, plan, evidence["baselineReadback"], **kwargs
    )
    assert approval["renewalPlanSha256"] == plan["planSha256"]
    legacy_plan = controller_renewal.build_plan(
        evidence, source_head="b" * 40, deadline=NEW, _legacy=True
    )
    assert controller_renewal.build_approval(
        evidence, legacy_plan, evidence["baselineReadback"], **kwargs
    ) == renewed_fixture()["renewal"]["approval"]
    changed_source_plan = controller_renewal.build_plan(
        evidence, source_head="b" * 40, deadline=NEW, source_script_hash="e" * 64,
    )
    assert controller_renewal.build_approval(
        evidence, changed_source_plan, evidence["baselineReadback"], **kwargs
    ) != approval
    changed = copy.deepcopy(plan)
    changed["requests"][0]["body"]["properties"]["tags"]["unexpected"] = "value"
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_approval(evidence, changed, evidence["baselineReadback"], **kwargs)
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_approval(evidence, plan, [], **kwargs)
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_approval(
            evidence,
            plan,
            evidence["baselineReadback"],
            issued_at="2030-01-02T01:00:00Z",
            expires_at="2030-01-02T01:00:01Z",
            now=now,
        )


def test_reconciliation_approval_is_separate_get_only_and_attempt_bound():
    evidence = authority_fixture()
    plan = controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=NEW, _legacy=True)
    original = renewed_fixture()["renewal"]["approval"]
    journal = {
        "version": "m7.8-controller-renewal-attempt-journal-v1",
        "renewalPlanSha256": plan["planSha256"],
        "renewalApprovalSha256": original["authorizationSha256"],
        "attempts": [
            {
                "index": i,
                "requestSha256": admission.digest("m7.8/controller-renewal-request/v1", request),
                "dispatchedAtUtc": f"2030-01-02T01:0{i + 1}:00Z",
                "outcome": "indeterminate" if i == 2 else "success",
            }
            for i, request in enumerate(plan["requests"])
        ],
    }
    kwargs = {
        "issued_at": "2030-01-02T03:00:00Z",
        "expires_at": "2030-01-02T04:00:00Z",
        "now": datetime(2030, 1, 2, 3, 1, tzinfo=UTC),
    }
    value = controller_renewal.build_reconciliation_approval(
        evidence, plan, evidence["baselineReadback"], original, journal, **kwargs
    )
    assert value["operation"] == "controller-renewal-reconcile-get-only"
    assert value["renewalApprovalSha256"] == original["authorizationSha256"]
    assert value["renewalPlanSha256"] == plan["planSha256"]
    transitioned = controller_renewal.build_reconciliation_approval(
        evidence, plan, evidence["baselineReadback"], original, journal,
        source_head="c" * 40, **kwargs,
    )
    assert transitioned["reconciliationSourceHead"] == "c" * 40
    assert transitioned["renewalPlanSha256"] == plan["planSha256"]
    assert transitioned["attemptJournalSha256"] == value["attemptJournalSha256"]
    assert transitioned["authorizationSha256"] != value["authorizationSha256"]
    renewed = ControllerConfig.from_document(plan["renewedConfig"])
    controller_renewal._validate_read_source(
        "reconcile", renewed, transitioned, "c" * 40, renewed.cleanup_script_sha256
    )
    for operation, head, script in (
        ("before-snapshot", "c" * 40, renewed.cleanup_script_sha256),
        ("reconcile", "d" * 40, renewed.cleanup_script_sha256),
        ("reconcile", "c" * 40, "0" * 64),
    ):
        with unittest.TestCase().assertRaises(CampaignError):
            controller_renewal._validate_read_source(
                operation, renewed, transitioned, head, script
            )
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_reconciliation_approval(
            evidence, plan, evidence["baselineReadback"], original, journal,
            source_head="not-a-commit", **kwargs,
        )
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_reconciliation_approval(
            evidence,
            plan,
            evidence["baselineReadback"],
            {**original, "authorizationSha256": "0" * 64},
            journal,
            **kwargs,
        )
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_reconciliation_approval(
            evidence,
            plan,
            evidence["baselineReadback"],
            original,
            journal,
            issued_at="2030-01-02T03:00:00Z",
            expires_at="2030-01-02T03:00:01Z",
            now=kwargs["now"],
        )

    renewed = renewed_fixture()
    renewed["renewal"]["completedAtUtc"] = "2030-01-02T03:01:00Z"
    renewed["renewal"]["reconciliation"] = {
        "plan": plan,
        "attemptJournal": journal,
        "authorization": value,
        "observationSha256": admission.digest(
            "m7.8/controller-renewal-observation/v1",
            {
                "observedAtUtc": "2030-01-02T03:01:00Z",
                "readback": admission._snapshot_values(renewed["renewal"]["afterReadback"]),
            },
        ),
    }
    assert admission.validate_authority_evidence(renewed).controller_authorized_until_utc == NEW
    for mutation in (
        "late",
        "missing",
        "partial",
        "journal_binding",
        "auth_scope",
        "expired",
        "observation",
        "request_binding",
        "changed_plan",
        "prior_indeterminate",
        "mixed_readback",
    ):
        bad = copy.deepcopy(renewed)
        rec = bad["renewal"]["reconciliation"]
        if mutation == "late":
            rec["attemptJournal"]["attempts"][2]["dispatchedAtUtc"] = "2030-01-02T02:00:00Z"
        elif mutation == "missing":
            del rec["attemptJournal"]
        elif mutation == "partial":
            rec["attemptJournal"]["attempts"].pop()
        elif mutation == "journal_binding":
            rec["attemptJournal"]["renewalApprovalSha256"] = "0" * 64
        elif mutation == "auth_scope":
            rec["authorization"]["operation"] = "controller-renew-deadline-tags"
        elif mutation == "expired":
            rec["authorization"]["expiresAtUtc"] = "2030-01-02T03:00:30Z"
        elif mutation == "request_binding":
            rec["attemptJournal"]["attempts"][1]["requestSha256"] = "0" * 64
        elif mutation == "changed_plan":
            rec["plan"]["requests"][0]["body"]["properties"]["tags"]["extra"] = "value"
        elif mutation == "prior_indeterminate":
            rec["attemptJournal"]["attempts"][1]["outcome"] = "indeterminate"
        elif mutation == "mixed_readback":
            bad["renewal"]["afterReadback"][0] = bad["renewal"]["beforeReadback"][0]
        else:
            rec["observationSha256"] = "0" * 64
        with unittest.TestCase().assertRaises(CampaignError):
            admission.validate_authority_evidence(bad)
    assert (
        admission.validate_authority_evidence(renewed_fixture()).controller_authorized_until_utc
        == NEW
    )


def test_renewal_preservation_allows_only_exact_metadata_values() -> None:
    evidence = renewed_fixture()
    before = copy.deepcopy(evidence["renewal"]["beforeReadback"])
    after = copy.deepcopy(evidence["renewal"]["afterReadback"])
    for records, value in ((before, "before"), (after, "after")):
        account = json.loads(records[1]["stdout"])
        account["lastModifiedTime"] = value
        account["systemData"] = {"lastModifiedAt": value}
        records[1] = result(account)
        runbook = json.loads(records[3]["stdout"])
        runbook["etag"] = value
        runbook["properties"]["lastModifiedTime"] = value
        records[3] = result(runbook)
    admission._preservation(before, after)
    for change in ("unrelated", "missing", "malformed"):
        changed = copy.deepcopy(after)
        account = json.loads(changed[1]["stdout"])
        if change == "unrelated":
            account["tags"]["unrelated"] = "changed"
        elif change == "missing":
            del account["systemData"]["lastModifiedAt"]
        else:
            account["lastModifiedTime"] = 42
        changed[1] = result(account)
        with unittest.TestCase().assertRaisesRegex(CampaignError, "other tags or properties"):
            admission._preservation(before, changed)


def test_second_renewal_preserves_and_binds_first_evidence() -> None:
    evidence = renewed_fixture()
    deadline = "2030-01-05T00:00:00Z"
    now = datetime(2030, 1, 3, 1, 0, tzinfo=UTC)
    plan = controller_renewal.build_plan(evidence, source_head="c" * 40, deadline=deadline)
    assert plan["originalDeadlineUtc"] == NEW
    assert plan["priorAuthorityEvidenceSha256"] == admission.digest(
        "m7.8/controller-authority-evidence/v1", evidence
    )
    auth = copy.deepcopy(evidence["verificationAuthorization"])
    auth.update({"sourceHead": "c" * 40, "controllerAuthorizedUntilUtc": deadline,
                 "expiresAtUtc": "2030-01-03T02:00:00Z"})
    del auth["authorizationSha256"]
    auth["authorizationSha256"] = admission.digest(
        "m7.8/controller-execution-authorization/v4", auth
    )

    class Provider:
        def __init__(self) -> None:
            self.values = copy.deepcopy(evidence["renewal"]["afterReadback"])
            self.reads = 0
            self.writes = 0

        def run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            if args[:3] == ("rest", "--method", "patch"):
                index = (0, 1, 3)[self.writes]
                self.writes += 1
                value = json.loads(self.values[index]["stdout"])
                value["tags"][admission.DEADLINE_TAG] = deadline
                self.values[index] = result(value)
                return subprocess.CompletedProcess(args, 0, "{}", "")
            value = self.values[self.reads % 7]
            self.reads += 1
            return subprocess.CompletedProcess(args, 0, value["stdout"], value["stderr"])

    drifted_provider = Provider()
    drifted_account = json.loads(drifted_provider.values[1]["stdout"])
    drifted_account["tags"]["unexpected"] = "changed"
    drifted_provider.values[1] = result(drifted_account)
    with unittest.TestCase().assertRaisesRegex(CampaignError, "other tags or properties"):
        controller_renewal.collect_before_snapshot(
            evidence, plan, auth, runner=drifted_provider, clock=lambda: now
        )
    assert drifted_provider.writes == 0
    provider = Provider()
    before = controller_renewal.collect_before_snapshot(
        evidence, plan, auth, runner=provider, clock=lambda: now
    )
    approval = controller_renewal.build_approval(
        evidence, plan, before, issued_at="2030-01-03T01:00:00Z",
        expires_at="2030-01-03T02:00:00Z", now=now,
    )
    with tempfile.TemporaryDirectory(prefix="m78-second-renewal-") as directory:
        root = Path(directory)
        controller_renewal.execute_renewal(
            evidence, plan, before, approval, output_dir=root / "attempt",
            runner=provider, clock=lambda: now,
        )
        journal = controller_renewal.load_executor_journal(root / "attempt", plan, approval, before)
        read_auth = controller_renewal.build_reconciliation_approval(
            evidence, plan, before, approval, journal,
            issued_at="2030-01-03T01:00:00Z", expires_at="2030-01-03T02:00:00Z", now=now,
        )
        completed = controller_renewal.reconcile_renewal(
            evidence, plan, before, approval, read_auth, journal_dir=root / "attempt",
            output_dir=root / "reconciliation", runner=provider, clock=lambda: now,
        )
        assert (
            admission.validate_authority_evidence(completed).controller_authorized_until_utc
            == deadline
        )
        assert completed["renewal"]["priorAuthorityEvidence"] == evidence
        assert provider.writes == 3
        # Reuse the second completion as the immutable baseline for a third renewal.
        third_deadline = "2030-01-06T00:00:00Z"
        third = controller_renewal.build_plan(
            completed, source_head="d" * 40, deadline=third_deadline
        )
        third_auth = copy.deepcopy(auth)
        third_auth.update({"sourceHead": "d" * 40,
                           "controllerAuthorizedUntilUtc": third_deadline})
        del third_auth["authorizationSha256"]
        third_auth["authorizationSha256"] = admission.digest(
            "m7.8/controller-execution-authorization/v4", third_auth
        )
        third_provider = Provider()
        third_provider.values = copy.deepcopy(provider.values)

        class ThirdProvider:
            def run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
                if args[:3] == ("rest", "--method", "patch"):
                    index = (0, 1, 3)[third_provider.writes]
                    third_provider.writes += 1
                    value = json.loads(third_provider.values[index]["stdout"])
                    value["tags"][admission.DEADLINE_TAG] = third_deadline
                    third_provider.values[index] = result(value)
                    return subprocess.CompletedProcess(args, 0, "{}", "")
                value = third_provider.values[third_provider.reads % 7]
                third_provider.reads += 1
                return subprocess.CompletedProcess(args, 0, value["stdout"], value["stderr"])

        runner = ThirdProvider()
        third_before = controller_renewal.collect_before_snapshot(
            completed, third, third_auth, runner=runner, clock=lambda: now
        )
        third_approval = controller_renewal.build_approval(
            completed, third, third_before, issued_at="2030-01-03T01:00:00Z",
            expires_at="2030-01-03T02:00:00Z", now=now,
        )
        controller_renewal.execute_renewal(
            completed, third, third_before, third_approval, output_dir=root / "third-attempt",
            runner=runner, clock=lambda: now,
        )
        third_journal = controller_renewal.load_executor_journal(
            root / "third-attempt", third, third_approval, third_before
        )
        third_read_auth = controller_renewal.build_reconciliation_approval(
            completed, third, third_before, third_approval, third_journal,
            issued_at="2030-01-03T01:00:00Z", expires_at="2030-01-03T02:00:00Z", now=now,
        )
        third_completed = controller_renewal.reconcile_renewal(
            completed, third, third_before, third_approval, third_read_auth,
            journal_dir=root / "third-attempt", output_dir=root / "third-reconciliation",
            runner=runner, clock=lambda: now,
        )
        assert (
            admission.validate_authority_evidence(third_completed).controller_authorized_until_utc
            == third_deadline
        )
        corrupted = copy.deepcopy(third_completed)
        prior = corrupted["renewal"]["priorAuthorityEvidence"]
        first = prior["renewal"]["priorAuthorityEvidence"]
        first["renewal"]["completion"]["status"] = "changed"
        with unittest.TestCase().assertRaises(CampaignError):
            admission.validate_authority_evidence(corrupted)
        fourth_plan = controller_renewal.build_plan(
            third_completed, source_head="e" * 40, deadline="2030-01-07T00:00:00Z"
        )
        assert fourth_plan["priorAuthorityEvidenceSha256"] == admission.digest(
            "m7.8/controller-authority-evidence/v1", third_completed
        )
        for kind in ("prior", "missing_prior", "approval", "journal"):
            altered = copy.deepcopy(completed)
            renewal = altered["renewal"]
            if kind == "prior":
                renewal["priorAuthorityEvidence"]["renewal"]["completion"]["status"] = "changed"
            elif kind == "missing_prior":
                del renewal["priorAuthorityEvidence"]
            elif kind == "approval":
                renewal["approval"]["authorizationSha256"] = "0" * 64
            else:
                attempt = renewal["reconciliation"]["attemptJournal"]["attempts"][0]
                attempt["requestSha256"] = "0" * 64
            with unittest.TestCase().assertRaises(CampaignError):
                admission.validate_authority_evidence(altered)


def test_renewal_executor_is_bounded_and_journaled() -> None:
    evidence = authority_fixture()
    plan = controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=NEW, _legacy=True)
    approval = renewed_fixture()["renewal"]["approval"]
    now = datetime(2030, 1, 2, 1, 1, tzinfo=UTC)

    class FakeProvider:
        def __init__(self, fail_at: int | None = None, lose: bool = False) -> None:
            self.requests: list[tuple[str, ...]] = []
            self.fail_at = fail_at
            self.lose = lose
            self.deadlines = [OLD, OLD, OLD]
            self.journal_dir: Path | None = None

        def run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.requests.append(args)
            index = len(self.requests) - 1
            if self.journal_dir is not None:
                assert (self.journal_dir / f"{index + 1:02d}-intent.json").is_file()
                assert not (self.journal_dir / f"{index + 1:02d}-dispatch.json").exists()
            if index == self.fail_at:
                if self.lose:
                    self.deadlines[index] = NEW
                    raise subprocess.TimeoutExpired("fake", 1)
                return subprocess.CompletedProcess(args, 1, "", "synthetic failure")
            self.deadlines[index] = NEW
            return subprocess.CompletedProcess(args, 0, "{}", "")

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        provider = FakeProvider()
        provider.journal_dir = base / "success"
        journal = controller_renewal.execute_renewal(
            evidence,
            plan,
            evidence["baselineReadback"],
            approval,
            output_dir=base / "success",
            runner=provider,
            clock=lambda: now,
        )
        assert len(provider.requests) == 3
        assert all((base / "success" / f"{i:02d}-dispatch.json").is_file() for i in (1, 2, 3))
        assert provider.deadlines == [NEW, NEW, NEW]
        assert controller_renewal.validate_attempt_journal(plan, approval, journal)
        assert all(req[:3] == ("rest", "--method", "patch") for req in provider.requests)
        for index, req in enumerate(provider.requests):
            assert req[req.index("--url") + 1] == plan["requests"][index]["url"]
            assert json.loads(req[req.index("--body") + 1]) == plan["requests"][index]["body"]
        assert not (base / "success" / "completion.json").exists()
        for filename, expected_calls in (
            ("00-context.json", 0),
            ("complete-dispatch-journal.json", 3),
        ):
            provider = FakeProvider()

            def fail_boundary(path: Path, value: object, name: str = filename) -> None:
                if path.name == name:
                    raise OSError("synthetic persistence failure")
                controller_renewal._durable_record(path, value)

            with unittest.TestCase().assertRaises(OSError):
                controller_renewal.execute_renewal(
                    evidence,
                    plan,
                    evidence["baselineReadback"],
                    approval,
                    output_dir=base / ("boundary-" + filename),
                    runner=provider,
                    clock=lambda: now,
                    persist=fail_boundary,
                )
            assert len(provider.requests) == expected_calls
        for index in range(3):
            for lost in (False, True):
                provider = FakeProvider(index, lost)
                target = base / f"failure-{index}-{lost}"
                with unittest.TestCase().assertRaises(CampaignError):
                    controller_renewal.execute_renewal(
                        evidence,
                        plan,
                        evidence["baselineReadback"],
                        approval,
                        output_dir=target,
                        runner=provider,
                        clock=lambda: now,
                    )
                assert len(provider.requests) == index + 1
                assert provider.deadlines[index] == (NEW if lost else OLD)
                assert not (target / "complete-dispatch-journal.json").exists()
                if lost and index == 2:
                    journal_path = target / "indeterminate-dispatch-journal.json"
                    saved_journal = json.loads(journal_path.read_text(encoding="utf-8"))
                    assert controller_renewal.validate_attempt_journal(
                        plan, approval, saved_journal
                    )
                    assert saved_journal["attempts"][2]["outcome"] == "indeterminate"
            for phase in ("intent", "dispatch", "response", "outcome"):
                provider = FakeProvider()
                target = base / f"persist-{index}-{phase}"
                fail_name = f"{index + 1:02d}-{phase}.json"

                def fail_persist(path: Path, value: object, name: str = fail_name) -> None:
                    if path.name == name:
                        raise OSError("synthetic persistence failure")
                    controller_renewal._durable_record(path, value)

                with unittest.TestCase().assertRaises(OSError):
                    controller_renewal.execute_renewal(
                        evidence,
                        plan,
                        evidence["baselineReadback"],
                        approval,
                        output_dir=target,
                        runner=provider,
                        clock=lambda: now,
                        persist=fail_persist,
                    )
                assert len(provider.requests) == index + (
                    phase in {"dispatch", "response", "outcome"}
                )
        changed = copy.deepcopy(plan)
        changed["requests"][0]["body"]["properties"]["tags"]["extra"] = "x"
        for bad_plan, bad_approval in (
            (changed, approval),
            (plan, {**approval, "authorizationSha256": "0" * 64}),
        ):
            provider = FakeProvider()
            with unittest.TestCase().assertRaises(CampaignError):
                controller_renewal.execute_renewal(
                    evidence,
                    bad_plan,
                    evidence["baselineReadback"],
                    bad_approval,
                    output_dir=base / "invalid",
                    runner=provider,
                    clock=lambda: now,
                )
            assert not provider.requests
        ticks = iter([now, now, now, datetime(2030, 1, 2, 2, tzinfo=UTC)])
        provider = FakeProvider()
        with unittest.TestCase().assertRaises(CampaignError):
            controller_renewal.execute_renewal(
                evidence,
                plan,
                evidence["baselineReadback"],
                approval,
                output_dir=base / "expired",
                runner=provider,
                clock=lambda: next(ticks),
            )
        assert len(provider.requests) == 1
        ticks = iter([now, now, datetime(2030, 1, 2, 2, tzinfo=UTC)])
        provider = FakeProvider()
        with unittest.TestCase().assertRaises(CampaignError):
            controller_renewal.execute_renewal(
                evidence,
                plan,
                evidence["baselineReadback"],
                approval,
                output_dir=base / "expired-after-intent",
                runner=provider,
                clock=lambda: next(ticks),
            )
        assert not provider.requests
        assert (base / "expired-after-intent" / "01-intent.json").exists()
        assert not (base / "expired-after-intent" / "01-dispatch.json").exists()


def test_renewal_cli_requires_explicit_execute_gate() -> None:
    evidence = authority_fixture()
    argv = ["controller_renewal", "--operation", "execute", "--authority-evidence", "unused"]
    with (
        patch.object(sys, "argv", argv),
        patch.object(
            controller_renewal.admission, "load_authority_evidence", return_value=evidence
        ),
        patch(
            "infra.milestone_7_8.azure_cli.AzureCliLauncher.resolve",
            side_effect=AssertionError("unexpected live runner"),
        ),
        redirect_stdout(io.StringIO()),
    ):
        assert controller_renewal.main() == 2


def test_readonly_reconciliation_uses_actual_executor_journal() -> None:
    evidence = authority_fixture()
    plan = controller_renewal.build_plan(evidence, source_head="b" * 40, deadline=NEW, _legacy=True)
    approval = renewed_fixture()["renewal"]["approval"]
    mutation_now = datetime(2030, 1, 2, 1, 1, tzinfo=UTC)
    reconcile_now = datetime(2030, 1, 2, 3, 1, tzinfo=UTC)
    read_auth = copy.deepcopy(evidence["verificationAuthorization"])
    read_auth.update(
        {
            "sourceHead": "b" * 40,
            "controllerAuthorizedUntilUtc": NEW,
            "expiresAtUtc": "2030-01-02T04:00:00Z",
        }
    )
    del read_auth["authorizationSha256"]
    read_auth["authorizationSha256"] = admission.digest(
        "m7.8/controller-execution-authorization/v4", read_auth
    )

    class FakeProvider:
        def __init__(self, lose_at: int | None = None) -> None:
            self.results = copy.deepcopy(evidence["baselineReadback"])
            self.lost = lose_at
            self.patches = 0
            self.reads = 0

        def run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            if args[:3] == ("rest", "--method", "patch"):
                index = self.patches
                self.patches += 1
                resource_index = (0, 1, 3)[index]
                resource = json.loads(self.results[resource_index]["stdout"])
                resource["tags"][admission.DEADLINE_TAG] = NEW
                self.results[resource_index] = result(resource)
                if index == self.lost:
                    raise subprocess.TimeoutExpired("fake", 1)
                return subprocess.CompletedProcess(args, 0, "{}", "")
            value = self.results[self.reads % 7]
            self.reads += 1
            return subprocess.CompletedProcess(args, 0, value["stdout"], value["stderr"])

    with tempfile.TemporaryDirectory(prefix="m78-renewal-fake-") as directory:
        base = Path(directory)
        for bad_auth in (
            {**read_auth, "operation": "controller-bootstrap"},
            {**read_auth, "expiresAtUtc": "2030-01-02T01:00:00Z"},
        ):
            probe = FakeProvider()
            with unittest.TestCase().assertRaises(CampaignError):
                controller_renewal.collect_before_snapshot(
                    evidence, plan, bad_auth, runner=probe, clock=lambda: mutation_now
                )
            assert probe.reads == 0
        for lost in (None, 0, 1, 2):
            provider = FakeProvider(lost)
            before = controller_renewal.collect_before_snapshot(
                evidence, plan, read_auth, runner=provider, clock=lambda: mutation_now
            )
            assert before == evidence["baselineReadback"]
            attempt_dir = base / f"attempt-{lost}"
            if lost is None:
                controller_renewal.execute_renewal(
                    evidence,
                    plan,
                    before,
                    approval,
                    output_dir=attempt_dir,
                    runner=provider,
                    clock=lambda: mutation_now,
                )
            else:
                with unittest.TestCase().assertRaises(CampaignError):
                    controller_renewal.execute_renewal(
                        evidence,
                        plan,
                        before,
                        approval,
                        output_dir=attempt_dir,
                        runner=provider,
                        clock=lambda: mutation_now,
                    )
            if lost in (0, 1):
                with unittest.TestCase().assertRaises(CampaignError):
                    controller_renewal.load_executor_journal(attempt_dir, plan, approval, before)
                assert provider.patches == lost + 1
                continue
            journal = controller_renewal.load_executor_journal(attempt_dir, plan, approval, before)
            dispatch_path = attempt_dir / "02-dispatch.json"
            saved_path = attempt_dir / "02-dispatch.saved"
            dispatch_path.rename(saved_path)
            try:
                with unittest.TestCase().assertRaises(CampaignError):
                    controller_renewal.load_executor_journal(attempt_dir, plan, approval, before)
            finally:
                saved_path.rename(dispatch_path)
            recon_auth = controller_renewal.build_reconciliation_approval(
                evidence,
                plan,
                before,
                approval,
                journal,
                issued_at="2030-01-02T03:00:00Z",
                expires_at="2030-01-02T04:00:00Z",
                now=reconcile_now,
                source_head="c" * 40,
            )
            completed = controller_renewal.reconcile_renewal(
                evidence,
                plan,
                before,
                approval,
                recon_auth,
                journal_dir=attempt_dir,
                output_dir=base / f"reconcile-{lost}",
                runner=provider,
                clock=lambda: reconcile_now,
            )
            assert (
                admission.validate_authority_evidence(completed).controller_authorized_until_utc
                == NEW
            )
            assert provider.patches == 3
            assert provider.reads == 14
            with unittest.TestCase().assertRaises(CampaignError):
                controller_renewal.reconcile_renewal(
                    evidence,
                    plan,
                    before,
                    approval,
                    {**recon_auth, "operation": "wrong"},
                    journal_dir=attempt_dir,
                    output_dir=base / f"wrong-{lost}",
                    runner=provider,
                    clock=lambda: reconcile_now,
                )
            with unittest.TestCase().assertRaises(CampaignError):
                controller_renewal.reconcile_renewal(
                    evidence,
                    plan,
                    before,
                    approval,
                    recon_auth,
                    journal_dir=attempt_dir,
                    output_dir=base / f"expired-{lost}",
                    runner=provider,
                    clock=lambda: datetime(2030, 1, 2, 4, tzinfo=UTC),
                )
            drifted = json.loads(provider.results[1]["stdout"])
            drifted["tags"]["unexpected"] = "changed"
            provider.results[1] = result(drifted)
            with unittest.TestCase().assertRaises(CampaignError):
                controller_renewal.reconcile_renewal(
                    evidence,
                    plan,
                    before,
                    approval,
                    recon_auth,
                    journal_dir=attempt_dir,
                    output_dir=base / f"drift-{lost}",
                    runner=provider,
                    clock=lambda: reconcile_now,
                )
            assert not (base / f"drift-{lost}" / "02-completed-authority-evidence.json").exists()


class DiscoveryRunner:
    def __init__(self, evidence: dict[str, object], *, changed_resources: int = 0) -> None:
        self.evidence = evidence
        self.commands: list[tuple[str, ...]] = []
        records = copy.deepcopy(evidence["baselineReadback"])
        if evidence["renewal"]:
            records = copy.deepcopy(evidence["renewal"]["afterReadback"])
        if evidence.get("runbookPublication"):
            records = copy.deepcopy(evidence["runbookPublication"]["afterReadback"])
        self.content = records[4]
        self.resources = [json.loads(records[index]["stdout"]) for index in (0, 1, 3)]
        self.resources[1]["resourceGroup"] = self.resources[0]["name"]
        for resource in self.resources[:changed_resources]:
            resource["tags"][admission.DEADLINE_TAG] = NEW

    def run(self, command: tuple[str, ...]) -> dict[str, object]:
        self.commands.append(command)
        config = ControllerConfig.from_document(self.evidence["verifiedConfig"])
        discovery = automation_region_discovery_commands(config.subscription_id)
        if command in discovery:
            return self.discovery_results()[discovery.index(command)]
        assert command[:4] == ("az", "rest", "--method", "get")
        url = command[command.index("--url") + 1]
        if "/content?" in url:
            return self.content
        return result(self.resources[2] if "/runbooks/" in url else self.resources[0])

    def discovery_results(self):
        config = ControllerConfig.from_document(self.evidence["verifiedConfig"])
        return (
            result(
                {
                    "id": config.subscription_id,
                    "tenantId": config.tenant_id,
                    "environmentName": "AzureCloud",
                    "state": "Enabled",
                }
            ),
            result(
                {
                    "id": f"/subscriptions/{config.subscription_id}",
                    "subscriptionId": config.subscription_id,
                    "subscriptionPolicies": {
                        "quotaId": "AzureForStudents_2018-01-01",
                        "locationPlacementId": "Public_2014-09-01",
                        "spendingLimit": "On",
                    },
                }
            ),
            result(
                {
                    "registrationState": "Registered",
                    "resourceTypes": [
                        {
                            "resourceType": "automationAccounts",
                            "locations": list(CLEANUP_REGION_CANDIDATES),
                        }
                    ],
                }
            ),
            result({"accounts": [self.resources[1]], "nextLink": None}),
            result({"accounts": [], "nextLink": None}),
            result([]),
        )

    def select(self, authority: object, required_until="2030-01-01T05:00:00Z", observed=None):
        config = ControllerConfig.from_document(self.evidence["verifiedConfig"])
        config = admission.validate_authority_evidence(self.evidence)
        observed = observed or admission.latest_observation(self.evidence) or NOW
        return select_automation_region_from_results(
            self,
            self.discovery_results(),
            subscription_id=config.subscription_id,
            observed_at=observed,
            controller_resource_group=config.controller_resource_group_name,
            controller_account=config.automation_account_name,
            subscription_correlation=config.subscription_correlation,
            cleanup_script_sha256=config.cleanup_script_sha256,
            fresh_controller_admission_evidence_sha256=(
                config.fresh_controller_admission_evidence_sha256
            ),
            controller_required_until_utc=required_until,
            controller_authority_evidence=authority,
        )


def campaign_fixture(evidence: dict[str, object]):
    controller = admission.validate_authority_evidence(evidence)
    selection = DiscoveryRunner(evidence).select(evidence)
    config = CampaignConfig(
        campaign_id=controller.campaign_id,
        generation_id=controller.generation_id,
        subscription_correlation=controller.subscription_correlation,
        tenant_correlation=sanitize(controller.tenant_id, domain="tenant"),
        target_resource_group="rg-m78-aabbccddee-target",
        cleanup_resource_group=controller.controller_resource_group_name,
        target_region="centralus",
        cleanup_region=controller.controller_location,
        postgres_region="centralus",
        cleanup_deadline_utc="2030-01-01T04:00:00Z",
        conservative_estimate_usd="25.6832",
        contingency_percent="25",
        resource_items=(CostItem("bounded", "5.13664", 4),),
        principal_manifest_sha256="c" * 64,
        cleanup_region_selection_sha256=selection.sha256(),
        cleanup_candidate_regions=",".join(selection.candidate_order),
        cleanup_offer_classification=selection.offer_classification,
        cleanup_offer_eligibility_disposition=selection.offer_eligibility_disposition,
        cleanup_offer_eligible_regions=",".join(selection.offer_eligible_regions),
        cleanup_offer_eligibility_source=selection.offer_eligibility_source,
        cleanup_offer_eligibility_sha256=selection.offer_eligibility_sha256,
        fresh_controller_admission_evidence_sha256=(
            controller.fresh_controller_admission_evidence_sha256
        ),
    )
    runtime = {
        "subscriptionId": controller.subscription_id,
        "automationAccountName": controller.automation_account_name,
        "cleanupScriptSha256": controller.cleanup_script_sha256,
        "controllerAuthorityEvidenceSha256": admission.digest(
            "m7.8/controller-authority-evidence/v1", evidence
        ),
        "controllerAuthorizedUntilUtc": controller.controller_authorized_until_utc,
        "runbookName": controller.runbook_name,
        "cleanupAuthorityExpiresUtc": "2030-01-01T05:00:00Z",
    }
    if admission.bootstrap_script_hash(evidence) != controller.cleanup_script_sha256:
        runtime["controllerBootstrapScriptSha256"] = admission.bootstrap_script_hash(evidence)
    return config, runtime


class PublicationProvider:
    def __init__(self, prior, *, failure=None):
        self.readback = copy.deepcopy(admission.latest_readback(prior))
        self.failure = failure
        self.reads = 0
        self.writes = []

    def run(self, command):
        assert command[-3:] == ("--subscription", SUBSCRIPTION, "--only-show-errors")
        if command[:2] == ("automation", "runbook"):
            self.writes.append(command)
            action = command[2]
            if self.failure == action:
                raise TimeoutError("response lost")
            if action == "publish" and self.failure != "stale-content":
                self.readback[4]["stdout"] = "corrected cleanup content"
                runbook = json.loads(self.readback[3]["stdout"])
                runbook["properties"]["lastModifiedTime"] = "2030-01-02T01:03:00Z"
                self.readback[3] = result(runbook)
                if self.failure == "drift":
                    account = json.loads(self.readback[1]["stdout"])
                    account["tags"]["unexpected"] = "changed"
                    self.readback[1] = result(account)
            return subprocess.CompletedProcess(command, 0, "", "")
        item = self.readback[self.reads % 7]
        self.reads += 1
        return subprocess.CompletedProcess(command, 0, item["stdout"], item["stderr"])


def publication_inputs(prior):
    script_hash = hashlib.sha256(b"corrected cleanup content").hexdigest()
    source = ("d" * 40, script_hash)
    plan = controller_publication.build_plan(
        prior, source_head=source[0], script_hash=source[1],
        artifact_root=".runtime/test-publication",
    )
    approval = controller_publication.build_approval(
        plan, issued_at="2030-01-02T01:02:30Z", expires_at="2030-01-02T01:10:00Z",
    )
    return plan, approval, source


def test_publication_proves_new_content_without_rewriting_renewal_or_tags(tmp_path):
    prior = renewed_fixture()
    saved = copy.deepcopy(prior)
    plan, approval, source = publication_inputs(prior)
    provider = PublicationProvider(prior)
    evidence = controller_publication.execute_publication(
        prior, plan, approval, output_dir=tmp_path / "attempt", runner=provider,
        clock=lambda: datetime(2030, 1, 2, 1, 3, tzinfo=UTC), source=lambda: source,
    )
    assert provider.reads == 14
    assert [command[2] for command in provider.writes] == ["replace-content", "publish"]
    assert [list(command) for command in provider.writes] == plan["requests"]
    assert prior == saved
    assert evidence["runbookPublication"]["priorAuthorityEvidence"] == saved
    # The already retained overlay format remains admissible without rewriting it.
    legacy = {**saved, "runbookPublication": {
        key: value for key, value in evidence["runbookPublication"].items()
        if key != "priorAuthorityEvidence"
    }}
    assert admission.validate_authority_evidence(legacy).cleanup_script_sha256 == source[1]
    accepted = admission.load_authority_evidence(
        tmp_path / "attempt/controller-authority-evidence.json"
    )
    assert admission.validate_authority_evidence(accepted).cleanup_script_sha256 == source[1]
    assert admission.validate_authority_evidence(accepted).controller_authorized_until_utc == NEW
    selector = DiscoveryRunner(accepted)
    assert selector.select(accepted).controller_disposition == "exact-controller-adoptable"
    assert any("/content?" in argument for cmd in selector.commands for argument in cmd)
    selector.content = {"exitCode": 0, "stdout": "cleanup-content", "stderr": ""}
    with unittest.TestCase().assertRaisesRegex(CampaignError, "content drifted"):
        selector.select(accepted)
    with unittest.TestCase().assertRaisesRegex(CampaignError, "binding differs"):
        DiscoveryRunner(accepted).select(prior)
    config, runtime = campaign_fixture(accepted)
    assert operator.validate_bound_controller_authority(accepted, runtime, config) == accepted
    operator._validate_controller_tags(
        selector.resources[1]["tags"], config=config, runtime=runtime
    )
    del runtime["controllerBootstrapScriptSha256"]
    with unittest.TestCase().assertRaisesRegex(CampaignError, "binding differs"):
        operator.validate_bound_controller_authority(accepted, runtime, config)
    bad = copy.deepcopy(accepted)
    bad["runbookPublication"]["attempts"].pop()
    with unittest.TestCase().assertRaisesRegex(CampaignError, "dispatch history is incomplete"):
        admission.validate_authority_evidence(bad)


def test_publication_blocks_expiry_drift_and_ambiguous_writes(tmp_path):
    prior = renewed_fixture()
    plan, approval, source = publication_inputs(prior)
    for failure, writes, message in (
        ("replace-content", 1, "outcome is indeterminate"),
        ("publish", 2, "outcome is indeterminate"),
        ("stale-content", 2, "publication readback differs"),
        ("drift", 2, "changed other tags or properties"),
        ("expired", 0, "approval is not current"),
        ("wrong-source", 0, "source boundary differs"),
        ("wrong-approval", 0, "approval binding differs"),
    ):
        provider = PublicationProvider(prior, failure=failure)
        directory = tmp_path / failure
        authorization = (
            {**approval, "planSha256": "f" * 64} if failure == "wrong-approval" else approval
        )
        current = datetime(2030, 1, 2, 1, 11 if failure == "expired" else 3, tzinfo=UTC)
        observed_source = ("e" * 40, source[1]) if failure == "wrong-source" else source
        with unittest.TestCase().assertRaisesRegex(CampaignError, message):
            controller_publication.execute_publication(
                prior, plan, authorization,
                output_dir=directory, runner=provider,
                clock=lambda current=current: current,
                source=lambda observed_source=observed_source: observed_source,
            )
        assert len(provider.writes) == writes
        assert not (directory / "controller-authority-evidence.json").exists()


class TransitionProvider(PublicationProvider):
    """The same exact seven readbacks survive every real transition API."""

    def __init__(self, prior):
        super().__init__(prior)
        self.next_content = "publication one"
        self.patch_count = 0
        self.lose_patch = None

    def run(self, command):
        if command[:3] == ("rest", "--method", "patch"):
            request = json.loads(command[command.index("--body") + 1])
            assert request["operation"] == "Merge"
            assert set(request["properties"]["tags"]) == {admission.DEADLINE_TAG}
            url = command[command.index("--url") + 1]
            resource_id = url.split("https://management.azure.com", 1)[1].split(
                "/providers/Microsoft.Resources/tags/default?", 1
            )[0]
            indexes = [
                i for i in (0, 1, 3)
                if json.loads(self.readback[i]["stdout"])["id"] == resource_id
            ]
            assert len(indexes) == 1
            resource = json.loads(self.readback[indexes[0]]["stdout"])
            resource["tags"].update(request["properties"]["tags"])
            self.readback[indexes[0]] = result(resource)
            self.patch_count += 1
            if self.lose_patch == self.patch_count:
                raise TimeoutError("successful response lost")
            return subprocess.CompletedProcess(command, 0, "{}", "")
        response = super().run(command)
        if command[:3] == ("automation", "runbook", "publish"):
            self.readback[4]["stdout"] = self.next_content
        return response


def publish_transition(prior, provider, root, *, minute=10, head="d" * 40):
    source = (head, hashlib.sha256(provider.next_content.encode()).hexdigest())
    plan = controller_publication.build_plan(
        prior, source_head=head, script_hash=source[1], artifact_root=".runtime/chain-publication",
    )
    authorization = controller_publication.build_approval(
        plan, issued_at=f"2030-01-02T01:{minute:02}:00Z", expires_at="2030-01-02T02:00:00Z",
    )
    return controller_publication.execute_publication(
        prior, plan, authorization, output_dir=root, runner=provider,
        clock=lambda: datetime(2030, 1, 2, 1, minute, tzinfo=UTC), source=lambda: source,
    )


def renewal_transition(prior, provider, root, *, minute=20, deadline="2030-01-04T00:00:00Z",
                       head="d" * 40, source_hash=None):
    root.mkdir()
    now = datetime(2030, 1, 2, 1, minute, tzinfo=UTC)
    issued = now.isoformat().replace("+00:00", "Z")
    expiry = "2030-01-02T02:00:00Z"
    plan = controller_renewal.build_plan(
        prior, source_head=head, deadline=deadline, source_script_hash=source_hash,
    )
    authorization = copy.deepcopy(prior["verificationAuthorization"])
    authorization.update({"sourceHead": head, "controllerAuthorizedUntilUtc": deadline,
                          "expiresAtUtc": expiry})
    del authorization["authorizationSha256"]
    authorization["authorizationSha256"] = admission.digest(
        "m7.8/controller-execution-authorization/v4", authorization
    )
    renewed = ControllerConfig.from_document(plan["renewedConfig"])
    controller_renewal._validate_read_source(
        "before-snapshot", renewed, authorization, head,
        source_hash or renewed.cleanup_script_sha256, source_script_hash=source_hash,
    )
    before = controller_renewal.collect_before_snapshot(
        prior, plan, authorization, runner=provider, clock=lambda: now,
    )
    approval = controller_renewal.build_approval(
        prior, plan, before, issued_at=issued, expires_at=expiry, now=now,
    )
    journal = controller_renewal.execute_renewal(
        prior, plan, before, approval, output_dir=root / "attempt",
        runner=provider, clock=lambda: now,
    )
    read_approval = controller_renewal.build_reconciliation_approval(
        prior, plan, before, approval, journal, issued_at=issued, expires_at=expiry, now=now,
    )
    accepted = controller_renewal.reconcile_renewal(
        prior, plan, before, approval, read_approval, journal_dir=root / "attempt",
        output_dir=root / "reconciliation", runner=provider, clock=lambda: now,
    )
    assert accepted["renewal"]["priorAuthorityEvidence"] == prior
    accepted_plan = accepted["renewal"]["reconciliation"]["plan"]
    assert accepted_plan["priorAuthorityEvidenceSha256"] == admission.digest(
        "m7.8/controller-authority-evidence/v1", prior,
    )
    return accepted


def alternating_transition_fixture(root):
    prior = renewed_fixture()
    saved = copy.deepcopy(prior)
    provider = TransitionProvider(prior)
    first = publish_transition(prior, provider, root / "publication-one")
    second = renewal_transition(
        first, provider, root / "renewal-one", head="e" * 40,
        source_hash=hashlib.sha256(b"publication two").hexdigest(),
    )
    provider.next_content = "publication two"
    # Renewal already bound this source: publishing new content from the same
    # clean commit is supported; no synthetic extra source commit is required.
    third = publish_transition(
        second, provider, root / "publication-two", minute=30, head="e" * 40,
    )
    fourth = renewal_transition(
        third, provider, root / "renewal-two", minute=40, deadline="2030-01-05T00:00:00Z",
        head="e" * 40,
    )
    assert prior == saved
    assert provider.reads == 56
    assert provider.patch_count == 6
    assert len(provider.writes) == 4
    for accepted in (first, second, third, fourth):
        selection = DiscoveryRunner(accepted).select(accepted)
        assert selection.controller_disposition == "exact-controller-adoptable"
        config, runtime = campaign_fixture(accepted)
        assert operator.validate_bound_controller_authority(accepted, runtime, config) == accepted
        # Both preparation discovery and subsequent campaign validation preserve
        # the bootstrap tag while requiring the latest published content hash.
        assert runtime["controllerBootstrapScriptSha256"] == admission.bootstrap_script_hash(saved)
    return fourth


def test_alternating_publications_and_renewals_admit_through_campaign(tmp_path):
    accepted = alternating_transition_fixture(tmp_path)
    assert admission.validate_authority_evidence(accepted).cleanup_script_sha256 == hashlib.sha256(
        b"publication two"
    ).hexdigest()
    third = accepted["renewal"]["priorAuthorityEvidence"]
    second = third["runbookPublication"]["priorAuthorityEvidence"]
    first = second["renewal"]["priorAuthorityEvidence"]
    assert first["runbookPublication"]["priorAuthorityEvidence"] == renewed_fixture()
    for kind in ("history", "script", "deadline", "approval", "journal", "prior", "baseline"):
        bad = copy.deepcopy(accepted)
        renewal = bad["renewal"]
        if kind == "history":
            attempt = renewal["priorAuthorityEvidence"]["runbookPublication"]["attempts"][0]
            attempt["requestSha256"] = "0" * 64
        elif kind in {"script", "deadline"}:
            field = "cleanupScriptSha256" if kind == "script" else "controllerAuthorizedUntilUtc"
            renewal["renewedConfig"][field] = (
                "0" * 64 if kind == "script" else "2030-01-07T00:00:00Z"
            )
        elif kind == "approval":
            renewal["approval"]["authorizationSha256"] = "0" * 64
        elif kind == "journal":
            renewal["reconciliation"]["attemptJournal"]["attempts"].pop()
        elif kind == "prior":
            renewal["priorAuthorityEvidence"] = renewed_fixture()
        else:
            renewal["beforeReadback"] = renewed_fixture()["renewal"]["afterReadback"]
        with unittest.TestCase().assertRaises(CampaignError):
            admission.validate_authority_evidence(bad)


def test_renew_then_publish_preserves_deployed_hash_and_binds_executing_source(tmp_path):
    prior = renewed_fixture()
    provider = TransitionProvider(prior)
    candidate = hashlib.sha256(provider.next_content.encode()).hexdigest()
    renewed = renewal_transition(prior, provider, tmp_path / "renew", source_hash=candidate)
    renewed_config = admission.validate_authority_evidence(renewed)
    assert renewed_config.cleanup_script_sha256 != candidate
    with unittest.TestCase().assertRaisesRegex(CampaignError, "source boundary"):
        controller_renewal._validate_read_source(
            "before-snapshot", renewed_config, {}, "d" * 40, "f" * 64, source_script_hash=candidate,
        )
    published = publish_transition(renewed, provider, tmp_path / "publish", minute=30)
    assert admission.validate_authority_evidence(published).cleanup_script_sha256 == candidate
    selection = DiscoveryRunner(published).select(published)
    assert selection.controller_disposition == "exact-controller-adoptable"
    provider.next_content = "cleanup-content"
    restored = publish_transition(
        published, provider, tmp_path / "restore-content", minute=40, head="e" * 40,
    )
    assert (
        admission.validate_authority_evidence(restored).cleanup_script_sha256
        == admission.bootstrap_script_hash(restored)
    )
    selector = DiscoveryRunner(restored)
    assert selector.select(restored).controller_disposition == "exact-controller-adoptable"
    assert any("/content?" in arg for command in selector.commands for arg in command)
    selector.content = {"exitCode": 0, "stdout": "drifted", "stderr": ""}
    with unittest.TestCase().assertRaisesRegex(CampaignError, "content drifted"):
        selector.select(restored)


def test_interrupted_transition_cannot_replace_latest_accepted_evidence(tmp_path):
    prior = renewed_fixture()
    provider = TransitionProvider(prior)
    published = publish_transition(prior, provider, tmp_path / "published")
    provider.lose_patch = 2
    with unittest.TestCase().assertRaisesRegex(CampaignError, "indeterminate"):
        renewal_transition(published, provider, tmp_path / "interrupted")
    assert provider.patch_count == 2
    assert not (
        tmp_path / "interrupted/reconciliation/02-completed-authority-evidence.json"
    ).exists()
    # A new plan cannot treat two updated tags as the accepted old deadline.
    plan = controller_renewal.build_plan(
        published, source_head="d" * 40, deadline="2030-01-04T00:00:00Z"
    )
    with unittest.TestCase().assertRaises(CampaignError):
        controller_renewal.build_approval(
            published, plan, provider.readback, issued_at="2030-01-02T01:21:00Z",
            expires_at="2030-01-02T02:00:00Z", now=datetime(2030, 1, 2, 1, 21, tzinfo=UTC),
        )
    cyclic = copy.deepcopy(published)
    cyclic["runbookPublication"]["priorAuthorityEvidence"] = cyclic
    with unittest.TestCase().assertRaisesRegex(CampaignError, "cyclic"):
        admission.validate_authority_evidence(cyclic)


def test_new_first_renewal_binds_exact_bootstrap_anchor_after_expiry(tmp_path):
    prior = authority_fixture()
    provider = TransitionProvider(prior)
    accepted = renewal_transition(prior, provider, tmp_path / "first-renewal")
    assert accepted["renewal"]["priorAuthorityEvidence"] == prior
    renewal = accepted["renewal"]
    assert (
        renewal["approval"]["renewalPlanSha256"]
        == renewal["reconciliation"]["plan"]["planSha256"]
    )
    assert (
        admission.validate_authority_evidence(accepted).controller_authorized_until_utc
        == "2030-01-04T00:00:00Z"
    )


class ControllerAdmissionTests(unittest.TestCase):
    def test_insufficient_controller_horizon_still_rejects_adoption(self):
        evidence = authority_fixture()
        with self.assertRaisesRegex(CampaignError, "authority is insufficient"):
            DiscoveryRunner(evidence).select(evidence, "2030-01-04T00:00:00Z")

    def test_campaign_execution_authorization_binds_the_exact_receipt(self):
        evidence = authority_fixture()
        config, runtime = campaign_fixture(evidence)
        runtime.update(
            {
                "sourceHead": "a" * 40,
                "controllerBindingSha256": "7" * 64,
                "freshControllerAdmissionEvidenceVersion": EVIDENCE_VERSION,
            }
        )
        authorization = {
            "version": "m7.8-execution-authorization-v5",
            "disposition": "separately-authorized-azure-execution",
            "campaignId": config.campaign_id,
            "generationId": config.generation_id,
            "subscriptionCorrelation": config.subscription_correlation,
            "sourceHead": runtime["sourceHead"],
            "controllerArchitecture": ARCHITECTURE,
            "controllerBindingSha256": runtime["controllerBindingSha256"],
            "controllerAuthorityEvidenceSha256": runtime["controllerAuthorityEvidenceSha256"],
            "freshControllerAdmissionEvidenceSha256": (
                config.fresh_controller_admission_evidence_sha256
            ),
            "freshControllerAdmissionEvidenceVersion": EVIDENCE_VERSION,
            "cleanupDeadlineUtc": config.cleanup_deadline_utc,
            "expiresAtUtc": "2030-01-01T01:00:00Z",
            "allowedOperations": ["capacity-check"],
        }
        authorization["authorizationSha256"] = admission.digest(
            "m7.8/execution-authorization/v5", authorization
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-authorization.json"
            path.write_text(json.dumps(authorization))
            load_execution_authorization(
                path, config=config, runtime=runtime, operation="capacity-check", now=NOW
            )
            runtime["controllerAuthorityEvidenceSha256"] = "0" * 64
            with self.assertRaisesRegex(CampaignError, "not exact"):
                load_execution_authorization(
                    path, config=config, runtime=runtime, operation="capacity-check", now=NOW
                )

    def test_campaign_preflight_uses_the_already_approved_upstream(self):
        evidence = authority_fixture()
        config, runtime = campaign_fixture(evidence)
        runtime.update(
            {
                "sourceHead": "a" * 40,
                "canonicalBuildInputSha256": "b" * 64,
                "dockerfileSha256": "c" * 64,
            }
        )
        texts = [
            "",
            runtime["sourceHead"],
            "milestone-7-8-production-readiness-audit-local",
            "refs/remotes/origin/milestone-7-8-production-readiness-audit-local",
            "\n".join(str(i) for i in range(5)),
        ]
        results = [{"exitCode": 0, "stdout": text} for text in texts]
        results += [
            result({}),
            result({"buildInputSha256": "b" * 64, "dockerfileSha256": "c" * 64}),
        ]
        operator.validate_operation_results("preflight", results, config, runtime)
        for upstream in ("", "refs/remotes/origin/other"):
            results[3]["stdout"] = upstream
            with self.assertRaisesRegex(CampaignError, "boundary differs"):
                operator.validate_operation_results("preflight", results, config, runtime)

    def test_original_verified_anchor_is_adoptable(self):
        evidence = authority_fixture()
        self.assertEqual(
            DiscoveryRunner(evidence).select(evidence).controller_disposition,
            "exact-controller-adoptable",
        )

    def test_tags_alone_cannot_establish_bootstrap_or_renewal_completion(self):
        evidence = authority_fixture()
        for changed in range(4):
            with self.subTest(changed=changed):
                runner = DiscoveryRunner(evidence, changed_resources=changed)
                with self.assertRaises(CampaignError):
                    runner.select(None)
                if changed:
                    with self.assertRaises(CampaignError):
                        runner.select(evidence)

    def test_completed_renewal_is_adoptable_even_after_old_deadline(self):
        evidence = renewed_fixture()
        self.assertEqual(
            admission.validate_authority_evidence(evidence).controller_authorized_until_utc, NEW
        )
        self.assertEqual(
            DiscoveryRunner(evidence).select(evidence).controller_disposition,
            "exact-controller-adoptable",
        )

    def test_completion_claims_cannot_replace_snapshots(self):
        for field in ("beforeReadback", "afterReadback", "completion", "approval"):
            with self.subTest(field=field):
                evidence = renewed_fixture()
                evidence["renewal"][field] = None
                with self.assertRaises(CampaignError):
                    admission.validate_authority_evidence(evidence)

    def test_indeterminate_or_hash_invalid_completion_is_rejected(self):
        for change in (
            {"status": "indeterminate"},
            {"receiptSha256": "0" * 64},
            {"otherTagsAndPropertiesPreserved": False},
        ):
            evidence = renewed_fixture()
            evidence["renewal"]["completion"].update(change)
            with self.subTest(change=change), self.assertRaises(CampaignError):
                admission.validate_authority_evidence(evidence)

    def test_preservation_rejects_other_properties_even_with_rehashed_receipt(self):
        evidence = renewed_fixture()
        after = evidence["renewal"]["afterReadback"]
        account = json.loads(after[1]["stdout"])
        account["tags"]["unrelated-owner"] = "changed"
        after[1] = result(account)
        with self.assertRaisesRegex(CampaignError, "other tags or properties"):
            admission.validate_authority_evidence(evidence)

    def test_identity_and_config_rebinding_is_rejected(self):
        for change in (
            {"subscriptionId": TENANT},
            {"cleanupScriptSha256": "8" * 64},
            {"campaignId": "different-campaign"},
        ):
            evidence = renewed_fixture()
            evidence["renewal"]["renewedConfig"].update(change)
            with self.subTest(change=change), self.assertRaises(CampaignError):
                admission.validate_authority_evidence(evidence)

    def test_completion_must_be_inside_exact_approval_window(self):
        evidence = renewed_fixture()
        evidence["renewal"]["completedAtUtc"] = "2030-01-02T03:00:00Z"
        with self.assertRaisesRegex(CampaignError, "outside approval window"):
            admission.validate_authority_evidence(evidence)

    def test_future_completion_cannot_admit_live_observation(self):
        evidence = renewed_fixture()
        evidence["renewal"]["completedAtUtc"] = "2030-01-02T01:10:00Z"
        with self.assertRaisesRegex(CampaignError, "later than live observation"):
            DiscoveryRunner(evidence).select(
                evidence, observed=datetime(2030, 1, 2, 1, 3, tzinfo=UTC)
            )

    def test_failed_or_wrong_scope_bootstrap_readback_cannot_anchor(self):
        for wrong_scope in (False, True):
            evidence = authority_fixture()
            if wrong_scope:
                group = json.loads(evidence["baselineReadback"][0]["stdout"])
                group["id"] = "/subscriptions/wrong/resourceGroups/wrong"
                evidence["baselineReadback"][0] = result(group)
            else:
                evidence["baselineReadback"][0]["exitCode"] = 1
            with self.assertRaises(CampaignError):
                admission.validate_authority_evidence(evidence)

    def test_each_failed_completion_readback_blocks_admission(self):
        for index in range(7):
            evidence = renewed_fixture()
            evidence["renewal"]["afterReadback"][index]["exitCode"] = 1
            with self.subTest(index=index), self.assertRaises(CampaignError):
                admission.validate_authority_evidence(evidence)

    def test_duplicate_fields_and_changed_anchor_result_are_rejected(self):
        evidence = authority_fixture()
        evidence["baselineReadback"][0]["stdout"] = '{"name":"one","name":"two"}'
        with self.assertRaises(CampaignError):
            admission.validate_authority_evidence(evidence)
        evidence = authority_fixture()
        evidence["verificationResult"]["controllerProofSha256"] = "0" * 64
        with self.assertRaisesRegex(CampaignError, "anchor differs"):
            admission.validate_authority_evidence(evidence)

    def test_local_assembler_preserves_inputs_and_refuses_overwrite(self):
        evidence = authority_fixture()
        arguments = ["controller_admission"]
        fields = {
            "--verified-config": "verifiedConfig",
            "--verification-authorization": "verificationAuthorization",
            "--verification-result": "verificationResult",
            "--baseline-readback": "baselineReadback",
        }
        with tempfile.TemporaryDirectory() as directory:
            for argument, field in fields.items():
                path = Path(directory) / (field + ".json")
                path.write_text(json.dumps(evidence[field]))
                arguments.extend([argument, str(path)])
            output = Path(directory) / "controller-authority-evidence.json"
            arguments.extend(["--output", str(output)])
            with patch.object(sys, "argv", arguments), redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(admission.main(), 0)
            self.assertNotIn(SUBSCRIPTION, printed.getvalue())
            saved = output.read_bytes()
            self.assertEqual(admission.load_authority_evidence(output), evidence)
            with patch.object(sys, "argv", arguments), patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(admission.main(), 2)
            self.assertEqual(output.read_bytes(), saved)

    def test_private_binding_loader_checks_hash_and_directory(self):
        evidence = renewed_fixture()
        config, runtime = campaign_fixture(evidence)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "controller-authority-evidence.json"
            path.write_text(json.dumps(evidence))
            runtime["controllerAuthorityEvidenceFile"] = str(path)
            self.assertEqual(
                operator.load_bound_controller_authority(
                    Path(directory) / "runtime.json", runtime, config
                ),
                evidence,
            )
            runtime["controllerAuthorityEvidenceSha256"] = "0" * 64
            with self.assertRaisesRegex(CampaignError, "binding differs"):
                operator.load_bound_controller_authority(
                    Path(directory) / "runtime.json", runtime, config
                )
            with self.assertRaisesRegex(CampaignError, "escaped"):
                operator.load_bound_controller_authority(
                    Path(directory) / "other/runtime.json", runtime, config
                )

    def test_capacity_cannot_drop_or_replace_receipt(self):
        evidence = renewed_fixture()
        config, runtime = campaign_fixture(evidence)
        for value in (None, authority_fixture()):
            with self.subTest(value=value is None), self.assertRaises(CampaignError):
                operator.validate_operation_results(
                    "capacity-check", [], config, runtime, controller_authority_evidence=value
                )

    def test_capacity_passes_same_bound_receipt_to_discovery(self):
        evidence = renewed_fixture()
        config, runtime = campaign_fixture(evidence)
        selection = DiscoveryRunner(evidence).select(evidence)
        prefix = [
            *[result({"registrationState": "Registered"}) for _ in range(6)],
            result(["Standard_D2ds_v4"]),
            result({"value": [
                {"name": {"value": n}, "unit": "Count", "currentValue": 0, "limit": 10}
                for n in ("cores", "standardDDSv4Family")
            ]}),
            result({"value": [{
                "name": {"value": "ManagedEnvironmentCount"}, "currentValue": 0, "limit": 1
            }]}),
            result({"nameAvailable": True}),
            result({"nameAvailable": True}),
        ]
        with (
            patch.object(
                operator, "select_automation_region_from_results", return_value=selection
            ) as selector,
            patch.object(operator, "validate_controller_baseline"),
        ):
            operator.validate_operation_results(
                "capacity-check",
                [*prefix, *[result({}) for _ in range(13)]],
                config,
                runtime,
                runner=DiscoveryRunner(evidence),
                controller_authority_evidence=evidence,
            )
        self.assertIs(selector.call_args.kwargs["controller_authority_evidence"], evidence)

    def test_complete_capacity_readback_admits_and_rejects_mixed_deadline(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2030, 1, 2, 1, 3, tzinfo=UTC)

        evidence = renewed_fixture()
        config, runtime = campaign_fixture(evidence)
        runner = DiscoveryRunner(evidence)
        prefix = [
            *[result({"registrationState": "Registered"}) for _ in range(6)],
            result(["Standard_D2ds_v4"]),
            result({"value": [
                {"name": {"value": n}, "unit": "Count", "currentValue": 0, "limit": 10}
                for n in ("cores", "standardDDSv4Family")
            ]}),
            result({"value": [{
                "name": {"value": "ManagedEnvironmentCount"}, "currentValue": 0, "limit": 1
            }]}),
            result({"nameAvailable": True}),
            result({"nameAvailable": True}),
        ]
        readback = evidence["renewal"]["afterReadback"]
        results = [*prefix, *runner.discovery_results(), *readback]
        with patch("infra.milestone_7_8.automation_region.datetime", Clock):
            operator.validate_operation_results(
                "capacity-check",
                results,
                config,
                runtime,
                runner=runner,
                controller_authority_evidence=evidence,
            )
        changed = copy.deepcopy(results)
        runbook = json.loads(changed[20]["stdout"])
        runbook["tags"][admission.DEADLINE_TAG] = OLD
        changed[20] = result(runbook)
        with (
            patch("infra.milestone_7_8.automation_region.datetime", Clock),
            self.assertRaisesRegex(CampaignError, "deadlines differ"),
        ):
            operator.validate_operation_results(
                "capacity-check",
                changed,
                config,
                runtime,
                runner=runner,
                controller_authority_evidence=evidence,
            )

    def test_preparation_copies_and_binds_authority_then_rejects_tampering(self):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return NOW

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scope_path = root / "scope.json"
            scope_path.write_text(
                json.dumps(
                    predeployment.build_runtime_document(
                        subscription_id=SUBSCRIPTION,
                        tenant_id=TENANT,
                        campaign_id="mobius78-region-proof",
                        generation_id="g1-aabbccddeeff",
                        region="eastus2",
                    )
                )
            )
            scope = predeployment.load_runtime(scope_path)
            authorization = predeployment.build_read_authorization(
                scope, issued_at=NOW, expires_at=NOW.replace(minute=30)
            )
            authorization_path = root / "read-authorization.json"
            authorization_path.write_text(json.dumps(authorization))
            proof = predeployment.build_evidence_document(
                scope,
                authorization=authorization,
                observed_at=NOW,
                pages=[
                    {
                        "requestSha256": predeployment.request_sha256(
                            predeployment.endpoint(SUBSCRIPTION)
                        ),
                        "recordIdentitySha256": [],
                        "nextRequestSha256": None,
                    }
                ],
            )
            proof_path = root / "proof.json"
            proof_path.write_text(json.dumps(proof))
            script = (
                Path(__file__).resolve().parents[3]
                / "infra/milestone_7_8/scripts/Remove-M78Campaign.ps1"
            ).read_bytes()
            authority = authority_fixture(
                cleanup_hash=hashlib.sha256(script).hexdigest(),
                evidence_hash=predeployment.evidence_sha256(proof),
            )
            authority_path = root / "controller-authority.json"
            authority_path.write_text(json.dumps(authority))
            output = root / "new-bundle"
            original = authority_path.read_bytes()
            runner = DiscoveryRunner(authority)

            def git(*arguments):
                if arguments[0] == "status":
                    return ""
                if arguments[0] == "branch":
                    return "milestone-7-8-production-readiness-audit-local"
                if arguments[0] == "for-each-ref":
                    return "refs/remotes/origin/milestone-7-8-production-readiness-audit-local"
                if arguments[0] == "stash":
                    return "\n".join(str(index) for index in range(5))
                return "a" * 40

            arguments = [
                "prepare",
                "--campaign-id",
                scope.campaign_id,
                "--generation-id",
                scope.generation_id,
                "--output",
                str(output),
                "--controller-region",
                "eastus2",
                "--target-region",
                "centralus",
                "--postgres-region",
                "centralus",
                "--fresh-subscription-runtime",
                str(scope_path),
                "--fresh-subscription-authorization",
                str(authorization_path),
                "--fresh-subscription-evidence",
                str(proof_path),
                "--controller-authority-evidence",
                str(authority_path),
            ]
            with (
                patch.object(prepare, "_git", side_effect=git),
                patch.object(
                    prepare,
                    "canonical_snapshot",
                    return_value={"buildInputSha256": "b" * 64, "dockerfileSha256": "c" * 64},
                ),
                patch.object(prepare, "SubprocessRunner", return_value=runner),
                patch.object(prepare, "datetime", Clock),
                patch.dict(
                    "os.environ", {"M78_SUBSCRIPTION_ID": SUBSCRIPTION, "M78_TENANT_ID": TENANT}
                ),
                patch.object(sys, "argv", arguments),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(prepare.main(), 0)
            runtime_path = output / "runtime.json"
            runtime = operator.load_runtime(runtime_path)
            config = CampaignConfig.from_json(output / "campaign.json")
            operator.validate_prepared_bundle(runtime_path, runtime, config)
            copied = Path(runtime["controllerAuthorityEvidenceFile"])
            self.assertEqual(json.loads(copied.read_text()), authority)
            self.assertEqual(authority_path.read_bytes(), original)
            copied.write_text("{}")
            with self.assertRaises(CampaignError):
                operator.validate_prepared_bundle(runtime_path, runtime, config)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infra.milestone_7_8 import predeployment, retention
from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.controller import (
    build_controller_config,
    controller_config_document,
)

SUBSCRIPTION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TENANT = "11111111-2222-3333-4444-555555555555"
CAMPAIGN = "mobius78-fresh-scope"
GENERATION = "g1-0123456789ab"
REGION = "centralus"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self.pages = pages
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
            return subprocess.CompletedProcess(command, 0, SUBSCRIPTION + "\n", "")
        assert command[:3] == ("rest", "--method", "get")
        return subprocess.CompletedProcess(
            command, 0, json.dumps(self.pages[command[command.index("--url") + 1]]), ""
        )


def _scope(tmp_path: Path) -> tuple[Path, predeployment.FreshSubscriptionScope]:
    runtime = predeployment.build_runtime_document(
        subscription_id=SUBSCRIPTION,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        generation_id=GENERATION,
        region=REGION,
    )
    path = tmp_path / "fresh-subscription-runtime.json"
    path.write_text(json.dumps(runtime), encoding="utf-8")
    return path, predeployment.load_runtime(path)


def _authorization(scope: predeployment.FreshSubscriptionScope) -> dict[str, object]:
    return predeployment.build_read_authorization(
        scope, issued_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30)
    )


def _record(
    scope: predeployment.FreshSubscriptionScope,
    name: str,
    *,
    resource_group: str = "rg-other",
) -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Automation/"
            f"deletedAutomationAccounts/{name}"
        ),
        "name": name,
        "properties": {
            "automationAccountResourceId": (
                f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{resource_group}/providers/"
                f"Microsoft.Automation/automationAccounts/{name}"
            )
        },
    }


def test_zero_inventory_is_valid_fresh_predeployment_evidence(tmp_path: Path) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    url = predeployment.endpoint(SUBSCRIPTION)
    runner = FakeRunner({url: {"value": []}})

    document = predeployment.PredeploymentVerifier(runner, clock=lambda: NOW).verify(
        scope, authorization
    )
    binding = predeployment.validate_evidence(document, scope=scope, authorization=authorization)

    assert document["status"] == "fresh-subscription-predeployment-inventory-clear"
    assert document["deletedAccountCount"] == 0
    assert document["plannedAccountCandidates"] == 0
    assert document["deletedInventoryPages"] == 1
    assert document["azureGetOperations"] == 2
    assert binding.evidence_sha256 == predeployment.evidence_sha256(document)
    assert len(runner.calls) == 2
    encoded = json.dumps(document, sort_keys=True)
    assert SUBSCRIPTION not in encoded
    assert TENANT not in encoded
    assert scope.automation_account_name not in encoded


def test_complete_inventory_with_unrelated_record_is_sanitized_and_bound(
    tmp_path: Path,
) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    url = predeployment.endpoint(SUBSCRIPTION)
    document = predeployment.PredeploymentVerifier(
        FakeRunner({url: {"value": [_record(scope, "aa-unrelated-1234")]}}),
        clock=lambda: NOW,
    ).verify(scope, authorization)

    assert document["deletedAccountCount"] == 1
    assert document["plannedAccountCandidates"] == 0
    assert isinstance(document["deletedInventorySha256"], str)
    assert len(document["deletedInventorySha256"]) == 64


def test_predeployment_follows_every_pagination_link(tmp_path: Path) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    first_url = predeployment.endpoint(SUBSCRIPTION)
    next_url = first_url + "&$skiptoken=opaque"
    document = predeployment.PredeploymentVerifier(
        FakeRunner(
            {
                first_url: {"value": [], "nextLink": next_url},
                next_url: {"value": []},
            }
        ),
        clock=lambda: NOW,
    ).verify(scope, authorization)

    assert document["deletedInventoryPages"] == 2
    assert document["continuationCount"] == 1
    assert document["azureGetOperations"] == 3


def test_predeployment_rejects_the_exact_planned_account(tmp_path: Path) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    url = predeployment.endpoint(SUBSCRIPTION)
    runner = FakeRunner(
        {
            url: {
                "value": [
                    _record(
                        scope,
                        scope.automation_account_name,
                        resource_group=scope.controller_resource_group_name,
                    )
                ]
            }
        }
    )

    with pytest.raises(
        predeployment.PredeploymentVerificationError,
        match="predeployment-planned-account-present",
    ):
        predeployment.PredeploymentVerifier(runner, clock=lambda: NOW).verify(scope, authorization)


def test_predeployment_authorization_rejects_a_scope_substitution(tmp_path: Path) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    authorization["campaignCorrelation"] = "f" * 16
    authorization["authorizationSha256"] = predeployment.authorization_sha256(authorization)

    with pytest.raises(
        predeployment.PredeploymentVerificationError,
        match="predeployment-authorization-not-exact",
    ):
        predeployment.validate_read_authorization(authorization, scope=scope, require_current=False)


def test_fresh_evidence_builds_a_local_prebootstrap_controller_config(
    tmp_path: Path,
) -> None:
    """A missing controller is bootstrap-eligible without a campaign bundle."""

    runtime_path, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    authorization_path = tmp_path / "predeployment-read-authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    evidence = predeployment.build_evidence_document(
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
    evidence_path = tmp_path / "predeployment-absence-evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    config = build_controller_config(
        subscription_id=SUBSCRIPTION,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        generation_id=GENERATION,
        controller_location=REGION,
        source_head="a" * 40,
        cleanup_script_sha256="b" * 64,
        controller_authorized_until_utc="2026-11-08T13:00:00Z",
        fresh_subscription_runtime=runtime_path,
        fresh_subscription_authorization=authorization_path,
        fresh_subscription_evidence=evidence_path,
    )

    document = controller_config_document(config)
    assert document["controllerLocation"] == REGION
    assert document["freshControllerAdmissionEvidenceSha256"] == (
        predeployment.evidence_sha256(evidence)
    )
    assert document["automationAccountName"] == scope.automation_account_name
    assert SUBSCRIPTION not in json.dumps(
        {key: value for key, value in document.items() if key != "subscriptionId"}
    )

    with pytest.raises(CampaignError, match="predeployment-live-admission-binding-invalid"):
        build_controller_config(
            subscription_id=SUBSCRIPTION,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            generation_id=GENERATION,
            controller_location="eastus",
            source_head="a" * 40,
            cleanup_script_sha256="b" * 64,
            controller_authorized_until_utc="2026-11-08T13:00:00Z",
            fresh_subscription_runtime=runtime_path,
            fresh_subscription_authorization=authorization_path,
            fresh_subscription_evidence=evidence_path,
        )


def test_predeployment_evidence_cannot_cross_the_v3_retention_boundary(
    tmp_path: Path,
) -> None:
    _, scope = _scope(tmp_path)
    authorization = _authorization(scope)
    url = predeployment.endpoint(SUBSCRIPTION)
    document = predeployment.PredeploymentVerifier(
        FakeRunner({url: {"value": []}}), clock=lambda: NOW
    ).verify(scope, authorization)
    path = tmp_path / "fresh-subscription-predeployment-absence-evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(retention.RetentionVerificationError, match="not-exact"):
        retention.validate_retention_absence_evidence(
            path,
            subscription_correlation=predeployment.scope_bindings(scope)["subscriptionCorrelation"],
            subscription_id=SUBSCRIPTION,
            allow_synthetic=False,
        )


def test_predeployment_schemas_are_closed_and_never_claim_v3_retention() -> None:
    root = Path(__file__).resolve().parents[3]
    contracts = (
        (
            "fresh-subscription-predeployment-runtime.schema.json",
            predeployment.RUNTIME_FIELDS,
        ),
        (
            "fresh-subscription-predeployment-read-authorization.schema.json",
            predeployment.AUTHORIZATION_FIELDS,
        ),
        (
            "fresh-subscription-predeployment-absence-evidence.schema.json",
            predeployment.EVIDENCE_FIELDS,
        ),
    )
    for name, fields in contracts:
        schema = json.loads(
            (root / "infra/milestone_7_8/schemas" / name).read_text(encoding="utf-8")
        )
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == fields
        assert "retained-account-absent" not in json.dumps(schema, sort_keys=True)
        assert "m7.8-retained-automation-absence-verification-v3" not in json.dumps(
            schema, sort_keys=True
        )

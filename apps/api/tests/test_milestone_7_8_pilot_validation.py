from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from infra.milestone_7_8.pilot_alerts import compile_catalog
from infra.milestone_7_8.pilot_validation import VERSION, authorize, digest, prepare, write_new


def package(tmp_path):
    bundle = tmp_path / "package"
    prepare(bundle, "rc-123", "m78-0123456789", 40)
    scope = "/subscriptions/12345678-1234-1234-1234-123456789012/resourceGroups/rg-m78-0123456789-target"
    bindings = {
        "targetResourceGroupId": scope,
        "release": "rc-123",
        "deployment": "m78-0123456789",
        "imageDigest": "sha256:" + "a" * 64,
        "sourceCommit": "b" * 40,
        "workspaceResourceId": scope + "/providers/Microsoft.OperationalInsights/workspaces/proof",
        "dcrResourceId": scope + "/providers/Microsoft.Insights/dataCollectionRules/proof",
        "actionGroupId": scope + "/providers/Microsoft.Insights/actionGroups/proof",
        "eventHubResourceId": scope
        + "/providers/Microsoft.EventHub/namespaces/proof/eventhubs/alerts",
    }
    plan = tmp_path / "bindings.json"
    write_new(plan, bindings)
    start = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    approval = {
        "schema": VERSION + "-approval",
        "approved": True,
        "packageSha256": digest(bundle / "manifest.json"),
        "bindingsSha256": digest(plan),
        "approvedAt": start.isoformat(),
        "targetResourceGroupId": scope,
        "operations": ["telemetry", "query", "core"],
    }
    authority = tmp_path / "authority.json"
    write_new(authority, approval)
    return bundle, authority, plan, start


def test_prepare_never_claims_managed_acceptance_and_keeps_closed_campaigns(tmp_path) -> None:
    manifest = prepare(tmp_path / "bundle", "rc-123", "m78-0123456789", 40)
    assert manifest["managedAcceptance"] == "unproved"
    assert manifest["closedCampaigns"] == ["PostgreSQL", "M78-D-001", "M78-D-002"]
    assert manifest["relativeWindowHours"] == {"provisionBy": 2, "stopProof": 8, "cleanupBy": 10}


def test_source_and_absolute_deadline_are_derived_from_exact_authority(tmp_path) -> None:
    bundle, authority, plan, start = package(tmp_path)
    _, _, deadline = authorize(bundle, authority, plan, "core", start + timedelta(minutes=1))
    assert deadline == start + timedelta(hours=8)


@pytest.mark.parametrize("offset", [-1, 8 * 3600, 10 * 3600])
def test_no_early_or_expired_proof(tmp_path, offset) -> None:
    bundle, authority, plan, start = package(tmp_path)
    with pytest.raises(ValueError, match="not current"):
        authorize(bundle, authority, plan, "telemetry", start + timedelta(seconds=offset))


@pytest.mark.parametrize("changed", ["approval", "binding", "catalog", "operation", "scope"])
def test_changed_or_out_of_scope_package_is_rejected(tmp_path, changed) -> None:
    bundle, authority, plan, start = package(tmp_path)
    operation = "telemetry"
    if changed == "operation":
        operation = "smtp"
    elif changed == "catalog":
        (bundle / "catalog.json").write_text("{}")
    elif changed == "binding":
        data = json.loads(plan.read_text())
        data["imageDigest"] = "sha256:" + "c" * 64
        plan.write_text(json.dumps(data))
    elif changed == "scope":
        data = json.loads(plan.read_text())
        data["workspaceResourceId"] = data["workspaceResourceId"].replace(
            "0123456789-target", "9876543210-target"
        )
        plan.write_text(json.dumps(data))
        approved = json.loads(authority.read_text())
        approved["bindingsSha256"] = digest(plan)
        authority.write_text(json.dumps(approved))
    else:
        data = json.loads(authority.read_text())
        data["approved"] = False
        authority.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        authorize(bundle, authority, plan, operation, start + timedelta(minutes=1))


def test_catalog_keeps_all_existing_items_without_enabling_external_outbox() -> None:
    catalog = compile_catalog(release="rc-123", deployment="m78-0123456789", ceiling=40)
    assert len(catalog["workbooks"]) == 13
    assert len(catalog["alerts"]) == 16
    assert sum(alert["enabled"] for alert in catalog["alerts"]) == 15
    assert not next(alert for alert in catalog["alerts"] if alert["id"] == "outbox-backlog-v1")[
        "enabled"
    ]
    for alert in catalog["alerts"]:
        assert 'Release == "rc-123"' in alert["query"]
        assert 'Deployment == "m78-0123456789"' in alert["query"]
        assert "by SignalId" in alert["query"]
        assert "Presence" in alert["query"]
        assert alert["query"].count("(") == alert["query"].count(")")


def test_catalog_boundaries_reject_query_injection_and_missing_ceiling() -> None:
    for release, ceiling in [('bad" | take 1', 40), ("rc-123", 0), ("rc-123", float("inf"))]:
        with pytest.raises(ValueError):
            compile_catalog(release=release, deployment="m78-0123456789", ceiling=ceiling)

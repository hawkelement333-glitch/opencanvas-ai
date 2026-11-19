from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from infra.milestone_7_8 import pilot_validation
from infra.milestone_7_8.pilot_alerts import compile_catalog
from infra.milestone_7_8.pilot_validation import VERSION, authorize, digest, prepare, write_new


def package(tmp_path):
    bundle = tmp_path / "package"
    prepare(bundle, "rc-123", "m78-0123456789", 40)
    scope = (
        "/subscriptions/12345678-1234-1234-1234-123456789012"
        "/resourceGroups/rg-m78-0123456789-target"
    )
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


def test_authorize_rejects_a_hashed_but_stale_verification_catalog(tmp_path):
    bundle, authority, plan, start = package(tmp_path)
    catalog = json.loads((bundle / "catalog.json").read_bytes())
    catalog["release"] = "previous"
    (bundle / "catalog.json").write_text(json.dumps(catalog))
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["catalogSha256"] = digest(bundle / "catalog.json")
    manifest_path.write_text(json.dumps(manifest))
    approval = json.loads(authority.read_bytes())
    approval["packageSha256"] = digest(manifest_path)
    authority.write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="catalog differs"):
        authorize(bundle, authority, plan, "query", start)


@pytest.mark.parametrize(
    "scenario", ["success", "wrong-ids", "partial-result", "gateway-503", "public-dns"]
)
async def test_transport_attributes_failure_and_requires_exact_ids(monkeypatch, scenario):
    source = {
        "service": "mobius-evidence", "environment": "staging",
        "release": "rc-fixture", "deployment": "m78p-fixture",
    }
    bindings = source | {
        "probeTelemetrySource": source,
        "gatewayUrl": "https://private.invalid/v1/signals",
    }
    requests = []
    queries = []

    def host(_):
        if scenario == "public-dns":
            raise ValueError("private destination DNS not proved")
        return ["10.0.0.1"]

    def gateway(request):
        assert request.url == bindings["gatewayUrl"]
        saw_auth = "authorization" in request.headers
        poisoned = "prompt" in json.loads(request.content)["signals"][0]["payload"]
        requests.append((saw_auth, poisoned))
        if not saw_auth:
            return httpx.Response(401)
        if poisoned:
            return httpx.Response(422)
        return httpx.Response(503 if scenario == "gateway-503" else 202)

    async def query(plan, kql):
        queries.append(kql)
        ids = re.findall(r'"([a-f0-9]{64})"', kql)
        assert len(ids) == 4
        if scenario == "wrong-ids":
            ids[-1] = "0" * 64
        table = {"columns": [{"name": "SignalId"}], "rows": [[value] for value in ids]}
        result = {"tables": [table]}
        if scenario == "partial-result":
            result["error"] = {"code": "PartialError"}
        return {"status": 200, "result": result}

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(
        transport=httpx.MockTransport(gateway), **kw
    ))
    monkeypatch.setattr(pilot_validation, "_private_host", host)
    monkeypatch.setattr(pilot_validation, "query", query)
    monkeypatch.setenv("OPENCANVAS_TELEMETRY_GATEWAY_TOKEN", "synthetic-test-token")
    deadline = datetime.now(UTC) + timedelta(minutes=1)
    if scenario == "success":
        result = await pilot_validation.telemetry(bindings, deadline)
        assert result["classification"] == "transport-fixture-only"
        assert len(result["expectedRows"]) == 4
    else:
        with pytest.raises(pilot_validation.TransportError) as error:
            await pilot_validation.telemetry(bindings, deadline)
        expected = {
            "wrong-ids": ("destination-query", "unexpected-signal-id-result", 200),
            "partial-result": ("destination-query", "unexpected-signal-id-result", 200),
            "gateway-503": ("gateway-valid-batch", "unexpected-http-status", 503),
            "public-dns": ("gateway-dns", "private-resolution-unproved", None),
        }[scenario]
        assert error.value.diagnostic == (
            dict(zip(("stage", "code", "httpStatus"), expected, strict=True))
            if expected[2] is not None else {"stage": expected[0], "code": expected[1]}
        )
    assert requests == ([] if scenario == "public-dns" else [
        (False, False), (True, True), (True, False),
    ])
    assert len(queries) == (0 if scenario in {"public-dns", "gateway-503"} else 1)


@pytest.mark.parametrize(
    ("alert_id", "signal", "breach", "recovery", "bad_windows", "good_windows", "missing"),
    [
        ("api-latency-v1", "mobius.api.duration", "V>=1000", "V<750", 2, 2, "false"),
        (
            "database-saturation-v1", "mobius.database.pool.acquire",
            "V>=500 or T>0", "V<250 and T==0", 2, 3, "true",
        ),
    ],
)
def test_percentile_rules_keep_population_missing_data_and_hysteresis(
    alert_id, signal, breach, recovery, bad_windows, good_windows, missing,
) -> None:
    catalog = compile_catalog(
        release="rc-123", deployment="m78-0123456789", ceiling=40, full_closure=True
    )
    rule = next(row for row in catalog["alerts"] if row["id"] == alert_id)
    query = rule["query"]
    assert f"V=percentile(iff(Name=='{signal}',V,real(null)),95)" in query
    assert "percentileif" not in query
    assert "bin_at(TimeGenerated,5m,End)" in query
    assert f"Breach=iff(Missing,{missing},coalesce({breach},false))" in query
    assert f"Healthy=iff(Missing,false,coalesce({recovery},false))" in query
    assert f"s.Bad+1>={bad_windows}" in query
    assert f"s.Good+1>={good_windows}" in query
    assert rule["evaluationFrequency"] == "PT5M"
    assert rule["evaluationWindowMinutes"] == 5
    assert rule["autoMitigate"] is True
    if alert_id == "database-saturation-v1":
        assert "T=sumif(V,Name=='mobius.database.timeouts')" in query
        assert "Name in ('mobius.database.pool.acquire','mobius.database.timeouts')" in query
    else:
        assert "Presence=countif(Name in ('mobius.api.duration'))" in query


@pytest.mark.parametrize("invalid", ["reserve", "allowance", "cumulative", "increase"])
def test_reconciled_alert_successor_ceiling_is_sealed(tmp_path, invalid) -> None:
    from infra.milestone_7_8.campaign import CampaignError
    from infra.milestone_7_8.pilot_cleanup import (
        ALERT_REPAIR_REVIEW_SCHEMA,
        MINUTE_START_RULE,
        validate_review,
    )

    write_new(tmp_path / "regional-pricing.json", {"forecastUsd": 39.4128})
    reconciliation = {
        "priorReserveUsd": "9",
        "nextExecutionCeilingUsd": "49.75",
        "cumulativeCeilingProposedUsd": "409.64",
    }
    write_new(tmp_path / "cost-reconciliation.json", reconciliation)
    review = {
        "schema": ALERT_REPAIR_REVIEW_SCHEMA, "sourceCommit": "a" * 40,
        "forecastUsd": 39.4128, "targetRegion": "canadacentral", "redisRegion": "eastus",
        "spendingApprovalReady": True, "incrementalCeilingUsd": 50,
        "priorAttemptReserveUsd": 9, "successorExecutionAllowanceUsd": 49.75,
        "combinedCeilingUsd": 58.75, "proposedCumulativeCeilingUsd": 409.64,
        "netCeilingIncreaseProposedUsd": 8.75,
        "costReconciliationSha256": digest(tmp_path / "cost-reconciliation.json"),
        "executionStartRule": MINUTE_START_RULE,
        "files": {
            name: digest(tmp_path / name)
            for name in ("regional-pricing.json", "cost-reconciliation.json")
        },
    }
    write_new(tmp_path / "review-package.json", review)
    approval = {
        "approved": True, "sourceHead": "a" * 40,
        "approvedAt": "2030-01-01T00:00:37Z",
        "executionStartAt": "2030-01-01T00:01:00Z",
        "reviewPackageSha256": digest(tmp_path / "review-package.json"),
    }
    assert validate_review(tmp_path, approval) == review
    field = {
        "reserve": "priorAttemptReserveUsd",
        "allowance": "successorExecutionAllowanceUsd",
        "cumulative": "proposedCumulativeCeilingUsd",
        "increase": "netCeilingIncreaseProposedUsd",
    }[invalid]
    review[field] += 1
    (tmp_path / "review-package.json").write_text(json.dumps(review), encoding="utf-8")
    approval["reviewPackageSha256"] = digest(tmp_path / "review-package.json")
    with pytest.raises(CampaignError, match="exact replacement review"):
        validate_review(tmp_path, approval)

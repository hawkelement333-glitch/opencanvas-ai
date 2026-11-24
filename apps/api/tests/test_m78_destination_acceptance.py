import copy
import hashlib
import json
import math
from datetime import UTC, datetime

import pytest
from infra.milestone_7_8.destination_acceptance import (
    Evidence,
    MissingEvidence,
    expected_alert_states,
    reconcile,
    rows,
    validate_access,
    validate_alerts,
    validate_outage,
    validate_rejection,
    validate_retention,
    validate_signal_row,
    validate_signals,
    validate_workbooks,
)
from infra.milestone_7_8.pilot_alerts import compile_catalog
from infra.milestone_7_8.pilot_validation import prepare


class LocalFixtureEvidence:
    """Unit-only receipt fake; cannot be serialized as managed acceptance."""

    def __init__(self, plan, documents):
        self.plan = plan
        self.documents = documents
        self.manifest = {"startedAt": "2026-11-16T00:00:00Z", "completedAt": "2026-11-16T00:10:00Z"}

    def read(self, name):
        if name not in self.documents:
            raise MissingEvidence(name)
        return self.documents[name]

    def raw(self, name):
        value = self.read(name)
        return value if isinstance(value, bytes) else json.dumps(value).encode()


def test_full_closure_package_binds_actual_collectors_and_probes(tmp_path):
    manifest = prepare(tmp_path / "package", "rc-123", "m78-0123456789", 50, full_closure=True)
    assert manifest["fullClosure"] is True
    assert manifest["managedAcceptance"] == "unproved"
    assert {
        "capacity",
        "integrity",
        "provider-observation",
        "restore-rollback",
        "password-reset-confirm",
        "activity-delivery-happy",
        "activity-delivery-network-delay",
        "queue-grant-outage",
        "queue-grant-restore",
    }.issubset(manifest["operations"])
    bindings = manifest["sourceBindings"]
    assert "infra/milestone_7_8/activity_delivery_validation.py" in bindings
    assert "infra/milestone_7_8/queue_grant_intervention.py" in bindings
    assert "infra/milestone_7_8/password_reset_validation.py" in bindings
    assert "apps/api/scripts/operational_observer.py" in bindings
    catalog = json.loads((tmp_path / "package" / "catalog.json").read_text())
    assert len([alert for alert in catalog["alerts"] if alert["enabled"]]) == 16


def native_rows(values):
    columns = list(values[0]) if values else ["Count"]
    return {
        "status": 200,
        "result": {
            "tables": [
                {
                    "columns": [{"name": name} for name in columns],
                    "rows": [[value.get(name) for name in columns] for value in values],
                }
            ]
        },
    }


def catalog_rule(name):
    from infra.milestone_7_8.pilot_alerts import ROOT

    rules = json.loads((ROOT / "docs/observability/alerts-v1.json").read_text())["alerts"]
    return next(rule for rule in rules if rule["id"] == name)


def test_full_catalog_preserves_daily_windows_and_manual_integrity_recovery():
    catalog = compile_catalog(
        release="rc-test", deployment="m78-test", ceiling=50, full_closure=True
    )
    assert len(catalog["alerts"]) == 16 and all(x["enabled"] for x in catalog["alerts"])
    # Provider one-minute optimization rejects union; use supported cadence.
    assert all(x["evaluationFrequency"] == "PT5M" for x in catalog["alerts"])
    assert all(
        'Service in ("mobius-api", "mobius-worker", "mobius-outbox")' in x["query"]
        for x in catalog["alerts"]
    )
    for name in ("backup-freshness-v1", "cost-v1"):
        rule = next(x for x in catalog["alerts"] if x["id"] == name)
        assert rule["evaluationWindowMinutes"] == 1440
        assert "1440m" in rule["query"] and "15m" not in rule["query"]
        assert "End=now()" in rule["query"] and "bin_at(TimeGenerated,1440m,End)" in rule["query"]
    evidence = next(x for x in catalog["alerts"] if x["id"] == "evidence-integrity-v1")
    assert evidence["autoMitigate"] is False
    assert evidence["recoveryMode"] == "authorized-investigation"
    outbox = next(x for x in catalog["alerts"] if x["id"] == "outbox-backlog-v1")
    assert "ForceFire=coalesce(T>0,false)" in outbox["query"]


def test_alert_hysteresis_terminal_failure_and_manual_integrity():
    latency = catalog_rule("api-latency-v1")
    windows = [{"Presence": 1, "V": value} for value in [1000, 1100, 800, 700, 700]]
    assert expected_alert_states(latency, windows, 50) == [False, True, True, True, False]
    outbox = catalog_rule("outbox-backlog-v1")
    assert expected_alert_states(outbox, [{"Presence": 1, "V": 0, "T": 1}], 50) == [True]
    integrity = catalog_rule("evidence-integrity-v1")
    assert expected_alert_states(
        integrity, [{"Presence": 1, "V": 1}, {"Presence": 1, "V": 0}], 50
    ) == [True, True]


def test_daily_latest_observation_uses_actual_age_and_forecast():
    assert expected_alert_states(
        catalog_rule("backup-freshness-v1"),
        [{"Presence": 1, "Values": [86401]}, {"Presence": 1, "Values": [3600]}],
        50,
    ) == [True, False]
    assert expected_alert_states(
        catalog_rule("cost-v1"),
        [
            {"Presence": 1, "Values": [41]},
            {"Presence": 1, "Values": [36]},
            {"Presence": 1, "Values": [34]},
        ],
        50,
    ) == [True, True, False]
    with pytest.raises(ValueError, match="latest provider observation absent"):
        expected_alert_states(catalog_rule("cost-v1"), [{"Presence": 1}], 50)


def test_missing_data_is_not_healthy_zero():
    assert expected_alert_states(
        catalog_rule("api-latency-v1"),
        [{"Presence": 1, "V": 1000}, {"Presence": 0}, {"Presence": 1, "V": 1000}],
        50,
    ) == [False, False, True]
    assert expected_alert_states(
        catalog_rule("database-saturation-v1"), [{"Presence": 0}, {"Presence": 0}], 50
    ) == [False, True]


def test_native_query_errors_partial_rows_and_duplicates_reject():
    with pytest.raises(ValueError):
        rows({"status": 403})
    receipt = native_rows([{"Count": 0}])
    receipt["result"]["error"] = {"code": "PartialError"}
    with pytest.raises(ValueError, match="partial error"):
        rows(receipt)
    receipt = native_rows([{"Count": 0}])
    receipt["result"]["tables"][0]["rows"] = [[]]
    with pytest.raises(ValueError, match="partial native"):
        rows(receipt)


def test_manifest_never_upgrades_local_fixture_or_changed_artifact(tmp_path):
    plan = {
        "sourceCommit": "a" * 40,
        "imageDigest": "sha256:" + "b" * 64,
        "release": "r",
        "deployment": "d",
    }
    manifest = {
        **plan,
        "schema": "m78-native-destination-evidence-v1",
        "executionIds": ["caj-native-actual"],
        "evidenceClass": "local-fixture",
        "artifacts": {},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="local fixtures"):
        Evidence(path, plan)
    manifest["evidenceClass"] = "managed-native"
    manifest["artifacts"] = {"receipt": {"path": "receipt.json", "sha256": "c" * 64}}
    path.write_text(json.dumps(manifest))
    (tmp_path / "receipt.json").write_text("{}")
    with pytest.raises(ValueError, match="hash differs"):
        Evidence(path, plan).read("receipt")


def test_missing_native_receipts_remain_unproved(tmp_path):
    plan = {
        "sourceCommit": "a" * 40,
        "imageDigest": "sha256:" + "b" * 64,
        "release": "r",
        "deployment": "d",
        "operatingCeilingUsd": 50,
    }
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                **plan,
                "schema": "m78-native-destination-evidence-v1",
                "executionIds": ["caj-native-actual"],
                "evidenceClass": "managed-native",
                "artifacts": {},
            }
        )
    )
    result = reconcile(path, plan)
    assert all(item["status"] == "unproved" for item in result["assertions"].values())
    assert result["areaClosed"] is False


def test_api_worker_native_signal_privacy_and_trace_continuity():
    from scripts.telemetry_destination import destination_rows

    sources = [
        {"service": service, "environment": "staging", "release": "r", "deployment": "d"}
        for service in ["mobius-api", "mobius-worker"]
    ]
    stamp = "2026-11-16T00:01:00Z"
    signals = []
    for index, source in enumerate(sources):
        signals.append(
            {
                **source,
                "schema_version": "mobius-operational-v1",
                "kind": "span",
                "name": "http.server.request",
                "timestamp": stamp,
                "component": "api",
                "payload": {
                    "trace_id": "a" * 32,
                    "span_id": str(index) * 16,
                    "depth": index,
                    "duration_ms": 10,
                    "outcome": "success",
                    "attributes": {},
                    "events": [],
                    "links": [],
                },
            }
        )
    native = destination_rows(
        {"resource": {"schema": "mobius-operational-v1"}, "signals": signals},
        sources,
        now=datetime(2026, 11, 16, 0, 1, tzinfo=UTC),
    )
    plan = {
        "productionSources": sources,
        "requiredProductionSignals": [
            [s["service"], "span", "http.server.request"] for s in sources
        ],
    }
    metric = destination_rows(
        {
            "resource": {"schema": "mobius-operational-v1"},
            "signals": [
                {
                    **sources[1],
                    "schema_version": "mobius-operational-v1",
                    "kind": "metric",
                    "name": "mobius.queue.depth",
                    "component": "queue",
                    "timestamp": "2026-11-16T00:01:00+00:00",
                    "payload": {
                        "catalog_version": "mobius-signals-v1",
                        "type": "gauge",
                        "unit": "job",
                        "value": 3.0,
                        "labels": {"component": "queue", "outcome": "success"},
                    },
                }
            ],
        },
        sources,
        now=datetime(2026, 11, 16, 0, 1, tzinfo=UTC),
    )[0]
    metric["TimeGenerated"] = stamp
    metric["Payload"]["value"] = 3
    fixture = LocalFixtureEvidence(plan, {"production-signals": native_rows([*native, metric])})
    result = validate_signals(fixture)
    assert result["signals"] == 3
    assert result["traceContinuity"] == "accepted"
    bad = copy.deepcopy(signals)
    bad[1]["payload"]["trace_id"] = "b" * 32
    fixture.documents["production-signals"] = native_rows(
        destination_rows(
            {"resource": {"schema": "mobius-operational-v1"}, "signals": bad},
            sources,
            now=datetime(2026, 11, 16, 0, 1, tzinfo=UTC),
        )
    )
    with pytest.raises(MissingEvidence, match="trace continuity"):
        validate_signals(fixture)
    for signal in bad:
        signal["payload"]["links"] = [
            {"trace_id": "c" * 32, "span_id": "d" * 16, "correlation": "e" * 20}
        ]
    fixture.documents["production-signals"] = native_rows(
        destination_rows(
            {"resource": {"schema": "mobius-operational-v1"}, "signals": bad},
            sources,
            now=datetime(2026, 11, 16, 0, 1, tzinfo=UTC),
        )
    )
    assert validate_signals(fixture)["traceContinuity"] == "accepted"
    fixture.documents["production-signals"] = native_rows(native)
    fixture.documents["production-signals"]["result"]["tables"][0]["rows"][0][-1]["attributes"][
        "prompt"
    ] = "private-sentinel"
    with pytest.raises(ValueError, match="privacy/schema/source contract"):
        validate_signals(fixture)


@pytest.mark.parametrize("value", [
    0.007399998139590025, 0.11410300000136431, math.nextafter(1.0, 0.0),
    math.ulp(0.0), math.nextafter(2.0**52, 0.0),
])
def test_native_metric_binary_projection_verifies_only_the_exact_gateway_digest(value):
    from scripts.telemetry_destination import destination_rows

    now = datetime(2026, 11, 24, tzinfo=UTC)
    source = {"service": "mobius-worker", "environment": "staging", "release": "r", "deployment": "d"}
    signal = source | {
        "schema_version": "mobius-operational-v1", "kind": "metric", "name": "mobius.queue.depth",
        "timestamp": now.isoformat(), "component": "queue", "payload": {
            "catalog_version": "mobius-signals-v1", "type": "gauge", "unit": "job", "value": value,
            "labels": {"component": "queue", "outcome": "success"},
        },
    }
    row, = destination_rows({"resource": {"schema": "mobius-operational-v1"}, "signals": [signal]},
                            [source], now=now)

    def encode(number):
        scale = max(-1022, int(math.log2(number)) - 2)
        return {"NativeMetricExponent": scale - 52,
                "NativeMetricSignificand": int((number / 2.0**scale) * 2**52)}

    projected = row | encode(value) | {"Payload": {k: v for k, v in row["Payload"].items() if k != "value"}}
    assert validate_signal_row(projected, [source], now, set()) == signal
    altered = math.nextafter(value, math.inf)
    with pytest.raises(ValueError):
        validate_signal_row(projected | encode(altered), [source], now, set())
    with pytest.raises(ValueError, match="invalid native metric encoding"):
        validate_signal_row(projected | {"Payload": row["Payload"]}, [source], now, set())
    incomplete = dict(projected)
    del incomplete["NativeMetricExponent"]
    with pytest.raises(ValueError, match="incomplete native metric encoding"):
        validate_signal_row(incomplete, [source], now, set())
    with pytest.raises(ValueError, match="native signal content/identity differs"):
        validate_signal_row(row | {"Payload": row["Payload"] | {"value": altered}}, [source], now, set())


def test_source_privacy_rejection_requires_destination_absence():
    hashes = {
        key: hashlib.sha256(key.encode()).hexdigest()
        for key in ("unauthenticated", "wrong-source", "private-content")
    }
    negative = {
        key: {
            "request": {"url": "https://private.test/v1/signals", "bodySha256": value},
            "response": {"status": 401 if key == "unauthenticated" else 422},
        }
        for key, value in hashes.items()
    }
    evidence = LocalFixtureEvidence(
        {"gatewayUrl": "https://private.test/v1/signals", "negativeRequestHashes": hashes},
        {
            "gateway-negative-requests": negative,
            "rejected-signal-absence": native_rows([{"Count": 0}]),
        },
    )
    assert validate_rejection(evidence)["destinationAbsence"] == "accepted"
    evidence.documents["rejected-signal-absence"] = native_rows([{"Count": 1}])
    with pytest.raises(ValueError, match="reached destination"):
        validate_rejection(evidence)


def test_access_requires_fresh_sessions_and_exact_assignment_restoration():
    plan = {
        "principalIds": {
            role: role + "-id" for role in ("api", "worker", "gateway", "operator", "evidence")
        },
        "queryAssignmentIds": {"operator": "op-grant", "evidence": "probe-grant"},
    }
    obs = {
        role: {"principalId": role + "-id", "queryStatus": 403}
        for role in ("api", "worker", "gateway")
    }
    for role in ("operator", "evidence"):
        obs[role] = {
            "principalId": role + "-id",
            "before": {"queryStatus": 200, "credentialSessionId": "before"},
            "revoked": {"queryStatus": 403, "credentialSessionId": "during"},
            "restored": {"queryStatus": 200, "credentialSessionId": "after"},
            "deletedAssignmentId": plan["queryAssignmentIds"][role],
            "restoredAssignmentId": plan["queryAssignmentIds"][role],
            "nativeDeleteStatus": 204,
            "nativeRestoreStatus": 201,
        }
    evidence = LocalFixtureEvidence(plan, {"destination-access": obs})
    assert validate_access(evidence)["revocation"] == ["operator", "evidence"]
    obs["operator"]["revoked"]["credentialSessionId"] = "before"
    with pytest.raises(ValueError, match="fresh sessions"):
        validate_access(evidence)


def test_exporter_outage_requires_loss_readiness_and_drain():
    def observation(ready, state, buffered, dropped):
        return {
            "readyStatus": ready,
            "operator": {
                "dependencies": {"telemetry": state},
                "telemetryBuffered": buffered,
                "telemetryDropped": dropped,
            },
        }

    scenario = {
        "targetResourceId": "gateway",
        "outageSeconds": 30,
        "before": observation(200, "healthy", 0, 0),
        "during": observation(503, "unavailable", 64, 3),
        "after": observation(200, "healthy", 0, 3),
        "nativeStopReceipt": "stop",
        "nativeStartReceipt": "start",
    }
    evidence = LocalFixtureEvidence(
        {"gatewayResourceId": "gateway", "outageMaxSeconds": 600, "telemetryBufferLimit": 64},
        {"exporter-outage": scenario, "stop": {}, "start": {}},
    )
    assert validate_outage(evidence)["bufferBound"] == 64
    scenario["after"]["operator"]["telemetryBuffered"] = 1
    with pytest.raises(ValueError, match="not drained"):
        validate_outage(evidence)


def test_rendering_and_alert_collection_alone_do_not_close():
    evidence = LocalFixtureEvidence(
        {
            "release": "r",
            "deployment": "d",
            "operatingCeilingUsd": 50,
            "operatorPrincipalIds": ["operator"],
        },
        {
            "workbook-render-review": {"reviewerPrincipalId": "operator", "workbooks": {}},
            "alert-scenarios": {},
            "native-alert-events": [],
        },
    )
    with pytest.raises(MissingEvidence, match="rendering absent"):
        validate_workbooks(evidence)
    with pytest.raises(MissingEvidence, match="scenario absent"):
        validate_alerts(evidence)


def test_retention_requires_exact_native_table_and_total_retention():
    values = {
        "MobiusApplication_CL": 30,
        "MobiusSecurity_CL": 90,
        "MobiusMetric_CL": 30,
        "MobiusSpan_CL": 14,
        "MobiusIncident_CL": 365,
    }
    native = {
        name: {
            "status": 200,
            "body": {
                "id": "workspace/tables/" + name,
                "properties": {"retentionInDays": days, "totalRetentionInDays": days},
            },
        }
        for name, days in values.items()
    }
    native["workspace"] = {
        "status": 200,
        "body": {
            "id": "workspace",
            "properties": {"features": {"immediatePurgeDataOn30Days": True}},
        },
    }
    evidence = LocalFixtureEvidence(
        {"workspaceResourceId": "workspace"}, {"retention-readbacks": native}
    )
    assert (
        validate_retention(evidence)["physicalExpiryObservation"]
        == "not inferred from configuration"
    )
    native["MobiusSpan_CL"]["body"]["properties"]["totalRetentionInDays"] = 30
    with pytest.raises(ValueError, match="retention differs"):
        validate_retention(evidence)


def test_all_catalog_native_pairs_require_metric_semantics_and_authorized_integrity_close():
    # Independently specified values exercise the catalog thresholds/recovery rules.
    observations = {
        "api-latency-v1": ({"V": 1100}, {"V": 700}, 2, 2),
        "database-saturation-v1": ({"V": 600, "T": 0}, {"V": 200, "T": 0}, 2, 3),
        "storage-outage-v1": ({"F": 10, "N": 100}, {"F": 0, "N": 100}, 2, 3),
        "scanner-outage-v1": ({"V": 1, "H": 0}, {"V": 0, "H": 3}, 1, 1),
        "queue-backlog-v1": ({"V": 301}, {"V": 100}, 2, 2),
        "worker-stale-v1": ({"V": 0}, {"V": 2}, 2, 1),
        "limiter-outage-v1": ({"V": 0, "Decisions": [0]}, {"V": 1, "Decisions": [1, 1, 1]}, 1, 1),
        "indexer-freshness-v1": ({"V": 901, "D": 0}, {"V": 200, "D": 0}, 2, 2),
        "provider-degradation-v1": ({"F": 10, "N": 100}, {"F": 0, "N": 100}, 2, 3),
        "outbox-backlog-v1": ({"V": 301, "T": 0}, {"V": 100, "T": 0}, 2, 2),
        "evidence-integrity-v1": ({"V": 1}, {"V": 0}, 1, 99),
        "telemetry-loss-v1": (
            {"D": 1, "F": 0, "H": [0], "B": 1},
            {"D": 0, "F": 0, "H": [1, 1, 1], "B": 0},
            1,
            1,
        ),
        "backup-freshness-v1": ({"Values": [90000]}, {"Values": [100]}, 1, 1),
        "capacity-v1": ({"V": 0.9}, {"V": 0.6}, 3, 3),
        "cost-v1": ({"Values": [41]}, {"Values": [34]}, 1, 1),
        "readiness-v1": ({"F": 3, "S": [503, 503, 503]}, {"F": 0, "S": [200, 200, 200]}, 1, 1),
    }
    plan = {
        "operatingCeilingUsd": 50,
        "workspaceResourceId": "workspace",
        "operatorPrincipalIds": ["operator"],
        "integrityClosureAuthorities": ["authorized-investigation"],
        "alertRuleNames": {key: "rule-" + key for key in observations},
    }
    documents = {"alert-scenarios": {}, "native-alert-events": [], "stimulus": {}, "recovery": {}}
    for name, (bad, good, fire_count, recover_count) in observations.items():
        documents["alert-scenarios"][name] = {
            "stimulusClass": "production-operation",
            "stimulusEvidence": "stimulus",
            "recoveryEvidence": "recovery",
            "startedAt": "2026-11-16T00:00:00Z",
            "endedAt": "2026-11-16T06:00:00Z",
            "findingEvidenceSha256": "finding",
        }
        windows = [{"Presence": 1, **bad, "Firing": i + 1 >= fire_count} for i in range(3)]
        windows += [{"Presence": 1, **good, "Firing": i + 1 < recover_count} for i in range(3)]
        documents["alert-windows-" + name] = native_rows(windows)
        conditions = ["Fired"] if name == "evidence-integrity-v1" else ["Fired", "Resolved"]
        for condition in conditions:
            essentials = {
                "alertRule": "rule-" + name,
                "alertId": "native-" + name,
                "alertTargetIDs": ["workspace"],
                "monitorCondition": condition,
                "firedDateTime": "2026-11-16T01:00:00Z",
                "resolvedDateTime": "2026-11-16T02:00:00Z",
            }
            documents["native-alert-events"].append(
                {
                    "enqueuedTime": "2026-11-16T02:01:00Z",
                    "native": {
                        "schemaId": "azureMonitorCommonAlertSchema",
                        "data": {"essentials": essentials},
                    },
                }
            )
    documents["integrity-authorized-closure"] = {
        "operatorPrincipalId": "operator",
        "authorizationSha256": "authorized-investigation",
        "findingEvidenceSha256": "finding",
        "nativeAlertStateChange": {
            "at": "2026-11-16T03:00:00Z",
            "request": {"alertId": "native-evidence-integrity-v1"},
            "response": {
                "status": 200,
                "body": {"properties": {"essentials": {"alertState": "Closed"}}},
            },
        },
    }
    evidence = LocalFixtureEvidence(plan, documents)
    assert len(validate_alerts(evidence)["alerts"]) == 16
    documents["integrity-authorized-closure"]["operatorPrincipalId"] = "unauthorized"
    with pytest.raises(ValueError, match="operator not authorized"):
        validate_alerts(evidence)


def test_selected_full_closure_window_preserves_historical_pilot_window(tmp_path):
    closure = tmp_path / "closure"
    pilot = tmp_path / "pilot"
    closure.mkdir()
    pilot.mkdir()
    selected = prepare(closure, "rc-window", "m78-window", 50, full_closure=True)
    historical = prepare(pilot, "rc-window", "m78-window", 50)
    assert selected["relativeWindowHours"] == {
        "provisionBy": 2,
        "readyBy": 2,
        "stopProof": 10,
        "cleanupBy": 12,
    }
    assert historical["relativeWindowHours"] == {
        "provisionBy": 2,
        "stopProof": 8,
        "cleanupBy": 10,
    }
    assert selected["managedAcceptance"] == "unproved"
    assert selected["closedCampaigns"] == ["PostgreSQL", "M78-D-001", "M78-D-002"]

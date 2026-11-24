"""Offline reconciliation of native destination evidence against the existing catalog.

No Azure calls, synthetic producers, inferred healthy zeros or automatic repair.
The collector's private receipt manifest binds every input by SHA-256. A local
fixture can test this validator but cannot become managed evidence by passing it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infra.milestone_7_8.pilot_alerts import ROOT, compile_catalog


class MissingEvidence(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timezone absent")
    return result.astimezone(UTC)


def rows(receipt: dict) -> list[dict]:
    require(receipt.get("status") == 200, "native destination query failed")
    require("error" not in receipt["result"], "native query contains partial error")
    tables = receipt["result"].get("tables", [])
    require(len(tables) == 1, "one exact native query result table required")
    table = tables[0]
    names = [column["name"] for column in table["columns"]]
    require(len(names) == len(set(names)), "duplicate native query column")
    require(len(table["rows"]) <= 10000, "bounded native query required")
    require(all(len(row) == len(names) for row in table["rows"]), "partial native row")
    return [dict(zip(names, row, strict=True)) for row in table["rows"]]


class Evidence:
    def __init__(self, manifest: Path, plan: dict):
        self.root = manifest.resolve().parent
        self.manifest = json.loads(manifest.read_text(encoding="utf-8"))
        require(
            self.manifest.get("schema") == "m78-native-destination-evidence-v1",
            "native evidence manifest required",
        )
        for key in ("sourceCommit", "imageDigest", "release", "deployment"):
            require(
                self.manifest.get(key) == plan[key], "release/source binding mismatch"
            )
        require(
            bool(self.manifest.get("executionIds")),
            "actual managed execution IDs absent",
        )
        require(
            self.manifest.get("evidenceClass") == "managed-native",
            "local fixtures are not managed acceptance",
        )
        self.plan = plan

    def raw(self, name: str) -> bytes:
        entry = self.manifest["artifacts"].get(name)
        if entry is None:
            raise MissingEvidence(name)
        target = (self.root / entry["path"]).resolve()
        require(target.is_relative_to(self.root), "evidence path escapes bundle")
        data = target.read_bytes()
        require(len(data) <= 8_000_000, "evidence artifact bound exceeded")
        require(
            hashlib.sha256(data).hexdigest() == entry["sha256"], "evidence hash differs"
        )
        return data

    def read(self, name: str) -> Any:
        return json.loads(self.raw(name))


# A dynamic JSON number can lose precision in the Azure query response. For
# positive nonintegral doubles, transfer the stored binary value as two native
# integers. A power two bits below log2 leaves room for rounding near a power
# boundary. Clamping at the smallest normal power also covers subnormal values.
METRIC_VALUE_PROJECTION = (
    '| extend M78Value = iff(Kind == "metric" and gettype(Payload.value) == "real", '
    'todouble(Payload.value), real(null)) '
    '| extend M78Scale = iff(M78Value > 0 and M78Value != bin(M78Value, 1.0), '
    'max_of(long(-1022), tolong(log2(M78Value)) - long(2)), long(null)) '
    '| extend NativeMetricExponent = M78Scale - 52, '
    'NativeMetricSignificand = tolong((M78Value / pow(2.0, M78Scale)) * 4503599627370496.0) '
    '| extend Payload = iff(isnotnull(M78Scale), bag_remove_keys(Payload, dynamic(["value"])), Payload) '
    '| project-away M78Value, M78Scale'
)


def native_payload(row: dict) -> dict:
    payload = row["Payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    require(("NativeMetricExponent" in row) == ("NativeMetricSignificand" in row),
            "incomplete native metric encoding")
    exponent, significand = row.get("NativeMetricExponent"), row.get("NativeMetricSignificand")
    if exponent is None and significand is None:
        return payload
    require(
        row["Kind"] == "metric" and isinstance(payload, dict) and "value" not in payload
        and type(exponent) is int and -1074 <= exponent <= 0
        and type(significand) is int and 0 < significand < 2**56
        and int(float(significand)) == significand,
        "invalid native metric encoding",
    )
    value = math.ldexp(float(significand), exponent)
    numerator, denominator = value.as_integer_ratio()
    require(not value.is_integer() and numerator * (1 << -exponent) == significand * denominator,
            "inexact native metric encoding")
    return payload | {"value": value}


def validate_signal_row(
    row: dict,
    expected_sources: list[dict[str, str]],
    stamp: datetime,
    seen_ids: set[str],
) -> dict:
    """Reproduce the signed gateway's digest from one native destination row."""
    from scripts.telemetry_destination import DestinationError, destination_rows

    payload = native_payload(row)
    signal = {
        "schema_version": "mobius-operational-v1",
        "kind": row["Kind"],
        "name": row["Name"],
        "timestamp": row["TimeGenerated"],
        "component": row["Component"],
        "payload": payload,
        **{
            key: row[key.title()]
            for key in ("service", "environment", "release", "deployment")
        },
    }
    signal_id = row["SignalId"]

    def matches(candidate: dict) -> bool:
        timestamps = dict.fromkeys((signal["timestamp"], stamp.isoformat()))
        return any(
            destination_rows(
                {
                    "resource": {"schema": "mobius-operational-v1"},
                    "signals": [candidate | {"timestamp": timestamp}],
                },
                expected_sources,
                now=stamp,
            )[0]["SignalId"]
            == signal_id
            for timestamp in timestamps
        )

    try:
        valid = matches(signal)
        if not valid and signal["kind"] == "metric":
            value = payload["value"]
            # Azure may read back an integral float as an integer. Reconstruct
            # only this metric value, within the IEEE-754 safe integer range.
            if type(value) is int and abs(value) < 2**53:
                valid = matches(signal | {"payload": payload | {"value": float(value)}})
    except DestinationError as error:
        raise ValueError(
            "native destination signal violates privacy/schema/source contract"
        ) from error
    require(valid, "native signal content/identity differs")
    require(signal_id not in seen_ids, "query did not deduplicate native delivery")
    seen_ids.add(signal_id)
    return signal


def validate_signals(evidence: Evidence) -> dict:
    native = rows(evidence.read("production-signals"))
    if not native:
        raise MissingEvidence("no production destination signals")
    plan = evidence.plan
    expected_sources = plan["productionSources"]
    source_services = {source["service"] for source in expected_sources}
    require(
        {"mobius-api", "mobius-worker"}
        <= source_services
        <= {"mobius-api", "mobius-worker", "mobius-outbox"},
        "exact production source set required",
    )
    seen: set[tuple[str, str, str]] = set()
    spans = []
    signal_ids = set()
    for row in native:
        stamp = utc(row["TimeGenerated"])
        require(
            utc(evidence.manifest["startedAt"])
            <= stamp
            <= utc(evidence.manifest["completedAt"]),
            "signal outside actual observation window",
        )
        signal = validate_signal_row(row, expected_sources, stamp, signal_ids)
        seen.add((signal["service"], signal["kind"], signal["name"]))
        if signal["kind"] == "span":
            spans.append(signal)
    expected = {tuple(item) for item in plan["requiredProductionSignals"]}
    require(bool(expected), "expected production observations absent")
    missing = expected - seen
    if missing:
        raise MissingEvidence("production signals missing: " + str(sorted(missing)))
    api = [s for s in spans if s["service"] == "mobius-api"]
    worker = [s for s in spans if s["service"] == "mobius-worker"]
    api_contexts = {(s["payload"]["trace_id"], s["payload"]["span_id"]) for s in api}
    durable_links = {
        (link["trace_id"], link["span_id"], link["correlation"])
        for signal in api
        for link in signal["payload"]["links"]
        if link["correlation"] is not None
    }
    continuity = any(
        any(
            (link["trace_id"], link["span_id"]) in api_contexts
            for link in s["payload"]["links"]
        )
        or any(s["payload"]["trace_id"] == context[0] for context in api_contexts)
        or any(
            (link["trace_id"], link["span_id"], link["correlation"]) in durable_links
            for link in s["payload"]["links"]
        )
        for s in worker
    )
    if not continuity:
        raise MissingEvidence("actual API-to-worker trace continuity absent")
    return {
        "signals": len(native),
        "requiredSignals": len(expected),
        "traceContinuity": "accepted",
    }


def validate_rejection(evidence: Evidence) -> dict:
    records = evidence.read("gateway-negative-requests")
    expected = {"unauthenticated": 401, "wrong-source": 422, "private-content": 422}
    for kind, status in expected.items():
        record = records[kind]
        require(
            record["request"]["url"] == evidence.plan["gatewayUrl"],
            "negative request destination differs",
        )
        require(
            record["response"]["status"] == status,
            "gateway did not reject negative request",
        )
        require(
            record["request"]["bodySha256"]
            == evidence.plan["negativeRequestHashes"][kind],
            "negative fixture hash differs",
        )
    observed = rows(evidence.read("rejected-signal-absence"))
    require(
        len(observed) == 1 and observed[0].get("Count") == 0,
        "rejected source/private sentinel reached destination",
    )
    return {"rejected": sorted(expected), "destinationAbsence": "accepted"}


def validate_workbooks(evidence: Evidence) -> dict:
    catalog = compile_catalog(
        release=evidence.plan["release"],
        deployment=evidence.plan["deployment"],
        ceiling=evidence.plan["operatingCeilingUsd"],
        full_closure=True,
    )
    reviewed = evidence.read("workbook-render-review")
    require(
        reviewed["reviewerPrincipalId"] in evidence.plan["operatorPrincipalIds"],
        "render review lacks authorized operator",
    )
    count = 0
    for workbook in catalog["workbooks"]:
        identity = workbook["id"]
        rendering = reviewed["workbooks"].get(identity)
        if rendering is None:
            raise MissingEvidence("dashboard rendering absent: " + identity)
        image = evidence.raw("render-" + identity)
        require(
            image.startswith(b"\x89PNG\r\n\x1a\n"), "dashboard screenshot is not PNG"
        )
        require(
            rendering["screenshotSha256"] == hashlib.sha256(image).hexdigest(),
            "render review/image differ",
        )
        require(
            rendering["workbookResourceId"]
            == evidence.plan["workbookResourceIds"][identity],
            "rendered workbook scope differs",
        )
        require(
            rendering["reviewOutcome"] == "panels-visible-no-errors",
            "dashboard visual inspection failed",
        )
        for index, panel in enumerate(workbook["workbook"]["items"]):
            receipt = evidence.read(f"dashboard-{identity}-{index}")
            require(
                receipt["querySha256"]
                == hashlib.sha256(panel["content"]["query"].encode()).hexdigest(),
                "dashboard query differs from catalog",
            )
            values = rows(receipt)
            if not values or not any(
                value.get("Value") is not None for value in values
            ):
                raise MissingEvidence(
                    "dashboard panel has no actual samples: " + panel["name"]
                )
            count += 1
    return {"dashboards": len(catalog["workbooks"]), "panels": count}


def expected_alert_states(
    rule: dict, windows: list[dict], ceiling: float
) -> list[bool]:
    """Independent catalog semantics for native aggregate windows, without KQL eval."""
    name = rule["id"]
    firing = False
    bad = good = 0
    required = {
        "api-latency-v1": (2, 2),
        "database-saturation-v1": (2, 3),
        "storage-outage-v1": (2, 3),
        "scanner-outage-v1": (1, 1),
        "queue-backlog-v1": (2, 2),
        "worker-stale-v1": (2, 1),
        "limiter-outage-v1": (1, 1),
        "indexer-freshness-v1": (2, 2),
        "provider-degradation-v1": (2, 3),
        "outbox-backlog-v1": (2, 2),
        "evidence-integrity-v1": (1, 1),
        "telemetry-loss-v1": (1, 1),
        "backup-freshness-v1": (1, 1),
        "capacity-v1": (3, 3),
        "cost-v1": (1, 1),
        "readiness-v1": (1, 1),
    }
    result = []
    for window in windows:
        force = False
        if not window.get("Presence"):
            if rule["missingData"] == "hold":
                result.append(firing)
                continue
            breach, healthy = True, False
        else:
            v, t, f, n = (window.get(key, 0) or 0 for key in ("V", "T", "F", "N"))
            if name == "api-latency-v1":
                breach, healthy = v >= 1000, v < 750
            elif name == "database-saturation-v1":
                breach, healthy = v >= 500 or t > 0, v < 250 and t == 0
            elif name in {"storage-outage-v1", "provider-degradation-v1"}:
                require(n > 0, "rate denominator absent")
                breach, healthy = f / n >= 0.05, f / n < 0.01
            elif name == "scanner-outage-v1":
                breach, healthy = v >= 1, v == 0 and window.get("H", 0) >= 3
            elif name == "queue-backlog-v1":
                breach, healthy = v >= 300, v < 120
            elif name == "worker-stale-v1":
                breach, healthy = v == 0, v >= 2
            elif name == "limiter-outage-v1":
                decisions = window.get("Decisions", [])
                breach, healthy = (
                    v < 1,
                    len(decisions) >= 3 and decisions[-3:] == [1, 1, 1],
                )
            elif name == "indexer-freshness-v1":
                breach, healthy = (
                    v >= 900 or window.get("D", 0) > 0,
                    v < 300 and window.get("D", 0) == 0,
                )
            elif name == "outbox-backlog-v1":
                breach, healthy, force = v >= 300 or t > 0, v < 120 and t == 0, t > 0
            elif name == "evidence-integrity-v1":
                breach, healthy = v > 0, False
            elif name == "telemetry-loss-v1":
                health = window.get("H", [])
                breach = window.get("D", 0) >= 1 or f >= 3
                healthy = (
                    len(health) >= 3
                    and health[-3:] == [1, 1, 1]
                    and window.get("B") == 0
                )
            elif name in {"backup-freshness-v1", "cost-v1"}:
                values = window.get("Values", [])
                require(bool(values), "latest provider observation absent")
                breach = values[-1] >= (
                    86400 if name == "backup-freshness-v1" else ceiling * 0.8
                )
                healthy = values[-1] < (
                    86400 if name == "backup-freshness-v1" else ceiling * 0.7
                )
            elif name == "capacity-v1":
                breach, healthy = v >= 0.8, v < 0.65
            elif name == "readiness-v1":
                statuses = window.get("S", [])
                breach, healthy = (
                    f >= 3,
                    len(statuses) >= 3 and statuses[-3:] == [200, 200, 200],
                )
            else:
                raise ValueError("uncatalogued alert")
        bad, good = (bad + 1 if breach else 0), (good + 1 if healthy else 0)
        if force or breach and bad >= required[name][0]:
            firing = True
        elif healthy and good >= required[name][1]:
            firing = False
        result.append(firing)
    return result


def validate_alerts(evidence: Evidence) -> dict:
    catalog = json.loads((ROOT / "docs/observability/alerts-v1.json").read_text())
    scenarios = evidence.read("alert-scenarios")
    delivery = evidence.read("native-alert-events")
    accepted = []
    for rule in catalog["alerts"]:
        name = rule["id"]
        scenario = scenarios.get(name)
        if scenario is None:
            raise MissingEvidence("required alert scenario absent: " + name)
        require(
            scenario["stimulusClass"]
            in {"production-operation", "native-provider-observation"},
            "synthetic metric injection does not close producer/alert acceptance",
        )
        evidence.raw(scenario["stimulusEvidence"])
        windows = rows(evidence.read("alert-windows-" + name))
        if not windows:
            raise MissingEvidence("native alert evaluation windows absent: " + name)
        expected = expected_alert_states(
            rule, windows, evidence.plan["operatingCeilingUsd"]
        )
        require(
            [row["Firing"] for row in windows] == expected,
            "native rule differs from catalog timing/threshold semantics: " + name,
        )
        if not any(expected):
            raise MissingEvidence("no expected production breach: " + name)
        if name != "evidence-integrity-v1" and expected[-1]:
            raise MissingEvidence("catalog recovery not observed: " + name)
        native = []
        for item in delivery:
            payload = item["native"]
            require(
                payload.get("schemaId") == "azureMonitorCommonAlertSchema",
                "non-native alert payload",
            )
            essentials = payload["data"]["essentials"]
            if essentials["alertRule"] != evidence.plan["alertRuleNames"][name]:
                continue
            require(
                essentials["alertTargetIDs"] == [evidence.plan["workspaceResourceId"]],
                "alert target differs",
            )
            require(
                utc(scenario["startedAt"])
                <= utc(item["enqueuedTime"])
                <= utc(scenario["endedAt"]),
                "alert outside stimulus window",
            )
            native.append(essentials)
        fired = [item for item in native if item["monitorCondition"] == "Fired"]
        if not fired:
            raise MissingEvidence("native Fired absent: " + name)
        if name == "evidence-integrity-v1":
            closure = evidence.read("integrity-authorized-closure")
            require(
                closure["operatorPrincipalId"] in evidence.plan["operatorPrincipalIds"],
                "integrity closure operator not authorized",
            )
            require(
                closure["authorizationSha256"]
                in evidence.plan["integrityClosureAuthorities"],
                "integrity investigation authority absent",
            )
            require(
                closure["findingEvidenceSha256"] == scenario["findingEvidenceSha256"],
                "closed a different finding",
            )
            action = closure["nativeAlertStateChange"]
            require(
                action["response"]["status"] == 200
                and action["response"]["body"]["properties"]["essentials"]["alertState"]
                == "Closed",
                "native authorized alert closure absent",
            )
            require(
                action["request"]["alertId"] in {item["alertId"] for item in fired},
                "closed unrelated native alert",
            )
            require(
                utc(action["at"]) >= min(utc(item["firedDateTime"]) for item in fired),
                "closure preceded finding",
            )
        else:
            resolved = [
                item for item in native if item["monitorCondition"] == "Resolved"
            ]
            pairs = [
                (f, r)
                for f in fired
                for r in resolved
                if f["alertId"] == r["alertId"]
                and utc(r["resolvedDateTime"]) >= utc(f["firedDateTime"])
            ]
            if not pairs:
                raise MissingEvidence(
                    "matching native Fired/Resolved pair absent: " + name
                )
            evidence.raw(scenario["recoveryEvidence"])
        accepted.append(name)
    return {"alerts": accepted, "integrityRecovery": "authorized-investigation-only"}


def validate_outage(evidence: Evidence) -> dict:
    scenario = evidence.read("exporter-outage")
    require(
        scenario["targetResourceId"] == evidence.plan["gatewayResourceId"],
        "outage target differs",
    )
    require(
        scenario["outageSeconds"] <= evidence.plan["outageMaxSeconds"],
        "outage exceeded authority",
    )
    before, failed, recovered = [scenario[key] for key in ("before", "during", "after")]
    require(
        before["readyStatus"] == recovered["readyStatus"] == 200
        and failed["readyStatus"] == 503,
        "readiness did not fail and recover",
    )
    require(
        failed["operator"]["dependencies"]["telemetry"]
        in {"unavailable", "indeterminate"},
        "outage not attributed to telemetry",
    )
    cap = evidence.plan["telemetryBufferLimit"]
    require(
        all(
            0 <= item["operator"]["telemetryBuffered"] <= cap
            for item in (before, failed, recovered)
        ),
        "export buffer exceeded configured bound",
    )
    require(
        failed["operator"]["telemetryDropped"] > before["operator"]["telemetryDropped"],
        "bounded loss not exercised",
    )
    require(
        recovered["operator"]["telemetryBuffered"] == 0, "export buffer not drained"
    )
    require(
        recovered["operator"]["dependencies"]["telemetry"] == "healthy",
        "exporter not healthy after restoration",
    )
    evidence.raw(scenario["nativeStopReceipt"])
    evidence.raw(scenario["nativeStartReceipt"])
    return {"outageSeconds": scenario["outageSeconds"], "bufferBound": cap}


def validate_access(evidence: Evidence) -> dict:
    observations = evidence.read("destination-access")
    for role in ("api", "worker", "gateway"):
        require(
            observations[role]["queryStatus"] in (401, 403),
            "export/scanner role can read operational destination",
        )
        require(
            observations[role]["principalId"] == evidence.plan["principalIds"][role],
            "query tested wrong principal",
        )
    for role in ("operator", "evidence"):
        item = observations[role]
        require(
            item["principalId"] == evidence.plan["principalIds"][role],
            "read/revoke tested wrong principal",
        )
        require(
            [item[key]["queryStatus"] for key in ("before", "revoked", "restored")]
            == [200, 403, 200],
            "read/revocation/recovery not observed",
        )
        sessions = [
            item[key]["credentialSessionId"]
            for key in ("before", "revoked", "restored")
        ]
        require(
            len(set(sessions)) == 3, "fresh sessions required across access changes"
        )
        require(
            item["deletedAssignmentId"]
            == item["restoredAssignmentId"]
            == evidence.plan["queryAssignmentIds"][role],
            "revocation changed unrelated assignment",
        )
        require(
            item["nativeDeleteStatus"] in (200, 204)
            and item["nativeRestoreStatus"] in (200, 201),
            "native assignment mutation absent",
        )
    return {
        "exportOnly": ["api", "worker", "gateway"],
        "revocation": ["operator", "evidence"],
    }


def validate_retention(evidence: Evidence) -> dict:
    expected = {
        "MobiusApplication_CL": 30,
        "MobiusSecurity_CL": 90,
        "MobiusMetric_CL": 30,
        "MobiusSpan_CL": 14,
        "MobiusIncident_CL": 365,
    }
    native = evidence.read("retention-readbacks")
    for name, days in expected.items():
        result = native[name]
        require(result["status"] == 200, "retention native readback failed")
        body = result["body"]
        require(
            body["id"] == evidence.plan["workspaceResourceId"] + "/tables/" + name,
            "retention target differs",
        )
        require(
            body["properties"]["retentionInDays"] == days
            and body["properties"]["totalRetentionInDays"] == days,
            "retention differs from approved class",
        )
    workspace = native["workspace"]
    require(
        workspace["status"] == 200
        and workspace["body"]["id"] == evidence.plan["workspaceResourceId"],
        "workspace retention binding differs",
    )
    require(
        workspace["body"]["properties"]["features"]["immediatePurgeDataOn30Days"]
        is True,
        "30-day purge setting absent",
    )
    return {
        "configuredRetentionDays": expected,
        "physicalExpiryObservation": "not inferred from configuration",
    }


VALIDATORS = {
    "production-signals-traces-privacy": validate_signals,
    "source-auth-private-rejection": validate_rejection,
    "all-dashboard-rendering": validate_workbooks,
    "all-alert-firing-recovery": validate_alerts,
    "exporter-outage-readiness": validate_outage,
    "destination-access-revocation": validate_access,
    "configured-retention": validate_retention,
}


def reconcile(manifest: Path, plan: dict) -> dict:
    evidence = Evidence(manifest, plan)
    assertions = {}
    for name, validator in VALIDATORS.items():
        try:
            assertions[name] = {"status": "accepted", "result": validator(evidence)}
        except (MissingEvidence, FileNotFoundError) as error:
            assertions[name] = {"status": "unproved", "reason": str(error)}
        except (ValueError, KeyError, TypeError) as error:
            assertions[name] = {"status": "failed", "reason": str(error)}
    return {
        "schema": "m78-destination-acceptance-v1",
        "sourceCommit": plan["sourceCommit"],
        "imageDigest": plan["imageDigest"],
        "executionIds": evidence.manifest["executionIds"],
        "assertions": assertions,
        "cleanupRequired": True,
        "areaClosed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.manifest, json.loads(args.plan.read_text(encoding="utf-8")))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()

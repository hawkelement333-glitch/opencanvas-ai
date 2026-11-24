"""Bounded pilot destination probes; prepare/help are strictly offline.

Live operations require a byte-bound package, separate recorded authorization,
an exact ACA execution ID, destination bindings and unexpired relative windows.
No provisioning, image building, broad discovery or closed-campaign replay.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from infra.milestone_7_8.pilot_alerts import ROOT, bound, compile_catalog

VERSION = "m78-pilot-destination-probe-v1"
SCANNER_PENDING_MARKER = "M78-SCANNER-PENDING:"
CORE_DIAGNOSTIC_SCOPE = "one-primary-scanner-diagnostic-v1"
SCANNER_OBSERVATION = {
    "fixture": "primary",
    "maximumExecutions": 1,
    "publishWhenSecondsRemaining": 900,
    "minimumDispatchSecondsRemaining": 135,
}
OPERATIONS = ("query", "telemetry", "alerts", "smtp", "provider-observation")
DELIVERY_OPERATIONS = (
    "password-reset-request",
    "password-reset-confirm",
    "password-reset-expiry",
    "activity-delivery-happy",
    "activity-delivery-lost-ack",
    "activity-delivery-stale",
    "activity-delivery-outage",
    "activity-delivery-final-recovery",
    "activity-delivery-delay",
    "activity-delivery-partial-response",
    "activity-delivery-retry-load",
    "activity-delivery-network-delay",
)
INTERVENTION_OPERATIONS = ("queue-grant-outage", "queue-grant-restore")
APPLICATION_OPERATIONS = (
    "account",
    "core",
    "workload",
    "capacity",
    "integrity",
    "telemetry-queue",
    "restore-snapshot",
    "restore-verify",
    "restore-fixture",
    "restore-fence",
    "restore-role",
    "restore-resume",
    "restore-rollback",
)
TABLES = {
    "application_log": "MobiusApplication_CL",
    "security_log": "MobiusSecurity_CL",
    "metric": "MobiusMetric_CL",
    "span": "MobiusSpan_CL",
    "incident": "MobiusIncident_CL",
}


class TransportError(ValueError):
    def __init__(self, stage: str, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.diagnostic = {"stage": stage, "code": code}
        if status is not None:
            self.diagnostic["httpStatus"] = status


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def prepare(
    output: Path,
    release: str,
    deployment: str,
    ceiling: float,
    *,
    full_closure: bool = False,
) -> dict[str, Any]:
    catalog = compile_catalog(
        release=release,
        deployment=deployment,
        ceiling=ceiling,
        full_closure=full_closure,
    )
    paths = [
        "infra/milestone_7_8/pilot_validation.py",
        "infra/milestone_7_8/pilot_alerts.py",
        "infra/milestone_7_8/pilot_observability.bicep",
        "infra/milestone_7_8/pilot/probe-requirements.txt",
        "infra/milestone_7_8/pilot.bicep",
        "infra/milestone_7_8/pilot_runtime.bicep",
        "infra/milestone_7_8/managed_objects.bicep",
        "infra/milestone_7_8/pilot/artifact_transport.py",
        "infra/milestone_7_8/pilot/pack_execution.py",
        "infra/milestone_7_8/signup_reconcile.py",
        "apps/api/scripts/telemetry_gateway.py",
        "apps/api/scripts/telemetry_destination.py",
        "docs/MILESTONE_7_8_PILOT_MANAGED_VALIDATION_PACKAGE.md",
        "docs/MILESTONE_7_8_PILOT_EXECUTION_COMMANDS.md",
        "docs/MILESTONE_7_8_PILOT_COST_MODEL.md",
        "docs/observability/alerts-v1.json",
        "docs/observability/dashboards-v1.json",
        "docs/observability/signals-v1.json",
    ]
    closure_paths = [
        "infra/milestone_7_8/operator_access_package.py",
        "infra/milestone_7_8/pilot_operator_access.bicep",
        "docs/MILESTONE_7_8_OPERATOR_ACCESS_EXECUTION.md",
        "infra/milestone_7_8/destination_acceptance.py",
        "infra/milestone_7_8/capacity_validation.py",
        "infra/milestone_7_8/capacity_fixtures.py",
        "infra/milestone_7_8/pilot_recovery_acceptance.py",
        "infra/milestone_7_8/password_reset_validation.py",
        "infra/milestone_7_8/activity_delivery_validation.py",
        "infra/milestone_7_8/queue_grant_intervention.py",
        "infra/milestone_7_8/operational_service_probe.py",
        "infra/milestone_7_8/pilot/full_closure_interventions.json",
        "infra/milestone_7_8/pilot/helper_job_patch.py",
        "apps/api/scripts/operational_observer.py",
        "apps/api/opencanvas_api/services/operational_observations.py",
        "apps/api/opencanvas_api/services/evidence_observer.py",
        "apps/api/opencanvas_api/services/outbox_dispatcher.py",
        "apps/api/scripts/activity_receiver.py",
        "apps/api/scripts/outbox_worker.py",
        "docs/MILESTONE_7_8_FULL_CLOSURE_VALIDATORS.md",
    ]
    if full_closure:
        if any(not (ROOT / path).is_file() for path in closure_paths):
            raise ValueError("full closure source/validator package is incomplete")
        paths.extend(closure_paths)
    application_probe = "infra/milestone_7_8/pilot_application_probe.py"
    if (ROOT / application_probe).exists():
        paths.append(application_probe)
    write_new(output / "catalog.json", catalog)
    manifest = {
        "schema": VERSION,
        "release": release,
        "deployment": deployment,
        "sourceBindings": {path: digest(ROOT / path) for path in paths},
        "catalogSha256": digest(output / "catalog.json"),
        "relativeWindowHours": (
            {"provisionBy": 2, "readyBy": 2, "stopProof": 10, "cleanupBy": 12}
            if full_closure
            else {"provisionBy": 2, "stopProof": 8, "cleanupBy": 10}
        ),
        "operations": list(
            (
                *OPERATIONS,
                *APPLICATION_OPERATIONS,
                *(DELIVERY_OPERATIONS if full_closure else ()),
                *(INTERVENTION_OPERATIONS if full_closure else ()),
            )
        ),
        "fullClosure": full_closure,
        "managedAcceptance": "unproved",
        "closedCampaigns": ["PostgreSQL", "M78-D-001", "M78-D-002"],
        "requirements": [
            "M78-D-003",
            "M78-D-004 enabled provider observations",
            "M78-D-007",
            "M78-D-005 four affected restore assertions",
            "M78-D-006 bounded workload and current release",
        ],
        "remainingBindings": [
            "exact deployment outputs",
            "candidate image digest",
            "actual source commit",
            "separate spending authorization",
            "SMTP provider",
            "OpenAI provider credentials",
            "operator identity",
            "controller cleanup binding",
        ],
    }
    write_new(output / "manifest.json", manifest)
    return manifest


def prepare_verification_queries(bundle: Path, output: Path) -> dict:
    """Export the sealed deployment catalog and its matching local KQL without I/O to Azure."""
    output = output.resolve()
    review_path = bundle / "review-package.json"
    review = json.loads(review_path.read_bytes())
    sources = {}
    for name in (
        "manifest.json", "planned-bindings.json", "destination-plan.bound.json",
        "catalog.json", "parameters.bound.json",
    ):
        path = bundle / name
        if digest(path) != review["files"][name]:
            raise ValueError("verification source differs from the sealed package")
        sources[name] = json.loads(path.read_bytes())
    manifest = sources["manifest.json"]
    plan = sources["planned-bindings.json"]
    destination = sources["destination-plan.bound.json"]
    arm = sources["parameters.bound.json"]["parameters"]
    previous = sources["catalog.json"]
    current = arm["catalog"]["value"]
    release, deployment = bound(plan["release"]), bound(plan["deployment"])
    if (
        any(record["release"] != release for record in (manifest, destination, current))
        or any(record["deployment"] != deployment for record in (
            manifest, destination, previous, current,
        ))
        or arm["release"]["value"] != release
        or manifest["catalogSha256"] != review["files"]["catalog.json"]
    ):
        raise ValueError("verification release/deployment bindings disagree")

    old_filter = f'Release == "{bound(previous["release"])}" and Deployment == "{deployment}"'
    new_filter = f'Release == "{release}" and Deployment == "{deployment}"'

    def replace_filter(query: str) -> str:
        if query.count(old_filter) != 1:
            raise ValueError("one exact catalog release predicate required")
        return query.replace(old_filter, new_filter, 1)

    def queries(catalog: dict) -> dict[str, str]:
        return {
            **{
                f"catalog-workbooks-{i}-workbook-items-{j}-content-query.kql":
                panel["content"]["query"]
                for i, workbook in enumerate(catalog["workbooks"])
                for j, panel in enumerate(workbook["workbook"]["items"])
            },
            **{
                f"catalog-alerts-{i}-{field}.kql": alert[field]
                for i, alert in enumerate(catalog["alerts"])
                for field in ("query", "observationQuery")
            },
        }

    # A full comparison also guards alert thresholds, cadence, and recovery windows.
    old_queries = queries(previous)
    current_queries = queries(current)
    if (
        {name: replace_filter(query) for name, query in old_queries.items()} != current_queries
        or json.loads(json.dumps(previous).replace(previous["release"], release)) != current
    ):
        raise ValueError("the sealed catalogs differ beyond the release binding")

    prior_unbound_queries = []
    output_queries = {}
    for name in sorted(review["files"]):
        if not name.startswith("queries/") or not name.endswith(".kql"):
            continue
        path = bundle / name
        sha = digest(path)
        if sha != review["files"][name]:
            raise ValueError("verification query differs from the sealed package")
        data = path.read_bytes()
        text = path.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() not in plan["approvedQueryHashes"]:
            prior_unbound_queries.append(name)
        if path.name in current_queries:
            if text.strip() != old_queries[path.name].strip():
                raise ValueError("sealed query differs from its catalog entry")
            data = data.replace(old_filter.encode(), new_filter.encode(), 1)
        elif old_filter.encode() in data:
            data = replace_filter(data.decode("utf-8")).encode("utf-8")
        output_queries[name] = data
    if not all(f"queries/{name}" in output_queries for name in current_queries):
        raise ValueError("sealed verification query inventory differs")

    output.mkdir(parents=True, exist_ok=False)
    (output / "queries").mkdir()
    for name, data in output_queries.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    write_new(output / "catalog.json", current)
    receipt = {
        "release": release,
        "deployment": deployment,
        "sourceReviewSha256": digest(review_path),
        "catalogSha256": digest(output / "catalog.json"),
        "querySha256": {name: digest(output / name) for name in output_queries},
        "approvedQueryHashes": sorted({
            hashlib.sha256((output / name).read_text(encoding="utf-8").encode()).hexdigest()
            for name in output_queries
        }),
        "priorQueryAuthorizationMismatches": prior_unbound_queries,
        "classification": "local-verification-inputs",
    }
    write_new(output / "verification-queries.json", receipt)
    return receipt


def authorize(
    bundle: Path,
    approval_path: Path,
    bindings_path: Path,
    operation: str,
    now: datetime | None = None,
) -> tuple[dict, dict, datetime]:
    current = now or datetime.now(UTC)
    manifest = json.loads((bundle / "manifest.json").read_text())
    approval = json.loads(approval_path.read_text())
    bindings = json.loads(bindings_path.read_text())
    if (
        manifest.get("schema") != VERSION
        or approval.get("schema") != VERSION + "-approval"
    ):
        raise ValueError("unsupported package or approval")
    if approval.get("packageSha256") != digest(bundle / "manifest.json"):
        raise ValueError("approval does not bind this package")
    if bindings.get("sha256") is not None:
        raise ValueError("binding digest must be external, not self-asserted")
    if approval.get("bindingsSha256") != digest(bindings_path):
        raise ValueError("approval does not bind exact destinations")
    if (
        operation not in manifest["operations"]
        or operation not in approval.get("operations", [])
        or approval.get("approved") is not True
    ):
        raise ValueError("operation not authorized")
    if digest(bundle / "catalog.json") != manifest["catalogSha256"]:
        raise ValueError("catalog changed after preparation")
    catalog = json.loads((bundle / "catalog.json").read_bytes())
    if any(catalog.get(key) != manifest[key] for key in ("release", "deployment")):
        raise ValueError("verification catalog differs from the package release/deployment")
    for path, expected in manifest["sourceBindings"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("bound source changed after preparation")
    start = utc(approval["approvedAt"])
    deadline = start + timedelta(hours=manifest["relativeWindowHours"]["stopProof"])
    if operation in {"account", "core"} and manifest["relativeWindowHours"].get("readyBy") == 3:
        deadline = min(deadline, start + timedelta(hours=3))
    if not start <= current < deadline:
        raise ValueError("proof authority is not current")
    if approval.get("targetResourceGroupId") != bindings.get("targetResourceGroupId"):
        raise ValueError("target scope mismatch")
    scope = bindings.get("targetResourceGroupId", "")
    if (
        re.fullmatch(
            r"/subscriptions/[a-f0-9-]{36}/resourceGroups/rg-m78-[a-f0-9]{10}-target",
            scope,
        )
        is None
    ):
        raise ValueError("isolated target group required")
    for key in (
        "workspaceResourceId",
        "dcrResourceId",
        "actionGroupId",
        "eventHubResourceId",
    ):
        if (
            not str(bindings.get(key, ""))
            .lower()
            .startswith(scope.lower() + "/providers/")
        ):
            raise ValueError("destination outside approved group")
    if (
        bindings.get("release") != manifest["release"]
        or bindings.get("deployment") != manifest["deployment"]
    ):
        raise ValueError("release/deployment mismatch")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", bindings.get("imageDigest", "")) is None:
        raise ValueError("immutable image binding required")
    if re.fullmatch(r"[a-f0-9]{40}", bindings.get("sourceCommit", "")) is None:
        raise ValueError("exact source commit required")
    return manifest, bindings, deadline


def _private_host(host: str) -> list[str]:
    addresses = sorted(
        {
            str(entry[4][0])
            for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    )
    if not addresses or any(
        not ipaddress.ip_address(address).is_private for address in addresses
    ):
        raise ValueError("private destination DNS not proved")
    return addresses


def provider_requests_for_approval(bindings: dict, approval: dict) -> list[dict]:
    """Resolve only approved UTC calendar-day slots for the temporary forecast.

    Native Daily forecast rows cover complete days, not an asserted hourly bill.
    Other request fields remain byte-equivalent to the source-bound plan.
    """
    start = utc(approval["approvedAt"])
    end = start + timedelta(hours=bindings["relativeWindowHours"]["cleanupBy"])
    slots = {
        "${APPROVAL_DAY_UTC}": start.strftime("%Y-%m-%dT00:00:00+00:00"),
        "${CLEANUP_DAY_UTC}": end.strftime("%Y-%m-%dT23:59:59+00:00"),
    }
    raw = json.dumps(bindings.get("providerObservationRequests", []), sort_keys=True)
    for marker, value in slots.items():
        raw = raw.replace(marker, value)
    if "${" in raw:
        raise ValueError("unknown provider request binding slot")
    return json.loads(raw)


def admit_runtime_bindings(plan: dict, readbacks: dict, *, plan_sha256: str) -> dict:
    """Derive provider-assigned addresses from exact approved ARM GET records.

    This is not a substitute for recording the actual approved GET operations.
    No runtime address, identity or image may be supplied by a free-form override.
    """
    if readbacks.get("planSha256") != plan_sha256:
        raise ValueError("readbacks do not bind the approved plan")
    records = readbacks.get("resources")
    if not isinstance(records, list) or len(records) > 16:
        raise ValueError("bounded native resource readbacks required")
    admitted: dict[str, dict] = {}
    versions = {
        "workspaceResourceId": "2023-09-01",
        "dcrResourceId": "2023-03-11",
        "dceResourceId": "2023-03-11",
        "applicationResourceId": "2025-01-01",
        "gatewayResourceId": "2025-01-01",
        "managedEnvironmentResourceId": "2025-01-01",
    }
    if plan.get("frontendResourceId"):
        versions["frontendResourceId"] = "2025-01-01"
    scope = plan["targetResourceGroupId"]
    for key, api_version in versions.items():
        expected = plan.get(key, "")
        if not expected.lower().startswith(scope.lower() + "/providers/"):
            raise ValueError("runtime resource is outside approved target")
        matches = [
            record
            for record in records
            if record.get("request", {}).get("resourceId", "").lower()
            == expected.lower()
        ]
        if len(matches) != 1:
            raise ValueError("exactly one native readback per resource required")
        record = matches[0]
        request, response = record["request"], record["response"]
        if (
            request.get("method") != "GET"
            or request.get("apiVersion") != api_version
            or response.get("status") != 200
        ):
            raise ValueError("unaccepted native readback")
        body = response.get("body", {})
        if body.get("id", "").lower() != expected.lower():
            raise ValueError("provider returned another resource")
        admitted[key] = body
    environment = admitted["managedEnvironmentResourceId"]["properties"]
    if environment.get("vnetConfiguration", {}).get("internal") is not True:
        raise ValueError("managed proof environment must be internal")
    domain = environment["defaultDomain"]
    if re.fullmatch(r"[a-z0-9.-]+\.azurecontainerapps\.io", domain) is None:
        raise ValueError("unexpected provider environment domain")
    result = dict(plan)
    applications = [
        ("applicationResourceId", "apiBaseUrl", "imageDigest"),
        ("gatewayResourceId", "gatewayUrl", "imageDigest"),
    ]
    if "frontendResourceId" in admitted:
        applications.append(("frontendResourceId", "frontendOrigin", "frontendImageDigest"))
    for key, result_key, image_key in applications:
        properties = admitted[key]["properties"]
        environment_id = properties.get(
            "environmentId", properties.get("managedEnvironmentId", "")
        )
        if environment_id.lower() != plan["managedEnvironmentResourceId"].lower():
            raise ValueError("application moved outside bound environment")
        fqdn = properties["configuration"]["ingress"]["fqdn"]
        name = plan[key].rsplit("/", 1)[-1]
        if fqdn not in (f"{name}.{domain}", f"{name}.internal.{domain}"):
            raise ValueError("application FQDN is not provider-bound")
        containers = properties["template"]["containers"]
        if not containers or any(
            not str(item.get("image", "")).endswith("@" + plan[image_key])
            for item in containers
        ):
            raise ValueError("application image differs from approved digest")
        if properties["configuration"]["ingress"].get("allowInsecure", False):
            raise ValueError("application accepts insecure ingress")
        result[result_key] = (
            "https://" + fqdn + ("/v1/signals" if key == "gatewayResourceId" else "")
        )
    workspace = admitted["workspaceResourceId"]["properties"]
    if (
        workspace.get("publicNetworkAccessForQuery") != "Disabled"
        or workspace.get("publicNetworkAccessForIngestion") != "Disabled"
    ):
        raise ValueError("workspace public access is enabled")
    result["workspaceCustomerId"] = workspace["customerId"]
    if re.fullmatch(r"[a-fA-F0-9-]{36}", result["workspaceCustomerId"]) is None:
        raise ValueError("workspace customer ID is invalid")
    rule = admitted["dcrResourceId"]["properties"]
    if rule["dataCollectionEndpointId"].lower() != plan["dceResourceId"].lower():
        raise ValueError("data collection endpoint changed")
    destinations = rule["destinations"]["logAnalytics"]
    if (
        set(rule["destinations"]) != {"logAnalytics"}
        or len(destinations) != 1
        or destinations[0]["workspaceResourceId"].lower()
        != plan["workspaceResourceId"].lower()
    ):
        raise ValueError("data collection destination changed")
    result["dcrImmutableId"] = rule["immutableId"]
    if re.fullmatch(r"dcr-[a-f0-9]{32}", result["dcrImmutableId"]) is None:
        raise ValueError("data collection immutable ID is invalid")
    endpoint = admitted["dceResourceId"]["properties"]
    if endpoint.get("networkAcls", {}).get("publicNetworkAccess") != "Disabled":
        raise ValueError("data collection endpoint is public")
    result["dceEndpoint"] = endpoint["logsIngestion"]["endpoint"]
    from urllib.parse import urlparse

    ingestion = urlparse(result["dceEndpoint"])
    if (
        ingestion.scheme != "https"
        or not ingestion.hostname
        or not ingestion.hostname.endswith(".ingest.monitor.azure.com")
        or ingestion.username
        or ingestion.query
        or ingestion.fragment
        or ingestion.port not in (None, 443)
    ):
        raise ValueError("data collection endpoint URL is invalid")
    namespace = plan["eventHubResourceId"].split("/namespaces/", 1)[1].split("/", 1)[0]
    if re.fullmatch(r"eh-m78p-[a-f0-9]{10}", namespace) is None:
        raise ValueError("alert namespace mismatch")
    result["eventHubNamespace"] = namespace + ".servicebus.windows.net"
    if "frontendOrigin" in result and "passwordResetProof" in plan:
        expected_origin = plan["passwordResetProof"].get("appOrigin")
        if expected_origin not in {"${admittedFrontendOrigin}", result["frontendOrigin"]}:
            raise ValueError("password-reset frontend origin differs from native readback")
        result["passwordResetProof"] = {
            **plan["passwordResetProof"], "appOrigin": result["frontendOrigin"],
        }
    return result


async def _identity_token(resource: str) -> str:
    import httpx

    if resource not in {"https://api.loganalytics.io/", "https://eventhubs.azure.net/"}:
        raise ValueError("token audience not permitted")
    endpoint = os.environ["IDENTITY_ENDPOINT"]
    from urllib.parse import urlparse

    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "169.254.169.254",
    }:
        raise ValueError("managed identity endpoint is invalid")
    async with httpx.AsyncClient(
        timeout=5, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.get(
            endpoint,
            params={
                "api-version": "2019-08-01",
                "resource": resource,
                "client_id": os.environ["AZURE_CLIENT_ID"],
            },
            headers={"X-IDENTITY-HEADER": os.environ["IDENTITY_HEADER"]},
        )
        response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("managed identity token missing")
    return token


async def query(bindings: dict, kql: str) -> dict:
    import httpx

    workspace = bindings["workspaceCustomerId"]
    if re.fullmatch(r"[a-fA-F0-9-]{36}", workspace) is None:
        raise ValueError("invalid workspace binding")
    addresses = _private_host("api.loganalytics.io")
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.post(
            f"https://api.loganalytics.io/v1/workspaces/{workspace}/query",
            headers={
                "Authorization": "Bearer "
                + await _identity_token("https://api.loganalytics.io/")
            },
            json={"query": kql, "timespan": "P2D"},
        )
    if response.status_code != 200:
        return {
            "status": response.status_code,
            "privateAddresses": addresses,
            "errorBodySha256": hashlib.sha256(response.content).hexdigest(),
        }
    return {"status": 200, "privateAddresses": addresses, "result": response.json()}


async def telemetry(bindings: dict, deadline: datetime) -> dict:
    from urllib.parse import urlparse

    import httpx
    from pydantic import SecretStr
    from scripts.telemetry_destination import destination_rows

    from opencanvas_api.services.observability import (
        InMemoryTelemetrySink,
        OperationalTelemetry,
        Severity,
    )

    source = bindings["probeTelemetrySource"]
    if (
        source["release"] != bindings["release"]
        or source["deployment"] != bindings["deployment"]
    ):
        raise ValueError("probe source is not bound to the deployed release")
    endpoint = bindings["gatewayUrl"]
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("verified TLS gateway required")
    try:
        addresses = _private_host(parsed.hostname)
    except (ValueError, OSError) as error:
        raise TransportError("gateway-dns", "private-resolution-unproved") from error
    sink = InMemoryTelemetrySink()
    telemetry_client = OperationalTelemetry(
        service=source["service"],
        environment=source["environment"],
        release=source["release"],
        deployment=source["deployment"],
        pseudonymization_secret=SecretStr(
            "synthetic-probe-hmac-not-an-application-secret"
        ),
        sink=sink,
        enabled=True,
        batch_size=64,
        buffer_size=64,
        export_timeout_seconds=1,
        retry_limit=0,
        shutdown_timeout_seconds=1,
        sample_ratio=1,
        max_span_depth=16,
        max_span_events=16,
        max_span_attributes=16,
        failure_threshold=3,
        cardinality_budget=128,
        baggage_allowlist=(),
    )
    telemetry_client.emit_log(
        event_name="integrity.check.completed",
        severity=Severity.INFO,
        component="telemetry",
        fields={"operation": "pilot_transport", "outcome": "success"},
    )
    telemetry_client.emit_log(
        event_name="security.control.triggered",
        severity=Severity.WARNING,
        component="telemetry",
        fields={"operation": "pilot_transport", "outcome": "denied"},
        security=True,
    )
    telemetry_client.record_metric(
        "mobius.queue.depth", 0, labels={"component": "queue", "outcome": "success"}
    )
    span = telemetry_client.start_span("http.server.request", component="api")
    span.end(outcome="success")
    await telemetry_client.flush()
    await telemetry_client.close()
    signals = [signal.as_dict() for signal in sink.signals]
    for signal in signals:
        signal["environment"] = source["environment"]
    payload = json.loads(
        json.dumps(
            {"resource": {"schema": "mobius-operational-v1"}, "signals": signals}
        )
    )
    expected = destination_rows(payload, [source])
    headers = {
        "Authorization": "Bearer " + os.environ["OPENCANVAS_TELEMETRY_GATEWAY_TOKEN"]
    }
    async with httpx.AsyncClient(
        timeout=6, follow_redirects=False, trust_env=False
    ) as client:
        # Native application schema sanitizer refuses content; the destination
        # also independently rejects a malicious authenticated producer.
        poisoned = json.loads(json.dumps(payload))
        poisoned["signals"][0]["payload"]["prompt"] = "M78_SYNTHETIC_PRIVATE_SENTINEL"
        for stage, body, auth, status in (
            ("gateway-unauthenticated", payload, {}, 401),
            ("gateway-forbidden-content", poisoned, headers, 422),
            ("gateway-valid-batch", payload, headers, 202),
        ):
            try:
                response = await client.post(endpoint, json=body, headers=auth)
            except httpx.HTTPError as error:
                raise TransportError(stage, "http-outcome-unproved") from error
            if response.status_code != status:
                raise TransportError(stage, "unexpected-http-status", response.status_code)
    ids = {row["SignalId"] for row in expected}
    id_list = ",".join(f'"{value}"' for value in sorted(ids))
    kql = (
        "union MobiusApplication_CL,MobiusSecurity_CL,MobiusMetric_CL,MobiusSpan_CL\n"
        f"| where SignalId in ({id_list})\n| summarize by SignalId"
    )
    stop = min(deadline, datetime.now(UTC) + timedelta(minutes=10))
    attempts = []
    while datetime.now(UTC) < stop:
        try:
            observed = await query(bindings, kql)
        except (KeyError, ValueError, OSError, httpx.HTTPError) as error:
            raise TransportError("destination-query", "query-outcome-unproved") from error
        attempts.append(
            {"at": datetime.now(UTC).isoformat(), "status": observed["status"]}
        )
        if observed["status"] == 200:
            try:
                native_result = observed["result"]
                if "error" in native_result:
                    raise ValueError("partial query result")
                (table,) = native_result["tables"]
                records = table["rows"]
                (column,) = table["columns"]
                if column["name"] != "SignalId" or not isinstance(records, list):
                    raise ValueError("invalid result shape")
                observed_ids = {signal_id for (signal_id,) in records}
                if len(records) != len(observed_ids) or not observed_ids <= ids:
                    raise ValueError("invalid signal IDs")
            except (KeyError, TypeError, ValueError) as error:
                raise TransportError(
                    "destination-query", "unexpected-signal-id-result", 200
                ) from error
            if observed_ids == ids:
                return {
                    "classification": "transport-fixture-only",
                    "privateAddresses": addresses,
                    "expectedRows": expected,
                    "destination": observed,
                    "polls": attempts,
                    "unauthenticatedStatus": 401,
                    "forbiddenContentStatus": 422,
                }
        elif observed["status"] in (401, 403):
            raise TransportError("destination-query", "operator-query-denied", observed["status"])
        await asyncio.sleep(min(10, max(0, (stop - datetime.now(UTC)).total_seconds())))
    raise TransportError("destination-query", "exact-signals-missing-at-deadline")


async def receive_alerts(bindings: dict, deadline: datetime, output: Path) -> dict:
    # This optional SDK is isolated to the evidence tool, not added to API image.
    from azure.core.credentials import AccessToken
    from azure.eventhub.aio import EventHubConsumerClient

    namespace = bindings["eventHubNamespace"]
    if (
        re.fullmatch(r"eh-m78p-[a-f0-9]{10}\.servicebus\.windows\.net", namespace)
        is None
    ):
        raise ValueError("event hub namespace is not an isolated pilot destination")
    addresses = _private_host(namespace)
    events: list[dict] = []

    class Credential:
        async def get_token(self, *_: str, **__: object) -> Any:
            return AccessToken(
                await _identity_token("https://eventhubs.azure.net/"),
                int(datetime.now(UTC).timestamp()) + 120,
            )

    async def on_event(context: Any, event: Any) -> None:
        if event is None:
            return
        if len(events) >= 256:
            raise ValueError("alert evidence bound exceeded")
        body = event.body_as_str()
        if len(body.encode()) > 128 * 1024:
            raise ValueError("alert record exceeded bound")
        payload = json.loads(body)
        essentials = payload.get("data", {}).get("essentials", {})
        if payload.get("schemaId") != "azureMonitorCommonAlertSchema":
            raise ValueError("unexpected alert source schema")
        if essentials.get("monitorCondition") not in {"Fired", "Resolved"}:
            raise ValueError("unexpected alert condition")
        if essentials.get("alertRule") not in bindings["alertRuleNames"]:
            raise ValueError("alert outside bound catalog")
        targets = essentials.get("alertTargetIDs", [])
        if [value.lower() for value in targets] != [
            bindings["workspaceResourceId"].lower()
        ]:
            raise ValueError("alert target mismatch")
        record = {
            "partitionId": context.partition_id,
            "sequenceNumber": event.sequence_number,
            "enqueuedTime": event.enqueued_time.isoformat(),
            "native": payload,
            "receivedAt": datetime.now(UTC).isoformat(),
        }
        write_new(
            output / f"event-{context.partition_id}-{event.sequence_number}.json",
            record,
        )
        events.append(record)

    seconds = min(600, max(0, (deadline - datetime.now(UTC)).total_seconds()))
    consumer = EventHubConsumerClient(
        fully_qualified_namespace=namespace,
        eventhub_name="alerts",
        consumer_group="managed-proof",
        credential=Credential(),
        retry_total=0,
        prefetch=16,
        logging_enable=False,
    )
    try:
        async with asyncio.timeout(seconds), consumer:
            await consumer.receive(
                on_event=on_event,
                starting_position=utc(bindings["approvedAt"]),
                max_wait_time=30,
            )
    except TimeoutError:
        pass
    return {
        "classification": "native-delivery-observation",
        "privateAddresses": addresses,
        "events": len(events),
        "accepted": False,
        "note": "Compare exact Fired/Resolved pairs against expected scenarios before acceptance.",
    }


def smtp_probe(bindings: dict, execution_id: str) -> dict:
    import smtplib

    config = bindings["smtp"]
    if config["port"] not in (465, 587) or config.get("tls") not in (
        "implicit",
        "starttls",
    ):
        raise ValueError("explicit TLS SMTP provider required")
    if (config["port"] == 465) != (config["tls"] == "implicit"):
        raise ValueError("SMTP port/TLS configuration mismatch")
    if config["recipient"] not in config["approvedRecipients"]:
        raise ValueError("SMTP recipient not explicitly authorized")
    message = EmailMessage()
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message["Subject"] = "M78 isolated SMTP delivery proof"
    marker = hashlib.sha256(execution_id.encode()).hexdigest()
    message["Message-ID"] = f"<{marker}@m78-evidence.invalid>"
    message.set_content(
        "Synthetic delivery evidence. No account token or private document.\n" + marker
    )
    context = ssl.create_default_context()
    connection = (
        smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=context)
        if config["tls"] == "implicit"
        else smtplib.SMTP(config["host"], config["port"], timeout=15)
    )
    with connection:
        connection.ehlo()
        if config["tls"] == "starttls":
            connection.starttls(context=context)
            connection.ehlo()
        connection.login(
            os.environ["OPENCANVAS_SMTP_USERNAME"],
            os.environ["OPENCANVAS_SMTP_PASSWORD"],
        )
        refused = connection.send_message(message)
        if refused:
            raise ValueError("SMTP provider refused approved recipient")
    return {
        "classification": "provider-submit-only",
        "messageIdSha256": hashlib.sha256(
            str(message["Message-ID"]).encode()
        ).hexdigest(),
        "marker": marker,
        "accepted": False,
        "missing": "provider delivery event and actual inbox receipt for exact Message-ID",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("prepare", "prepare-verification-queries", *OPERATIONS)
    )
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--release")
    parser.add_argument("--deployment")
    parser.add_argument("--ceiling", type=float)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--runtime-readbacks", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execution-id")
    parser.add_argument("--query-file", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--full-closure", action="store_true")
    parser.add_argument("--provider-readback", type=Path)
    parser.add_argument("--provider-binding", type=Path)
    args = parser.parse_args()
    if args.operation == "prepare-verification-queries":
        if args.execute or args.output is None:
            parser.error("prepare-verification-queries requires --output and no --execute")
        prepare_verification_queries(args.bundle, args.output)
        return 0
    if args.operation == "prepare":
        if (
            not args.release
            or not args.deployment
            or args.ceiling is None
            or args.execute
        ):
            parser.error(
                "prepare requires release, deployment, ceiling and no --execute"
            )
        prepare(
            args.bundle,
            args.release,
            args.deployment,
            args.ceiling,
            full_closure=args.full_closure,
        )
        print(
            json.dumps(
                {
                    "packageSha256": digest(args.bundle / "manifest.json"),
                    "liveOperations": 0,
                }
            )
        )
        return 0
    if not all(
        (
            args.execute,
            args.authorization,
            args.bindings,
            args.output,
            args.execution_id,
        )
    ):
        parser.error(
            "live observation requires --execute, authorization, bindings, output and execution-id"
        )
    if args.execution_id != os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"):
        raise ValueError("actual managed job execution ID required")
    _, bindings, deadline = authorize(
        args.bundle, args.authorization, args.bindings, args.operation
    )
    if args.runtime_readbacks is None:
        parser.error("live observation requires exact --runtime-readbacks")
    if args.runtime_readbacks.suffix == ".gz":
        with gzip.open(args.runtime_readbacks, "rb") as source:
            readback_bytes = source.read(250_001)
        if len(readback_bytes) > 250_000:
            raise ValueError("runtime readback exceeds the artifact bound")
    else:
        readback_bytes = args.runtime_readbacks.read_bytes()
    bindings = admit_runtime_bindings(
        bindings,
        json.loads(readback_bytes),
        plan_sha256=digest(args.bindings),
    )
    bindings["approvedAt"] = json.loads(args.authorization.read_text())["approvedAt"]
    intent = args.output.with_suffix(".intent.json")
    if args.output.exists() or intent.exists():
        raise ValueError(
            "preserve existing evidence; reconcile outcome before another execution"
        )
    write_new(
        intent,
        {
            "schema": VERSION,
            "operation": args.operation,
            "executionId": args.execution_id,
            "at": datetime.now(UTC).isoformat(),
            "approvalSha256": digest(args.authorization),
            "bindingsSha256": digest(args.bindings),
        },
    )
    failed = False
    try:
        if args.operation == "query":
            if args.query_file is None:
                raise ValueError("query requires --query-file")
            kql = args.query_file.read_text()
            if hashlib.sha256(kql.encode()).hexdigest() not in bindings.get(
                "approvedQueryHashes", []
            ):
                raise ValueError("query is not part of the approved execution package")
            result = asyncio.run(query(bindings, kql))
        elif args.operation == "provider-observation":
            if args.provider_readback is None or args.provider_binding is None:
                raise ValueError("exact provider readback and binding required")
            provider_binding = json.loads(args.provider_binding.read_text())
            native = json.loads(args.provider_readback.read_text())
            if (
                provider_binding.get("release") != bindings["release"]
                or provider_binding.get("deployment") != bindings["deployment"]
                or set(provider_binding.get("resourceIds", []))
                != set(bindings.get("providerObservationResourceIds", []))
                or not provider_binding.get("resourceIds")
                or native.get("resourceId") not in provider_binding["resourceIds"]
            ):
                raise ValueError(
                    "provider observation scope differs from approved plan"
                )
            if native["native"]["request"] not in provider_requests_for_approval(
                bindings, json.loads(args.authorization.read_text())
            ):
                raise ValueError("provider observation request not authorized")
            from scripts.operational_observer import observe

            result = asyncio.run(
                observe(
                    argparse.Namespace(
                        bindings=args.provider_binding,
                        bindings_sha256=digest(args.provider_binding),
                        readback=args.provider_readback,
                        readback_sha256=digest(args.provider_readback),
                        emit=True,
                    )
                )
            )
        elif args.operation == "telemetry":
            result = asyncio.run(telemetry(bindings, deadline))
        elif args.operation == "alerts":
            result = asyncio.run(
                receive_alerts(bindings, deadline, args.output.with_suffix(""))
            )
        else:
            result = smtp_probe(bindings, args.execution_id)
    except Exception as exc:
        failed = True
        result = {
            "classification": "failed_or_unknown",
            "errorType": type(exc).__name__,
            "accepted": False,
            "nextAction": "reconcile exact intent and provider outcome before retry",
        }
        if isinstance(exc, TransportError):
            result["transportDiagnostic"] = exc.diagnostic
    write_new(
        args.output,
        {
            "schema": VERSION,
            "operation": args.operation,
            "executionId": args.execution_id,
            "at": datetime.now(UTC).isoformat(),
            "result": result,
        },
    )
    print(
        json.dumps({"operation": args.operation, "receiptSha256": digest(args.output)})
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Collect read-only scanner evidence with the worker identity on an idle helper job."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import time
import uuid
import zlib
from datetime import timedelta
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError, parse_utc
from infra.milestone_7_8.pilot.scanner_hold import POLICY
from infra.milestone_7_8.pilot.scanner_read_diagnostic import MARKER, PROBE_TIMEOUT
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new

ARM = "https://management.azure.com"
AUTH = "/providers/Microsoft.Authorization/"
ROLE_API = "2022-04-01"
SCANNER_ROLE_ACTIONS = {
    "Microsoft.OperationalInsights/workspaces/read",
    "Microsoft.OperationalInsights/workspaces/query/StorageMalwareScanningResults/read",
}
BICEP_NAMESPACE = uuid.UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
JOB_API = "2025-01-01"
TERMINAL = {"Succeeded", "Failed", "Stopped", "Degraded", "Canceled"}
READ_SETTINGS = {
    "PGSSLROOTCERT",
    "OPENCANVAS_DATABASE_URL",
    "OPENCANVAS_DATABASE_ROLE",
    "OPENCANVAS_DATABASE_AUTH_MODE",
    "OPENCANVAS_DATABASE_TLS_MODE",
    "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID",
    "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID",
    "OPENCANVAS_STORAGE_PROVIDER",
    "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL",
    "OPENCANVAS_OBJECT_INGESTION_MODE",
    "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID",
    "OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE",
    "OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS",
    "OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS",
}
OPTIONAL_READ_SETTINGS = {
    "OPENCANVAS_AZURE_LOG_ANALYTICS_ENDPOINT",
    "OPENCANVAS_MALWARE_SCAN_RESULT_MAX_AGE_SECONDS",
    "OPENCANVAS_SCANNER_RESULT_BRIDGE_MAX_LOG_ROWS",
    "OPENCANVAS_SCANNER_RESULT_BRIDGE_QUERY_TIMEOUT_SECONDS",
    "OPENCANVAS_AZURE_QUARANTINE_CONTAINER",
}


class DiagnosticUnavailable(CampaignError):
    pass


def worker_command(inputs: dict, source: Path) -> list[str]:
    # No secret, account credential, Blob path or token is passed to the CLI.
    raw = source.read_bytes() + b"\nmain(" + repr(inputs).encode() + b")\n"
    packed = base64.b64encode(zlib.compress(raw, level=9)).decode()
    expected = hashlib.sha256(raw).hexdigest()
    return [
        "python", "-c",
        "import base64,hashlib,zlib\n"
        f"source=zlib.decompress(base64.b64decode({packed!r},validate=True))\n"
        f"if hashlib.sha256(source).hexdigest() != {expected!r}: raise SystemExit(1)\n"
        "exec(compile(source,'scanner_read_diagnostic.py','exec'))",
    ]


def console_markers(stdout: str, prefix: str) -> list:
    results = []
    for line in stdout.splitlines():
        if prefix in line:
            try:
                # ACA CLI wraps console text in JSON, sometimes with an unescaped
                # CRI log fragment in its Log property.
                log = line.strip()
                if log.startswith("{"):
                    try:
                        log = json.loads(log)["Log"]
                    except ValueError:
                        match = re.fullmatch(
                            r'\{"TimeStamp":"[0-9T:+.Z-]+","Log":"F (.*)"\}', log
                        )
                        if match is None:
                            raise
                        log = match[1]
                log = log.removeprefix("F ")
                if log.startswith(prefix):
                    results.append(json.loads(log[len(prefix):]))
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise DiagnosticUnavailable(
                    "worker diagnostic marker is incomplete"
                ) from error
    return results


def worker_result(stdout: str, inputs: dict, execution: str) -> dict:
    results = console_markers(stdout, MARKER)
    if (
        len(results) != 1
        or not isinstance(results[0], dict)
        or results[0].get("executionId") != execution
        or any(
            results[0].get(key) != inputs[key]
            for key in ("challenge", "objectVersionId")
        )
    ):
        raise DiagnosticUnavailable("worker diagnostic output was not reconciled")
    return results[0]


def job_state(job: dict) -> dict:
    identity = job["identity"]
    properties = job["properties"]
    if identity["type"] != "UserAssigned":
        raise CampaignError("scanner helper identity type differs")
    return {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {key: {} for key in identity["userAssignedIdentities"]},
        },
        "properties": {
            key: copy.deepcopy(properties[key]) for key in ("configuration", "template")
        },
    }


def job_binding(state: dict) -> tuple[set[str], dict]:
    ids = {key.casefold() for key in state["identity"]["userAssignedIdentities"]}
    config = state["properties"]["configuration"]
    return ids, config | {
        "registries": [
            row | {"identity": row["identity"].casefold()} for row in config["registries"]
        ]
    }


def prepare_worker_job(original, container, plan, foundation, worker, inputs):
    job_id = plan["targetResourceGroupId"] + "/providers/Microsoft.App/jobs/caj-" + (
        plan["deployment"] + "-migration"
    )
    before = job_state(original)
    identities, configuration = job_binding(before)
    (old,) = before["properties"]["template"]["containers"]
    (migration,) = (item for item in foundation["identityBindings"] if item["role"] == "migration")
    registry = container["image"].split("/", 1)[0]
    if (
        original["id"].casefold() != job_id.casefold()
        or plan["helperJobResourceId"].casefold() != job_id.casefold()
        or original["properties"]["environmentId"] != plan["managedEnvironmentResourceId"]
        or original["properties"]["provisioningState"] != "Succeeded"
        or identities != {migration["id"].casefold()}
        or configuration["triggerType"] != "Manual"
        or configuration["manualTriggerConfig"] != {"parallelism": 1, "replicaCompletionCount": 1}
        or configuration.get("secrets")
        or configuration.get("identitySettings")
        or configuration["registries"]
        != [{"server": registry, "identity": migration["id"].casefold()}]
        or before["properties"]["template"].get("initContainers")
        or before["properties"]["template"].get("volumes")
        or old["name"] != "migration"
        or old["image"] != container["image"]
        or old["command"] != ["python", "-m", "scripts.migrate_and_grant"]
        or old["resources"].get("cpu") != 0.5
        or old["resources"].get("memory") != "1Gi"
    ):
        raise CampaignError("original scanner helper bindings differ")
    env = [
        row for row in container["env"]
        if row["name"] in READ_SETTINGS | OPTIONAL_READ_SETTINGS
    ]
    values = {row["name"]: row["value"] for row in env}
    expected = {
        "OPENCANVAS_DATABASE_URL": inputs["databaseUrl"],
        "OPENCANVAS_DATABASE_ROLE": "worker",
        "OPENCANVAS_DATABASE_AUTH_MODE": "entra",
        "OPENCANVAS_DATABASE_TLS_MODE": "verify-full",
        "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": inputs["clientId"],
        "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID": inputs["clientId"],
        "OPENCANVAS_STORAGE_PROVIDER": "azure",
        "OPENCANVAS_AZURE_STORAGE_ACCOUNT_URL": inputs["storageUrl"],
        "OPENCANVAS_AZURE_LOG_ANALYTICS_WORKSPACE_ID": inputs["workspaceId"],
        "OPENCANVAS_OBJECT_INGESTION_MODE": "trusted",
        "OPENCANVAS_SCANNER_RESULT_BRIDGE_MODE": "private_pull",
        "OPENCANVAS_MALWARE_SCAN_TIMEOUT_SECONDS": "900",
        "OPENCANVAS_SCANNER_RESULT_BRIDGE_RETRY_MAX_SECONDS": "20",
    }
    if (
        not values.keys() >= READ_SETTINGS
        or len(values) != len(env)
        or any(set(row) != {"name", "value"} for row in env)
        or any(values.get(key) != value for key, value in expected.items())
    ):
        raise CampaignError("worker scanner settings differ")
    command = worker_command(inputs, Path(__file__).with_name("scanner_read_diagnostic.py"))
    apply = copy.deepcopy(before)
    apply["identity"]["userAssignedIdentities"] = {worker["id"]: {}}
    apply["properties"]["configuration"].update(
        registries=[{"server": registry, "identity": worker["id"]}],
        replicaRetryLimit=0,
        replicaTimeout=PROBE_TIMEOUT + 20,
    )
    apply["properties"]["template"]["containers"] = [{
        "name": "migration",
        "image": container["image"],
        "resources": {"cpu": 0.5, "memory": "1Gi"},
        "command": command,
        "env": [*env, {"name": "OPENCANVAS_APP_MODE", "value": "development"}],
    }]
    return job_id, before, apply


def read_worker_job(
    context, root, label, container, foundation, worker, inputs, *, scan_cutoff=None
):
    context.policy.check(seconds_needed=210)
    plan = context.plan
    job_id = plan["targetResourceGroupId"] + (
        "/providers/Microsoft.App/jobs/caj-" + plan["deployment"] + "-migration"
    )
    history = context.get(root, label + "-history", job_id + "/executions", JOB_API)
    if history.get("nextLink") or any(
        row["properties"]["status"] not in TERMINAL for row in history["value"]
    ):
        raise DiagnosticUnavailable("scanner helper needs a complete idle inventory")
    original = context.get(root, label + "-original", job_id, JOB_API)
    _, before, apply = prepare_worker_job(
        original, container, plan, foundation, worker, inputs
    )
    (desired,) = apply["properties"]["template"]["containers"]

    def matches_template(template):
        (deployed,) = template["containers"]
        return (
            not template.get("initContainers")
            and not template.get("volumes")
            and not deployed.get("args")
            and all(deployed.get(key) == desired[key] for key in ("name", "image", "command"))
            and sorted(deployed["env"], key=lambda entry: entry["name"])
            == sorted(desired["env"], key=lambda entry: entry["name"])
            and all(
                deployed["resources"].get(key) == value
                for key, value in desired["resources"].items()
            )
        )

    def patch(stage, payload):
        body = root / (label + "-" + stage + ".json")
        write_new(body, payload)
        context.call(
            root, label + "-" + stage,
            ("rest", "--method", "patch", "--url", f"{ARM}{job_id}?api-version={JOB_API}",
             "--body", "@" + str(body.resolve())),
        )

    def capture(stage):
        actual = context.get(root, label + "-" + stage, job_id, JOB_API)
        if (
            actual["id"].casefold() != job_id.casefold()
            or actual["properties"]["environmentId"] != plan["managedEnvironmentResourceId"]
            or actual["properties"]["provisioningState"] != "Succeeded"
        ):
            raise CampaignError("scanner helper native scope or provisioning is unproved")
        return job_state(actual)

    dispatch_attempted = terminal = False
    try:
        patch("apply", apply)
        actual = capture("applied")
        # The provider can fill defaults on the replacement container.
        if (
            job_binding(actual) != job_binding(apply)
            or not matches_template(actual["properties"]["template"])
        ):
            raise CampaignError("scanner helper template or identity readback differs")
        context.policy.check(seconds_needed=135)
        if scan_cutoff is not None and (
            context.policy.clock() + timedelta(seconds=135)
            >= min(scan_cutoff, context.policy.core_by)
        ):
            raise DiagnosticUnavailable("insufficient time for the read before the scan deadline")
        name = job_id.rsplit("/", 1)[-1]
        native_args = ("--name", name, "--resource-group", context.runtime["resourceGroupName"])
        write_new(root / (label + "-start-intent.json"), {"jobResourceId": job_id})
        dispatch_attempted = True
        start = context.call(root, label + "-start", ("containerapp", "job", "start", *native_args))
        execution = start["name"].rsplit("/", 1)[-1]
        if not re.fullmatch(re.escape(name) + r"-[a-z0-9]+", execution):
            raise CampaignError("scanner helper execution is unbound")
        execution_id = job_id + "/executions/" + execution
        end = time.monotonic() + 120
        for attempt in range(25):
            run = context.get(root, f"{label}-execution-{attempt}", execution_id, JOB_API)
            if run["id"].casefold() != execution_id.casefold():
                raise CampaignError("scanner helper execution readback differs")
            state = run["properties"]["status"]
            if state in TERMINAL:
                terminal = True
                break
            if time.monotonic() >= end:
                break
            time.sleep(5)
    except Exception as error:
        if dispatch_attempted and not terminal:
            raise CampaignError(
                "scanner helper execution must be reconciled before restore"
            ) from error
        raise
    finally:
        if terminal or not dispatch_attempted:
            try:
                patch("restore", before)
                restored = capture("restored")
                if (
                    job_binding(restored) != job_binding(before)
                    or restored["properties"]["template"] != before["properties"]["template"]
                ):
                    raise CampaignError("scanner helper original state differs")
            except Exception as error:
                raise CampaignError("scanner helper restore needs native reconciliation") from error
    if not terminal:
        raise CampaignError("scanner helper execution must be reconciled before restore")
    if state != "Succeeded":
        raise DiagnosticUnavailable("scanner helper did not produce a successful execution")
    if not matches_template(run["properties"]["template"]):
        raise CampaignError("scanner helper execution command or read settings differ")
    # Read only the named execution's own console after restoring the helper.
    logs = context.call(
        root, label + "-console",
        ("containerapp", "job", "logs", "show", *native_args, "--execution", execution,
         "--container", "migration", "--tail", "40", "--follow", "false", "--format", "json"),
        as_json=False,
    )
    return worker_result(logs, inputs, execution)


def exact_role(definition: dict, scope: str, expected_name: str) -> str:
    p = definition["properties"]
    (permission,) = p["permissions"]
    if not (
        p["roleName"] == expected_name
        and p["type"] == "CustomRole"
        and [s.casefold() for s in p["assignableScopes"]] == [scope.casefold()]
        and set(permission["actions"]) == SCANNER_ROLE_ACTIONS
        and not any(
            permission[k] for k in ("notActions", "dataActions", "notDataActions")
        )
    ):
        raise CampaignError(
            "scanner grant definition does not match the sealed narrow role"
        )
    return definition["id"]


def exact_assignment(
    assignment: dict, workspace: str, principal: str, role: str
) -> bool:
    p = assignment["properties"]
    at_scope = p.get("scope", "").casefold() == workspace.casefold()
    return (
        at_scope
        and p.get("principalId", "").casefold() == principal.casefold()
        and p.get("roleDefinitionId", "").rsplit("/", 1)[-1].casefold()
        == role.rsplit("/", 1)[-1].casefold()
        and not p.get("condition")
    )


def worker_observer(context, root, upload):
    plan = context.plan
    application = read(context.run / "activation/application-terminal.json")
    foundation = application["properties"]["outputs"]["foundationBindings"]["value"]
    (worker,) = (
        item for item in foundation["identityBindings"] if item["role"] == "worker"
    )
    scope = plan["targetResourceGroupId"]
    workspace = plan["workspaceResourceId"]
    app_id = plan["workerResourceId"]
    for rid in (worker["id"], workspace, app_id):
        if not rid.casefold().startswith(scope.casefold() + "/providers/"):
            raise CampaignError("worker diagnostic escaped the approved scope")
    worker_arm = context.get(root, "worker-arm", app_id, "2025-01-01")
    identity_ids = list(worker_arm["identity"]["userAssignedIdentities"])
    properties = worker_arm["properties"]
    revision = properties["latestReadyRevisionName"]
    if (
        worker_arm["id"].casefold() != app_id.casefold()
        or worker_arm["identity"]["type"] != "UserAssigned"
        or [v.casefold() for v in identity_ids] != [worker["id"].casefold()]
        or properties["managedEnvironmentId"] != plan["managedEnvironmentResourceId"]
        or properties["latestRevisionName"] != revision
        or properties["provisioningState"] != "Succeeded"
        or not re.fullmatch(r"[a-z0-9-]+", revision)
        or properties["configuration"]["activeRevisionsMode"] != "Single"
    ):
        raise CampaignError("worker identity or active revision differs")
    (container,) = properties["template"]["containers"]
    if (
        container["name"] != "worker"
        or container["command"] != ["python", "-m", "scripts.worker"]
        or not container["image"].endswith("@" + plan["imageDigest"])
    ):
        raise CampaignError("worker image differs")
    workspace_body = context.get(root, "workspace-arm", workspace, "2023-09-01")
    if workspace_body["id"].casefold() != workspace.casefold():
        raise CampaignError("scanner workspace readback differs")
    customer = workspace_body["properties"]["customerId"]
    common = {
        key: upload[key]
        for key in ("sessionId", "documentId", "objectVersionId", "contentSha256")
    }
    common.update(
        clientId=worker["clientId"],
        databaseUrl=f"postgresql+asyncpg://{worker['name']}@{foundation['postgresHost']}:5432/opencanvas",
        workspaceId=customer,
        storageUrl=foundation["storageUrl"],
    )
    if "serverScanDeadlineAt" in upload:
        common["serverScanDeadlineAt"] = upload["serverScanDeadlineAt"]

    def observe(label, *, scan_cutoff=None):
        inputs = common | {"challenge": uuid.uuid4().hex}
        args = (context, root, label, container, foundation, worker, inputs)
        evidence = read_worker_job(*args, scan_cutoff=scan_cutoff)
        write_new(root / (label + ".json"), evidence)
        return evidence

    return worker, workspace, observe


def collect_pending(context, marker):
    root = context.run / "scanner-in-window"
    root.mkdir(exist_ok=False)
    write_new(root / "pending-marker.json", marker)
    upload = marker["upload"]
    _, _, observe = worker_observer(context, root, upload)
    return observe("worker-read", scan_cutoff=parse_utc(upload["scanDeadlineAt"]))


def collect_and_repair(context, *, repair: bool) -> str:
    policy = context.policy
    hold = policy.require_hold()
    policy.check(dependent=repair, seconds_needed=1700 if repair else 230)
    root = context.run / ("scanner-repair" if repair else "scanner-diagnostic")
    root.mkdir(exist_ok=False)
    if context.plan.get("scannerObservation") is not None:
        if repair:
            raise CampaignError("the successor scope allows one diagnostic only")
        if (context.run / "scanner-in-window/worker-read-start-intent.json").exists():
            raise DiagnosticUnavailable("in-window diagnostic already dispatched")
        if hold["upload"]["suffix"] != "primary":
            raise DiagnosticUnavailable("diagnostic scope is the first primary upload")
        write_new(root / "timing.json", {"classification": "post-deadline"})
    worker, workspace, observe = worker_observer(context, root, hold["upload"])
    scope = context.plan["targetResourceGroupId"]
    before = observe("worker-read")
    if not repair:
        return before["status"]
    if (
        before.get("logAnalytics", {}).get("code")
        != "scanner-log-query-authorization-unavailable"
    ):
        return "no-authorized-repair-demonstrated"

    role_name = (
        "m78o-"
        + context.runtime["resourceGroupName"].split("-")[2]
        + "-scanner-table-query"
    )
    roles = context.get(root, "definitions", scope + AUTH + "roleDefinitions", ROLE_API)
    if roles.get("nextLink"):
        raise CampaignError("incomplete scanner role definition read")
    (definition,) = (
        r for r in roles["value"] if r["properties"]["roleName"] == role_name
    )
    role = exact_role(definition, scope, role_name)
    got = context.get(
        root, "assignments-before", workspace + AUTH + "roleAssignments", ROLE_API
    )
    if got.get("nextLink"):
        raise CampaignError("incomplete role-assignment read")
    # Bicep guid(logs.id, identities[2].id, 'pilot-scanner-table-query').
    token = uuid.uuid5(
        BICEP_NAMESPACE,
        "-".join((workspace, worker["id"], "pilot-scanner-table-query")),
    )
    rid = workspace + AUTH + "roleAssignments/" + str(token)
    principal = worker["principalId"]
    if any(
        row["id"].casefold() == rid.casefold()
        or exact_assignment(row, workspace, principal, role)
        for row in got["value"]
    ):
        return "assignment-already-present-no-write"
    body = root / "assignment-body.json"
    write_new(
        body,
        {
            "properties": {
                "roleDefinitionId": role,
                "principalId": principal,
                "principalType": "ServicePrincipal",
            }
        },
    )
    policy.check(dependent=True, seconds_needed=1500)
    write_new(
        root / "assignment-write-intent.json",
        {"resourceId": rid, "bodySha256": file_hash(body)},
    )
    context.call(
        root,
        "assignment-write",
        (
            "rest",
            "--method",
            "put",
            "--url",
            f"{ARM}{rid}?api-version={ROLE_API}",
            "--body",
            "@" + str(body.resolve()),
        ),
        timeout=40,
    )
    after_grant = context.get(root, "assignment-readback", rid, ROLE_API)
    if after_grant["id"].casefold() != rid.casefold() or not exact_assignment(
        after_grant, workspace, principal, role
    ):
        raise CampaignError("scanner assignment write remains uncertain")
    verification = None
    for attempt in range(4):
        label = f"grant-verification-{attempt}"
        if policy.clock() + timedelta(seconds=1410) >= policy.core_by:
            break
        after = observe(label)
        if (
            after.get("logAnalytics", {}).get("status") == "read"
            and after["logAnalytics"].get("versionBound") is True
        ):
            verification = after
            break
        if attempt < 3:
            time.sleep(20)
    if verification is None:
        return "grant-restored-worker-query-still-unproved"
    write_new(root / "after-worker-read.json", verification)
    write_new(
        root / "verified.json",
        {
            "repair": POLICY["authorizedRepair"],
            "deployment": policy.deployment,
            "pausedResultSha256": hold["resultSha256"],
            "objectVersionId": hold["upload"]["objectVersionId"],
            "exactLogReadVerified": True,
            "verificationSha256": file_hash(root / "after-worker-read.json"),
            "roleReadbackSha256": file_hash(root / "assignment-readback.json"),
        },
    )
    return "verified"

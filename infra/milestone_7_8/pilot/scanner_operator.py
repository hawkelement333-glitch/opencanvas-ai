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
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError, parse_utc, utc
from infra.milestone_7_8.pilot.scanner_hold import POLICY
from infra.milestone_7_8.pilot.scanner_read_diagnostic import MARKER, PROBE_TIMEOUT
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new
from infra.milestone_7_8.pilot_validation import SCANNER_OBSERVATION

ARM = "https://management.azure.com"
AUTH = "/providers/Microsoft.Authorization/"
ROLE_API = "2022-04-01"
SCANNER_ROLE_ACTIONS = {
    "Microsoft.OperationalInsights/workspaces/read",
    "Microsoft.OperationalInsights/workspaces/query/read",
    "Microsoft.OperationalInsights/workspaces/query/StorageMalwareScanningResults/read",
}
BICEP_NAMESPACE = uuid.UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")
JOB_API = "2025-01-01"
TERMINAL = {"Succeeded", "Failed", "Stopped", "Degraded", "Canceled"}
UPDATE_TERMINAL = {"Succeeded", "Failed", "Canceled"}
RECONCILE_SECONDS = 120
CLEANUP_RESERVE_SECONDS = 300
UPLOAD_ENV = "M78_SCANNER_UPLOAD"
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


def worker_command(inputs: dict, source: Path, *, deferred=False) -> list[str]:
    # No secret, account credential, Blob path or token is passed to the CLI.
    call = repr(inputs)
    if deferred:
        call += f" | json.loads(os.environ[{UPLOAD_ENV!r}])"
    raw = source.read_bytes() + b"\nmain(" + call.encode() + b")\n"
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
    config = dict(state["properties"]["configuration"])
    # ARM omitted this empty optional setting in the terminal November readback.
    if config.get("identitySettings") in (None, []):
        config.pop("identitySettings", None)
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
    command = worker_command(
        inputs, Path(__file__).with_name("scanner_read_diagnostic.py"), deferred=True
    )
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


@contextmanager
def prepared_worker_job(
    context, root, label, container, foundation, worker, settings, *, ready_by
):
    policy = context.policy
    policy.check(seconds_needed=CLEANUP_RESERVE_SECONDS + 210)
    hard_cutoff = policy.stop_by - timedelta(seconds=CLEANUP_RESERVE_SECONDS)
    ready_by = min(ready_by, hard_cutoff)
    plan = context.plan
    job_id = plan["targetResourceGroupId"] + (
        "/providers/Microsoft.App/jobs/caj-" + plan["deployment"] + "-migration"
    )
    history = context.get(
        root, label + "-history", job_id + "/executions", JOB_API, cutoff=ready_by
    )
    if history.get("nextLink") or any(
        row["properties"]["status"] not in TERMINAL for row in history["value"]
    ):
        raise DiagnosticUnavailable("scanner helper needs a complete idle inventory")
    original = context.get(root, label + "-original", job_id, JOB_API, cutoff=ready_by)
    _, before, apply = prepare_worker_job(
        original, container, plan, foundation, worker, settings
    )
    (desired,) = apply["properties"]["template"]["containers"]

    def matches_template(template, expected):
        (deployed,) = template["containers"]
        return (
            not template.get("initContainers")
            and not template.get("volumes")
            and not deployed.get("args")
            and all(deployed.get(key) == expected[key] for key in ("name", "image", "command"))
            and sorted(deployed["env"], key=lambda entry: entry["name"])
            == sorted(expected["env"], key=lambda entry: entry["name"])
            and all(
                deployed["resources"].get(key) == value
                for key, value in expected["resources"].items()
            )
        )

    def patch(stage, wanted, current, cutoff):
        payload = copy.deepcopy(wanted)
        target_ids = payload["identity"]["userAssignedIdentities"]
        target_keys = {key.casefold() for key in target_ids}
        # ARM merges the identity dictionary. Explicitly remove the previous identity.
        target_ids.update({
            key: None for key in current["identity"]["userAssignedIdentities"]
            if key.casefold() not in target_keys
        })
        body = root / (label + "-" + stage + ".json")
        write_new(body, payload)
        write_new(root / (label + "-" + stage + "-intent.json"), {
            "resourceId": job_id, "bodySha256": file_hash(body), "atUtc": utc(policy.clock()),
        })
        context.call(
            root, label + "-" + stage,
            ("rest", "--method", "patch", "--url", f"{ARM}{job_id}?api-version={JOB_API}",
             "--body", "@" + str(body.resolve())),
            cutoff=cutoff, timeout=40,
        )

    def differences(actual, expected):
        ids, config = job_binding(actual)
        wanted_ids, wanted_config = job_binding(expected)
        return [
            key for key, equal in (
                ("identity", ids == wanted_ids),
                ("configuration", config == wanted_config),
                ("template", actual["properties"]["template"] == expected["properties"]["template"]),
            ) if not equal
        ]

    last = ("Succeeded", before, label + "-original.native.json")

    def wait_for_update(stage, cutoff, previous, *, expected=None):
        nonlocal last
        saw_update = False
        for attempt in range(25):
            if policy.clock() >= cutoff:
                break
            entry = f"{label}-{stage}-{attempt:02}"
            actual = context.get(root, entry, job_id, JOB_API, cutoff=cutoff)
            props = actual["properties"]
            if (actual["id"].casefold() != job_id.casefold()
                    or props["environmentId"] != plan["managedEnvironmentResourceId"]):
                raise CampaignError("scanner helper native scope differs")
            state = props["provisioningState"]
            last = (state, None, entry + ".native.json")
            try:
                observed = job_state(actual)
                job_binding(observed)
            except (CampaignError, KeyError, TypeError):
                if state in UPDATE_TERMINAL:
                    raise
                observed = None
            last = (state, observed, entry + ".native.json")
            # A successful read of the old configuration can precede the update.
            if state in UPDATE_TERMINAL and (
                state != "Succeeded" or saw_update or differences(observed, previous)
                or (expected is not None and not differences(observed, expected))
            ):
                return state, observed
            saw_update = state not in UPDATE_TERMINAL
            time.sleep(max(0, min(5, (cutoff - policy.clock()).total_seconds())))
        raise CampaignError("scanner helper update did not settle before its deadline")

    name = job_id.rsplit("/", 1)[-1]
    native_args = ("--name", name, "--resource-group", context.runtime["resourceGroupName"])
    execution_pending = False

    def observe(inputs, *, scan_cutoff=None):
        nonlocal execution_pending
        started_at = policy.clock()
        end = min(hard_cutoff, started_at + timedelta(seconds=120))
        minimum = timedelta(seconds=SCANNER_OBSERVATION["minimumDispatchSecondsRemaining"])
        if scan_cutoff is not None and started_at + minimum >= min(
            scan_cutoff, policy.core_by, hard_cutoff
        ):
            raise DiagnosticUnavailable("insufficient time for the read before the scan deadline")
        target = copy.deepcopy(desired)
        target["env"].append({"name": UPLOAD_ENV, "value": json.dumps(inputs, separators=(",", ":"))})
        body = root / (label + "-execution.yaml")
        write_new(body, {"containers": [target]})
        write_new(root / (label + "-start-intent.json"), {
            "jobResourceId": job_id, "templateSha256": file_hash(body), "atUtc": utc(started_at),
        })
        execution_pending = True
        start = context.call(
            root, label + "-start", ("containerapp", "job", "start", *native_args,
                                     "--yaml", str(body.resolve())),
            cutoff=end, timeout=40,
        )
        execution = start.get("name", "").rsplit("/", 1)[-1]
        if not re.fullmatch(re.escape(name) + r"-[a-z0-9]+", execution):
            raise CampaignError("scanner helper execution is unbound")
        execution_id = job_id + "/executions/" + execution
        for attempt in range(25):
            run = context.get(
                root, f"{label}-execution-{attempt}", execution_id, JOB_API, cutoff=end
            )
            if run["id"].casefold() != execution_id.casefold():
                raise CampaignError("scanner helper execution readback differs")
            state = run["properties"]["status"]
            if state in TERMINAL:
                execution_pending = False
                break
            if policy.clock() >= end:
                break
            time.sleep(max(0, min(5, (end - policy.clock()).total_seconds())))
        if execution_pending:
            raise CampaignError("scanner helper execution must be reconciled before restore")
        if state != "Succeeded":
            raise DiagnosticUnavailable("scanner helper did not produce a successful execution")
        if not matches_template(run["properties"]["template"], target):
            raise CampaignError("scanner helper execution command or read settings differ")
        logs = context.call(
            root, label + "-console",
            ("containerapp", "job", "logs", "show", *native_args, "--execution", execution,
             "--container", "migration", "--tail", "40", "--follow", "false", "--format", "json"),
            as_json=False, cutoff=hard_cutoff, timeout=15,
        )
        result = worker_result(logs, inputs, execution)
        write_new(root / (label + ".json"), result)
        return result

    apply_by = min(hard_cutoff, policy.clock() + timedelta(seconds=RECONCILE_SECONDS))
    applied = None
    restored = False
    restore_error = None
    try:
        patch("apply", apply, before, min(ready_by, apply_by))
        state, applied = wait_for_update("applied", min(ready_by, apply_by), before)
        if (state != "Succeeded" or job_binding(applied) != job_binding(apply)
                or not matches_template(applied["properties"]["template"], desired)):
            raise CampaignError("scanner helper template or identity readback differs")
        yield observe
    finally:
        if (root / (label + "-apply-intent.json")).exists():
            try:
                if applied is None:
                    _, applied = wait_for_update("apply-reconcile", apply_by, before)
                if execution_pending:
                    raise CampaignError("scanner helper execution must be reconciled before restore")
                restore_by = min(
                    hard_cutoff, policy.clock() + timedelta(seconds=RECONCILE_SECONDS)
                )
                if policy.clock() >= restore_by:
                    raise CampaignError("scanner helper restore would enter the cleanup reserve")
                # Even a failed restore call may have submitted a native write.
                try:
                    patch("restore", before, applied, restore_by)
                except (CampaignError, OSError, ValueError):
                    if not (root / (label + "-restore-intent.json")).exists():
                        raise
                state, actual = wait_for_update("restored", restore_by, applied, expected=before)
                restored = state == "Succeeded" and not differences(actual, before)
                if not restored:
                    raise CampaignError("scanner helper original state differs")
            except (CampaignError, OSError, ValueError, KeyError, TypeError) as error:
                restore_error = str(error)
                raise CampaignError(f"scanner helper restoration unverified: {restore_error}") from error
            finally:
                state, actual, receipt = last
                write_new(root / (label + "-restoration.json"), {
                    "verified": restored, "lastProvisioningState": state,
                    "lastNativeReadback": receipt,
                    "differencesFromOriginal": differences(actual, before) if actual is not None else None,
                    "executionPendingOrUnknown": execution_pending,
                    "unresolvedReason": restore_error, "atUtc": utc(policy.clock()),
                })


def read_worker_job(context, root, label, container, foundation, worker, inputs, *, scan_cutoff=None):
    settings = {key: inputs[key] for key in ("clientId", "databaseUrl", "workspaceId", "storageUrl")}
    dynamic = {key: value for key, value in inputs.items() if key not in settings}
    with prepared_worker_job(
        context, root, label, container, foundation, worker, settings,
        ready_by=context.policy.core_by if scan_cutoff else context.policy.stop_by,
    ) as observe:
        return observe(dynamic, scan_cutoff=scan_cutoff)


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


def worker_bindings(context, root, *, cutoff=None):
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
    worker_arm = context.get(root, "worker-arm", app_id, "2025-01-01", cutoff=cutoff)
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
    workspace_body = context.get(root, "workspace-arm", workspace, "2023-09-01", cutoff=cutoff)
    if workspace_body["id"].casefold() != workspace.casefold():
        raise CampaignError("scanner workspace readback differs")
    customer = workspace_body["properties"]["customerId"]
    settings = dict(
        clientId=worker["clientId"],
        databaseUrl=f"postgresql+asyncpg://{worker['name']}@{foundation['postgresHost']}:5432/opencanvas",
        workspaceId=customer,
        storageUrl=foundation["storageUrl"],
    )
    return worker, workspace, container, foundation, settings


def upload_inputs(upload):
    return {
        key: upload[key]
        for key in ("sessionId", "documentId", "objectVersionId", "contentSha256", "scanDeadlineAt")
    } | {"challenge": uuid.uuid4().hex}


def scanner_assignment_id(workspace, identity_id):
    # Bicep guid(logs.id, identities[2].id, 'pilot-scanner-table-query').
    token = uuid.uuid5(BICEP_NAMESPACE, "-".join((workspace, identity_id, "pilot-scanner-table-query")))
    return f"{workspace}{AUTH}roleAssignments/{token}"


def verify_worker_query_permission(context, root, worker, workspace, cutoff):
    scope = context.plan["targetResourceGroupId"]
    assignment_id = scanner_assignment_id(workspace, worker["id"])
    assignment = context.get(root, "worker-query-assignment", assignment_id, ROLE_API, cutoff=cutoff)
    if assignment["id"].casefold() != assignment_id.casefold():
        raise CampaignError("exact worker workspace assignment is unproved")
    rid = assignment["properties"]["roleDefinitionId"]
    subscription = "/".join(scope.split("/")[:3])
    prefixes = {prefix.casefold() + AUTH.casefold() + "roledefinitions" for prefix in (subscription, scope)}
    prefix, guid = rid.rsplit("/", 1)
    if prefix.casefold() not in prefixes or str(uuid.UUID(guid)) != guid.lower():
        raise CampaignError("scanner role definition differs from the bound scope")
    definition = context.get(root, "worker-query-definition", rid, ROLE_API, cutoff=cutoff)
    name = "m78o-" + context.runtime["resourceGroupName"].split("-")[2] + "-scanner-table-query"
    role = exact_role(definition, scope, name)
    actual_prefix, actual_guid = role.rsplit("/", 1)
    if (actual_prefix.casefold() not in prefixes or actual_guid.casefold() != guid.casefold()
            or not exact_assignment(assignment, workspace, worker["principalId"], role)):
        raise CampaignError("scanner query permission differs from the worker assignment")
    write_new(root / "worker-query-permission.json", {
        "verified": True, "actions": sorted(SCANNER_ROLE_ACTIONS), "assignment": assignment_id,
        "roleDefinition": role, "workspace": workspace, "principal": worker["principalId"],
    })


@contextmanager
def prepared_pending(context, cutoff):
    root = context.run / "scanner-in-window"
    root.mkdir(exist_ok=False)
    worker, workspace, container, foundation, settings = worker_bindings(context, root, cutoff=cutoff)
    if context.plan.get("verifyWorkerQueryBeforeUpload"):
        verify_worker_query_permission(context, root, worker, workspace, cutoff)
    with prepared_worker_job(
        context, root, "worker-read", container, foundation, worker, settings, ready_by=cutoff,
    ) as observe:
        yield observe


def collect_pending(context, marker, observe):
    root = context.run / "scanner-in-window"
    write_new(root / "pending-marker.json", marker)
    upload = marker["upload"]
    inputs = upload_inputs(upload) | {"serverScanDeadlineAt": upload["serverScanDeadlineAt"]}
    return observe(inputs, scan_cutoff=parse_utc(upload["scanDeadlineAt"]))


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
    worker, workspace, container, foundation, settings = worker_bindings(context, root)

    def observe(label):
        return read_worker_job(
            context, root, label, container, foundation, worker,
            settings | upload_inputs(hold["upload"]),
        )

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
    rid = scanner_assignment_id(workspace, worker["id"])
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

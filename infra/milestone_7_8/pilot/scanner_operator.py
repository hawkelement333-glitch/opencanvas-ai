"""Collect scanner evidence in the exact running worker and restore one missing grant."""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
import zlib
from datetime import timedelta
from pathlib import Path

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.pilot.scanner_read_diagnostic import MARKER
from infra.milestone_7_8.pilot.scanner_hold import POLICY
from infra.milestone_7_8.pilot_cleanup import file_hash, read, write_new

ARM = "https://management.azure.com"
AUTH = "/providers/Microsoft.Authorization/"
ROLE_API = "2022-04-01"
SCANNER_ROLE_ACTIONS = {
    "Microsoft.OperationalInsights/workspaces/read",
    "Microsoft.OperationalInsights/workspaces/query/StorageMalwareScanningResults/read",
}
BICEP_NAMESPACE = uuid.UUID("11fb06fb-712d-4ddd-98c7-e71bbd588830")


class DiagnosticUnavailable(CampaignError):
    pass


def worker_command(inputs: dict, source: Path) -> str:
    # No secret, account credential, Blob path or token is passed to the CLI.
    raw = source.read_bytes() + b"\nmain(" + repr(inputs).encode() + b")\n"
    encoded = base64.b64encode(zlib.compress(raw, level=9)).decode()
    return f"""python -c "import base64,zlib;exec(zlib.decompress(base64.b64decode('{encoded}')))" """.strip()


def worker_result(stdout: str, inputs: dict) -> dict:
    results = []
    for line in stdout.splitlines():
        # Accept only the exact challenge-bound marker, independent of CLI banners.
        if line.strip().startswith(MARKER):
            try:
                results.append(json.loads(line.strip()[len(MARKER) :]))
            except ValueError as error:
                raise DiagnosticUnavailable(
                    "worker diagnostic marker is incomplete"
                ) from error
    if (
        len(results) != 1
        or not isinstance(results[0], dict)
        or any(
            results[0].get(key) != inputs[key]
            for key in ("challenge", "objectVersionId")
        )
    ):
        raise DiagnosticUnavailable("worker diagnostic output was not reconciled")
    return results[0]


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


def collect_and_repair(context, *, repair: bool) -> str:
    policy = context.policy
    hold = policy.require_hold()
    policy.check(dependent=repair, seconds_needed=1500 if repair else 65)
    root = context.run / ("scanner-repair" if repair else "scanner-diagnostic")
    root.mkdir(exist_ok=False)
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
        [v.casefold() for v in identity_ids] != [worker["id"].casefold()]
        or properties["latestRevisionName"] != revision
        or properties["provisioningState"] != "Succeeded"
        or not re.fullmatch(r"[a-z0-9-]+", revision)
        or properties["configuration"]["activeRevisionsMode"] != "Single"
    ):
        raise CampaignError("worker identity or active revision differs")
    (container,) = properties["template"]["containers"]
    if container["name"] != "worker" or not container["image"].endswith(
        "@" + plan["imageDigest"]
    ):
        raise CampaignError("worker image differs")
    workspace_body = context.get(root, "workspace-arm", workspace, "2023-09-01")
    customer = workspace_body["properties"]["customerId"]
    upload = hold["upload"]
    common = {
        key: upload[key]
        for key in ("sessionId", "documentId", "objectVersionId", "contentSha256")
    }
    common.update(
        clientId=worker["clientId"],
        databaseHost=foundation["postgresHost"],
        workspaceId=customer,
        storageUrl=foundation["storageUrl"].rstrip("/"),
    )

    def observe(label):
        policy.check(seconds_needed=65)
        inputs = common | {"challenge": uuid.uuid4().hex}
        command = worker_command(
            inputs, Path(__file__).with_name("scanner_read_diagnostic.py")
        )
        result = context.call(
            root,
            label + "-native",
            (
                "containerapp",
                "exec",
                "--resource-group",
                context.runtime["resourceGroupName"],
                "--name",
                app_id.rsplit("/", 1)[-1],
                "--revision",
                revision,
                "--container",
                "worker",
                "--command",
                command,
            ),
            timeout=75,
            as_json=False,
        )
        evidence = worker_result(result, inputs)
        write_new(root / (label + ".json"), evidence)
        return evidence

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
        if policy.clock() + timedelta(seconds=1275) >= policy.core_by:
            break
        after = observe(label)
        if (
            after.get("logAnalytics", {}).get("status") == "read"
            and after["logAnalytics"].get("rows", 0) > 0
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
            "objectVersionId": upload["objectVersionId"],
            "exactLogReadVerified": True,
            "verificationSha256": file_hash(root / "after-worker-read.json"),
            "roleReadbackSha256": file_hash(root / "assignment-readback.json"),
        },
    )
    return "verified"

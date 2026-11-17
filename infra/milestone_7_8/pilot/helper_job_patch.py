"""Prepare two exact reversible PATCH bodies for the existing idle migration job.

Local preparation only. No HTTP calls, new jobs, identity union, secret values,
or configuration changes while an execution remains active.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import uuid
from pathlib import Path

from infra.milestone_7_8.pilot.pack_execution import SOURCE_VERIFIER


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def identity_id(scope, role):
    require(role in {"migration", "worker"}, "unsupported helper identity role")
    name = "id-m78p-a712b8c940-migration" if role == "migration" else "id-m78o-a712b8c940-worker"
    return scope + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + name


def mutable_state(body):
    require(
        body["identity"]["type"] == "UserAssigned", "only captured user-assigned identity allowed"
    )
    return {
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {
                key: {} for key in body["identity"]["userAssignedIdentities"]
            },
        },
        "properties": {
            key: copy.deepcopy(body["properties"][key]) for key in ("configuration", "template")
        },
    }


def prepare(before: dict, identity: dict, packed: dict, plan: dict, role: str) -> dict:
    require(role in {"migration", "worker"}, "only the two bound helper roles allowed")
    scope = plan["targetResourceGroupId"]
    require(
        scope.endswith("/resourceGroups/rg-m78-a712b8c940-target"), "exact isolated group required"
    )
    job = scope + "/providers/Microsoft.App/jobs/caj-m78p-a712b8c940-migration"
    require(
        before["id"] == job and plan["helperJobResourceId"] == job,
        "only existing migration job allowed",
    )
    require(
        before["properties"]["environmentId"] == plan["managedEnvironmentResourceId"],
        "job environment differs",
    )
    original = mutable_state(before)
    require(
        set(original["identity"]["userAssignedIdentities"]) == {identity_id(scope, "migration")},
        "capture original migration identity, never an already-mutated job",
    )
    original_container = original["properties"]["template"]["containers"]
    require(
        len(original_container) == 1
        and original_container[0]["name"] == "migration"
        and original_container[0]["image"].endswith("@" + plan["imageDigest"]),
        "exact source image/container required",
    )
    require(
        original["properties"]["configuration"]["triggerType"] == "Manual", "manual job required"
    )
    require(
        not original["properties"]["configuration"].get("secrets"),
        "original migration job must have no app secrets",
    )
    require(identity["id"] == identity_id(scope, role), "exact native identity required")
    client = str(uuid.UUID(identity["properties"]["clientId"]))
    principal = str(uuid.UUID(identity["properties"]["principalId"]))
    require(
        packed["proofCommand"] == ["python", "-c", SOURCE_VERIFIER],
        "exact prepared transport command required",
    )
    supplied = {row["name"]: row for row in packed["proofEnvironment"]}
    allowed = {
        "M78_EXECUTION_SOURCE",
        "M78_EXECUTION_SHA256",
        "M78_PILOT_ARTIFACT_SHA256",
        "M78_PILOT_MODULE",
        "M78_PILOT_ARGUMENTS_JSON",
        "M78_PILOT_ARTIFACT_VERSION_ID",
    }
    require(
        set(supplied) <= allowed and len(supplied) == len(packed["proofEnvironment"]),
        "unbound helper env override",
    )
    require(
        hashlib.sha256(supplied["M78_EXECUTION_SOURCE"]["value"].encode()).hexdigest()
        == supplied["M78_EXECUTION_SHA256"]["value"],
        "loader byte binding differs",
    )
    require(
        supplied["M78_EXECUTION_SOURCE"]["value"]
        == (Path(__file__).parent / "artifact_transport.py").read_text() + "\nload_probe()\n",
        "only the existing bound artifact loader may run",
    )
    module = (
        "infra.milestone_7_8.queue_grant_intervention"
        if role == "migration"
        else "infra.milestone_7_8.activity_delivery_validation"
    )
    require(
        supplied["M78_PILOT_MODULE"]["value"] == module, "helper module differs from identity scope"
    )
    require(
        supplied.get("M78_PILOT_ARTIFACT_VERSION_ID", {}).get("value"),
        "verified staged exact object version required",
    )
    result = copy.deepcopy(original)
    result["identity"]["userAssignedIdentities"] = {identity["id"]: {}}
    configuration = result["properties"]["configuration"]
    configuration["replicaRetryLimit"] = 0
    configuration["replicaTimeout"] = 660 if role == "migration" else 120
    for registry in configuration["registries"]:
        require(
            registry["server"] == "crm78oa712b8c940.azurecr.io", "exact private registry required"
        )
        registry["identity"] = identity["id"]
    container = result["properties"]["template"]["containers"][0]
    require(
        container["resources"] == {"cpu": 0.5, "memory": "1Gi"},
        "bounded existing helper allocation required",
    )
    env = {row["name"]: row for row in container["env"] if not row["name"].startswith("M78_")}
    require(
        env["OPENCANVAS_DATABASE_ROLE"]["value"] == "migration", "captured original role differs"
    )
    name = identity["id"].rsplit("/", 1)[-1]
    updates = {
        "OPENCANVAS_DATABASE_ROLE": role,
        "OPENCANVAS_DATABASE_URL": f"postgresql+asyncpg://{name}@pg-m78o-a712b8c940.postgres.database.azure.com:5432/opencanvas",
        "OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID": client,
        "OPENCANVAS_AZURE_MANAGED_IDENTITY_CLIENT_ID": client,
        "AZURE_CLIENT_ID": client,
        "OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID": principal,
        "M78_PILOT_STORAGE_HOST": "stm78oa712b8c940.blob.core.windows.net",
        "M78_PILOT_SUFFIX": "a712b8c940",
    }
    env.update({key: {"name": key, "value": value} for key, value in updates.items()})
    env.update(supplied)
    if role == "worker":
        configuration["secrets"] = [
            {
                "name": alias,
                "keyVaultUrl": "https://kv-m78p-a712b8c940.vault.azure.net/secrets/" + key,
                "identity": identity["id"],
            }
            for alias, key in (
                ("outbox-delivery-secret", "opencanvas-outbox-delivery-secret"),
                ("telemetry-token", "opencanvas-telemetry-token"),
                ("telemetry-pseudonym", "opencanvas-telemetry-pseudonymization-secret"),
            )
        ]
        env["OPENCANVAS_OUTBOX_DELIVERY_SECRET"] = {
            "name": "OPENCANVAS_OUTBOX_DELIVERY_SECRET",
            "secretRef": "outbox-delivery-secret",
        }
        env["OPENCANVAS_TELEMETRY_AUTH_TOKEN"] = {
            "name": "OPENCANVAS_TELEMETRY_AUTH_TOKEN",
            "secretRef": "telemetry-token",
        }
        env["OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET"] = {
            "name": "OPENCANVAS_TELEMETRY_PSEUDONYMIZATION_SECRET",
            "secretRef": "telemetry-pseudonym",
        }
        telemetry = {
            "OPENCANVAS_TELEMETRY_ENABLED": "true",
            "OPENCANVAS_TELEMETRY_EXPORTER": "http",
            "OPENCANVAS_TELEMETRY_SERVICE_NAME": "mobius-worker",
            "OPENCANVAS_TELEMETRY_RELEASE": plan["release"],
            "OPENCANVAS_TELEMETRY_DEPLOYMENT": plan["deployment"],
            "OPENCANVAS_TELEMETRY_TLS_VERIFY": "true",
            "OPENCANVAS_TELEMETRY_AUTH_SECRET_REFERENCE": "env://OPENCANVAS_TELEMETRY_AUTH_TOKEN",
            "OPENCANVAS_TELEMETRY_ENDPOINT": "https://ca-m78p-a712b8c940-gateway.internal."
            + plan["managedEnvironmentDefaultDomain"]
            + "/v1/signals",
        }
        env.update({key: {"name": key, "value": value} for key, value in telemetry.items()})
    container["command"] = packed["proofCommand"]
    container.pop("args", None)
    container["env"] = list(env.values())
    return {
        "resourceId": job,
        "beforeSha256": canonical_hash(original),
        "apply": result,
        "restore": original,
        "identityRole": role,
        "noActiveExecutionRequired": True,
        "imageUnchanged": True,
    }


def verify_restored(before, restored):
    require(before["id"] == restored["id"], "restore resource differs")
    require(
        mutable_state(before) == mutable_state(restored),
        "captured template/configuration/identity not restored",
    )
    return True


def admit_runtime_job(plan, readbacks, *, key, role, execution):
    scope = plan["targetResourceGroupId"]
    require(
        scope.endswith("/resourceGroups/rg-m78-a712b8c940-target"), "exact isolated group required"
    )
    expected = plan[key]
    allowed = {
        scope + "/providers/Microsoft.App/jobs/caj-m78p-a712b8c940-" + name
        for name in ("migration", "evidence")
    }
    require(expected in allowed, "unapproved helper/evidence job")
    records = [
        row
        for row in readbacks["resources"]
        if row.get("request", {}).get("resourceId") == expected
    ]
    require(len(records) == 1, "one exact native helper job readback required")
    row = records[0]
    require(
        row["request"]["method"] == "GET"
        and row["request"]["apiVersion"] == "2025-01-01"
        and row["response"]["status"] == 200,
        "native job readback method/version/status differs",
    )
    body = row["response"]["body"]
    require(
        body["id"] == expected
        and body["properties"]["environmentId"] == plan["managedEnvironmentResourceId"]
        and set(body["identity"]["userAssignedIdentities"]) == {identity_id(scope, role)},
        "native job resource/environment/identity differs",
    )
    containers = body["properties"]["template"]["containers"]
    require(
        len(containers) == 1
        and containers[0]["image"].endswith("@" + plan["imageDigest"])
        and containers[0]["command"] == ["python", "-c", SOURCE_VERIFIER],
        "native job source/command differs",
    )
    env = {item["name"]: item for item in containers[0]["env"]}
    require(
        env["OPENCANVAS_DATABASE_ROLE"]["value"] == role
        and execution.startswith(expected.rsplit("/", 1)[-1] + "-")
        and "/" not in execution,
        "actual job execution/role differs",
    )
    return {
        "jobResourceId": expected,
        "jobReadbackSha256": canonical_hash(row),
        "executionId": execution,
        "nativeExecutionTemplateStillRequired": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "identity", "packed", "plan", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--role", choices=("migration", "worker"), required=True)
    args = parser.parse_args()
    require(
        ".runtime" in args.output.resolve().parts, "prepared bodies must remain private runtime"
    )
    result = prepare(
        *(
            json.loads(getattr(args, name).read_text())
            for name in ("before", "identity", "packed", "plan")
        ),
        args.role,
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2)
    for name in ("apply", "restore"):
        with args.output.with_suffix("." + name + ".json").open("x", encoding="utf-8") as output:
            json.dump(result[name], output, indent=2)


if __name__ == "__main__":
    main()

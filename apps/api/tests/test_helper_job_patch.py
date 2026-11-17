from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from infra.milestone_7_8.pilot.helper_job_patch import (
    admit_runtime_job,
    identity_id,
    prepare,
    verify_restored,
)
from infra.milestone_7_8.pilot.pack_execution import SOURCE_VERIFIER


def fixture(role="worker"):
    scope = (
        "/subscriptions/00000000-0000-0000-0000-000000000001"
        "/resourceGroups/rg-m78-a712b8c940-target"
    )
    job = scope + "/providers/Microsoft.App/jobs/caj-m78p-a712b8c940-migration"
    plan = {
        "targetResourceGroupId": scope,
        "helperJobResourceId": job,
        "activityDeliveryJobResourceId": job,
        "managedEnvironmentResourceId": scope
        + "/providers/Microsoft.App/managedEnvironments/cae-m78o-a712b8c940",
        "managedEnvironmentDefaultDomain": "local.eastus.azurecontainerapps.io",
        "imageDigest": "sha256:" + "1" * 64,
        "release": "test-release",
        "deployment": "m78p-a712b8c940",
    }
    before = {
        "id": job,
        "identity": {
            "type": "UserAssigned",
            "userAssignedIdentities": {identity_id(scope, "migration"): {}},
        },
        "properties": {
            "environmentId": plan["managedEnvironmentResourceId"],
            "configuration": {
                "triggerType": "Manual",
                "secrets": [],
                "replicaTimeout": 1800,
                "registries": [
                    {
                        "server": "crm78oa712b8c940.azurecr.io",
                        "identity": identity_id(scope, "migration"),
                    }
                ],
            },
            "template": {
                "containers": [
                    {
                        "name": "migration",
                        "image": "crm78oa712b8c940.azurecr.io/opencanvas-api@"
                        + plan["imageDigest"],
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                        "command": ["python", "-m", "scripts.migrate_and_grant"],
                        "env": [{"name": "OPENCANVAS_DATABASE_ROLE", "value": "migration"}],
                    }
                ]
            },
        },
    }
    identity = {
        "id": identity_id(scope, role),
        "properties": {
            "clientId": "00000000-0000-0000-0000-000000000002",
            "principalId": "00000000-0000-0000-0000-000000000003",
        },
    }
    source = (
        Path("infra/milestone_7_8/pilot/artifact_transport.py").read_text() + "\nload_probe()\n"
    )
    module = "queue_grant_intervention" if role == "migration" else "activity_delivery_validation"
    values = {
        "M78_EXECUTION_SOURCE": source,
        "M78_EXECUTION_SHA256": hashlib.sha256(source.encode()).hexdigest(),
        "M78_PILOT_MODULE": "infra.milestone_7_8." + module,
        "M78_PILOT_ARTIFACT_VERSION_ID": "native-test-version",
    }
    packed = {
        "proofCommand": ["python", "-c", SOURCE_VERIFIER],
        "proofEnvironment": [{"name": k, "value": v} for k, v in values.items()],
    }
    return before, identity, packed, plan


@pytest.mark.parametrize("role", ["worker", "migration"])
def test_helper_has_one_exact_identity_and_restores_original_template(role):
    before, identity, packed, plan = fixture(role)
    untouched = copy.deepcopy(before)
    result = prepare(before, identity, packed, plan, role)
    assert before == untouched
    assert set(result["apply"]["identity"]["userAssignedIdentities"]) == {identity["id"]}
    container = result["apply"]["properties"]["template"]["containers"][0]
    assert container["image"] == before["properties"]["template"]["containers"][0]["image"]
    assert result["apply"]["properties"]["configuration"]["replicaTimeout"] == (
        120 if role == "worker" else 660
    )
    restored = {**before, **result["restore"]}
    restored["properties"]["environmentId"] = plan["managedEnvironmentResourceId"]
    assert verify_restored(before, restored)
    restored["identity"]["userAssignedIdentities"] = {
        identity_id(plan["targetResourceGroupId"], "worker"): {}
    }
    with pytest.raises(ValueError, match="not restored"):
        verify_restored(before, restored)


def test_wrong_job_or_native_identity_is_rejected_before_patch():
    before, identity, packed, plan = fixture()
    wrong = copy.deepcopy(before)
    wrong["id"] += "-unrelated"
    with pytest.raises(ValueError, match="existing migration"):
        prepare(wrong, identity, packed, plan, "worker")
    wrong_identity = copy.deepcopy(identity)
    wrong_identity["id"] = identity_id(plan["targetResourceGroupId"], "migration")
    with pytest.raises(ValueError, match="native identity"):
        prepare(before, wrong_identity, packed, plan, "worker")


def test_native_job_admission_binds_exact_execution_source_identity():
    before, identity, packed, plan = fixture()
    changed = prepare(before, identity, packed, plan, "worker")["apply"]
    body = {**before, **changed, "properties": {**before["properties"], **changed["properties"]}}
    records = {
        "resources": [
            {
                "request": {
                    "resourceId": before["id"],
                    "method": "GET",
                    "apiVersion": "2025-01-01",
                },
                "response": {"status": 200, "body": body},
            }
        ]
    }
    execution = "caj-m78p-a712b8c940-migration-native"
    assert (
        admit_runtime_job(
            plan, records, key="activityDeliveryJobResourceId", role="worker", execution=execution
        )["executionId"]
        == execution
    )
    with pytest.raises(ValueError, match="execution/role"):
        admit_runtime_job(
            plan,
            records,
            key="activityDeliveryJobResourceId",
            role="worker",
            execution="caj-unrelated-native",
        )

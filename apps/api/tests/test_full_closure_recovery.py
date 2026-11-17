from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from infra.milestone_7_8.pilot_recovery_acceptance import (
    RECOVERY_PHASES,
    collect_recovery,
    reconcile_recovery,
)


def chain():
    plan = {
        "sourceCommit": "a" * 40,
        "imageDigest": "sha256:" + "b" * 64,
        "targetResourceGroupId": "/isolated-test",
        "databaseResourceId": "/isolated-test/source",
        "restoredDatabaseResourceId": "/isolated-test/restore",
    }
    now = datetime(2026, 11, 17, tzinfo=UTC)
    evidence = {
        "quiescence": {"activeWrites": 0, "workerStopped": True, "outboxStopped": True},
        "snapshot": {"tables": "private-hashed-inventory"},
        "restore": {
            "sourceServerId": plan["databaseResourceId"],
            "restoredServerId": plan["restoredDatabaseResourceId"],
            "nativeProvisioningState": "Succeeded",
            "sourceSchema": "20260726_0029",
            "targetSchema": "20260726_0029",
            "restorePoint": now.isoformat(),
            "latestAcknowledgedCommit": (now + timedelta(seconds=2)).isoformat(),
            "requestedAt": (now + timedelta(seconds=5)).isoformat(),
        },
        "roles-api": {
            "role": "api",
            "freshIdentitySession": True,
            "ownershipAndPrivileges": "accepted",
        },
        "roles-worker": {
            "role": "worker",
            "freshIdentitySession": True,
            "ownershipAndPrivileges": "accepted",
        },
        "verify": {
            key: True
            for key in (
                "postReplayAllRowsUnchanged",
                "appendOnlyRejected",
                "scopeDenial",
                "jointManifestEquality",
                "exactFileChecksum",
                "staleResultPublicationRejected",
            )
        },
        "fence": {
            "staleLeaseRejected": True,
            "providerSuccessDbRollback": True,
            "absenceReconciled": True,
            "deletionEffects": 1,
            "jobId": "one-job",
        },
        "resume": {"jobId": "one-job", "durableOutcomes": 1, "status": "succeeded"},
        "rollback": {
            "databaseResourceId": plan["databaseResourceId"],
            "originalSourceRetained": True,
            "effectsReconciled": True,
            "ready": True,
        },
    }
    evidence["verify"]["servingReadyAt"] = (now + timedelta(seconds=35)).isoformat()
    records = []
    previous = None
    for i, phase in enumerate(RECOVERY_PHASES):
        record = {
            "phase": phase,
            **{k: plan[k] for k in ("sourceCommit", "imageDigest", "targetResourceGroupId")},
            "previousSha256": previous,
            "status": "accepted",
            "observedAt": (now + timedelta(minutes=i)).isoformat(),
            "evidence": evidence[phase],
            "evidenceSha256": digest(evidence[phase]),
        }
        records.append(record)
        previous = digest(record)
    return plan, records


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def rebind(records):
    previous = None
    for record in records:
        record["evidenceSha256"] = digest(record["evidence"])
        record["previousSha256"] = previous
        previous = digest(record)


def test_recovery_chain_measures_instead_of_inventing_targets():
    plan, records = chain()
    result = reconcile_recovery(plan, records)
    assert result["restoreRtoSeconds"] == 30
    assert result["acknowledgedCommitExposureSeconds"] == 2
    assert "zero data loss" in result["rpoQualification"]


@pytest.mark.parametrize(
    "phase,key,value",
    [
        ("quiescence", "outboxStopped", False),
        ("verify", "postReplayAllRowsUnchanged", False),
        ("verify", "staleResultPublicationRejected", False),
        ("resume", "durableOutcomes", 2),
        ("fence", "deletionEffects", 2),
        ("roles-worker", "freshIdentitySession", False),
        ("rollback", "effectsReconciled", False),
    ],
)
def test_partial_or_repeated_effect_never_closes_recovery(phase, key, value):
    plan, records = chain()
    next(r for r in records if r["phase"] == phase)["evidence"][key] = value
    rebind(records)
    with pytest.raises(ValueError):
        reconcile_recovery(plan, records)


def test_0028_requires_real_migration_evidence_before_unlock():
    plan, records = chain()
    r = next(r for r in records if r["phase"] == "restore")["evidence"]
    r["sourceSchema"] = "20260726_0028"
    rebind(records)
    with pytest.raises(ValueError, match="0028 restore"):
        reconcile_recovery(plan, records)
    r.update(
        guardedMigrationReceiptSha256="c" * 64,
        preexistingRowsUnchanged=True,
        effectsLockedUntilMigration=True,
    )
    rebind(records)
    assert reconcile_recovery(plan, records)["status"] == "accepted"


async def test_stale_restored_result_cannot_replace_real_publication(
    app, client, api_prefix, database, tmp_path
):
    import uuid

    from infra.milestone_7_8.pilot_application_probe import Journal
    from infra.milestone_7_8.pilot_recovery_acceptance import verify_stale_publication

    from opencanvas_api.core.config import get_settings
    from opencanvas_api.db.models import SYSTEM_USER_ID
    from tests.test_canvas_api import _create_canvas
    from tests.test_indexer import _register_canvas_resource, _upload_ready_document

    canvas = await _create_canvas(client, api_prefix, "Recovery stale publication")
    await _register_canvas_resource(
        database, workspace_id=uuid.UUID(canvas["workspaceId"]), canvas_id=uuid.UUID(canvas["id"])
    )
    document = await _upload_ready_document(client, api_prefix, canvas["id"])
    response = await client.post(
        f"{api_prefix}/workspaces/{canvas['workspaceId']}/canvases/{canvas['id']}/documents/{document['id']}/versions/1/index-requests",
        json={"idempotencyKey": "recovery-native-initial"},
    )
    assert response.status_code == 202, response.text
    plan, _ = chain()
    journal = Journal(
        tmp_path / "stale.json",
        "actual-local-recovery",
        "restore-verify",
        {**plan, "release": "local", "deployment": "local"},
        datetime.now(UTC) + timedelta(minutes=3),
    )
    fixture = {
        "userId": str(SYSTEM_USER_ID),
        "canvasId": canvas["id"],
        "workspaceId": canvas["workspaceId"],
        "primary": {"documentId": document["id"]},
    }
    result = await verify_stale_publication(
        database, app.dependency_overrides[get_settings](), fixture, journal
    )
    assert result["status"] == "accepted" and result["noNewPublication"] is True


async def test_restored_scope_validator_uses_actual_two_user_authorization(
    app, database, tmp_path, monkeypatch
):
    import httpx
    from infra.milestone_7_8.pilot_application_probe import Api, Journal
    from infra.milestone_7_8.pilot_recovery_acceptance import verify_scope_denial

    from opencanvas_api.core.config import get_settings
    from tests.test_indexer import _upload_ready_document

    original = app.dependency_overrides[get_settings]()
    app.dependency_overrides[get_settings] = lambda: original.model_copy(
        update={"auth_test_bypass": False}
    )
    first = "recovery-primary@example.test"
    second = "recovery-secondary@example.test"
    password = "LocalRecoveryPass123"
    monkeypatch.setenv("OPENCANVAS_PILOT_EMAIL", first)
    monkeypatch.setenv("OPENCANVAS_PILOT_PASSWORD", password)
    monkeypatch.setenv("OPENCANVAS_PILOT_SECONDARY_EMAIL", second)
    monkeypatch.setenv("OPENCANVAS_PILOT_SECONDARY_PASSWORD", password)
    plan, _ = chain()
    journal = Journal(
        tmp_path / "scope.json",
        "scope-local",
        "restore-verify",
        {**plan, "release": "local", "deployment": "local"},
        datetime.now(UTC) + timedelta(minutes=2),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local.test"
    ) as client:
        api = Api(client, journal, "scope-local")
        for email in [first, second]:
            created = await client.post(
                "/api/v1/auth/signup",
                json={"email": email, "password": password, "displayName": "Synthetic recovery"},
            )
            assert created.status_code == 201, created.text
        user = await api.signin()
        primary = await api.request(
            "POST",
            "/api/v1/canvases",
            data={"name": "Primary", "idempotencyKey": "scope-primary"},
            statuses=(201,),
        )
        # Exercise a real stored file boundary, not only a nonexistent identifier.
        client.headers["X-CSRF-Token"] = api.csrf
        document = await _upload_ready_document(client, "/api/v1", primary["id"])
        other = await api.signin(secondary=True)
        foreign = await api.request(
            "POST",
            "/api/v1/canvases",
            data={"name": "Foreign", "idempotencyKey": "scope-foreign"},
            statuses=(201,),
        )
        fixture = {
            "userId": user["id"],
            "workspaceId": primary["workspaceId"],
            "canvasId": primary["id"],
            "primary": {"documentId": document["id"]},
            "foreign": {
                "userId": other["id"],
                "workspaceId": foreign["workspaceId"],
                "canvasId": foreign["id"],
            },
        }
        result = await verify_scope_denial(api, fixture)
        assert result["status"] == "accepted" and len(result["checks"]) == 4


def raw_recovery_export(tmp_path):
    """Local transport fixtures: these test admission, never claim managed proof."""
    from infra.milestone_7_8.pilot_application_probe import RELATED_TABLES, SNAPSHOT_TABLES

    plan, _ = chain()
    plan.update(
        release="current-test-release",
        deployment="isolated-test-deployment",
        workerResourceId="/isolated-test/providers/Microsoft.App/containerApps/worker",
        dispatcherResourceId="/isolated-test/providers/Microsoft.App/containerApps/dispatcher",
        recoveryJobResourceIds=["/isolated-test/providers/Microsoft.App/jobs/proof"],
    )
    base = datetime(2026, 11, 17, tzinfo=UTC)

    def at(seconds):
        return (base + timedelta(seconds=seconds)).isoformat()

    raw = {}
    manifest = {"artifacts": {}, "executions": {}, "exclusiveSyntheticWriters": True}

    def native(name, resource, version, body, observed):
        raw[name] = {
            "request": {"method": "GET", "resourceId": resource, "apiVersion": version},
            "response": {"status": 200, "body": {"id": resource, **body}},
            "observedAt": at(observed),
        }

    def probe(name, operation, start, finish, content):
        execution = "proof-" + name
        resource = plan["recoveryJobResourceIds"][0] + "/executions/" + execution
        manifest["executions"][name] = resource
        raw[name] = {
            **{key: plan[key] for key in ("sourceCommit", "imageDigest", "release", "deployment")},
            "operation": operation,
            "executionId": execution,
            "startedAt": at(start),
            "finishedAt": at(finish),
            **content,
        }
        native(
            name + "-execution",
            resource,
            "2025-01-01",
            {
                "name": execution,
                "properties": {
                    "status": "Succeeded",
                    "startTime": at(start - 0.1),
                    "endTime": at(finish + 0.1),
                    "template": {
                        "containers": [
                            {
                                "image": "private.example/api@" + plan["imageDigest"],
                                "command": [
                                    "python",
                                    "-m",
                                    "infra.milestone_7_8.pilot_application_probe",
                                ],
                                "args": [operation],
                            }
                        ]
                    },
                },
            },
            finish + 0.2,
        )

    for name, key in (("worker-stop", "workerResourceId"), ("outbox-stop", "dispatcherResourceId")):
        native(
            name,
            plan[key],
            "2025-01-01",
            {
                "properties": {
                    "runningStatus": "Stopped",
                    "template": {
                        "containers": [{"image": "private.example/api@" + plan["imageDigest"]}]
                    },
                }
            },
            0,
        )
    tables = {name: [] for name in (*SNAPSHOT_TABLES, *RELATED_TABLES)}
    for name in (
        "legacy_creation_request_identities",
        "upload_sessions",
        "storage_object_versions",
        "malware_scan_results",
        "object_promotions",
        "index_publications",
        "retrieval_heads",
    ):
        tables[name] = [{"identity": {"id": name + "-id"}, "sha256": "c" * 64}]
    tables["document_processing_jobs"] = [{"identity": {"id": "retained-job"}, "sha256": "d" * 64}]
    tables["object_deletion_requests"] = [
        {"identity": {"deletion_request_id": "retained-deletion"}, "sha256": "e" * 64}
    ]
    state = {
        "tables": tables,
        "schemaRevision": "20260726_0029",
        "identity": {"role": "observer", "database": "synthetic", "tls": True, "privileged": False},
        "workspaceId": "same-workspace",
        "grants": [{"table_name": "documents", "privilege_type": "SELECT"}],
    }
    probe(
        "recovery-fixture",
        "restore-fixture",
        1,
        3,
        {
            "nonterminal": {
                "jobId": "retained-job",
                "deletionRequestId": "retained-deletion",
                "deletionObjectVersionId": "storage_object_versions-id",
                "latestAcknowledgedMutationAt": at(2),
            }
        },
    )
    for name, start, finish in (("quiescent-before", 4, 5), ("snapshot", 6, 7)):
        probe(
            name,
            "restore-snapshot",
            start,
            finish,
            {"snapshot": {**deepcopy(state), "observedAt": at(start + 0.5)}},
        )
    native(
        "restored-server",
        plan["restoredDatabaseResourceId"],
        "2025-08-01",
        {"properties": {"state": "Ready"}},
        10,
    )
    raw["restore-intent"] = {
        "request": {
            "method": "PUT",
            "resourceId": plan["restoredDatabaseResourceId"],
            "apiVersion": "2025-08-01",
            "body": {
                "properties": {
                    "createMode": "PointInTimeRestore",
                    "sourceServerResourceId": plan["databaseResourceId"],
                    "pointInTimeUTC": at(8),
                }
            },
        },
        "requestedAt": at(9),
    }
    for role, start in (("api", 11), ("worker", 13)):
        probe(
            "roles-" + role,
            "restore-role",
            start,
            start + 1,
            {
                "role": role,
                "tablesChecked": 20,
                "runtimeReport": {
                    "dialect": "postgresql",
                    "schema_revision": "20260726_0029",
                    "database_user": role,
                },
                "assertions": {"R2FreshRuntimeRoleOwnershipPositiveNegativePrivileges": "accepted"},
            },
        )
    probe(
        "verify",
        "restore-verify",
        15,
        16,
        {
            "snapshot": {**deepcopy(state), "observedAt": at(15.5)},
            "scopeDenial": {"status": "accepted"},
            "stalePublication": {"noNewPublication": True},
            "assertions": {
                key: "accepted"
                for key in (
                    "R1RestoredIdentityRows",
                    "R4JointManifestRows",
                    "R1AppendOnlyAndReplay",
                    "R1CreationReplay",
                    "R4RestoredServing",
                    "R2RestoredScopeDenial",
                    "R4StaleResultAndPublication",
                )
            },
        },
    )
    fences = {
        key: "accepted"
        for key in ("staleLeaseRejected", "exactVersionAbsentRetry", "singleDeletionEffect")
    }
    fences["resumeJobId"] = "retained-job"
    resumed = {
        "jobId": "retained-job",
        "assertions": {"R3RestoredWorkerResumptionOneEffect": "accepted"},
    }
    probe("fence", "restore-fence", 17, 18, fences)
    probe("resume", "restore-resume", 19, 20, resumed)
    probe(
        "rollback",
        "restore-rollback",
        21,
        22,
        {
            "assertions": {"RollbackOriginalEffectsAndServing": "accepted"},
            "originalSourceRetained": True,
            "effectsReconciled": True,
            "ready": True,
            "fences": deepcopy(fences),
            "resume": deepcopy(resumed),
        },
    )

    def export():
        for name, value in raw.items():
            path = tmp_path / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            manifest["artifacts"][name] = {
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        return plan, manifest

    export()
    return plan, manifest, raw, export


def test_collect_recovery_binds_raw_native_executions_and_actual_mutation_ack(tmp_path):
    plan, manifest, raw, export = raw_recovery_export(tmp_path)
    # Equivalent non-UTC representations must compare as instants, not strings.
    raw["quiescent-before"]["finishedAt"] = "2026-11-17T01:00:05+01:00"
    export()
    result = collect_recovery(plan, manifest, tmp_path)
    assert result["status"] == "accepted" and result["restoreRtoSeconds"] == 7
    assert result["acknowledgedCommitExposureSeconds"] == 0
    assert len(result["executionIds"]) == 9
    restore = next(row["evidence"] for row in result["chain"] if row["phase"] == "restore")
    assert (
        restore["latestAcknowledgedCommit"]
        == raw["recovery-fixture"]["nonterminal"]["latestAcknowledgedMutationAt"]
    )
    assert restore["latestAcknowledgedCommit"] != raw["snapshot"]["finishedAt"]
    assert "not a claim of zero global data loss" in result["rpoQualification"]


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "path",
        "scope",
        "image",
        "execution-end",
        "naive",
        "stop-late",
        "empty-stopped",
        "snapshot-partial",
        "workspace",
        "restore-point",
        "snapshot-time",
        "reordered",
        "role",
        "rollback",
        "marker-time",
        "marker-id",
        "operation",
        "release",
    ],
)
def test_collect_recovery_rejects_tampered_or_incomplete_observations(tmp_path, mutation):
    plan, manifest, raw, export = raw_recovery_export(tmp_path)
    if mutation == "hash":
        (tmp_path / "verify.json").write_text("{}")
    elif mutation == "path":
        manifest["artifacts"]["verify"]["path"] = "../outside.json"
    else:
        if mutation == "scope":
            manifest["executions"]["verify"] = "/unrelated/jobs/proof/executions/proof-verify"
        elif mutation == "image":
            raw["verify-execution"]["response"]["body"]["properties"]["template"]["containers"][0][
                "image"
            ] = "different:latest"
        elif mutation == "execution-end":
            raw["verify-execution"]["response"]["body"]["properties"]["endTime"] = raw["verify"][
                "startedAt"
            ]
        elif mutation == "naive":
            raw["verify"]["startedAt"] = "2026-11-17T00:00:15"
        elif mutation == "stop-late":
            raw["worker-stop"]["observedAt"] = raw["snapshot"]["finishedAt"]
        elif mutation == "empty-stopped":
            raw["worker-stop"]["response"]["body"]["properties"]["template"]["containers"] = []
        elif mutation == "snapshot-partial":
            for name in ("quiescent-before", "snapshot", "verify"):
                raw[name]["snapshot"]["tables"].pop("trace_events")
        elif mutation == "workspace":
            raw["snapshot"]["snapshot"]["workspaceId"] = "other-workspace"
        elif mutation == "restore-point":
            raw["restore-intent"]["request"]["body"]["properties"]["pointInTimeUTC"] = raw[
                "quiescent-before"
            ]["startedAt"]
        elif mutation == "snapshot-time":
            raw["snapshot"]["snapshot"]["observedAt"] = raw["verify"]["finishedAt"]
        elif mutation == "reordered":
            raw["verify"]["startedAt"] = raw["roles-worker"]["startedAt"]
        elif mutation == "role":
            raw["roles-worker"]["runtimeReport"]["dialect"] = "sqlite"
        elif mutation == "rollback":
            raw["rollback"]["resume"]["jobId"] = "different-job"
        elif mutation == "marker-time":
            raw["recovery-fixture"]["nonterminal"]["latestAcknowledgedMutationAt"] = raw["verify"][
                "finishedAt"
            ]
        elif mutation == "marker-id":
            raw["recovery-fixture"]["nonterminal"]["deletionRequestId"] = "unrelated-deletion"
        elif mutation == "operation":
            raw["verify-execution"]["response"]["body"]["properties"]["template"]["containers"][0][
                "args"
            ] = ["restore-snapshot"]
        elif mutation == "release":
            raw["verify"]["sourceCommit"] = "f" * 40
        export()
    with pytest.raises(ValueError):
        collect_recovery(plan, manifest, tmp_path)


@pytest.mark.parametrize("wrong_job,bad_content", [(False, False), (True, False), (False, True)])
async def test_original_rollback_checks_fence_resume_and_served_bytes(
    monkeypatch, wrong_job, bad_content
):
    from unittest.mock import AsyncMock

    from infra.milestone_7_8 import pilot_application_probe
    from infra.milestone_7_8.pilot_recovery_acceptance import reconcile_original_after_restore

    fences = {
        key: "accepted"
        for key in ("staleLeaseRejected", "exactVersionAbsentRetry", "singleDeletionEffect")
    }
    fences["resumeJobId"] = "retained-job"
    fence = AsyncMock(return_value=fences)
    resume = AsyncMock(
        return_value={
            "jobId": "different" if wrong_job else "retained-job",
            "assertions": {"R3RestoredWorkerResumptionOneEffect": "accepted"},
        }
    )
    monkeypatch.setattr(pilot_application_probe, "restore_fence", fence)
    monkeypatch.setattr(pilot_application_probe, "restored_resume", resume)
    api = AsyncMock()
    api.request.return_value = b"wrong" if bad_content else b"real fixture"
    api.ground.return_value = {"status": "accepted"}
    fixture = {
        "primary": {
            "documentId": "actual-document",
            "contentSha256": hashlib.sha256(b"real fixture").hexdigest(),
        }
    }
    retained = {"nonterminal": {"jobId": "retained-job"}}
    if wrong_job or bad_content:
        with pytest.raises(ValueError):
            await reconcile_original_after_restore(None, None, fixture, retained, api, None)
        api.ground.assert_not_awaited()
    else:
        result = await reconcile_original_after_restore(None, None, fixture, retained, api, None)
        assert result["effectsReconciled"] is True and result["ready"] is True
        api.request.assert_awaited_once_with("GET", "/api/v1/documents/actual-document/file")
    fence.assert_awaited_once()
    resume.assert_awaited_once()


async def test_original_rollback_does_not_resume_after_incomplete_fencing(monkeypatch):
    from unittest.mock import AsyncMock

    from infra.milestone_7_8 import pilot_application_probe
    from infra.milestone_7_8.pilot_recovery_acceptance import reconcile_original_after_restore

    fence = AsyncMock(return_value={"staleLeaseRejected": "unproved"})
    resume = AsyncMock()
    monkeypatch.setattr(pilot_application_probe, "restore_fence", fence)
    monkeypatch.setattr(pilot_application_probe, "restored_resume", resume)
    with pytest.raises(ValueError, match="original fencing"):
        await reconcile_original_after_restore(
            None, None, {}, {"nonterminal": {"jobId": "retained"}}, AsyncMock(), None
        )
    resume.assert_not_awaited()


def packed_recovery_export(tmp_path, monkeypatch):
    from infra.milestone_7_8.pilot import pack_execution

    directory = tmp_path / ".runtime"
    directory.mkdir()
    plan, manifest, raw, export = raw_recovery_export(directory)
    original_root = pack_execution.ROOT
    monkeypatch.setattr(pack_execution, "ROOT", tmp_path)
    wheel_directory = directory / "wheels"
    wheel_directory.mkdir()
    wheels = []
    for index in range(8):
        # Transport-only local wheel fixtures, never installed or executed.
        name = f"transport_fixture_{index}-0-py3-none-any.whl"
        data = pack_execution.archive({f"fixture{index}.txt": b"local transport check"})
        (wheel_directory / name).write_bytes(data)
        wheels.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    wheel_manifest = directory / "wheels.json"
    wheel_manifest.write_text(json.dumps({"wheels": wheels}))
    sources = {}
    for relative in (
        "infra/milestone_7_8/pilot_validation.py",
        "infra/milestone_7_8/pilot_alerts.py",
        "infra/milestone_7_8/pilot_application_probe.py",
        "infra/milestone_7_8/pilot/probe-requirements.txt",
    ):
        data = (
            "\n".join(wheel["sha256"] for wheel in wheels).encode()
            if relative.endswith("probe-requirements.txt")
            else (original_root / relative).read_bytes()
        )
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        sources[relative] = hashlib.sha256(data).hexdigest()
    bundle = directory / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({"sourceBindings": sources}))
    (bundle / "catalog.json").write_text("{}")
    authorization = directory / "approval.json"
    authorization.write_text('{"localFixtureOnly":true}')
    bindings = directory / "bindings.json"
    bindings.write_text(json.dumps(plan))
    output = directory / "packed.json"
    pack_execution.pack(
        bundle,
        authorization,
        bindings,
        "infra.milestone_7_8.pilot_application_probe",
        ["restore-verify", "--execution-id", "${EXECUTION_ID}", "--execute"],
        output,
        wheel_manifest,
        wheel_directory,
    )
    packed = json.loads(output.read_text())
    container = raw["verify-execution"]["response"]["body"]["properties"]["template"]["containers"][
        0
    ]
    container.update(command=packed["proofCommand"], args=[], env=packed["proofEnvironment"])
    manifest["executionArtifacts"] = {
        "verify": {"path": "packed.zip", "sha256": packed["artifactSha256"]}
    }
    export()
    return directory, plan, manifest, raw, export


def test_collect_recovery_accepts_actual_pack_execution_environment(tmp_path, monkeypatch):
    directory, plan, manifest, raw, _ = packed_recovery_export(tmp_path, monkeypatch)
    container = raw["verify-execution"]["response"]["body"]["properties"]["template"]["containers"][
        0
    ]
    assert "restore-verify" not in container["command"] + container["args"]
    result = collect_recovery(plan, manifest, directory)
    assert result["status"] == "accepted"
    assert (
        result["sourceArtifacts"]["verify-archive"]
        == manifest["executionArtifacts"]["verify"]["sha256"]
    )


@pytest.mark.parametrize(
    "tamper",
    [
        "loader",
        "loader-hash",
        "module",
        "operation",
        "artifact-hash",
        "archive",
        "missing-archive",
        "duplicate-env",
    ],
)
def test_collect_recovery_rejects_packed_execution_binding_tampering(tmp_path, monkeypatch, tamper):
    directory, plan, manifest, raw, export = packed_recovery_export(tmp_path, monkeypatch)
    container = raw["verify-execution"]["response"]["body"]["properties"]["template"]["containers"][
        0
    ]
    environment = {entry["name"]: entry for entry in container["env"]}
    if tamper == "loader":
        value = environment["M78_EXECUTION_SOURCE"]["value"] + "\n# changed loader\n"
        environment["M78_EXECUTION_SOURCE"]["value"] = value
        environment["M78_EXECUTION_SHA256"]["value"] = hashlib.sha256(value.encode()).hexdigest()
    elif tamper == "loader-hash":
        environment["M78_EXECUTION_SHA256"]["value"] = "a" * 64
    elif tamper == "module":
        environment["M78_PILOT_MODULE"]["value"] = "infra.milestone_7_8.pilot_validation"
    elif tamper == "operation":
        environment["M78_PILOT_ARGUMENTS_JSON"]["value"] = '["restore-snapshot"]'
    elif tamper == "artifact-hash":
        environment["M78_PILOT_ARTIFACT_SHA256"]["value"] = "a" * 64
    elif tamper == "archive":
        (directory / "packed.zip").write_bytes(b"changed archive")
    elif tamper == "missing-archive":
        manifest.pop("executionArtifacts")
    elif tamper == "duplicate-env":
        container["env"].append(dict(environment["M78_PILOT_MODULE"]))
    export()
    with pytest.raises(ValueError):
        collect_recovery(plan, manifest, directory)

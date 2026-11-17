"""Current-release recovery acceptance; no provisioning or historical campaign replay."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timezone-aware recovery timestamp required")
    return result


async def verify_scope_denial(api: Any, fixture: dict) -> dict:
    foreign = fixture["foreign"]
    require(
        foreign["workspaceId"] != fixture["workspaceId"] and foreign["userId"] != fixture["userId"],
        "independent persisted scope required",
    )
    await api.signin()
    hidden = await api.request(
        "GET", f"/api/v1/canvases/{foreign['canvasId']}/snapshot", statuses=(404,)
    )
    absent = await api.request("GET", f"/api/v1/canvases/{uuid.uuid4()}/snapshot", statuses=(404,))
    require(hidden.get("code") == absent.get("code"), "foreign resource is enumerable")
    await api.signin(secondary=True)
    primary = await api.request(
        "GET", f"/api/v1/canvases/{fixture['canvasId']}/snapshot", statuses=(404,)
    )
    document = await api.request(
        "GET",
        f"/api/v1/documents/{fixture['primary']['documentId']}/file",
        statuses=(404,),
    )
    require(
        primary.get("code") == hidden.get("code") and isinstance(document.get("code"), str),
        "restored denial contract changed",
    )
    await api.signin()
    return {
        "status": "accepted",
        "checks": [
            "primary-cannot-read-foreign",
            "foreign-cannot-read-primary",
            "foreign-cannot-read-primary-file",
            "foreign-and-absent-non-enumerating",
        ],
    }


async def verify_stale_publication(db: Any, settings: Any, fixture: dict, journal: Any) -> dict:
    from sqlalchemy import select

    from opencanvas_api.db.models import Document, IndexPublication, RetrievalHead
    from opencanvas_api.services.auth import Principal
    from opencanvas_api.services.documents import (
        build_document_storage,
        build_embedding_provider,
    )
    from opencanvas_api.services.indexer import IndexerConflictError, IngestionService

    document_id = uuid.UUID(fixture["primary"]["documentId"])
    workspace = uuid.UUID(fixture["workspaceId"])
    canvas = uuid.UUID(fixture["canvasId"])
    principal = Principal(
        user_id=uuid.UUID(fixture["userId"]),
        email="scoped-recovery@mobius.invalid",
        display_name="Recorded request actor",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )

    def service(session: Any) -> IngestionService:
        return IngestionService(
            session,
            settings=settings,
            storage=build_document_storage(settings),
            provider=build_embedding_provider(settings),
        )

    async def state(session: Any) -> dict:
        head = await session.scalar(
            select(RetrievalHead).where(RetrievalHead.document_id == document_id)
        )
        rows = list(
            (
                await session.scalars(
                    select(IndexPublication.publication_id).where(
                        IndexPublication.document_id == document_id
                    )
                )
            ).all()
        )
        require(head is not None, "published restored head required")
        return {
            "head": str(head.publication_id),
            "revision": str(head.revision_id),
            "generation": head.generation,
            "publications": sorted(map(str, rows)),
        }

    async with db.sessions() as session:
        before = await state(session)
        document = await session.get(Document, document_id)
        require(
            document is not None and document.status == "ready",
            "current restored document required",
        )
        view = await service(session).request(
            principal=principal,
            workspace_id=workspace,
            canvas_id=canvas,
            document_id=document_id,
            document_version=document.current_version,
            idempotency_key=journal.header["executionId"] + ":stale-restored-publication",
            operation="reindex",
        )
        request_id = view.request.request_id
        await session.commit()
    journal.step("stale-publication-request", {"requestId": str(request_id)})
    async with db.sessions() as session:
        revision = await service(session).build(request_id)
        require(revision is not None, "real completed revision required")
        revision_id = revision.revision_id
        await session.commit()
    async with db.sessions() as session:
        await service(session).cancel(
            principal=principal,
            workspace_id=workspace,
            canvas_id=canvas,
            request_id=request_id,
        )
        await session.commit()
    journal.step(
        "stale-publication-canceled",
        {"requestId": str(request_id), "revisionId": str(revision_id)},
    )
    async with db.sessions() as session:
        try:
            await service(session).publish(request_id, revision_id)
        except IndexerConflictError:
            await session.rollback()
        else:
            await session.rollback()
            raise ValueError("canceled restored result was publishable")
    async with db.sessions() as session:
        after = await state(session)
        require(
            before == after and str(revision_id) != after["revision"],
            "stale result changed restored serving or publication effects",
        )
    return {
        "status": "accepted",
        "rejectedRequestId": str(request_id),
        "rejectedRevisionId": str(revision_id),
        "currentPublication": before,
        "noNewPublication": True,
    }


RECOVERY_PHASES = (
    "quiescence",
    "snapshot",
    "restore",
    "roles-api",
    "roles-worker",
    "verify",
    "fence",
    "resume",
    "rollback",
)


async def reconcile_original_after_restore(
    db: Any, settings: Any, fixture: dict, retained: dict, api: Any, journal: Any
) -> dict:
    """Reconcile shared provider effects before unlocking the retained original.

    The source worker and dispatcher remain stopped. Existing exact-scope guards
    fence the original expired lease and reconcile the same provider version,
    whose deletion may already have committed on the restored database.
    """
    from infra.milestone_7_8.pilot_application_probe import (
        restore_fence,
        restored_resume,
    )

    fences = await restore_fence(db, settings, fixture, retained, journal)
    require(
        all(
            fences.get(k) == "accepted"
            for k in ("staleLeaseRejected", "exactVersionAbsentRetry", "singleDeletionEffect")
        )
        and fences.get("resumeJobId") == retained["nonterminal"]["jobId"],
        "original fencing did not reconcile the retained job",
    )
    resumed = await restored_resume(db, settings, fixture, retained, journal)
    require(
        resumed.get("assertions", {}).get("R3RestoredWorkerResumptionOneEffect") == "accepted"
        and resumed.get("jobId") == fences.get("resumeJobId") == retained["nonterminal"]["jobId"],
        "original effects were not reconciled for the retained job",
    )
    await api.signin()
    content = await api.request("GET", f"/api/v1/documents/{fixture['primary']['documentId']}/file")
    require(
        hashlib.sha256(content).hexdigest() == fixture["primary"]["contentSha256"],
        "original source file differs after rollback",
    )
    grounded = await api.ground(fixture)
    return {
        "assertions": {"RollbackOriginalEffectsAndServing": "accepted"},
        "originalSourceRetained": True,
        "effectsReconciled": True,
        "ready": True,
        "fences": fences,
        "resume": resumed,
        "grounded": grounded,
    }


def reconcile_recovery(plan: dict, records: list[dict]) -> dict:
    """Reconcile a finite ordered chain of bound native/probe receipts.

    Observed elapsed values are measurements, not invented RPO/RTO targets.
    This never accepts partial chains or a snapshot as a behavioral substitute.
    """
    require(
        tuple(r["phase"] for r in records) == RECOVERY_PHASES,
        "complete ordered recovery chain required",
    )
    previous = None
    times = []
    for record in records:
        require(
            record["sourceCommit"] == plan["sourceCommit"]
            and record["imageDigest"] == plan["imageDigest"],
            "recovery release differs",
        )
        require(
            record["targetResourceGroupId"] == plan["targetResourceGroupId"],
            "recovery scope differs",
        )
        require(record.get("previousSha256") == previous, "recovery chain changed")
        native = record["evidence"]
        require(
            hashlib.sha256(
                json.dumps(native, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            ).hexdigest()
            == record["evidenceSha256"],
            "recovery evidence hash differs",
        )
        require(
            record["status"] == "accepted",
            "a recovery observation is unproved or failed",
        )
        when = datetime.fromisoformat(record["observedAt"].replace("Z", "+00:00"))
        require(
            when.tzinfo is not None and (not times or when >= times[-1]),
            "recovery time order differs",
        )
        times.append(when)
        previous = hashlib.sha256(
            json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    by_phase = {r["phase"]: r["evidence"] for r in records}
    stopped = by_phase["quiescence"]
    require(
        stopped.get("activeWrites") == 0
        and stopped.get("workerStopped") is True
        and stopped.get("outboxStopped") is True,
        "all source effects must be quiescent",
    )
    restored = by_phase["restore"]
    require(
        restored["sourceServerId"] == plan["databaseResourceId"]
        and restored["restoredServerId"] == plan["restoredDatabaseResourceId"]
        and restored["sourceServerId"] != restored["restoredServerId"],
        "restore boundary differs",
    )
    require(restored["nativeProvisioningState"] == "Succeeded", "restore is not terminal")
    require(
        (
            restored["sourceSchema"] in {"20260726_0028", "20260726_0029"}
            and restored["targetSchema"] == "20260726_0029"
        )
        or (
            restored["sourceSchema"] == "20261116_0030"
            and restored["targetSchema"] == "20261116_0030"
        ),
        "unsupported schema compatibility path",
    )
    if restored["sourceSchema"].endswith("0028"):
        require(
            restored.get("guardedMigrationReceiptSha256")
            and restored.get("preexistingRowsUnchanged") is True
            and restored.get("effectsLockedUntilMigration") is True,
            "0028 restore requires explicit guarded 0029 compatibility proof",
        )
    for role in ("api", "worker"):
        r = by_phase["roles-" + role]
        require(
            r.get("role") == role
            and r.get("freshIdentitySession") is True
            and r.get("ownershipAndPrivileges") == "accepted",
            "fresh restored role proof missing",
        )
    v = by_phase["verify"]
    for key in (
        "postReplayAllRowsUnchanged",
        "appendOnlyRejected",
        "scopeDenial",
        "jointManifestEquality",
        "exactFileChecksum",
        "staleResultPublicationRejected",
    ):
        require(v.get(key) is True, "restored verification missing: " + key)
    f, resumed = by_phase["fence"], by_phase["resume"]
    require(
        f.get("staleLeaseRejected") is True
        and f.get("providerSuccessDbRollback") is True
        and f.get("absenceReconciled") is True
        and f.get("deletionEffects") == 1,
        "nonterminal fencing sequence missing",
    )
    require(
        resumed.get("jobId") == f.get("jobId")
        and resumed.get("durableOutcomes") == 1
        and resumed.get("status") == "succeeded",
        "restored work did not resume exactly once",
    )
    rollback = by_phase["rollback"]
    require(
        rollback.get("databaseResourceId") == plan["databaseResourceId"]
        and rollback.get("originalSourceRetained") is True
        and rollback.get("effectsReconciled") is True
        and rollback.get("ready") is True,
        "rollback to reconciled original is unproved",
    )
    point = datetime.fromisoformat(restored["restorePoint"].replace("Z", "+00:00"))
    committed = datetime.fromisoformat(restored["latestAcknowledgedCommit"].replace("Z", "+00:00"))
    start = datetime.fromisoformat(restored["requestedAt"].replace("Z", "+00:00"))
    ready = datetime.fromisoformat(v["servingReadyAt"].replace("Z", "+00:00"))
    require(
        all(t.tzinfo is not None for t in (point, committed, start, ready))
        and point <= start <= ready
        and committed <= start,
        "recovery timestamps invalid",
    )
    return {
        "status": "accepted",
        "R1": "accepted",
        "R2": "accepted",
        "R3": "accepted",
        "R4": "accepted",
        "restoreRtoSeconds": (ready - start).total_seconds(),
        "acknowledgedCommitExposureSeconds": max(0.0, (committed - point).total_seconds()),
        "rpoQualification": (
            "commit exposure interval; requires recorded marker reconciliation, "
            "not inferred zero data loss"
        ),
        "finalChainSha256": previous,
    }


def collect_recovery(plan: dict, manifest: dict, directory: Path) -> dict:
    """Normalize actual probe/native files; never accept handwritten pass flags.

    The manifest names exclusive output files and their exported SHA-256 hashes.
    Native envelopes retain request, response and observation time. The restore
    intent retains the exact submitted PUT body and request time. The snapshot
    is the last acknowledged quiescent marker: its rows must survive verbatim.
    Historical 0028 compatibility remains separately credited local evidence;
    this current-release managed chain restores 0030 without schema fabrication.
    Historical 0028-to-0029 compatibility remains a separate credited path.
    """
    raw: dict[str, dict] = {}
    hashes: dict[str, str] = {}
    paths: set[Path] = set()
    require(1 <= len(manifest["artifacts"]) <= 32, "bounded recovery export required")
    for name, reference in manifest["artifacts"].items():
        path = (directory / reference["path"]).resolve()
        require(path.is_relative_to(directory.resolve()), "evidence path escapes export")
        require(path not in paths, "recovery artifact reused under another name")
        paths.add(path)
        value = path.read_bytes()
        require(len(value) <= 16 * 1024 * 1024, "recovery artifact exceeds bound")
        digest = hashlib.sha256(value).hexdigest()
        require(digest == reference["sha256"], "recovery export hash differs")
        raw[name], hashes[name] = json.loads(value), digest

    def native(name: str, resource: str, version: str) -> dict:
        record = raw[name]
        request, response = record["request"], record["response"]
        require(
            request["method"] == "GET"
            and request["resourceId"].lower() == resource.lower()
            and request["apiVersion"] == version
            and response["status"] == 200
            and response["body"]["id"].lower() == resource.lower(),
            "native recovery resource binding differs",
        )
        timestamp(record["observedAt"])
        return response["body"]

    executions = set()
    allowed_jobs = plan["recoveryJobResourceIds"]
    prefix = plan["targetResourceGroupId"].rstrip("/") + "/providers/Microsoft.App/jobs/"
    require(
        isinstance(allowed_jobs, list)
        and 1 <= len(allowed_jobs) <= 8
        and all(
            job.lower().startswith(prefix.lower())
            and re.fullmatch(r"[-\w.()]+", job[len(prefix) :])
            for job in allowed_jobs
        ),
        "exact scoped recovery job inventory required",
    )

    def admit_container(name: str, container: dict, operation: str) -> None:
        from infra.milestone_7_8.pilot.pack_execution import SOURCE_VERIFIER

        module = "infra.milestone_7_8.pilot_application_probe"
        command = container.get("command", []) + container.get("args", [])
        if command[:3] == ["python", "-m", module]:
            require(command[3:4] == [operation], "native direct probe operation differs")
            return
        require(command == ["python", "-c", SOURCE_VERIFIER], "native probe loader differs")
        environment = container.get("env", [])
        require(
            len({entry["name"] for entry in environment}) == len(environment),
            "native probe environment has duplicate names",
        )
        values = {entry["name"]: entry.get("value") for entry in environment}
        loader = (Path(__file__).parent / "pilot" / "artifact_transport.py").read_text(
            encoding="utf-8"
        ) + "\nload_probe()\n"
        require(
            values.get("M78_EXECUTION_SOURCE") == loader
            and values.get("M78_EXECUTION_SHA256") == hashlib.sha256(loader.encode()).hexdigest()
            and values.get("M78_PILOT_MODULE") == module,
            "native packed loader or module binding differs",
        )
        arguments = json.loads(values["M78_PILOT_ARGUMENTS_JSON"])
        require(
            isinstance(arguments, list)
            and all(isinstance(argument, str) for argument in arguments)
            and arguments[:1] == [operation],
            "native packed probe operation differs",
        )
        reference = manifest.get("executionArtifacts", {}).get(name)
        require(isinstance(reference, dict), "retained packed execution artifact required")
        path = (directory / reference["path"]).resolve()
        require(path.is_relative_to(directory.resolve()), "packed artifact path escapes export")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        require(
            len(content) <= 2_000_000
            and digest == reference["sha256"] == values.get("M78_PILOT_ARTIFACT_SHA256"),
            "native packed artifact hash differs",
        )
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            require(len(names) == len(set(names)), "packed artifact contains duplicate entries")
            relative = module.replace(".", "/") + ".py"
            for member in ("bindings.json", "package/manifest.json", relative):
                require(
                    archive.getinfo(member).file_size <= 2_000_000, "packed source exceeds bound"
                )
            bindings = json.loads(archive.read("bindings.json"))
            package = json.loads(archive.read("package/manifest.json"))
            require(
                bindings == plan
                and hashlib.sha256(archive.read(relative)).hexdigest()
                == package["sourceBindings"][relative],
                "packed recovery plan or source binding differs",
            )
        hashes[name + "-archive"] = digest

    def probe(name: str, operation: str) -> dict:
        record = raw[name]
        require(
            record["operation"] == operation
            and record["sourceCommit"] == plan["sourceCommit"]
            and record["imageDigest"] == plan["imageDigest"]
            and record["release"] == plan["release"]
            and record["deployment"] == plan["deployment"],
            "recovery probe release differs",
        )
        execution = record["executionId"]
        execution_resource = manifest["executions"][name]
        require(
            any(
                execution_resource.lower() == (job + "/executions/" + execution).lower()
                for job in allowed_jobs
            ),
            "execution is outside exact recovery jobs",
        )
        execution_native = native(name + "-execution", execution_resource, "2025-01-01")
        require(
            execution_native["name"] == execution
            and execution_native["properties"]["status"] == "Succeeded"
            and execution not in executions,
            "actual distinct successful job execution required",
        )
        properties = execution_native["properties"]
        containers = properties["template"]["containers"]
        require(
            len(containers) == 1 and containers[0]["image"].endswith("@" + plan["imageDigest"]),
            "native execution image or operation differs",
        )
        admit_container(name, containers[0], operation)
        require(
            timestamp(properties["startTime"])
            <= timestamp(record["startedAt"])
            <= timestamp(record["finishedAt"])
            <= timestamp(properties["endTime"])
            <= timestamp(raw[name + "-execution"]["observedAt"]),
            "probe and native execution times differ",
        )
        executions.add(execution)
        return record

    for name, key in (
        ("worker-stop", "workerResourceId"),
        ("outbox-stop", "dispatcherResourceId"),
    ):
        app = native(name, plan[key], "2025-01-01")
        require(
            app["properties"]["runningStatus"] == "Stopped",
            "source effects still running",
        )
        require(
            bool(app["properties"]["template"]["containers"])
            and all(
                c["image"].endswith("@" + plan["imageDigest"])
                for c in app["properties"]["template"]["containers"]
            ),
            "stopped source image differs",
        )
    # An API ingress/config readback alone cannot prove write quiescence. Two
    # independent snapshots must contain identical complete scoped inventories.
    fixture = probe("recovery-fixture", "restore-fixture")
    first = probe("quiescent-before", "restore-snapshot")
    snap = probe("snapshot", "restore-snapshot")
    from infra.milestone_7_8.pilot_application_probe import (
        RELATED_TABLES,
        SNAPSHOT_TABLES,
        compare_snapshots,
    )

    expected_tables = set(SNAPSHOT_TABLES) | set(RELATED_TABLES)
    for receipt in (first, snap):
        state = receipt["snapshot"]
        require(
            set(state["tables"]) == expected_tables
            and state["schemaRevision"] == "20261116_0030"
            and state["identity"]["tls"] is True
            and state["identity"]["privileged"] is False,
            "complete current-release scoped snapshot required",
        )
        require(
            timestamp(receipt["startedAt"])
            <= timestamp(state["observedAt"])
            <= timestamp(receipt["finishedAt"]),
            "snapshot observation time is outside probe",
        )
    compare_snapshots(first["snapshot"], snap["snapshot"])
    mutation = fixture["nonterminal"]
    require(
        timestamp(fixture["startedAt"])
        <= timestamp(mutation["latestAcknowledgedMutationAt"])
        <= timestamp(fixture["finishedAt"])
        <= timestamp(first["startedAt"]),
        "acknowledged fixture mutation is not before quiescence",
    )
    for table, key in (
        ("document_processing_jobs", "jobId"),
        ("object_deletion_requests", "deletionRequestId"),
        ("storage_object_versions", "deletionObjectVersionId"),
    ):
        require(
            any(
                mutation[key] in row["identity"].values()
                for row in snap["snapshot"]["tables"][table]
            ),
            "acknowledged recovery identity missing from snapshot",
        )
    require(
        first["snapshot"]["tables"] == snap["snapshot"]["tables"],
        "source still changes",
    )
    require(
        timestamp(first["finishedAt"]) < timestamp(snap["startedAt"]),
        "quiescence snapshots overlap",
    )
    require(
        all(
            timestamp(raw[name]["observedAt"]) <= timestamp(first["startedAt"])
            for name in ("worker-stop", "outbox-stop")
        ),
        "source stop readbacks must precede snapshots",
    )
    require(
        manifest["exclusiveSyntheticWriters"] is True,
        "exclusive fixture writers required",
    )
    restore = native("restored-server", plan["restoredDatabaseResourceId"], "2025-08-01")
    intent = raw["restore-intent"]
    require(
        intent["request"]["method"] == "PUT"
        and intent["request"]["resourceId"] == plan["restoredDatabaseResourceId"]
        and intent["request"]["apiVersion"] == "2025-08-01",
        "exact restore request required",
    )
    properties = intent["request"]["body"]["properties"]
    require(
        properties["createMode"] == "PointInTimeRestore"
        and properties["sourceServerResourceId"] == plan["databaseResourceId"]
        and restore["properties"]["state"] == "Ready",
        "native restored server is not ready or source differs",
    )
    require(
        timestamp(snap["finishedAt"])
        <= timestamp(properties["pointInTimeUTC"])
        <= timestamp(intent["requestedAt"])
        <= timestamp(raw["restored-server"]["observedAt"]),
        "restore point does not include quiescent snapshot",
    )
    api, worker = (
        probe("roles-api", "restore-role"),
        probe("roles-worker", "restore-role"),
    )
    verified = probe("verify", "restore-verify")
    fence, resume = probe("fence", "restore-fence"), probe("resume", "restore-resume")
    rollback = probe("rollback", "restore-rollback")
    restored_at = timestamp(raw["restored-server"]["observedAt"])
    require(
        all(restored_at <= timestamp(record["startedAt"]) for record in (api, worker)),
        "restored role proof predates native readiness",
    )
    prior = max(timestamp(api["finishedAt"]), timestamp(worker["finishedAt"]))
    for record in (verified, fence, resume, rollback):
        require(prior <= timestamp(record["startedAt"]), "recovery operations overlap or reorder")
        prior = timestamp(record["finishedAt"])
    expected = (
        "R1RestoredIdentityRows",
        "R4JointManifestRows",
        "R1AppendOnlyAndReplay",
        "R1CreationReplay",
        "R4RestoredServing",
        "R2RestoredScopeDenial",
        "R4StaleResultAndPublication",
    )
    require(
        all(verified["assertions"].get(k) == "accepted" for k in expected),
        "restore checks incomplete",
    )
    require(
        verified["snapshot"]["tables"] == snap["snapshot"]["tables"],
        "restore lost marker rows",
    )
    compare_snapshots(snap["snapshot"], verified["snapshot"])
    require(
        timestamp(verified["startedAt"])
        <= timestamp(verified["snapshot"]["observedAt"])
        <= timestamp(verified["finishedAt"])
        and verified["scopeDenial"]["status"] == "accepted",
        "restored observation time or scope denial differs",
    )
    require(
        verified["stalePublication"]["noNewPublication"] is True,
        "stale publication escaped",
    )
    require(
        resume["assertions"]["R3RestoredWorkerResumptionOneEffect"] == "accepted",
        "resume absent",
    )
    require(
        rollback["assertions"]["RollbackOriginalEffectsAndServing"] == "accepted",
        "rollback absent",
    )
    for role, result in (("api", api), ("worker", worker)):
        require(
            result["role"] == role
            and result["assertions"]["R2FreshRuntimeRoleOwnershipPositiveNegativePrivileges"]
            == "accepted",
            "role proof missing",
        )
        require(
            result["runtimeReport"]["dialect"] == "postgresql"
            and result["runtimeReport"]["schema_revision"] == "20261116_0030"
            and bool(result["runtimeReport"]["database_user"])
            and result["tablesChecked"] > 0,
            "native restored role report missing",
        )
    require(
        all(
            fence[k] == "accepted"
            for k in (
                "staleLeaseRejected",
                "exactVersionAbsentRetry",
                "singleDeletionEffect",
            )
        ),
        "fencing incomplete",
    )
    require(
        resume["jobId"] == fence["resumeJobId"] == mutation["jobId"],
        "resumed different job",
    )
    require(
        rollback["resume"]["jobId"] == resume["jobId"]
        and rollback["fences"]["resumeJobId"] == resume["jobId"]
        and rollback["resume"]["assertions"]["R3RestoredWorkerResumptionOneEffect"] == "accepted"
        and all(
            rollback["fences"][key] == "accepted"
            for key in ("staleLeaseRejected", "exactVersionAbsentRetry", "singleDeletionEffect")
        ),
        "rollback nested effects differ from retained job",
    )
    times = {
        "quiescence": first["finishedAt"],
        "snapshot": snap["finishedAt"],
        "restore": raw["restored-server"]["observedAt"],
        **{
            k: raw[k]["finishedAt"]
            for k in (
                "roles-api",
                "roles-worker",
                "verify",
                "fence",
                "resume",
                "rollback",
            )
        },
    }
    evidence = {
        "quiescence": {"activeWrites": 0, "workerStopped": True, "outboxStopped": True},
        "snapshot": snap["snapshot"],
        "restore": {
            "sourceServerId": plan["databaseResourceId"],
            "restoredServerId": plan["restoredDatabaseResourceId"],
            "nativeProvisioningState": "Succeeded",
            "sourceSchema": snap["snapshot"]["schemaRevision"],
            "targetSchema": verified["snapshot"]["schemaRevision"],
            "restorePoint": properties["pointInTimeUTC"],
            "latestAcknowledgedCommit": mutation["latestAcknowledgedMutationAt"],
            "requestedAt": intent["requestedAt"],
        },
        **{
            f"roles-{r}": {
                "role": r,
                "freshIdentitySession": True,
                "ownershipAndPrivileges": "accepted",
            }
            for r in ("api", "worker")
        },
        "verify": {
            **{
                k: True
                for k in (
                    "postReplayAllRowsUnchanged",
                    "appendOnlyRejected",
                    "scopeDenial",
                    "jointManifestEquality",
                    "exactFileChecksum",
                    "staleResultPublicationRejected",
                )
            },
            "servingReadyAt": verified["finishedAt"],
        },
        "fence": {
            "staleLeaseRejected": True,
            "providerSuccessDbRollback": True,
            "absenceReconciled": True,
            "deletionEffects": 1,
            "jobId": fence["resumeJobId"],
        },
        "resume": {
            "jobId": resume["jobId"],
            "durableOutcomes": 1,
            "status": "succeeded",
        },
        "rollback": {
            "databaseResourceId": plan["databaseResourceId"],
            **{k: rollback[k] for k in ("originalSourceRetained", "effectsReconciled", "ready")},
        },
    }
    records, previous = [], None

    def digest(value: dict) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()

    for phase in RECOVERY_PHASES:
        record = {
            "phase": phase,
            **{k: plan[k] for k in ("sourceCommit", "imageDigest", "targetResourceGroupId")},
            "previousSha256": previous,
            "status": "accepted",
            "observedAt": times[phase],
            "evidence": evidence[phase],
            "evidenceSha256": digest(evidence[phase]),
        }
        records.append(record)
        previous = digest(record)
    return {
        **reconcile_recovery(plan, records),
        "sourceArtifacts": hashes,
        "executionIds": sorted(executions),
        "chain": records,
        "markerRowsReconciled": True,
        "rpoQualification": (
            "acknowledged final synthetic fixture mutation exposure interval with exact restored "
            "row reconciliation; not a claim of zero global data loss"
        ),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect_recovery(
        json.loads(args.plan.read_text(encoding="utf-8")),
        json.loads(args.manifest.read_text(encoding="utf-8")),
        args.manifest.parent,
    )
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Approval-bound application and current-release recovery observations.

Preparation/help and unit tests perform no managed calls. Each live invocation is
exclusive: reconcile its saved intent before a retry. Receipts describe actual
observations, never turn a small workload into a supported pilot cohort.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from infra.milestone_7_8.pilot_validation import (
    _private_host,
    admit_runtime_bindings,
    authorize,
    digest,
    utc,
    write_new,
)

OPERATIONS = (
    "account",
    "core",
    "workload",
    "restore-snapshot",
    "restore-verify",
    "restore-fixture",
    "restore-fence",
    "restore-role",
    "restore-resume",
)
FIXTURE = b"Observatory calibration note. The calibration code is NOVA-731. The telescope aperture is 6.5 meters.\n"
QUESTION = (
    "What calibration code and telescope aperture does the observatory note specify?"
)
UNSUPPORTED = "What is the orbital velocity of Neptune's moon Proteus?"
SCHEMA = "m78-pilot-application-v1"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False
    ).encode()


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class Journal:
    def __init__(
        self,
        output: Path,
        execution: str,
        operation: str,
        bindings: dict,
        deadline: datetime,
    ) -> None:
        self.output, self.deadline = output, deadline
        self.directory = output.with_suffix(".steps")
        self.sequence = 0
        self.header = {
            "schema": SCHEMA,
            "executionId": execution,
            "operation": operation,
            "imageDigest": bindings["imageDigest"],
            "sourceCommit": bindings["sourceCommit"],
            "release": bindings["release"],
            "deployment": bindings["deployment"],
            "startedAt": datetime.now(UTC).isoformat(),
            "managedAcceptance": "unproved",
        }
        write_new(output.with_suffix(".intent.json"), self.header)

    def check_time(self) -> None:
        require(datetime.now(UTC) < self.deadline, "approved proof window ended")

    def step(self, name: str, detail: dict) -> Path:
        self.check_time()
        self.sequence += 1
        path = self.directory / f"{self.sequence:04d}-{name}.json"
        write_new(path, {"at": datetime.now(UTC).isoformat(), **detail})
        return path

    def finish(self, observations: dict) -> dict:
        result = {
            **self.header,
            "finishedAt": datetime.now(UTC).isoformat(),
            **observations,
        }
        write_new(self.output, result)
        return result


class Api:
    def __init__(self, client: Any, journal: Journal, execution: str) -> None:
        self.client, self.journal, self.execution = client, journal, execution
        self.csrf = ""

    async def request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        content: bytes | None = None,
        headers: dict | None = None,
        statuses: tuple[int, ...] = (200,),
        secret: bool = False,
    ) -> Any:
        require(
            path.startswith("/api/v1/") and "//" not in path and "?" not in path,
            "API path is not an exact relative endpoint",
        )
        self.journal.check_time()
        intent = self.journal.step(
            "http-intent",
            {
                "method": method,
                "path": path,
                "requestSha256": None
                if secret
                else sha(data)
                if data is not None
                else hashlib.sha256(content).hexdigest()
                if content is not None
                else None,
            },
        )
        started = time.monotonic()
        response = await self.client.request(
            method,
            path,
            json=data,
            content=content,
            headers={"X-CSRF-Token": self.csrf, **(headers or {})},
        )
        # No cookies, credentials, upload capability or response body in step logs.
        write_new(
            intent.with_name(intent.stem + "-result.json"),
            {
                "status": response.status_code,
                "elapsedMs": (time.monotonic() - started) * 1000,
                "responseBytes": len(response.content),
                "responseSha256": None
                if secret
                else hashlib.sha256(response.content).hexdigest(),
            },
        )
        require(
            response.status_code in statuses,
            f"{method} {path}: unexpected HTTP {response.status_code}",
        )
        if not response.content:
            return None
        return (
            response.json()
            if "json" in response.headers.get("content-type", "")
            else response.content
        )

    async def signin(self) -> dict:
        result = await self.request(
            "POST",
            "/api/v1/auth/signin",
            secret=True,
            data={
                "email": os.environ["OPENCANVAS_PILOT_EMAIL"],
                "password": os.environ["OPENCANVAS_PILOT_PASSWORD"],
            },
        )
        self.csrf = result["csrfToken"]
        return result["user"]

    async def clean_upload(self, fixture: dict, suffix: str) -> dict:
        path = f"/api/v1/workspaces/{fixture['workspaceId']}/canvases/{fixture['canvasId']}/upload-sessions"
        result = await self.request(
            "POST",
            path,
            statuses=(201,),
            secret=True,
            data={
                "fileName": f"pilot-{suffix}.txt",
                "mediaType": "text/plain",
                "sizeBytes": len(FIXTURE),
                "sha256": hashlib.sha256(FIXTURE).hexdigest(),
                "idempotencyKey": f"{self.execution}:{suffix}",
                "x": 300,
                "y": 200,
            },
        )
        require(
            result["workspaceId"] == fixture["workspaceId"]
            and result["canvasId"] == fixture["canvasId"],
            "upload scope changed",
        )
        session_path = path + "/" + result["sessionId"]
        expected_path = f"/api/v1/upload-sessions/{result['sessionId']}/content"
        require(result["uploadPath"] == expected_path, "unexpected capability target")
        await self.request(
            "PUT",
            expected_path,
            content=FIXTURE,
            headers={
                "X-Upload-Capability": result["capability"],
                "Content-Type": "text/plain",
            },
            statuses=(200, 204),
            secret=True,
        )
        state = await self.request("POST", session_path + "/complete")
        started = time.monotonic()
        while state.get("scanOutcome") is None or state.get("objectState") != "clean":
            require(
                time.monotonic() - started <= 900,
                "production scanner/promotion did not complete within 900 seconds",
            )
            require(
                state.get("scanOutcome")
                not in {"infected", "suspicious", "unsupported", "timeout", "error"},
                "scanner rejected the clean fixture",
            )
            search = await self.request(
                "POST",
                f"/api/v1/canvases/{fixture['canvasId']}/documents/search",
                data={"query": QUESTION, "documentIds": [result["documentId"]]},
                statuses=(200, 400),
            )
            require(not search.get("matches"), "quarantined source entered retrieval")
            await asyncio.sleep(5)
            state = await self.request("GET", session_path)
        require(state["scanOutcome"] == "clean", "clean native result missing")
        while True:
            doc = await self.request("GET", f"/api/v1/documents/{result['documentId']}")
            if doc["status"] == "ready":
                break
            require(
                time.monotonic() - started <= 1200,
                "production worker did not publish within bounded wait",
            )
            require(
                doc["status"] not in {"failed", "error", "deleted"},
                "document processing failed",
            )
            await asyncio.sleep(5)
        snapshot = await self.request(
            "GET", f"/api/v1/canvases/{fixture['canvasId']}/snapshot"
        )
        nodes = [
            node
            for node in snapshot["nodes"]
            if (node.get("document") or {}).get("id") == result["documentId"]
            or node.get("documentId") == result["documentId"]
        ]
        require(len(nodes) == 1, "exactly one production document card required")
        return {
            key: result[key]
            for key in (
                "sessionId",
                "documentId",
                "documentVersionId",
                "objectVersionId",
            )
        } | {
            "nodeId": nodes[0]["id"],
            "sessionPath": session_path,
            "contentSha256": hashlib.sha256(FIXTURE).hexdigest(),
            "scanElapsedSeconds": time.monotonic() - started,
        }

    async def ground(
        self,
        fixture: dict,
        *,
        refusal: bool = False,
        request_key: str = "",
        bounded: bool = False,
    ) -> dict:
        doc = fixture["primary"]
        query = UNSUPPORTED if refusal else QUESTION
        prepared = await self.request(
            "POST",
            f"/api/v1/workspaces/{fixture['workspaceId']}/agent-executions/drafts/prepare",
            statuses=(201, 429, 503) if bounded else (201,),
            data={
                "canvasId": fixture["canvasId"],
                "instruction": query,
                "selectedNodeIds": [doc["nodeId"]],
                "idempotencyKey": f"{self.execution}:draft:{'refusal' if refusal else 'positive'}{request_key}",
            },
        )
        if bounded and "executionId" not in prepared:
            return {"boundedRejection": True}
        result = await self.request(
            "POST",
            f"/api/v1/workspaces/{fixture['workspaceId']}/agent-executions/{prepared['executionId']}/run",
            statuses=(200, 429, 503) if bounded else (200,),
        )
        if bounded and "insufficientEvidence" not in result:
            return {"boundedRejection": True}
        if refusal:
            require(
                result["insufficientEvidence"] is True and result["citations"] == [],
                "unsupported query was not refused",
            )
        else:
            require(
                result["insufficientEvidence"] is False and bool(result["citations"]),
                "grounded answer/citation missing",
            )
            for citation in result["citations"]:
                require(
                    citation["documentId"] == doc["documentId"],
                    "citation escaped selected document",
                )
                passage = await self.request(
                    "GET",
                    f"/api/v1/documents/{doc['documentId']}/chunks/{citation['chunkId']}",
                )
                require(
                    citation["quote"] in passage["text"],
                    "citation quote missing from authoritative passage",
                )
            require("NOVA-731" in result["text"], "supported calibration fact missing")
        return {
            "executionId": prepared["executionId"],
            "responseSha256": sha(result),
            "insufficientEvidence": result["insufficientEvidence"],
            "citations": result["citations"],
        }


async def core(api: Api) -> dict:
    user = await api.signin()
    payload: dict[str, Any] = {
        "name": "Isolated managed pilot proof",
        "idempotencyKey": f"{api.execution}:canvas",
    }
    canvas = await api.request(
        "POST", "/api/v1/canvases", data=payload, statuses=(200, 201)
    )
    replay = await api.request(
        "POST", "/api/v1/canvases", data=payload, statuses=(200, 201)
    )
    require(canvas["id"] == replay["id"], "canvas replay created another result")
    fixture = {
        "userId": user["id"],
        "canvasId": canvas["id"],
        "workspaceId": canvas["workspaceId"],
        "creationRequests": [
            {"path": "/api/v1/canvases", "payload": payload, "id": canvas["id"]}
        ],
    }
    nodes = []
    for n in range(2):
        path = f"/api/v1/canvases/{canvas['id']}/nodes"
        payload = {
            "type": "note",
            "title": f"Proof note {n}",
            "text": "Synthetic local proof note.",
            "position": {"x": n * 200, "y": 20},
            "idempotencyKey": f"{api.execution}:note:{n}",
        }
        node = await api.request("POST", path, data=payload, statuses=(200, 201))
        replay = await api.request("POST", path, data=payload, statuses=(200, 201))
        require(node["id"] == replay["id"], "node replay changed identity")
        nodes.append(node["id"])
        fixture["creationRequests"].append(
            {"path": path, "payload": payload, "id": node["id"]}
        )
    path = f"/api/v1/canvases/{canvas['id']}/edges"
    payload = {
        "sourceNodeId": nodes[0],
        "targetNodeId": nodes[1],
        "kind": "default",
        "idempotencyKey": f"{api.execution}:edge",
    }
    edge = await api.request("POST", path, data=payload, statuses=(200, 201))
    replay = await api.request("POST", path, data=payload, statuses=(200, 201))
    require(edge["id"] == replay["id"], "edge replay changed identity")
    fixture["creationRequests"].append(
        {"path": path, "payload": payload, "id": edge["id"]}
    )
    fixture["primary"] = await api.clean_upload(fixture, "primary")
    search = await api.request(
        "POST",
        f"/api/v1/canvases/{canvas['id']}/documents/search",
        data={"query": QUESTION, "documentIds": [fixture["primary"]["documentId"]]},
    )
    require(
        search["insufficientContext"] is False and bool(search["matches"]),
        "current publication not searchable",
    )
    file = await api.request(
        "GET", f"/api/v1/documents/{fixture['primary']['documentId']}/file"
    )
    require(
        hashlib.sha256(file).hexdigest() == fixture["primary"]["contentSha256"],
        "served exact file checksum changed",
    )
    positive, negative = (
        await api.ground(fixture),
        await api.ground(fixture, refusal=True),
    )
    # These independent clean fixtures are preserved for the paused-worker PITR exercise.
    fixture["queued"] = await api.clean_upload(fixture, "queued-recovery")
    fixture["deletion"] = await api.clean_upload(fixture, "deletion-recovery")
    return {
        "fixture": fixture,
        "core": {"status": "accepted", "positive": positive, "refusal": negative},
        "providerCalls": 2,
        "managedAcceptance": "only listed core observations accepted",
    }


async def workload(api: Api, fixture: dict, plan: dict) -> dict:
    caps = plan["applicationProofCaps"]
    count, concurrency = caps["requests"], caps["concurrency"]
    require(
        type(count) is int
        and 1 <= count <= 200
        and type(concurrency) is int
        and 1 <= concurrency <= 8,
        "workload exceeds prepared bound",
    )
    await api.signin()
    semaphore = asyncio.Semaphore(concurrency)
    measurements = []

    async def request_one(index: int) -> None:
        async with semaphore:
            started = time.monotonic()
            if index in {0, 100}:
                result = await api.ground(
                    fixture, request_key=f":load:{index}", bounded=True
                )
                admitted = not result.get("boundedRejection", False)
            elif index % 20 == 10:
                result = await api.request(
                    "POST",
                    f"/api/v1/canvases/{fixture['canvasId']}/nodes",
                    data={
                        "type": "note",
                        "title": "Bounded workload fixture",
                        "text": "Synthetic non-sensitive workload note.",
                        "position": {"x": index, "y": index},
                        "idempotencyKey": f"{api.execution}:load:{index}",
                    },
                    statuses=(201, 429, 503),
                )
                admitted = "id" in result
            elif index % 2:
                result = await api.request(
                    "POST",
                    f"/api/v1/canvases/{fixture['canvasId']}/documents/search",
                    data={
                        "query": QUESTION,
                        "documentIds": [fixture["primary"]["documentId"]],
                    },
                    statuses=(200, 429, 503),
                )
                admitted = bool(result.get("matches"))
            else:
                result = await api.request(
                    "GET",
                    f"/api/v1/canvases/{fixture['canvasId']}/snapshot",
                    statuses=(200, 429, 503),
                )
                admitted = "nodes" in result
            measurements.append(
                {
                    "index": index,
                    "elapsedMs": (time.monotonic() - started) * 1000,
                    "admitted": admitted,
                }
            )

    await asyncio.gather(*(request_one(index) for index in range(count)))
    recovery_start = time.monotonic()
    while True:
        recovered = await api.request(
            "POST",
            f"/api/v1/canvases/{fixture['canvasId']}/documents/search",
            data={"query": QUESTION, "documentIds": [fixture["primary"]["documentId"]]},
            statuses=(200, 429, 503),
        )
        if recovered.get("matches"):
            break
        require(
            time.monotonic() - recovery_start < 90,
            "bounded post-load retrieval recovery not observed",
        )
        await asyncio.sleep(2)
    return {
        "measurements": measurements,
        "requests": count,
        "concurrency": concurrency,
        "observedUsers": 1,
        "postLoadRetrieval": "accepted",
        "managedAcceptance": "bounded observations only",
        "limitations": [
            "No supported cohort inferred",
            "No stress/soak/spike/fault envelope closure inferred",
            "At most two model requests and ten note writes per stage; retry budget included in forecast",
        ],
    }


# Only exact synthetic workspace rows are read. Whole rows are hashed rather than
# exported; credentials, document content and provider payloads never enter receipts.
SNAPSHOT_TABLES = (
    "legacy_creation_request_identities",
    "upload_sessions",
    "storage_objects",
    "storage_object_versions",
    "storage_object_lifecycle_transitions",
    "malware_scan_requests",
    "malware_scan_results",
    "object_promotions",
    "object_deletion_requests",
    "pipeline_manifests",
    "index_publications",
    "retrieval_heads",
    "domain_events",
    "domain_event_outbox",
    "domain_activity_entries",
    "durable_job_requests",
    "document_processing_jobs",
    "durable_job_outcomes",
)
MUTABLE_TABLES = {"retrieval_heads", "domain_event_outbox", "document_processing_jobs"}


def database(plan: dict, *, restored: bool, worker: bool = False) -> tuple[Any, Any]:
    from sqlalchemy.engine import make_url
    from opencanvas_api.core.config import DatabaseRole, Settings
    from opencanvas_api.db.session import Database

    settings = Settings()
    target = plan["restoredDatabaseResourceId" if restored else "databaseResourceId"]
    require(
        target.lower().startswith(
            plan["targetResourceGroupId"].lower()
            + "/providers/microsoft.dbforpostgresql/flexibleservers/"
        ),
        "database is outside approved isolated group",
    )
    require(
        plan["databaseResourceId"].lower()
        != plan["restoredDatabaseResourceId"].lower(),
        "restore must use a distinct server",
    )
    host = make_url(settings.database_url_value).host
    require(
        host == target.rsplit("/", 1)[-1] + ".postgres.database.azure.com",
        "database host does not match approved resource",
    )
    require(
        settings.database_auth_mode == "entra"
        and settings.database_tls_mode == "verify-full",
        "identity-backed verified TLS required",
    )
    require(isinstance(host, str), "database host required")
    assert isinstance(host, str)
    _private_host(host)
    role = DatabaseRole.WORKER if worker else DatabaseRole.API
    return Database.from_settings(settings, expected_role=role), settings


async def snapshot(db: Any, fixture: dict) -> dict:
    from sqlalchemy import select, text
    from opencanvas_api.db.models import Base

    workspace = uuid.UUID(fixture["workspaceId"])
    tables = {}
    async with db.engine.connect() as connection:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        identity = dict(
            (
                await connection.execute(
                    text(
                        "SELECT current_user AS role, current_database() AS database, "
                        "(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()) AS tls, "
                        "(SELECT rolsuper OR rolbypassrls OR rolcreaterole FROM pg_roles WHERE rolname=current_user) AS privileged"
                    )
                )
            )
            .mappings()
            .one()
        )
        require(
            identity["tls"] is True and identity["privileged"] is False,
            "nonprivileged TLS database session required",
        )
        revision = (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one()
        require(str(revision).endswith("0029"), "current release schema 0029 required")
        for name in SNAPSHOT_TABLES:
            table = Base.metadata.tables[name]
            require("workspace_id" in table.c, "snapshot table lacks explicit scope")
            rows = (
                (
                    await connection.execute(
                        select(table)
                        .where(table.c.workspace_id == workspace)
                        .limit(2049)
                    )
                )
                .mappings()
                .all()
            )
            require(
                len(rows) <= 2048,
                "snapshot row cap exceeded; partial evidence rejected",
            )
            tables[name] = sorted(
                [
                    {
                        "identity": {
                            col.name: str(row[col.name])
                            for col in table.primary_key.columns
                        },
                        "sha256": sha(dict(row)),
                    }
                    for row in rows
                ],
                key=canonical,
            )
        grants = (
            (
                await connection.execute(
                    text(
                        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                        "WHERE grantee=current_user AND table_schema='public' ORDER BY table_name, privilege_type"
                    )
                )
            )
            .mappings()
            .all()
        )
        await connection.rollback()
    return {
        "tables": tables,
        "schemaRevision": revision,
        "identity": identity,
        "grants": [dict(row) for row in grants],
        "workspaceId": str(workspace),
        "observedAt": datetime.now(UTC).isoformat(),
    }


def compare_snapshots(before: dict, after: dict) -> dict:
    require(before["workspaceId"] == after["workspaceId"], "restore workspace changed")
    require(
        before["schemaRevision"] == after["schemaRevision"], "restore revision changed"
    )
    require(
        before["tables"] == after["tables"],
        "restored rows differ from pre-PITR snapshot; reconcile exact rows",
    )
    require(before["grants"] == after["grants"], "restored observer grants differ")
    require(
        bool(after["tables"]["legacy_creation_request_identities"]),
        "creation identities absent",
    )
    for name in (
        "upload_sessions",
        "storage_object_versions",
        "malware_scan_results",
        "object_promotions",
        "index_publications",
        "retrieval_heads",
    ):
        require(bool(after["tables"][name]), f"joint manifest missing {name}")
    return {
        "R1RestoredIdentityRows": "accepted",
        "R2ObserverSessionAndGrants": "accepted",
        "R4JointManifestRows": "accepted",
        "R1AppendOnlyAndReplay": "unproved",
        "R2ApiWorkerOwnershipAndScope": "unproved",
        "R3NonterminalRecovery": "unproved",
        "R4RestoredServingAndNoStaleReuse": "unproved",
    }


def fixture_from(path: Path, plan: dict) -> dict:
    receipt = json.loads(path.read_text())
    require(
        receipt.get("schema") == SCHEMA
        and receipt.get("imageDigest") == plan["imageDigest"]
        and receipt.get("sourceCommit") == plan["sourceCommit"]
        and receipt.get("release") == plan["release"],
        "fixture receipt does not bind current release",
    )
    require(
        receipt.get("core", {}).get("status") == "accepted",
        "accepted actual core fixture required",
    )
    return receipt["fixture"]


def admit_paused_worker(plan: dict, readback: dict) -> None:
    expected = plan["workerResourceId"]
    require(
        expected.lower().startswith(
            plan["targetResourceGroupId"].lower()
            + "/providers/microsoft.app/containerapps/"
        ),
        "worker outside scope",
    )
    require(
        readback.get("request", {}).get("method") == "GET"
        and readback["request"].get("resourceId", "").lower() == expected.lower()
        and readback["request"].get("apiVersion") == "2025-01-01",
        "exact worker native readback required",
    )
    response = readback.get("response", {})
    require(
        response.get("status") == 200
        and response.get("body", {}).get("id", "").lower() == expected.lower(),
        "worker readback mismatch",
    )
    properties = response["body"]["properties"]
    require(
        properties.get("runningStatus") == "Stopped",
        "source worker must be stopped before nonterminal fixture",
    )
    require(
        all(
            item["image"].endswith("@" + plan["imageDigest"])
            for item in properties["template"]["containers"]
        ),
        "worker image mismatch",
    )


async def restore_fixture(db: Any, settings: Any, fixture: dict, api: Api) -> dict:
    """Create actual durable nonterminal work while the exact worker is stopped."""
    from sqlalchemy import select
    from opencanvas_api.db.models import (
        Document,
        DocumentProcessingJob,
        ObjectDeletionRequest,
    )
    from opencanvas_api.services.jobs import (
        ACTIVE_JOB_STATUSES,
        DatabaseJobProvider,
        _durable_service,
    )

    await api.signin()
    async with db.sessions() as session:
        active = list(
            (
                await session.scalars(
                    select(DocumentProcessingJob.id).where(
                        DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                        DocumentProcessingJob.completed_at.is_(None),
                    )
                )
            ).all()
        )
        require(
            not active, "isolated queue is not drained; no arbitrary job may be claimed"
        )
        document = await session.get(
            Document, uuid.UUID(fixture["queued"]["documentId"])
        )
        require(
            document is not None
            and str(document.canvas_id) == fixture["canvasId"]
            and document.status == "ready",
            "exact ready recovery document required",
        )
        job = await DatabaseJobProvider(settings).enqueue(
            session,
            user_id=uuid.UUID(fixture["userId"]),
            workspace_id=uuid.UUID(fixture["workspaceId"]),
            document=document,
            force=True,
        )
        lease = await _durable_service(session, settings).claim_one(
            worker_id="pilot-pre-restore-" + api.execution
        )
        require(
            lease is not None and lease.job_run_id == job.id,
            "another queue item was selected; transaction aborted",
        )
        await session.commit()
        job_id = str(job.id)
    deletion = await api.request(
        "POST",
        fixture["deletion"]["sessionPath"] + "/deletion-requests",
        data={
            "idempotencyKey": api.execution + ":restore-deletion",
            "reasonCode": "pilot_restore_proof",
        },
    )
    require(
        deletion["objectState"] == "deletion_requested", "deletion not durably queued"
    )
    async with db.sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(ObjectDeletionRequest).where(
                        ObjectDeletionRequest.workspace_id
                        == uuid.UUID(fixture["workspaceId"]),
                        ObjectDeletionRequest.idempotency_key
                        == api.execution + ":restore-deletion",
                    )
                )
            ).all()
        )
        require(len(rows) == 1, "exact deletion request missing")
        deletion_id, version_id = (
            str(rows[0].deletion_request_id),
            str(rows[0].object_version_id),
        )
    return {
        "nonterminal": {
            "jobId": job_id,
            "lease": json.loads(canonical(asdict(lease))),
            "deletionRequestId": deletion_id,
            "deletionObjectVersionId": version_id,
            "capturedAt": datetime.now(UTC).isoformat(),
            "eligibilityAfter": lease.expires_at.isoformat(),
        },
        "managedAcceptance": "nonterminal fixture captured; recovery unproved",
    }


async def restore_fence(
    db: Any, settings: Any, fixture: dict, retained: dict, journal: Journal
) -> dict:
    """Actual stale completion, exact-version ambiguous deletion, retry and worker resume.

    All queue/deletion candidates must be the exact isolated fixtures before a
    service that selects globally is called. No test clock is advanced.
    """
    from sqlalchemy import select
    from opencanvas_api.db.models import (
        DocumentProcessingJob,
        DurableJobOutcome,
        ObjectDeletionRequest,
        StorageObjectLifecycleTransition,
        StorageObjectVersion,
    )
    from opencanvas_api.services.documents import build_versioned_object_storage
    from opencanvas_api.services.durable_jobs import DurableJobConflictError, JobLease
    from opencanvas_api.services.jobs import ACTIVE_JOB_STATUSES, _durable_service
    from opencanvas_api.services.object_ingestion import ObjectReconciler

    raw = retained["nonterminal"]["lease"]
    lease = JobLease(
        **{
            key: uuid.UUID(value)
            if key in {"job_run_id", "attempt_id", "delivery_id"}
            else utc(value)
            if key == "expires_at"
            else value
            for key, value in raw.items()
        }
    )
    while datetime.now(UTC) <= lease.expires_at:
        journal.check_time()
        await asyncio.sleep(
            min(5, max(0.1, (lease.expires_at - datetime.now(UTC)).total_seconds()))
        )
    async with db.sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(DocumentProcessingJob).where(
                        DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                        DocumentProcessingJob.completed_at.is_(None),
                    )
                )
            ).all()
        )
        require(
            len(rows) == 1
            and rows[0].id == lease.job_run_id
            and str(rows[0].document_id) == fixture["queued"]["documentId"],
            "only the exact retained nonterminal job may be recovered",
        )
        try:
            await _durable_service(session, settings).complete(lease)
        except DurableJobConflictError:
            await session.rollback()
        else:
            await session.rollback()
            raise ValueError("pre-restore expired lease was accepted")
    journal.step("stale-lease-rejected", {"jobId": str(lease.job_run_id)})
    version_id = uuid.UUID(retained["nonterminal"]["deletionObjectVersionId"])
    storage = build_versioned_object_storage(settings)
    async with db.sessions() as session:
        done = select(StorageObjectLifecycleTransition.object_version_id).where(
            StorageObjectLifecycleTransition.current_state == "deleted"
        )
        pending = list(
            (
                await session.scalars(
                    select(ObjectDeletionRequest).where(
                        ~ObjectDeletionRequest.object_version_id.in_(done)
                    )
                )
            ).all()
        )
        require(
            len(pending) == 1
            and str(pending[0].deletion_request_id)
            == retained["nonterminal"]["deletionRequestId"],
            "only exact pending deletion may be reconciled",
        )
        version = await session.get(StorageObjectVersion, version_id)
        require(
            version is not None and str(version.workspace_id) == fixture["workspaceId"],
            "deletion version scope mismatch",
        )
        journal.step(
            "exact-provider-delete-intent",
            {
                "objectVersionId": str(version_id),
                "providerVersionId": version.provider_version_id,
                "contentSha256": version.content_sha256,
            },
        )
        # This models provider success followed by loss of the DB transaction.
        require(
            await ObjectReconciler(
                session, settings=settings
            ).execute_deletion_requests(storage, limit=1)
            == 1,
            "first exact deletion did not execute",
        )
        await session.rollback()
    journal.step("provider-delete-db-rollback", {"objectVersionId": str(version_id)})
    async with db.sessions() as session:
        require(
            await ObjectReconciler(
                session, settings=settings
            ).execute_deletion_requests(storage, limit=1)
            == 1,
            "provider absence did not reconcile to durable completion",
        )
        await session.commit()
    async with db.sessions() as session:
        transitions = list(
            (
                await session.scalars(
                    select(StorageObjectLifecycleTransition).where(
                        StorageObjectLifecycleTransition.object_version_id
                        == version_id,
                        StorageObjectLifecycleTransition.current_state == "deleted",
                    )
                )
            ).all()
        )
        require(len(transitions) == 1, "duplicate durable deletion effect")
        require(
            await ObjectReconciler(
                session, settings=settings
            ).execute_deletion_requests(storage, limit=1)
            == 0,
            "completed deletion was selected again",
        )
        await session.rollback()
    # The package must resume the restored worker separately after this receipt.
    # Do not manufacture worker success from a manual terminal outcome.
    return {
        "staleLeaseRejected": "accepted",
        "exactVersionAbsentRetry": "accepted",
        "singleDeletionEffect": "accepted",
        "restoredWorkerResume": "unproved",
        "resumeJobId": str(lease.job_run_id),
        "outcomeTable": DurableJobOutcome.__tablename__,
        "managedAcceptance": "listed fences only; worker resumption still requires restore-verify",
    }


async def restored_role(db: Any, settings: Any, plan: dict) -> dict:
    from sqlalchemy import text
    from opencanvas_api.db.models import Base
    from opencanvas_api.db.role_privileges import (
        RUNTIME_TABLE_PRIVILEGES,
        require_runtime_function_privileges,
    )
    from opencanvas_api.db.runtime import validate_database_runtime

    role = settings.database_role
    require(role in RUNTIME_TABLE_PRIVILEGES, "only runtime API/worker roles allowed")
    report = await validate_database_runtime(db.engine, settings, expected_role=role)
    policy = RUNTIME_TABLE_PRIVILEGES[role]
    names = sorted(Base.metadata.tables)
    async with db.engine.connect() as connection:
        actual = (
            (
                await connection.execute(
                    text(
                        "SELECT c.relname, pg_get_userbyid(c.relowner) AS owner, has_table_privilege(current_user,c.oid,'SELECT') AS s, has_table_privilege(current_user,c.oid,'INSERT') AS i, has_table_privilege(current_user,c.oid,'UPDATE') AS u, has_table_privilege(current_user,c.oid,'DELETE') AS d FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname"
                    )
                )
            )
            .mappings()
            .all()
        )
        for row in actual:
            if row["relname"] not in names:
                continue
            require(
                row["owner"] == plan["migrationPrincipalName"],
                "restored table ownership differs",
            )
            for operation, key in (
                ("SELECT", "s"),
                ("INSERT", "i"),
                ("UPDATE", "u"),
                ("DELETE", "d"),
            ):
                require(
                    row[key] == (row["relname"] in policy[operation]),
                    "restored runtime privilege differs",
                )
        require(
            set(names) <= {row["relname"] for row in actual},
            "restored table inventory incomplete",
        )
        await require_runtime_function_privileges(
            connection, role, principal=report.database_user, managed=True
        )
        await connection.rollback()
    return {
        "assertions": {
            "R2FreshRuntimeRoleOwnershipPositiveNegativePrivileges": "accepted"
        },
        "role": role.value,
        "runtimeReport": asdict(report),
        "tablesChecked": len(names),
    }


async def restored_resume(
    db: Any, settings: Any, fixture: dict, before: dict, journal: Journal
) -> dict:
    from sqlalchemy import select
    from opencanvas_api.db.models import DocumentProcessingJob, DurableJobOutcome
    from opencanvas_api.services.jobs import DocumentWorker, ACTIVE_JOB_STATUSES

    job_id = uuid.UUID(before["nonterminal"]["jobId"])
    async with db.sessions() as session:
        active = (
            await session.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                    DocumentProcessingJob.completed_at.is_(None),
                )
            )
        ).all()
        require(
            len(active) == 1
            and active[0].id == job_id
            and str(active[0].document_id) == fixture["queued"]["documentId"],
            "only exact restored job may resume",
        )
    worker = DocumentWorker(
        settings=settings, sessions=db.sessions, worker_id="pilot-restored-resume"
    )
    journal.step("restored-worker-resume-intent", {"jobId": str(job_id)})
    require(await worker.run_once(), "restored worker did not claim eligible work")
    async with db.sessions() as session:
        job = await session.get(DocumentProcessingJob, job_id)
        require(
            job is not None and job.status == "succeeded",
            "restored worker did not complete",
        )
        rows = (
            await session.scalars(
                select(DurableJobOutcome).where(DurableJobOutcome.job_run_id == job_id)
            )
        ).all()
        require(len(rows) == 1, "exactly one restored durable outcome required")
    return {
        "assertions": {"R3RestoredWorkerResumptionOneEffect": "accepted"},
        "jobId": str(job_id),
    }


async def run(args: argparse.Namespace) -> dict:
    import httpx

    _, plan, deadline = authorize(
        args.bundle, args.authorization, args.bindings, args.operation
    )
    require(
        args.execute
        and args.execution_id == os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
        "exact actual ACA job execution required",
    )
    runtime = admit_runtime_bindings(
        plan,
        json.loads(args.runtime_readbacks.read_text()),
        plan_sha256=digest(args.bindings),
    )
    if args.operation == "restore-verify":
        records = json.loads(args.runtime_readbacks.read_text())["resources"]
        body = next(
            row["response"]["body"]
            for row in records
            if row["request"]["resourceId"].lower()
            == plan["applicationResourceId"].lower()
        )
        database_urls = [
            entry.get("value", "")
            for container in body["properties"]["template"]["containers"]
            for entry in container.get("env", [])
            if entry["name"] == "OPENCANVAS_DATABASE_URL"
        ]
        expected_host = (
            plan["restoredDatabaseResourceId"].rsplit("/", 1)[-1]
            + ".postgres.database.azure.com"
        )
        require(
            bool(database_urls)
            and all(expected_host in value for value in database_urls),
            "restored API must bind restored server before replay",
        )
    parsed = urlparse(runtime["apiBaseUrl"])
    require(
        parsed.scheme == "https" and bool(parsed.hostname), "private HTTPS API required"
    )
    _private_host(parsed.hostname)
    journal = Journal(args.output, args.execution_id, args.operation, plan, deadline)
    async with httpx.AsyncClient(
        base_url=runtime["apiBaseUrl"],
        timeout=45,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        api = Api(client, journal, args.execution_id)
        if args.operation == "account":
            user = await api.request(
                "POST",
                "/api/v1/auth/signup",
                secret=True,
                statuses=(201,),
                data={
                    "email": os.environ["OPENCANVAS_PILOT_EMAIL"],
                    "password": os.environ["OPENCANVAS_PILOT_PASSWORD"],
                    "displayName": "M78 synthetic pilot operator",
                },
            )
            return journal.finish(
                {"accountCreated": True, "userId": user["user"]["id"]}
            )
        if args.operation == "core":
            return journal.finish(await core(api))
        fixture = fixture_from(args.fixture, plan)
        if args.operation == "workload":
            stages = plan.get("applicationProofStages")
            if not isinstance(stages, list):
                raise ValueError("exact four-stage workload plan required")
            require(
                isinstance(stages, list)
                and len(stages) == 4
                and 0 <= args.workload_stage < 4,
                "exact four-stage workload plan required",
            )
            return journal.finish(
                await workload(
                    api,
                    fixture,
                    {**plan, "applicationProofCaps": stages[args.workload_stage]},
                )
            )
        worker = args.operation in {
            "restore-fixture",
            "restore-fence",
            "restore-resume",
        } or (
            args.operation == "restore-role"
            and os.environ.get("OPENCANVAS_DATABASE_ROLE") == "worker"
        )
        restored = args.operation in {
            "restore-fence",
            "restore-verify",
            "restore-role",
            "restore-resume",
        }
        if args.operation in {"restore-fixture", "restore-fence", "restore-resume"}:
            require(
                plan.get("workerRecoveryOperations")
                == ["restore-fixture", "restore-fence", "restore-resume"],
                "worker recovery capabilities not approved",
            )
            admit_paused_worker(plan, json.loads(args.worker_readback.read_text()))
        db, settings = database(plan, restored=restored, worker=worker)
        try:
            if args.operation == "restore-role":
                result = await restored_role(db, settings, plan)
            elif args.operation == "restore-resume":
                result = await restored_resume(
                    db, settings, fixture, json.loads(args.before.read_text()), journal
                )
            elif args.operation == "restore-fixture":
                result = await restore_fixture(db, settings, fixture, api)
            elif args.operation == "restore-fence":
                retained = json.loads(args.before.read_text())
                require(
                    retained.get("imageDigest") == plan["imageDigest"]
                    and retained.get("operation") == "restore-fixture",
                    "exact nonterminal receipt required",
                )
                result = await restore_fence(db, settings, fixture, retained, journal)
            else:
                state = await snapshot(db, fixture)
                result = {"snapshot": state}
                if restored:
                    before = json.loads(args.before.read_text())
                    result["assertions"] = compare_snapshots(before["snapshot"], state)
                    await api.signin()
                    for creation in fixture["creationRequests"]:
                        replay = await api.request(
                            "POST",
                            creation["path"],
                            data=creation["payload"],
                            statuses=(200, 201),
                        )
                        require(
                            replay["id"] == creation["id"],
                            "restored creation replay changed result",
                        )
                    repeated = await snapshot(db, fixture)
                    require(
                        repeated["tables"]["legacy_creation_request_identities"]
                        == state["tables"]["legacy_creation_request_identities"],
                        "replay duplicated identity evidence",
                    )
                    from sqlalchemy import text
                    from sqlalchemy.exc import DBAPIError

                    async with db.engine.connect() as connection:
                        try:
                            await connection.execute(
                                text(
                                    "UPDATE legacy_creation_request_identities SET request_digest=request_digest WHERE workspace_id=:workspace"
                                ),
                                {"workspace": uuid.UUID(fixture["workspaceId"])},
                            )
                        except DBAPIError as error:
                            require(
                                getattr(error.orig, "sqlstate", None)
                                in {"42501", "55000"},
                                "unexpected append-only rejection",
                            )
                            await connection.rollback()
                        else:
                            await connection.rollback()
                            raise ValueError(
                                "restored runtime allowed identity mutation"
                            )
                    result["assertions"]["R1AppendOnlyAndReplay"] = "accepted"
                    result["assertions"]["R1CreationReplay"] = "accepted"
                    restored_file = await api.request(
                        "GET",
                        f"/api/v1/documents/{fixture['primary']['documentId']}/file",
                    )
                    require(
                        hashlib.sha256(restored_file).hexdigest()
                        == fixture["primary"]["contentSha256"],
                        "restored exact provider file changed",
                    )
                    result["restoredGrounded"] = await api.ground(fixture)
                    result["assertions"]["R4RestoredServingAndNoStaleReuse"] = (
                        "accepted"
                    )
            return journal.finish(result)
        finally:
            await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    for name in ("bundle", "authorization", "bindings", "runtime-readbacks", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("fixture", "before", "worker-readback"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--workload-stage", type=int, default=0)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        # Provider exceptions may contain URLs/tokens. Retain only the exception
        # class here; native request records are separately private and scoped.
        if not args.output.exists():
            write_new(
                args.output,
                {
                    "schema": SCHEMA,
                    "operation": args.operation,
                    "executionId": args.execution_id,
                    "status": "failed",
                    "errorClass": type(error).__name__,
                    "managedAcceptance": "unproved",
                    "reconcileBeforeRetry": True,
                },
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

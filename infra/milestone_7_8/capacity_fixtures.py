"""Finite synthetic capacity fixture setup through existing production endpoints.

No provider calls at preparation. Accounts/credentials and actual IDs stay in
the source-bound private execution bundle and native receipts, never in Git.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infra.milestone_7_8.capacity_validation import require, reserve_requests


def prepare_fixture_package(capacity: dict, *, namespace: str, model: str) -> dict:
    from opencanvas_api.core.config import Settings
    from opencanvas_api.services.agent_studio import _PROVIDER_MODELS
    from opencanvas_api.services.documents.extraction import extract_document
    from opencanvas_api.services.documents.chunking import chunk_document

    require(
        namespace.isalnum() and 8 <= len(namespace) <= 32,
        "bounded unique fixture namespace required",
    )
    require(
        bool(model) and len(model) <= 160, "existing approved provider model required"
    )
    require(
        model in _PROVIDER_MODELS["openai"],
        "model is not allowed by existing agent contract",
    )
    profiles = [p for p in capacity["profiles"] if p["name"] != "abusive-boundary"]
    users = max(p["users"] for p in profiles)
    byte_count = sum(
        p["users"]
        * p["workspacesPerUser"]
        * p["canvasesPerWorkspace"]
        * p["documentsPerCanvas"]
        * p["fileBytes"]
        for p in profiles
    )
    documents = sum(
        p["users"]
        * p["workspacesPerUser"]
        * p["canvasesPerWorkspace"]
        * p["documentsPerCanvas"]
        for p in profiles
    )
    require(
        users <= 4 and documents <= 64 and byte_count <= 16 * 1024 * 1024,
        "fixture allocation exceeded",
    )
    settings = Settings(**capacity["settings"])
    embedding_bytes = 0
    for profile in profiles:
        for ordinal in range(profile["documentsPerCanvas"]):
            raw = content(profile["fileBytes"], f"{profile['name']}-{ordinal}")
            extracted = extract_document(
                file_type="txt", content=raw, settings=settings
            )
            chunks = chunk_document(
                extracted,
                chunk_size=settings.document_chunk_size_chars,
                overlap=settings.document_chunk_overlap_chars,
            )
            embedding_bytes += (
                sum(len(chunk.content.encode()) for chunk in chunks)
                * profile["users"]
                * profile["workspacesPerUser"]
                * profile["canvasesPerWorkspace"]
            )
    return {
        "schema": "m78-capacity-fixtures-v1",
        "namespace": namespace,
        "profiles": profiles,
        "model": model,
        "activateIsolatedFixtureAgents": True,
        "accounts": [
            {
                "email": f"m78-{namespace}-{n}@example.invalid",
                "password": secrets.token_urlsafe(32) + "Aa1!",
                "displayName": f"Synthetic capacity user {n}",
            }
            for n in range(users)
        ],
        "bounds": {
            "requests": 6000,
            "documentBytes": byte_count,
            "documents": documents,
            "uploadConcurrency": 4,
            "modelCallsDuringSetup": 0,
            "embeddingInputCharacters": byte_count,
            "embeddingInputUtf8BytesIncludingOverlap": embedding_bytes,
            "embeddingTokenUpperBoundIncludingSdkRetries": embedding_bytes * 3,
            "embeddingTokenUpperBoundIncludingWorkerRetries": embedding_bytes
            * 3
            * (settings.processing_retry_limit + 1),
            "embeddingPasses": 1,
        },
        "managedAcceptance": "unproved",
    }


def content(size: int, marker: str) -> bytes:
    require(1 <= size <= 262144, "synthetic fixture size outside package bounds")
    line = f"Synthetic calibration {marker}: NOVA-731 is the supported reference value.\n".encode()
    return (line * ((size // len(line)) + 1))[:size]


def workflow_payload(key: str) -> dict:
    kinds = [
        "validate_input",
        "capture_context",
        "graph_retrieval",
        "evaluate_evidence",
        "grounded_model",
        "render_citations",
        "record_output",
    ]
    return {
        "kind": "grounded_answer",
        "name": "Synthetic bounded capacity workflow",
        "idempotencyKey": key,
        "version": {
            "maxDurationSeconds": 300,
            "maxRetriesPerStep": 0,
            "steps": [
                {
                    "stepKey": f"step-{i}",
                    "stepType": kind,
                    "dependsOn": [f"step-{i - 1}"] if i else [],
                    "maxAttempts": 1,
                }
                for i, kind in enumerate(kinds)
            ],
        },
    }


def agent_payload(key: str, workflow_version: str, model: str) -> dict:
    return {
        "kind": "grounded_research_assistant",
        "displayName": "Synthetic bounded capacity agent",
        "description": "Isolated selected-context capacity fixture.",
        "idempotencyKey": key,
        "version": {
            "purpose": "Answer only from the selected synthetic document.",
            "systemInstruction": "Use only the selected context, preserve citations and refuse unsupported claims.",
            "workflowVersionIds": [workflow_version],
            "provider": "openai",
            "model": model,
            "capabilityRequirements": [
                {"capability": capability, "resourceKind": "canvas"}
                for capability in (
                    "context.selected.read",
                    "retrieval.selected.search",
                    "draft.answer.create",
                    "workflow.step.execute",
                    "trace.scoped.read",
                )
            ],
            "limits": {
                "maxWorkflowExecutions": 1,
                "maxModelCalls": 1,
                "maxRetrievalCalls": 1,
                "maxEffects": 0,
                "maxApprovals": 0,
                "maxRetries": 0,
                "maxDurationSeconds": 300,
                "maxInputChars": 20000,
                "maxOutputChars": 4000,
                "maxEvidenceBundleRequests": 0,
            },
        },
    }


def prepare_stages(
    directory: Path,
    capacity: dict,
    *,
    namespace: str,
    model: str,
    row_lock_hold_seconds: int = 0,
) -> dict:
    """Write exact private setup + finite measured stages without provider access."""
    directory.mkdir(parents=True, exist_ok=False)
    fixture = prepare_fixture_package(capacity, namespace=namespace, model=model)
    stages: list[dict] = []

    def save(value: Any, metadata: dict) -> None:
        path = directory / f"capacity-{len(stages):02}.json"
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        stages.append(
            {
                **metadata,
                "file": path.name,
                "operationsSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    save(fixture, {"kind": "fixture", "phase": "setup", "concurrency": 4})
    canvases = sum(
        p["users"] * p["workspacesPerUser"] * p["canvasesPerWorkspace"]
        for p in fixture["profiles"]
    )

    def operations(phase: str, count: int, *, models: bool = False) -> list[dict]:
        result = []
        for number in range(count):
            index = number % canvases
            slot = f"CAPACITY_{index}"
            canvas = "${" + slot + "_CANVAS}"
            workspace = "${" + slot + "_WORKSPACE}"
            actor = "${" + slot + "_USER}"
            base = f"/api/v1/workspaces/{workspace}/canvases/{canvas}"
            kind = "search" if number % 2 else "snapshot"
            path = (
                f"/api/v1/canvases/{canvas}/documents/search"
                if kind == "search"
                else f"/api/v1/canvases/{canvas}/snapshot"
            )
            payload = (
                {"query": "NOVA-731", "documentIds": ["${" + slot + "_DOCUMENT_0}"]}
                if kind == "search"
                else None
            )
            item = {
                "operation_id": "${EXECUTION_ID}:" + phase + f":{number}",
                "actor_id": actor,
                "workspace_id": workspace,
                "kind": kind,
                "method": "POST" if payload else "GET",
                "path": path,
                "payload": payload,
                "expected_statuses": [200, 429, 503],
            }
            if models and number < 2:
                agent = number == 1
                kind = "agent" if agent else "workflow"
                payload = {
                    "workflowVersionId" if agent else "versionId": "${"
                    + slot
                    + "_WORKFLOW}",
                    "query": "What is the supported synthetic calibration reference value?",
                    "selectedObjectIds": [
                        "${" + slot + "_NOTE_0}",
                        "${" + slot + "_NOTE_1}",
                    ],
                    "seedObjectIds": ["${" + slot + "_NOTE_0}"],
                    "idempotencyKey": "${EXECUTION_ID}:" + phase + f":{kind}:{number}",
                }
                item.update(
                    {
                        "kind": kind,
                        "method": "POST",
                        "path": base
                        + (
                            "/agent-studio/agents/${" + slot + "_AGENT}/invocations"
                            if agent
                            else "/workflows/executions"
                        ),
                        "payload": payload,
                        "expected_json": {
                            "workflowStatus" if agent else "status": "completed"
                        },
                    }
                )
            result.append(item)
        return result

    baseline = operations("baseline", canvases, models=True)
    baseline.append(
        {
            "operation_id": "${EXECUTION_ID}:oversized-upload",
            "actor_id": "${CAPACITY_0_USER}",
            "workspace_id": "${CAPACITY_0_WORKSPACE}",
            "kind": "oversized-upload",
            "method": "POST",
            "path": "/api/v1/workspaces/${CAPACITY_0_WORKSPACE}/canvases/${CAPACITY_0_CANVAS}/upload-sessions",
            "payload": {
                "fileName": "synthetic-over-limit.txt",
                "mediaType": "text/plain",
                "sizeBytes": capacity["settings"]["document_max_file_size_bytes"] + 1,
                "sha256": hashlib.sha256(b"declared-oversized-fixture").hexdigest(),
                "idempotencyKey": "${EXECUTION_ID}:oversized-upload",
                "x": 0,
                "y": 0,
            },
            "expected_statuses": [413],
            "expected_rejection": True,
        }
    )
    save(
        baseline,
        {"phase": "baseline", "concurrency": 1},
    )
    for concurrency in capacity["rampConcurrencies"]:
        save(
            operations("ramp", max(canvases, concurrency * 2), models=True),
            {"phase": "ramp", "concurrency": concurrency},
        )
    save(
        operations(
            "spike",
            min(900, max(canvases * 2, capacity["concurrencyCap"] * 4)),
            models=True,
        ),
        {"phase": "spike", "concurrency": capacity["concurrencyCap"]},
    )
    if row_lock_hold_seconds:
        metadata, pressure = prepare_row_lock_stage(
            capacity, hold_seconds=row_lock_hold_seconds
        )
        save(pressure, metadata)
    for fault in capacity["selectedFaults"]:
        save(
            operations("failure", max(4, capacity["concurrencyCap"])),
            {
                "phase": "failure-under-load",
                "fault": fault,
                "concurrency": capacity["concurrencyCap"],
            },
        )
        save(
            operations("recovery", 4),
            {"phase": "recovery", "fault": fault, "concurrency": 1},
        )
    reserved = (
        fixture["bounds"]["requests"]
        + sum(
            len(stage.get("rowLock", {}).get("recoveryOperations", []))
            for stage in stages
        )
        + sum(
            len(json.loads((directory / stage["file"]).read_text()))
            for stage in stages[1:]
        )
    )
    require(
        reserved <= capacity["requestBudget"],
        "prepared stages exceed global request budget",
    )
    model_calls = 2 * (len(capacity["rampConcurrencies"]) + 2)
    require(
        model_calls <= capacity["logicalModelCallBudget"],
        "prepared model allocation exceeded",
    )
    return {
        "capacityStages": stages,
        "capacityFixturePackageSha256": stages[0]["operationsSha256"],
        "reservedRequests": reserved,
        "logicalModelCalls": model_calls,
        "maximumSdkModelAttempts": model_calls * 3,
        "fixtureBounds": fixture["bounds"],
    }


def prepare_row_lock_stage(
    capacity: dict, *, hold_seconds: int
) -> tuple[dict, list[dict]]:
    require(
        type(hold_seconds) is int and 1 <= hold_seconds <= 600,
        "row-lock hold must be1..600seconds",
    )
    pool = (
        capacity["settings"]["database_pool_size"]
        + capacity["settings"]["database_max_overflow"]
    )
    require(
        capacity["concurrencyCap"] > pool,
        "concurrency must exceed actual API pool to attempt pool pressure",
    )

    def writes(prefix: str, count: int, statuses: list[int]) -> list[dict]:
        return [
            {
                "operation_id": "${EXECUTION_ID}:" + prefix + f":{number}",
                "actor_id": "${PRIMARY_USER}",
                "workspace_id": "${PRIMARY_WORKSPACE}",
                "kind": "canvas-write",
                "method": "POST",
                "path": "/api/v1/canvases/${PRIMARY_CANVAS}/nodes",
                "payload": {
                    "type": "note",
                    "title": "Isolated capacity pressure",
                    "text": "Synthetic bounded row-lock observation.",
                    "position": {"x": number * 30, "y": 200},
                    "idempotencyKey": "${EXECUTION_ID}:" + prefix + f":{number}",
                },
                "expected_statuses": statuses,
            }
            for number in range(count)
        ]

    metadata = {
        "phase": "failure-under-load",
        "fault": "database-pool-pressure",
        "proofRole": "api",
        "concurrency": capacity["concurrencyCap"],
        "rowLock": {
            "faultSource": "postgresql-exact-core-canvas-row",
            "target": {
                "canvasId": "${PRIMARY_CANVAS}",
                "workspaceId": "${PRIMARY_WORKSPACE}",
                "ownerId": "${PRIMARY_USER}",
            },
            "holdSeconds": hold_seconds,
            "recoveryOperations": writes("rowlock-recovery", 2, [201]),
        },
    }
    return metadata, writes(
        "rowlock-pressure", capacity["concurrencyCap"] * 2, [201, 429, 503]
    )


async def run_setup(
    api: Any, plan: dict, package: dict, args: Any, deadline: datetime, root: Path
) -> dict:
    import httpx
    from infra.milestone_7_8.pilot_application_probe import Api

    capacity = plan["capacityProof"]
    require(
        package["schema"] == "m78-capacity-fixtures-v1",
        "fixture package schema differs",
    )
    require(
        package["profiles"]
        == [p for p in capacity["profiles"] if p["name"] != "abusive-boundary"],
        "fixture profiles differ from approval",
    )
    bounds = package["bounds"]
    require(
        bounds["requests"] <= capacity["requestBudget"]
        and bounds["modelCallsDuringSetup"] == 0
        and package["activateIsolatedFixtureAgents"] is True,
        "fixture allowance differs",
    )
    reserve_requests(root / "setup", capacity, bounds["requests"], args.execution_id)
    calls = 0
    bytes_sent = 0
    documents_sent = 0
    outputs: list[dict] = []
    accounts: list[dict] = []
    observed_profiles: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(bounds["uploadConcurrency"])
    journal_path = root / "requests.jsonl"
    journal_path.touch(exist_ok=False)

    def record(value: dict) -> None:
        with journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    async def request(selected: Any, method: str, path: str, **kwargs: Any) -> Any:
        nonlocal calls
        require(datetime.now(UTC) < deadline, "capacity fixture deadline expired")
        require(
            calls < bounds["requests"], "capacity fixture request allowance exhausted"
        )
        calls += 1
        sequence = calls
        require(
            path.startswith("/api/v1/") and "?" not in path and "//" not in path,
            "exact fixture endpoint required",
        )
        secret = kwargs.pop("secret", False)
        statuses = kwargs.pop("statuses", (200,))
        data = kwargs.pop("data", None)
        raw = kwargs.pop("content", None)
        headers = kwargs.pop("headers", {})
        require(not kwargs, "unexpected fixture HTTP option")
        record(
            {
                "sequence": sequence,
                "event": "intent",
                "method": method,
                "pathSha256": hashlib.sha256(path.encode()).hexdigest(),
                "requestSha256": None
                if secret
                else hashlib.sha256(
                    raw
                    if raw is not None
                    else json.dumps(data, sort_keys=True).encode()
                ).hexdigest(),
                "at": datetime.now(UTC).isoformat(),
            }
        )
        started = time.monotonic()
        try:
            response = await selected.client.request(
                method,
                path,
                json=data,
                content=raw,
                headers={"X-CSRF-Token": selected.csrf, **headers},
                timeout=min(45, (deadline - datetime.now(UTC)).total_seconds()),
            )
        except Exception as error:
            record(
                {
                    "sequence": sequence,
                    "event": "uncertain",
                    "errorClass": type(error).__name__,
                    "reconcileBeforeRetry": True,
                }
            )
            raise
        record(
            {
                "sequence": sequence,
                "event": "result",
                "status": response.status_code,
                "elapsedMs": (time.monotonic() - started) * 1000,
                "bodyBytes": len(response.content),
                "bodySha256": None
                if secret
                else hashlib.sha256(response.content).hexdigest(),
                "retryAfter": response.headers.get("retry-after"),
                "returnedIds": {}
                if secret
                or "json" not in response.headers.get("content-type", "")
                or not isinstance(response.json(), dict)
                else {
                    key: value
                    for key, value in response.json().items()
                    if key
                    in {
                        "id",
                        "workspaceId",
                        "canvasId",
                        "agentId",
                        "definitionId",
                        "versionId",
                        "documentId",
                        "objectVersionId",
                        "activationRequestId",
                        "sessionId",
                    }
                },
            }
        )
        require(
            response.status_code in statuses,
            f"capacity fixture {method}: unexpected HTTP {response.status_code}",
        )
        if not response.content:
            return None
        return (
            response.json()
            if "json" in response.headers.get("content-type", "")
            else response.content
        )

    async def upload(selected: Any, canvas: dict, size: int, ordinal: int) -> dict:
        nonlocal bytes_sent, documents_sent
        async with semaphore:
            raw = content(size, f"{canvas['profile']}-{ordinal}")
            require(
                bytes_sent + len(raw) <= bounds["documentBytes"]
                and documents_sent < bounds["documents"],
                "capacity object allocation exhausted",
            )
            bytes_sent += len(raw)
            documents_sent += 1
            base = f"/api/v1/workspaces/{canvas['workspaceId']}/canvases/{canvas['canvasId']}/upload-sessions"
            created = await request(
                selected,
                "POST",
                base,
                secret=True,
                statuses=(201,),
                data={
                    "fileName": f"synthetic-{ordinal}.txt",
                    "mediaType": "text/plain",
                    "sizeBytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "idempotencyKey": f"{args.execution_id}:doc:{canvas['canvasId']}:{ordinal}",
                    "x": ordinal * 150,
                    "y": 100,
                },
            )
            require(
                created["workspaceId"] == canvas["workspaceId"]
                and created["canvasId"] == canvas["canvasId"],
                "upload scope differs",
            )
            path = f"/api/v1/upload-sessions/{created['sessionId']}/content"
            require(created["uploadPath"] == path, "upload capability target differs")
            await request(
                selected,
                "PUT",
                path,
                content=raw,
                headers={
                    "X-Upload-Capability": created["capability"],
                    "Content-Type": "text/plain",
                },
                statuses=(200, 204),
                secret=True,
            )
            session_path = base + "/" + created["sessionId"]
            state = await request(selected, "POST", session_path + "/complete")
            started = time.monotonic()
            while state.get("objectState") != "clean":
                require(
                    time.monotonic() - started <= 900,
                    "capacity clean promotion exceeded unchanged 900-second policy",
                )
                require(
                    state.get("scanOutcome")
                    not in {
                        "infected",
                        "suspicious",
                        "timeout",
                        "error",
                        "unsupported",
                    },
                    "capacity fixture scanner rejected",
                )
                await asyncio.sleep(10)
                state = await request(selected, "GET", session_path)
            require(
                state["scanOutcome"] == "clean", "native clean scanner result absent"
            )
            while True:
                document = await request(
                    selected, "GET", f"/api/v1/documents/{created['documentId']}"
                )
                if document["status"] == "ready":
                    break
                require(
                    document["status"] not in {"failed", "error", "deleted"}
                    and time.monotonic() - started <= 1200,
                    "capacity document publication not ready",
                )
                await asyncio.sleep(10)
            return {
                key: created[key]
                for key in (
                    "documentId",
                    "documentVersionId",
                    "objectVersionId",
                    "sessionId",
                )
            } | {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "scanAndPublishSeconds": time.monotonic() - started,
            }

    async with AsyncExitStack() as stack:
        clients = []
        for index, account in enumerate(package["accounts"]):
            require(
                account["email"]
                == f"m78-{package['namespace']}-{index}@example.invalid",
                "fixture account escaped isolated namespace",
            )
            client = await stack.enter_async_context(
                httpx.AsyncClient(
                    base_url=api.client.base_url,
                    timeout=45,
                    follow_redirects=False,
                    trust_env=False,
                )
            )
            selected = Api(client, api.journal, api.execution)
            signed = await request(
                selected,
                "POST",
                "/api/v1/auth/signup",
                data=account,
                secret=True,
                statuses=(201,),
            )
            selected.csrf = signed["csrfToken"]
            accounts.append({"accountIndex": index, "userId": signed["user"]["id"]})
            clients.append(selected)
        for profile in package["profiles"]:
            profile_canvases = []
            for index in range(profile["users"]):
                selected = clients[index]
                for workspace_index in range(profile["workspacesPerUser"]):
                    workspace = await request(
                        selected,
                        "POST",
                        "/api/v1/workspaces",
                        statuses=(201,),
                        data={
                            "name": f"Capacity {package['namespace']} {profile['name']} {index}-{workspace_index}",
                            "description": "Synthetic isolated capacity fixture.",
                        },
                    )
                    for canvas_index in range(profile["canvasesPerWorkspace"]):
                        key = f"{args.execution_id}:{profile['name']}:{index}:{workspace_index}:{canvas_index}"
                        canvas = await request(
                            selected,
                            "POST",
                            "/api/v1/canvases",
                            statuses=(201,),
                            data={
                                "name": "Synthetic capacity canvas",
                                "workspaceId": workspace["id"],
                                "idempotencyKey": key + ":canvas",
                            },
                        )
                        item = {
                            "profile": profile["name"],
                            "accountIndex": index,
                            "userId": accounts[index]["userId"],
                            "workspaceId": workspace["id"],
                            "canvasId": canvas["id"],
                        }
                        require(
                            canvas["workspaceId"] == workspace["id"],
                            "canvas scope differs",
                        )
                        note = await request(
                            selected,
                            "POST",
                            f"/api/v1/canvases/{canvas['id']}/nodes",
                            statuses=(201,),
                            data={
                                "type": "note",
                                "title": "Synthetic capacity note",
                                "text": "Synthetic resource; NOVA-731.",
                                "position": {"x": 0, "y": 0},
                                "idempotencyKey": key + ":note",
                            },
                        )
                        canonical_notes = []
                        for number in range(2):
                            canonical_note = await request(
                                selected,
                                "POST",
                                f"/api/v1/workspaces/{workspace['id']}/notes",
                                statuses=(201,),
                                data={
                                    "title": f"Synthetic reference {number}",
                                    "content": "NOVA-731 is the supported synthetic calibration reference value.",
                                },
                            )
                            canonical_notes.append(canonical_note["id"])
                        comment = await request(
                            selected,
                            "POST",
                            f"/api/v1/workspaces/{workspace['id']}/resources/canvas/{canvas['id']}/comments",
                            statuses=(201,),
                            data={
                                "content": "Synthetic capacity comment.",
                                "idempotencyKey": key + ":comment",
                            },
                        )
                        shares = await request(
                            selected,
                            "POST",
                            f"/api/v1/workspaces/{workspace['id']}/shares",
                            statuses=(201,),
                            data={
                                "targets": [
                                    {
                                        "resourceKind": "canvas",
                                        "resourceId": canvas["id"],
                                        "audienceKind": "workspace",
                                        "accessLevel": "view",
                                    }
                                ],
                                "idempotencyKey": key + ":share",
                            },
                        )
                        base = f"/api/v1/workspaces/{workspace['id']}/canvases/{canvas['id']}"
                        await request(
                            selected,
                            "POST",
                            base + "/knowledge-graph/relationships",
                            statuses=(201,),
                            data={
                                "relationshipType": "related_to",
                                "source": {
                                    "kind": "note",
                                    "objectId": canonical_notes[0],
                                },
                                "target": {
                                    "kind": "note",
                                    "objectId": canonical_notes[1],
                                },
                                "idempotencyKey": key + ":graph",
                            },
                        )
                        workflow = await request(
                            selected,
                            "POST",
                            base + "/workflows",
                            statuses=(201,),
                            data=workflow_payload(key + ":workflow"),
                        )
                        version = workflow["versions"][0]["versionId"]
                        await request(
                            selected,
                            "POST",
                            base + f"/workflows/versions/{version}/validate",
                        )
                        await request(
                            selected,
                            "POST",
                            base + f"/workflows/versions/{version}/activate",
                        )
                        agent = await request(
                            selected,
                            "POST",
                            base + "/agent-studio/agents",
                            statuses=(201,),
                            data=agent_payload(
                                key + ":agent", version, package["model"]
                            ),
                        )
                        agent_version = agent["versions"][0]["versionId"]
                        validated = await request(
                            selected,
                            "POST",
                            base + f"/agent-studio/versions/{agent_version}/validate",
                        )
                        require(
                            validated["outcome"] == "valid",
                            "capacity agent failed production validation",
                        )
                        activation = await request(
                            selected,
                            "POST",
                            base
                            + f"/agent-studio/versions/{agent_version}/activation-requests",
                            data={"idempotencyKey": key + ":activate"},
                        )
                        decision = await request(
                            selected,
                            "POST",
                            base
                            + f"/agent-studio/activation-requests/{activation['activationRequestId']}/decision",
                            data={"decision": "approved"},
                        )
                        require(
                            decision["decision"] == "approved",
                            "isolated fixture agent activation not accepted",
                        )
                        item.update(
                            {
                                "noteId": note["id"],
                                "canonicalNoteIds": canonical_notes,
                                "comment": comment,
                                "shares": shares,
                                "workflow": workflow,
                                "agent": agent,
                            }
                        )
                        profile_canvases.append(item)

            async def populate(item: dict) -> None:
                item["documents"] = await asyncio.gather(
                    *(
                        upload(
                            clients[item["accountIndex"]],
                            item,
                            profile["fileBytes"],
                            ordinal,
                        )
                        for ordinal in range(profile["documentsPerCanvas"])
                    )
                )
                snapshot = await request(
                    clients[item["accountIndex"]],
                    "GET",
                    f"/api/v1/canvases/{item['canvasId']}/snapshot",
                )
                for document in item["documents"]:
                    nodes = [
                        node
                        for node in snapshot["nodes"]
                        if (node.get("document") or {}).get("id")
                        == document["documentId"]
                        or node.get("documentId") == document["documentId"]
                    ]
                    require(
                        len(nodes) == 1,
                        "published capacity document lacks exact canvas node",
                    )
                    document["nodeId"] = nodes[0]["id"]

            await asyncio.gather(*(populate(item) for item in profile_canvases))
            outputs.extend(profile_canvases)
            observed_profiles[profile["name"]] = {
                "users": len({x["userId"] for x in profile_canvases}),
                "workspaces": len({x["workspaceId"] for x in profile_canvases}),
                "canvases": len(profile_canvases),
                "documents": sum(len(x["documents"]) for x in profile_canvases),
                "bytes": sum(
                    d["bytes"] for x in profile_canvases for d in x["documents"]
                ),
                "observed": {
                    "users": len({x["userId"] for x in profile_canvases}),
                    "workspacesPerUser": min(
                        len(
                            {
                                y["workspaceId"]
                                for y in profile_canvases
                                if y["userId"] == x["userId"]
                            }
                        )
                        for x in profile_canvases
                    ),
                    "canvasesPerWorkspace": min(
                        sum(
                            y["workspaceId"] == x["workspaceId"]
                            for y in profile_canvases
                        )
                        for x in profile_canvases
                    ),
                    "documentsPerCanvas": min(
                        len(x["documents"]) for x in profile_canvases
                    ),
                    "fileBytes": min(
                        d["bytes"] for x in profile_canvases for d in x["documents"]
                    ),
                },
            }
    return {
        "capacityFixture": {
            "accounts": accounts,
            "canvases": outputs,
            "profiles": observed_profiles,
        },
        "requestCount": calls,
        "documentBytes": bytes_sent,
        "documents": documents_sent,
        "modelCalls": 0,
        "reservedRequestAllowance": bounds["requests"],
        "capacityStage": args.capacity_stage,
        "fixturePackageSha256": plan["capacityFixturePackageSha256"],
        "budgetReceiptSha256": hashlib.sha256(
            (root / "capacity-budget.json").read_bytes()
        ).hexdigest(),
        "managedAcceptance": "fixture observations only; capacity correlations/failure/recovery required",
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capacity-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--row-lock-seconds", type=int, default=0)
    args = parser.parse_args()
    prepared = prepare_stages(
        args.output,
        json.loads(args.capacity_plan.read_text()),
        namespace=args.namespace,
        model=args.model,
        row_lock_hold_seconds=args.row_lock_seconds,
    )
    with (args.output / "capacity-preparation.json").open(
        "x", encoding="utf-8"
    ) as handle:
        json.dump(prepared, handle, sort_keys=True, indent=2)
    print(
        json.dumps(
            {
                "stages": len(prepared["capacityStages"]),
                "reservedRequests": prepared["reservedRequests"],
                "logicalModelCalls": prepared["logicalModelCalls"],
                "fixtureBounds": prepared["fixtureBounds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

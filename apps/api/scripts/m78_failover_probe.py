"""One bounded campaign interruption; no cloud control-plane authority lives here."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.session import Database
from scripts.m78_database_identity import APPLICATION_DATABASE, require_bound_connection, sqlstate
from scripts.managed_postgres_evidence import (
    EvidenceError,
    _assertion,
    _authenticate_synthetic,
    _digest,
    _synthetic_password,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _object(response: httpx.Response, status: int) -> dict[str, Any]:
    if response.status_code != status:
        raise EvidenceError("failover setup or replay response was not accepted")
    value = response.json()
    if not isinstance(value, dict):
        raise EvidenceError("failover response is malformed")
    return value


def _transition_observations(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Retain observed transition boundaries, not a potentially truncated log line."""
    healthy = [
        all(row[key] is True for key in (
            "apiReadPassed", "apiWritePassed", "workerDatabaseActive",
        )) and int(str(row["workerOutcomes"])) > 0
        for row in rows
    ]
    first = next(index for index, valid in enumerate(healthy) if valid)
    failures = [index for index in range(first + 1, len(rows)) if not healthy[index]]
    if not failures:
        raise EvidenceError("failover transition observation is absent")
    selected = {first, failures[0] - 1, failures[0], failures[-1], len(rows) - 2, len(rows) - 1}
    return [rows[index] for index in sorted(selected)]


class FailoverProbe:
    def __init__(
        self,
        client: httpx.AsyncClient,
        other: httpx.AsyncClient,
        database: Database,
        *,
        token: str,
        worker_execution: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client, self.other, self.database = client, other, database
        self.token, self.worker_execution, self.clock = token, worker_execution, clock
        self.headers: dict[str, str] = {}
        self.other_headers: dict[str, str] = {}
        self.canvas = self.workspace = self.other_canvas = ""
        self.documents: list[str] = []
        self.requests: list[tuple[str, dict[str, object], str]] = []
        self.opaque_dispatches: list[dict[str, object]] = []
        self.activity_sequence = 0
        self.stage = "setup"
        self.started = _now()

    async def setup(self) -> None:
        campaign = os.environ["OPENCANVAS_CAMPAIGN_ID"]
        generation = os.environ["OPENCANVAS_CAMPAIGN_GENERATION_ID"]
        suffix = self.token[:12]
        for client, tenant in ((self.client, "a"), (self.other, "b")):
            csrf = await _authenticate_synthetic(
                client,
                suffix=suffix,
                tenant=tenant,
                password=_synthetic_password(campaign, generation, tenant),
            )
            headers = {"X-CSRF-Token": csrf}
            if tenant == "a":
                self.headers = headers
            else:
                self.other_headers = headers
        first = _object(
            await self.client.post(
                "/api/v1/canvases",
                headers=self.headers,
                json={"idempotencyKey": f"setup-{self.token}", "name": "M78 disruption"},
            ),
            201,
        )
        self.canvas, self.workspace = first["id"], first["workspaceId"]
        self.other_canvas = _object(
            await self.other.post(
                "/api/v1/canvases",
                headers=self.other_headers,
                json={"idempotencyKey": f"other-{self.token}", "name": "M78 other scope"},
            ),
            201,
        )["id"]
        nodes = []
        for ordinal in range(2):
            nodes.append(
                _object(
                    await self.client.post(
                        f"/api/v1/canvases/{self.canvas}/nodes",
                        headers=self.headers,
                        json={
                            "idempotencyKey": f"seed-{ordinal}-{self.token}",
                            "type": "note",
                            "title": "seed",
                            "text": "synthetic",
                            "position": {"x": 1, "y": 2},
                        },
                    ),
                    201,
                )
            )
        self.requests = [
            (
                "/api/v1/canvases",
                {"idempotencyKey": f"amb-canvas-{self.token}", "name": "M78 unknown result"},
                "canvas.create",
            ),
            (
                f"/api/v1/canvases/{self.canvas}/nodes",
                {
                    "idempotencyKey": f"amb-node-{self.token}",
                    "type": "note",
                    "title": "unknown",
                    "text": "synthetic",
                    "position": {"x": 3, "y": 4},
                },
                "node.create",
            ),
            (
                f"/api/v1/canvases/{self.canvas}/nodes/{nodes[0]['id']}/duplicate",
                {"idempotencyKey": f"amb-duplicate-{self.token}", "revision": nodes[0]["revision"]},
                "node.duplicate",
            ),
            (
                f"/api/v1/canvases/{self.canvas}/edges",
                {
                    "idempotencyKey": f"amb-edge-{self.token}",
                    "sourceNodeId": nodes[0]["id"],
                    "targetNodeId": nodes[1]["id"],
                    "kind": "default",
                },
                "edge.create",
            ),
        ]
        # The harness deliberately withholds the first response from its resolver.
        # No result ID/status from these calls is used to certify commit success.
        for url, payload, operation in self.requests:
            started = _now()
            try:
                response = await self.client.post(url, json=payload, headers=self.headers)
                await response.aclose()
            except httpx.TransportError:
                pass
            self.opaque_dispatches.append(
                {
                    "operation": operation,
                    "keySha256": _digest(payload["idempotencyKey"]),
                    "startedAtUtc": started,
                    "endedAtUtc": _now(),
                    "responseWithheld": True,
                }
            )
        await self.upload()

    async def upload(self) -> None:
        if len(self.documents) >= 64:
            return
        content = (f"M78 {self.token} {len(self.documents)} synthetic document.\n" * 1024).encode()
        result = _object(
            await self.client.post(
                f"/api/v1/canvases/{self.canvas}/documents",
                headers=self.headers,
                files={"file": (f"m78-{len(self.documents)}.txt", content, "text/plain")},
            ),
            201,
        )
        self.documents.append(result["document"]["id"])

    async def worker_snapshot(self) -> dict[str, list[dict[str, Any]]]:
        # Scope every durable observation to this run's documents and exact execution.
        async with self.database.engine.begin() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT worker_id, last_seen_at::text AS seen FROM worker_heartbeats "
                            "WHERE worker_id LIKE :prefix "
                            "AND last_seen_at > now() - interval '15 seconds'"
                        ),
                        {"prefix": self.worker_execution + "-%"},
                    )
                )
                .mappings()
                .all()
            )
            attempts = (
                (
                    await connection.execute(
                        text(
                            "SELECT a.attempt_id::text AS id, a.job_run_id::text AS job, "
                            "a.worker_id, a.outcome, a.started_at::text AS started, "
                            "a.completed_at::text AS completed, a.lease_generation "
                            "FROM durable_job_attempts a "
                            "JOIN document_processing_jobs j ON j.id=a.job_run_id "
                            "WHERE j.document_id::text = ANY(CAST(:documents AS text[])) "
                            "AND a.worker_id LIKE :prefix ORDER BY a.attempt_id"
                        ),
                        {"documents": self.documents, "prefix": self.worker_execution + "-%"},
                    )
                )
                .mappings()
                .all()
            )
            outcomes = (
                (
                    await connection.execute(
                        text(
                            "SELECT o.job_run_id::text AS job, o.outcome, "
                            "o.attempt_id::text AS attempt, "
                            "o.recorded_at::text AS recorded "
                            "FROM durable_job_outcomes o "
                            "JOIN document_processing_jobs j ON j.id=o.job_run_id "
                            "WHERE j.document_id::text = ANY(CAST(:documents AS text[])) "
                            "ORDER BY o.job_run_id"
                        ),
                        {"documents": self.documents},
                    )
                )
                .mappings()
                .all()
            )
        if len({row["job"] for row in outcomes}) != len(outcomes):
            raise EvidenceError("duplicate durable worker outcomes observed")
        if any(row["outcome"] != "succeeded" for row in outcomes):
            raise EvidenceError("synthetic worker processing did not succeed")
        return {
            "heartbeats": [dict(row) for row in rows],
            "attempts": [dict(row) for row in attempts],
            "outcomes": [dict(row) for row in outcomes],
        }

    async def observe(self) -> dict[str, object]:
        self.activity_sequence += 1
        read = write = active = False
        snapshot: dict[str, Any] = {"heartbeats": [], "attempts": [], "outcomes": []}
        try:
            ready = await self.client.get("/api/v1/health/ready")
            result = await self.client.get(f"/api/v1/canvases/{self.canvas}")
            read = ready.status_code == 200 and result.status_code == 200
            result = await self.client.post(
                f"/api/v1/canvases/{self.canvas}/nodes",
                headers=self.headers,
                json={
                    "idempotencyKey": f"activity-{self.token}-{self.activity_sequence}",
                    "type": "note",
                    "title": "ongoing",
                    "text": "bounded activity",
                    "position": {"x": 1, "y": 1},
                },
            )
            write = result.status_code == 201
        except httpx.TransportError:
            pass
        try:
            snapshot = await self.worker_snapshot()
            active = len(snapshot["heartbeats"]) == 4
        except DBAPIError as exc:
            if (not exc.connection_invalidated
                    and sqlstate(exc) not in {"08003", "08006", "57P01", "57P02", "57P03"}):
                raise
        except TimeoutError:
            # A new snapshot opens a fresh connection on the next bounded iteration.
            # Connection acquisition can time out before a DBAPI error exists.
            pass
        heartbeats = snapshot["heartbeats"]
        return {
            "observedAtUtc": _now(),
            "apiReadPassed": read,
            "apiWritePassed": write,
            "workerDatabaseActive": active,
            "workerObservedAtUtc": min((row["seen"] for row in heartbeats), default=None),
            "workerLatestClaimAtUtc": max(
                (row["started"] for row in snapshot["attempts"] if row["started"]),
                default=None,
            ),
            "workerLatestOutcomeAtUtc": max(
                (row["recorded"] for row in snapshot["outcomes"]),
                default=None,
            ),
            "workerClaims": len(snapshot["attempts"]),
            "workerOutcomes": len(snapshot["outcomes"]),
            "evidenceSha256": _digest(snapshot),
        }

    async def replay(self) -> str:
        records = []
        for url, payload, operation in self.requests:
            async with self.database.engine.begin() as connection:
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                rows = (
                    (
                        await connection.execute(
                            text(
                                "SELECT i.result_id::text AS result, "
                                "i.result_kind, i.request_digest, "
                                "CASE i.result_kind WHEN 'canvas' THEN "
                                "(SELECT count(*) FROM canvases c "
                                "WHERE c.id=i.result_id AND c.workspace_id=i.workspace_id) "
                                "WHEN 'node' THEN (SELECT count(*) FROM nodes n "
                                "WHERE n.id=i.result_id AND n.canvas_id=i.canvas_id) "
                                "WHEN 'edge' THEN (SELECT count(*) FROM edges e "
                                "WHERE e.id=i.result_id AND e.canvas_id=i.canvas_id) "
                                "END AS resources FROM legacy_creation_request_identities i "
                                "JOIN users u ON u.id=i.actor_user_id "
                                "WHERE i.operation=:operation AND i.idempotency_key=:key "
                                "AND u.email=:email"
                            ),
                            {
                                "operation": operation,
                                "key": payload["idempotencyKey"],
                                "email": f"m78-{self.token[:12]}-a@example.test",
                            },
                        )
                    )
                    .mappings()
                    .all()
                )
            # Resolve the withheld outcome before replay can create anything.
            # A failed initial request must not become a false ambiguous-commit proof.
            if len(rows) != 1 or rows[0]["resources"] != 1:
                raise EvidenceError("withheld request has no unique committed result before replay")
            replay = _object(await self.client.post(url, json=payload, headers=self.headers), 201)
            again = _object(await self.client.post(url, json=payload, headers=self.headers), 201)
            if not (rows[0]["result"] == replay.get("id") == again.get("id")):
                raise EvidenceError("ambiguous request did not resolve to one durable result")
            records.append(
                {
                    "operation": operation,
                    "row": dict(rows[0]),
                    "replayId": replay["id"],
                    "againId": again["id"],
                }
            )
        return _digest({"withheld": self.opaque_dispatches, "resolved": records})

    async def tenant_checks(self) -> str:
        invitation = _object(
            await self.client.post(
                f"/api/v1/workspaces/{self.workspace}/invitations",
                headers=self.headers,
                json={
                    "recipientEmail": f"m78-{self.token[:12]}-b@example.test",
                    "intendedRole": "editor",
                    "idempotencyKey": f"invite-{self.token}",
                },
            ),
            201,
        )
        member = _object(
            await self.other.post(
                f"/api/v1/collaboration-invitations/{invitation['invitationId']}/accept",
                headers=self.other_headers,
                json={
                    "token": invitation.get("developmentToken"),
                    "idempotencyKey": f"accept-{self.token}",
                },
            ),
            200,
        )
        context_url = f"/api/v1/workspaces/{self.workspace}/collaboration-context"
        if (await self.other.get(context_url)).status_code != 200:
            raise EvidenceError("membership access before revocation was not established")
        _object(
            await self.client.post(
                f"/api/v1/workspaces/{self.workspace}/memberships/{member['membershipId']}/suspend",
                headers=self.headers,
                json={"idempotencyKey": f"suspend-{self.token}"},
            ),
            200,
        )
        statuses = []
        for _ in range(3):
            for url in (
                context_url,
                f"/api/v1/canvases/{self.canvas}",
                f"/api/v1/documents/{self.documents[0]}",
                f"/api/v1/documents/{self.documents[0]}/text",
            ):
                statuses.append((await self.other.get(url)).status_code)
            statuses.append(
                (
                    await self.other.post(
                        f"/api/v1/canvases/{self.canvas}/nodes",
                        headers=self.other_headers,
                        json=self.requests[1][1],
                    )
                ).status_code
            )
        if any(status not in (403, 404) for status in statuses):
            raise EvidenceError("revoked membership or pooled tenant access was accepted")
        own = await self.client.get(f"/api/v1/documents/{self.documents[0]}/text")
        if own.status_code != 200:
            raise EvidenceError("worker/indexer output was not readable by its owner")
        search = await self.client.post(
            f"/api/v1/canvases/{self.canvas}/documents/search",
            headers=self.headers,
            json={
                "query": "synthetic document",
                "documentIds": [self.documents[0]],
                "minRelevance": -1,
                "topK": 1,
            },
        )
        if search.status_code != 200 or not search.json().get("matches"):
            raise EvidenceError("indexed document retrieval was not established")
        return _digest(
            {
                "denied": statuses,
                "ownerStatus": own.status_code,
                "ownerBodySha256": hashlib.sha256(own.content).hexdigest(),
                "retrievalSha256": hashlib.sha256(search.content).hexdigest(),
            }
        )

    async def exercise(self) -> dict[str, object]:
        await self.setup()
        self.stage = "sampling"
        observations: list[dict[str, object]] = []
        end = self.clock() + 900
        ready: str | None = None
        interrupted = False
        disruption_at: datetime | None = None
        last_upload = self.clock()
        while self.clock() < end:
            row = await self.observe()
            observations.append(row)
            green = all(
                row[key] is True
                for key in (
                    "apiReadPassed",
                    "apiWritePassed",
                    "workerDatabaseActive",
                )
            )
            if ready is None and green and int(str(row["workerOutcomes"])) > 0:
                ready = _now()
                print(
                    f"M78_FAILOVER_READY {self.token} "
                    + json.dumps(
                        {
                            "version": "m7.8-failover-ready-v1",
                            "observedAtUtc": ready,
                            "workerExecution": self.worker_execution,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            elif ready is not None and not green:
                interrupted = True
                disruption_at = datetime.fromisoformat(str(row["observedAtUtc"]))
            elif ready is not None and interrupted and green:
                before = next(item for item in observations if int(str(item["workerOutcomes"])) > 0)
                if (
                    int(str(row["workerClaims"])) > int(str(before["workerClaims"]))
                    and int(str(row["workerOutcomes"])) > int(str(before["workerOutcomes"]))
                    and disruption_at is not None
                    and all(
                        isinstance(row.get(key), str)
                        and datetime.fromisoformat(str(row[key])) > disruption_at
                        for key in ("workerLatestClaimAtUtc", "workerLatestOutcomeAtUtc")
                    )
                ):
                    self.stage = "ambiguous-result-replay"
                    replay_hash = await self.replay()
                    self.stage = "tenant-revocation-and-retrieval"
                    tenant_hash = await self.tenant_checks()
                    finished = _now()
                    disruption = {
                        "version": "m7.8-failover-window-v1",
                        "startedAtUtc": self.started,
                        "readyAtUtc": ready,
                        "endedAtUtc": finished,
                        "observations": _transition_observations(observations),
                        "workerClaimsObserved": True,
                        "workerRecoveryObserved": True,
                        "ambiguousReplayVerified": True,
                        "tenantIsolationVerified": True,
                        "replayEvidenceSha256": replay_hash,
                        "tenantEvidenceSha256": tenant_hash,
                    }
                    return {
                        "version": "m7.8-managed-postgres-evidence-v1",
                        "status": "passed",
                        "observedAtUtc": finished,
                        "disruption": disruption,
                        "assertions": [
                            asdict(_assertion(code, True, disruption))
                            for code in (
                                "recovery.failover",
                                "recovery.stale-pool",
                                "tenant.post-failover",
                                "idempotency.canvas",
                                "idempotency.node",
                                "idempotency.duplicate-node",
                                "idempotency.edge",
                                "idempotency.authority-revalidation",
                            )
                        ],
                    }
            if (
                green
                and self.clock() - last_upload >= 10
                and (interrupted or len(self.documents) < 32)
            ):
                await self.upload()
                last_upload = self.clock()
            await asyncio.sleep(1)
        raise EvidenceError("failover did not establish disruption and application/worker recovery")


async def run() -> dict[str, object]:
    token = os.environ.get("M78_EVIDENCE_TOKEN", "")
    worker = os.environ.get("M78_FAILOVER_WORKER_EXECUTION", "")
    url = os.environ.get("M78_PRIVATE_API_URL", "")
    if (
        re.fullmatch(r"[a-f0-9]{32}", token) is None
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", worker) is None
        or not url.startswith("https://")
    ):
        raise EvidenceError("failover execution or private API binding is absent")
    settings = get_settings()
    settings.require_database_role(DatabaseRole.MIGRATION)
    manifest = load_principal_manifest()
    database = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        async with database.engine.connect() as connection:
            await require_bound_connection(
                connection,
                manifest,
                PrincipalSlot.MIGRATION,
                APPLICATION_DATABASE,
            )
        async with (
            httpx.AsyncClient(base_url=url, timeout=5) as client,
            httpx.AsyncClient(base_url=url, timeout=5) as other,
        ):
            async with asyncio.timeout(960):
                probe = FailoverProbe(
                    client,
                    other,
                    database,
                    token=token,
                    worker_execution=worker,
                )
                try:
                    return await probe.exercise()
                except Exception as exc:
                    state = sqlstate(exc)
                    print(json.dumps({
                        "status": "blocked", "phase": "failover-window", "stage": probe.stage,
                        "errorClass": type(exc).__name__,
                        "sqlstate": (state if state and re.fullmatch(r"[0-9A-Z]{5}", state)
                                     else None),
                    }, sort_keys=True), file=sys.stderr, flush=True)
                    raise
    finally:
        await database.dispose()

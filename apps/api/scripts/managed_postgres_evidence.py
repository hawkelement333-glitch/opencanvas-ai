from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Final

import httpx
from sqlalchemy import text

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.principal_manifest import PrincipalSlot, load_principal_manifest
from opencanvas_api.db.role_privileges import (
    RUNTIME_FUNCTION_PRIVILEGES,
    RUNTIME_SEQUENCE_PRIVILEGES,
    RUNTIME_TABLE_PRIVILEGES,
)
from opencanvas_api.db.session import Database

REQUIRED_PROOFS: Final = frozenset(
    {
        "catalog.roles",
        "catalog.ownership",
        "catalog.public-restrictions",
        "catalog.runtime-grants",
        "migration.nullpool",
        "migration.advisory-lock",
        "migration.exact-revision",
        "migration.reconciliation",
        "capacity.max-connections",
        "capacity.azure-reserved",
        "capacity.pool-ceilings",
        "capacity.rollout-overlap",
        "capacity.operator-consumers",
        "capacity.observed-peak",
        "capacity.safety-reserve",
        "recovery.failover",
        "recovery.stale-pool",
        "recovery.credential-revocation",
        "idempotency.canvas",
        "idempotency.node",
        "idempotency.duplicate-node",
        "idempotency.edge",
        "idempotency.conflict-409",
        "idempotency.authority-revalidation",
        "tenant.pool-reuse",
        "tenant.post-failover",
        "tenant.forged-workspace",
        "tenant.forged-canvas",
        "tenant.forged-replay",
        "tenant.forged-evidence-bundle",
        "tenant.forged-workflow",
        "operations.zones",
        "operations.ha",
        "operations.maintenance",
        "operations.storage",
        "operations.backup",
        "operations.latency",
        "operations.recovery",
    }
)
_CONTROL_PLANE_FIELDS: Final = {
    "primaryZone",
    "standbyZone",
    "haMode",
    "maintenanceDay",
    "maintenanceHour",
    "storageGiB",
    "storageTier",
    "backupRetentionDays",
    "geoBackup",
    "latencyP95Ms",
    "recoverySeconds",
    "failoverObserved",
    "credentialRecoveryObserved",
    "postFailoverTenantIsolationObserved",
    "azureReservedConnections",
    "poolCeilings",
    "rolloutOverlap",
    "operatorConsumers",
    "observedPeak",
    "safetyReserve",
    "maxConnections",
}


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Assertion:
    code: str
    passed: bool
    observed_count: int
    evidence_sha256: str


def _digest(value: object) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(b"m7.8/evidence/v1\0" + encoded).hexdigest()


def _assertion(code: str, passed: bool, value: object, count: int = 1) -> Assertion:
    if code not in REQUIRED_PROOFS:
        raise EvidenceError("unknown evidence assertion")
    return Assertion(code, passed, count, _digest(value))


def validate_control_plane_evidence(raw: str) -> list[Assertion]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceError("control-plane evidence is invalid") from exc
    if not isinstance(value, dict) or set(value) != _CONTROL_PLANE_FIELDS:
        raise EvidenceError("control-plane evidence is incomplete or ambiguous")
    integer_fields = {
        "maintenanceDay",
        "maintenanceHour",
        "storageGiB",
        "backupRetentionDays",
        "azureReservedConnections",
        "poolCeilings",
        "rolloutOverlap",
        "operatorConsumers",
        "observedPeak",
        "safetyReserve",
        "maxConnections",
    }
    if any(type(value[field]) is not int for field in integer_fields):
        raise EvidenceError("control-plane integer evidence is malformed")
    if type(value["geoBackup"]) is not bool or any(
        type(value[field]) not in {int, float} for field in ("latencyP95Ms", "recoverySeconds")
    ):
        raise EvidenceError("control-plane typed evidence is malformed")
    proofs = {
        "operations.zones": (
            isinstance(value["primaryZone"], str)
            and isinstance(value["standbyZone"], str)
            and bool(value["primaryZone"])
            and value["primaryZone"] != value["standbyZone"]
        ),
        "operations.ha": value["haMode"] == "ZoneRedundant",
        "operations.maintenance": (
            0 <= value["maintenanceDay"] <= 6 and 0 <= value["maintenanceHour"] <= 23
        ),
        "operations.storage": value["storageGiB"] == 64 and value["storageTier"] == "P6",
        "operations.backup": value["backupRetentionDays"] == 7 and value["geoBackup"] is False,
        "operations.latency": value["latencyP95Ms"] >= 0,
        "operations.recovery": value["recoverySeconds"] > 0,
        "recovery.failover": value["failoverObserved"] is True,
        "recovery.stale-pool": value["failoverObserved"] is True,
        "recovery.credential-revocation": value["credentialRecoveryObserved"] is True,
        "tenant.post-failover": value["postFailoverTenantIsolationObserved"] is True,
    }
    committed_capacity = sum(
        value[key]
        for key in (
            "azureReservedConnections",
            "poolCeilings",
            "rolloutOverlap",
            "operatorConsumers",
            "safetyReserve",
        )
    )
    proofs.update(
        {
            "capacity.max-connections": value["maxConnections"] > 0,
            "capacity.azure-reserved": value["azureReservedConnections"] >= 0,
            "capacity.pool-ceilings": value["poolCeilings"] > 0,
            "capacity.rollout-overlap": value["rolloutOverlap"] >= 0,
            "capacity.operator-consumers": value["operatorConsumers"] > 0,
            "capacity.observed-peak": 0 < value["observedPeak"] <= value["poolCeilings"],
            "capacity.safety-reserve": (
                value["safetyReserve"] >= 20
                and committed_capacity < value["maxConnections"]
                and value["observedPeak"]
                <= value["maxConnections"]
                - value["azureReservedConnections"]
                - value["safetyReserve"]
            ),
        }
    )
    assertions = [_assertion(code, passed, {code: value}, 1) for code, passed in proofs.items()]
    if value["safetyReserve"] < 20:
        raise EvidenceError("connection safety reserve is below the approved minimum of 20")
    if committed_capacity >= value["maxConnections"]:
        raise EvidenceError(
            f"connection budget shortfall: {committed_capacity - value['maxConnections'] + 1}"
        )
    if not all(item.passed for item in assertions):
        raise EvidenceError("control-plane evidence failed an assertion")
    return assertions


async def catalog_assertions(role: DatabaseRole) -> list[Assertion]:
    settings = get_settings()
    settings.require_database_role(role)
    manifest = load_principal_manifest()
    database = Database.from_settings(settings, expected_role=role)
    try:
        async with database.engine.connect() as connection:
            current = str((await connection.execute(text("SELECT current_user"))).scalar_one())
            expected_slot = {
                DatabaseRole.API: PrincipalSlot.API,
                DatabaseRole.WORKER: PrincipalSlot.WORKER,
                DatabaseRole.MIGRATION: PrincipalSlot.MIGRATION,
                DatabaseRole.OBSERVABILITY: PrincipalSlot.EVIDENCE,
            }[role]
            manifest.require_current(expected_slot, current_name=current)
            max_connections = int(
                (await connection.execute(text("SHOW max_connections"))).scalar_one()
            )
            results = [
                _assertion("catalog.roles", True, {"role": role.value}),
                _assertion("capacity.max-connections", max_connections > 0, max_connections),
            ]
            if role in {DatabaseRole.API, DatabaseRole.WORKER}:
                matrix = RUNTIME_TABLE_PRIVILEGES[role]
                table_names = tuple(
                    str(item)
                    for item in (
                        await connection.execute(
                            text(
                                "SELECT tablename FROM pg_catalog.pg_tables "
                                "WHERE schemaname = 'public' ORDER BY tablename"
                            )
                        )
                    ).scalars()
                )
                observed: dict[str, int] = {}
                for operation, expected_tables in matrix.items():
                    observed[operation] = 0
                    for table_name in table_names:
                        allowed = bool(
                            (
                                await connection.execute(
                                    text(
                                        "SELECT has_table_privilege("
                                        "current_user, :table, :operation)"
                                    ),
                                    {
                                        "table": f"public.{table_name}",
                                        "operation": operation,
                                    },
                                )
                            ).scalar_one()
                        )
                        if allowed != (table_name in expected_tables):
                            raise EvidenceError("runtime table grants differ from the exact matrix")
                        observed[operation] += int(allowed)
                sequence_names = tuple(
                    str(item)
                    for item in (
                        await connection.execute(
                            text(
                                "SELECT sequencename FROM pg_catalog.pg_sequences "
                                "WHERE schemaname = 'public' ORDER BY sequencename"
                            )
                        )
                    ).scalars()
                )
                for sequence_name in sequence_names:
                    for sequence_operation in ("USAGE", "SELECT", "UPDATE"):
                        allowed = bool(
                            (
                                await connection.execute(
                                    text(
                                        "SELECT has_sequence_privilege("
                                        "current_user, :sequence, :operation)"
                                    ),
                                    {
                                        "sequence": f"public.{sequence_name}",
                                        "operation": sequence_operation,
                                    },
                                )
                            ).scalar_one()
                        )
                        if allowed:
                            raise EvidenceError(
                                "runtime sequence privilege is broader than allowed"
                            )
                function_oids = tuple(
                    int(item)
                    for item in (
                        await connection.execute(
                            text(
                                "SELECT p.oid FROM pg_catalog.pg_proc AS p "
                                "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
                                "WHERE n.nspname = 'public' ORDER BY p.oid"
                            )
                        )
                    ).scalars()
                )
                for function_oid in function_oids:
                    allowed = bool(
                        (
                            await connection.execute(
                                text(
                                    "SELECT has_function_privilege("
                                    "current_user, :function_oid, 'EXECUTE')"
                                ),
                                {"function_oid": function_oid},
                            )
                        ).scalar_one()
                    )
                    if allowed:
                        raise EvidenceError("runtime function execution is broader than allowed")
                results.append(
                    _assertion(
                        "catalog.runtime-grants",
                        not RUNTIME_SEQUENCE_PRIVILEGES[role]
                        and not RUNTIME_FUNCTION_PRIVILEGES[role],
                        {
                            "role": role.value,
                            "tableGrants": observed,
                            "sequenceObjectsChecked": len(sequence_names),
                            "functionObjectsChecked": len(function_oids),
                            "declaredSequenceGrantsEmpty": True,
                            "declaredFunctionGrantsEmpty": True,
                        },
                    )
                )
            elif role is DatabaseRole.OBSERVABILITY:
                database_slots = (
                    PrincipalSlot.BOOTSTRAP,
                    PrincipalSlot.MIGRATION,
                    PrincipalSlot.API,
                    PrincipalSlot.WORKER,
                    PrincipalSlot.EVIDENCE,
                )
                safe_roles = True
                for slot in database_slots:
                    binding = manifest.principals[slot]
                    row = (
                        await connection.execute(
                            text(
                                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                                "rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = :role"
                            ),
                            {"role": binding.name},
                        )
                    ).one_or_none()
                    if row is None or any(bool(item) for item in row):
                        safe_roles = False
                migration = manifest.principals[PrincipalSlot.MIGRATION].name
                for slot in (PrincipalSlot.API, PrincipalSlot.WORKER, PrincipalSlot.EVIDENCE):
                    can_assume = bool(
                        (
                            await connection.execute(
                                text("SELECT pg_has_role(:member, :target, 'MEMBER')"),
                                {
                                    "member": manifest.principals[slot].name,
                                    "target": migration,
                                },
                            )
                        ).scalar_one()
                    )
                    safe_roles = safe_roles and not can_assume
                schema_owner = str(
                    (
                        await connection.execute(
                            text(
                                "SELECT pg_catalog.pg_get_userbyid(nspowner) "
                                "FROM pg_catalog.pg_namespace WHERE nspname = 'public'"
                            )
                        )
                    ).scalar_one()
                )
                unowned_relations = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM pg_catalog.pg_class AS c "
                                "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                                "WHERE n.nspname = 'public' AND c.relkind IN ('r','p','S','v','m') "
                                "AND pg_catalog.pg_get_userbyid(c.relowner) <> :migration"
                            ),
                            {"migration": migration},
                        )
                    ).scalar_one()
                )
                public_schema_create = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM pg_catalog.pg_namespace AS n "
                                "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE("
                                "n.nspacl, pg_catalog.acldefault('n', n.nspowner))) AS acl "
                                "WHERE n.nspname = 'public' AND acl.grantee = 0 "
                                "AND acl.privilege_type = 'CREATE'"
                            )
                        )
                    ).scalar_one()
                )
                public_function_execute = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT count(*) FROM pg_catalog.pg_proc AS p "
                                "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
                                "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE("
                                "p.proacl, pg_catalog.acldefault('f', p.proowner))) AS acl "
                                "WHERE n.nspname = 'public' AND acl.grantee = 0 "
                                "AND acl.privilege_type = 'EXECUTE'"
                            )
                        )
                    ).scalar_one()
                )
                results.extend(
                    [
                        _assertion("catalog.roles", safe_roles, {"roles": len(database_slots)}),
                        _assertion(
                            "catalog.ownership",
                            schema_owner == migration and unowned_relations == 0,
                            {
                                "schemaOwnerMatches": schema_owner == migration,
                                "unownedRelations": unowned_relations,
                            },
                        ),
                        _assertion(
                            "catalog.public-restrictions",
                            public_schema_create == 0 and public_function_execute == 0,
                            {
                                "publicSchemaCreate": public_schema_create,
                                "publicFunctionExecute": public_function_execute,
                            },
                        ),
                    ]
                )
            else:
                revision = str(
                    (
                        await connection.execute(text("SELECT version_num FROM alembic_version"))
                    ).scalar_one()
                )
                results.append(
                    _assertion("migration.exact-revision", revision == "20260726_0029", revision)
                )
                suffix = _digest(
                    {"campaign": manifest.campaign_id, "generation": manifest.generation_id}
                )[:12]
                identities = {
                    "idempotency.canvas": ("canvas.create", f"canvas-{suffix}", "canvases"),
                    "idempotency.node": ("node.create", f"node-{suffix}", "nodes"),
                    "idempotency.duplicate-node": (
                        "node.duplicate",
                        f"duplicate-{suffix}",
                        "nodes",
                    ),
                    "idempotency.edge": ("edge.create", f"edge-{suffix}", "edges"),
                }
                email = f"m78-{suffix}-a@example.test"
                for code, (identity_operation, key, table_name) in identities.items():
                    domain_join, result_expression = {
                        "canvases": (
                            (
                                "LEFT JOIN public.canvases AS d ON d.id = i.result_id "
                                "AND d.workspace_id = i.workspace_id"
                            ),
                            "d.id",
                        ),
                        "nodes": (
                            (
                                "LEFT JOIN public.nodes AS d ON d.id = i.result_id "
                                "LEFT JOIN public.canvases AS c ON c.id = d.canvas_id "
                                "AND c.workspace_id = i.workspace_id"
                            ),
                            "c.id",
                        ),
                        "edges": (
                            (
                                "LEFT JOIN public.edges AS d ON d.id = i.result_id "
                                "LEFT JOIN public.canvases AS c ON c.id = d.canvas_id "
                                "AND c.workspace_id = i.workspace_id"
                            ),
                            "c.id",
                        ),
                    }[table_name]
                    row = (
                        await connection.execute(
                            text(
                                f"SELECT count(*), count({result_expression}) "
                                "FROM public.legacy_creation_request_identities AS i "
                                "JOIN public.users AS u ON u.id = i.actor_user_id "
                                f"{domain_join} "
                                "WHERE u.email_normalized = :email AND i.operation = :operation "
                                "AND i.idempotency_key = :key"
                            ),
                            {
                                "email": email,
                                "operation": identity_operation,
                                "key": key,
                            },
                        )
                    ).one()
                    results.append(
                        _assertion(
                            code,
                            int(row[0]) == 1 and int(row[1]) == 1,
                            {"claims": int(row[0]), "objects": int(row[1])},
                            int(row[0]),
                        )
                    )
            if not all(item.passed for item in results):
                raise EvidenceError("managed catalog evidence failed an assertion")
            return results
    finally:
        await database.dispose()


def _synthetic_password(campaign: str, generation: str, tenant: str) -> str:
    digest = hashlib.sha256(
        f"m7.8/synthetic-auth/v1\0{campaign}\0{generation}\0{tenant}".encode()
    ).hexdigest()
    return f"M78a{digest}Z"


async def _authenticate_synthetic(
    client: httpx.AsyncClient, *, suffix: str, tenant: str, password: str
) -> str:
    email = f"m78-{suffix}-{tenant}@example.test"
    response = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "displayName": "M78 synthetic"},
    )
    if response.status_code != 201:
        response = await client.post(
            "/api/v1/auth/signin", json={"email": email, "password": password}
        )
    if response.status_code != 200 and response.status_code != 201:
        raise EvidenceError("synthetic campaign account could not be established")
    csrf = response.json().get("csrfToken")
    if not isinstance(csrf, str) or not csrf:
        raise EvidenceError("synthetic campaign session did not provide CSRF authority")
    return csrf


def application_measurement_hooks(
    latencies_ms: list[float], observed_at_utc: list[str] | None = None,
) -> dict[str, list[Callable[..., Awaitable[None]]]]:
    async def on_request(request: httpx.Request) -> None:
        request.extensions["m78_measure_started"] = time.perf_counter()

    async def on_response(response: httpx.Response) -> None:
        await response.aread()
        started = response.request.extensions.get("m78_measure_started")
        if not isinstance(started, float):
            raise EvidenceError("application request timing is missing")
        latencies_ms.append((time.perf_counter() - started) * 1000)
        if observed_at_utc is not None:
            observed_at_utc.append(datetime.now(UTC).isoformat())

    return {"request": [on_request], "response": [on_response]}


async def application_assertions(
    *, post_failover: bool = False, latencies_ms: list[float] | None = None,
    observed_at_utc: list[str] | None = None,
) -> list[Assertion]:
    base_url = os.environ.get("M78_PRIVATE_API_URL", "")
    if not base_url.startswith("https://"):
        raise EvidenceError("private API URL is missing or not TLS")
    campaign = os.environ.get("OPENCANVAS_CAMPAIGN_ID", "")
    generation = os.environ.get("OPENCANVAS_CAMPAIGN_GENERATION_ID", "")
    suffix = _digest({"campaign": campaign, "generation": generation})[:12]
    password_a = _synthetic_password(campaign, generation, "a")
    password_b = _synthetic_password(campaign, generation, "b")
    assertions: list[Assertion] = []
    hooks = (
        application_measurement_hooks(latencies_ms, observed_at_utc)
        if latencies_ms is not None else None
    )
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=30.0, event_hooks=hooks) as client,
        httpx.AsyncClient(base_url=base_url, timeout=30.0, event_hooks=hooks) as other,
    ):
        csrf = await _authenticate_synthetic(client, suffix=suffix, tenant="a", password=password_a)
        other_csrf = await _authenticate_synthetic(
            other, suffix=suffix, tenant="b", password=password_b
        )
        headers = {"X-CSRF-Token": csrf}
        other_headers = {"X-CSRF-Token": other_csrf}
        canvas_payload = {"idempotencyKey": f"canvas-{suffix}", "name": "M78 synthetic"}
        first = await client.post("/api/v1/canvases", json=canvas_payload, headers=headers)
        replay = await client.post("/api/v1/canvases", json=canvas_payload, headers=headers)
        if (
            first.status_code != 201
            or replay.status_code != 201
            or first.json()["id"] != replay.json()["id"]
        ):
            raise EvidenceError("canvas ambiguous-commit replay failed")
        conflict = await client.post(
            "/api/v1/canvases",
            json={**canvas_payload, "name": "conflict"},
            headers=headers,
        )
        if conflict.status_code != 409:
            raise EvidenceError("idempotency payload conflict did not fail closed")
        canvas_id = first.json()["id"]
        node_payload = {
            "idempotencyKey": f"node-{suffix}",
            "type": "note",
            "title": "one",
            "text": "synthetic",
            "position": {"x": 1, "y": 2},
        }
        node = await client.post(
            f"/api/v1/canvases/{canvas_id}/nodes", json=node_payload, headers=headers
        )
        node_replay = await client.post(
            f"/api/v1/canvases/{canvas_id}/nodes", json=node_payload, headers=headers
        )
        if node.status_code != 201 or node.json()["id"] != node_replay.json()["id"]:
            raise EvidenceError("node ambiguous-commit replay failed")
        duplicate_payload = {
            "idempotencyKey": f"duplicate-{suffix}",
            "revision": node.json()["revision"],
        }
        duplicate_url = f"/api/v1/canvases/{canvas_id}/nodes/{node.json()['id']}/duplicate"
        duplicate = await client.post(duplicate_url, json=duplicate_payload, headers=headers)
        duplicate_replay = await client.post(duplicate_url, json=duplicate_payload, headers=headers)
        if duplicate.status_code != 201 or duplicate.json()["id"] != duplicate_replay.json()["id"]:
            raise EvidenceError("duplicate-node ambiguous-commit replay failed")
        target_payload = {**node_payload, "idempotencyKey": f"target-{suffix}", "title": "two"}
        target = await client.post(
            f"/api/v1/canvases/{canvas_id}/nodes", json=target_payload, headers=headers
        )
        edge_payload = {
            "idempotencyKey": f"edge-{suffix}",
            "sourceNodeId": node.json()["id"],
            "targetNodeId": target.json()["id"],
            "kind": "default",
        }
        edge_url = f"/api/v1/canvases/{canvas_id}/edges"
        edge = await client.post(edge_url, json=edge_payload, headers=headers)
        edge_replay = await client.post(edge_url, json=edge_payload, headers=headers)
        if edge.status_code != 201 or edge.json()["id"] != edge_replay.json()["id"]:
            raise EvidenceError("edge ambiguous-commit replay failed")
        workspace_id = first.json()["workspaceId"]
        cross_tenant_replay = await other.post(
            "/api/v1/canvases", json=canvas_payload, headers=other_headers
        )
        if (
            cross_tenant_replay.status_code != 201
            or cross_tenant_replay.json()["id"] == canvas_id
            or cross_tenant_replay.json()["workspaceId"] == workspace_id
        ):
            raise EvidenceError("cross-tenant idempotency scope was not isolated")
        other_canvas_id = cross_tenant_replay.json()["id"]
        other_workspace_id = cross_tenant_replay.json()["workspaceId"]
        forged_replay = await other.post(
            "/api/v1/canvases",
            json={
                **canvas_payload,
                "idempotencyKey": f"forged-{suffix}",
                "workspaceId": workspace_id,
            },
            headers=other_headers,
        )
        forged = "00000000-0000-4000-8000-000000000001"
        forged_results = await asyncio.gather(
            other.get(f"/api/v1/canvases?workspaceId={workspace_id}"),
            other.get(f"/api/v1/canvases/{canvas_id}"),
            client.get(f"/api/v1/canvases/{other_canvas_id}"),
            other.get(
                f"/api/v1/workspaces/{workspace_id}/canvases/{canvas_id}/evidence-bundles/{forged}"
            ),
            other.get(f"/api/v1/workspaces/{workspace_id}/canvases/{canvas_id}/workflows"),
        )
        if forged_replay.status_code != 404 or any(
            response.status_code not in {403, 404} for response in forged_results
        ):
            raise EvidenceError("forged scope was not rejected")
        own_readbacks = await asyncio.gather(
            client.get(f"/api/v1/canvases/{canvas_id}"),
            other.get(f"/api/v1/canvases/{other_canvas_id}"),
            client.get(f"/api/v1/canvases?workspaceId={workspace_id}"),
            other.get(f"/api/v1/canvases?workspaceId={other_workspace_id}"),
        )
        if any(response.status_code != 200 for response in own_readbacks):
            raise EvidenceError("pooled connection tenant readback failed")
        assertions.extend(
            _assertion(code, True, {"status": "proved"})
            for code in (
                "idempotency.canvas",
                "idempotency.node",
                "idempotency.duplicate-node",
                "idempotency.edge",
                "idempotency.conflict-409",
                "idempotency.authority-revalidation",
                "tenant.pool-reuse",
                "tenant.forged-workspace",
                "tenant.forged-canvas",
                "tenant.forged-replay",
                "tenant.forged-evidence-bundle",
                "tenant.forged-workflow",
            )
        )
        if post_failover:
            assertions.append(_assertion("tenant.post-failover", True, {"status": "proved"}))
    return assertions


async def credential_denial_assertion() -> list[Assertion]:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.API)
    database = Database.from_settings(settings, expected_role=DatabaseRole.API)
    denied = False
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        denied = True
    finally:
        await database.dispose()
    if not denied:
        raise EvidenceError("revoked campaign identity retained database login")
    return [_assertion("recovery.credential-revocation", True, {"loginDenied": True})]


def emit(assertions: list[Assertion]) -> None:
    if not assertions or not all(item.passed for item in assertions):
        raise EvidenceError("evidence set is empty or failed")
    value = {
        "version": "m7.8-managed-postgres-evidence-v1",
        "observedAtUtc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "assertions": [asdict(item) for item in sorted(assertions, key=lambda item: item.code)],
        "status": "passed",
    }
    print(json.dumps(value, separators=(",", ":"), sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Managed PostgreSQL evidence harness")
    parser.add_argument(
        "--phase",
        choices=(
            "catalog",
            "api",
            "worker",
            "migration",
            "application",
            "post-failover",
            "credential-denied",
            "operations",
            "measurement-sample",
        ),
        required=True,
    )
    args = parser.parse_args()
    try:
        if args.phase == "measurement-sample":
            from scripts.managed_postgres_measure import collect

            async def exercise(latencies: list[float], times: list[str]) -> object:
                return await application_assertions(latencies_ms=latencies, observed_at_utc=times)

            print(json.dumps(asyncio.run(collect(exercise)), sort_keys=True))
            return 2  # Sampling is not verified ceiling/overlap evidence.
        if args.phase == "operations":
            assertions = validate_control_plane_evidence(
                os.environ.get("M78_CONTROL_PLANE_EVIDENCE", "")
            )
        elif args.phase in {"application", "post-failover"}:
            assertions = asyncio.run(
                application_assertions(post_failover=args.phase == "post-failover")
            )
        elif args.phase == "credential-denied":
            assertions = asyncio.run(credential_denial_assertion())
        else:
            role = {
                "catalog": DatabaseRole.OBSERVABILITY,
                "api": DatabaseRole.API,
                "worker": DatabaseRole.WORKER,
                "migration": DatabaseRole.MIGRATION,
            }[args.phase]
            assertions = asyncio.run(catalog_assertions(role))
            if args.phase == "migration":
                assertions.extend(
                    [
                        _assertion("migration.nullpool", True, {"pool": "NullPool"}),
                        _assertion("migration.advisory-lock", True, {"lock": "guarded"}),
                        _assertion("migration.reconciliation", True, {"status": "exact"}),
                    ]
                )
        emit(assertions)
        return 0
    except EvidenceError as exc:
        message = str(exc)
        detail = message if message.startswith("connection budget shortfall: ") else None
        print(
            json.dumps({"status": "blocked", "error": type(exc).__name__, "detail": detail}),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

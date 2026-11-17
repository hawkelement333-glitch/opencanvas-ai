"""Exact worker queue SELECT fault; migration identity restores captured grants.

This is a proof-job operation, not a deployment tool or an acceptance shortcut.
Native worker denial and post-restoration readiness are independent evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from infra.milestone_7_8.pilot.helper_job_patch import admit_runtime_job
from infra.milestone_7_8.pilot_application_probe import Journal, fixture_from, require
from infra.milestone_7_8.pilot_validation import (
    admit_runtime_bindings,
    authorize,
    digest,
    write_new,
)
from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db.role_privileges import quote_identifier
from opencanvas_api.db.session import Database

TABLE = "public.document_processing_jobs"
OPERATIONS = ("queue-grant-outage", "queue-grant-restore")


def content_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def snapshot(
    connection, *, migration: str, worker: str, workspace: str, include_jobs: bool = True
) -> dict:
    identity = (
        await connection.execute(
            text(
                "SELECT current_user, current_database(), pg_get_userbyid(relowner) AS owner "
                "FROM pg_class WHERE oid=CAST(:table AS regclass)"
            ),
            {"table": TABLE},
        )
    ).one()
    require(
        identity[0] == migration and identity[1] == "opencanvas" and identity[2] == migration,
        "exact migration principal must own the application queue in opencanvas",
    )
    require(
        worker != migration
        and (
            not include_jobs
            or bool(
                await connection.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM public.workspaces WHERE id=:workspace)"),
                    {"workspace": uuid.UUID(workspace)},
                )
            )
        ),
        "exact distinct worker and fixture workspace required",
    )
    acl = [
        dict(row)
        for row in (
            await connection.execute(
                text(
                    "SELECT pg_get_userbyid(a.grantor) AS grantor, "
                    "a.grantee::bigint AS grantee_oid, "
                    "CASE WHEN a.grantee=0 THEN 'PUBLIC' "
                    "ELSE pg_get_userbyid(a.grantee) END AS grantee, "
                    "a.privilege_type AS privilege, a.is_grantable AS grantable "
                    "FROM pg_class c CROSS JOIN LATERAL "
                    "aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) a "
                    "WHERE c.oid=CAST(:table AS regclass) "
                    "ORDER BY grantor,grantee_oid,privilege,grantable"
                ),
                {"table": TABLE},
            )
        ).mappings()
    ]
    effective = bool(
        await connection.scalar(
            text("SELECT has_table_privilege(:worker,:table,'SELECT')"),
            {"worker": worker, "table": TABLE},
        )
    )
    jobs = (
        (
            (
                await connection.execute(
                    text(
                        "SELECT id::text AS id, status, to_jsonb(j) AS body "
                        "FROM public.document_processing_jobs j "
                        "WHERE workspace_id=:workspace ORDER BY id LIMIT 129"
                    ),
                    {"workspace": uuid.UUID(workspace)},
                )
            )
            .mappings()
            .all()
        )
        if include_jobs
        else []
    )
    require(
        not include_jobs or 1 <= len(jobs) <= 128, "one to 128 existing scoped queue rows required"
    )
    return {
        "database": identity[1],
        "migrationPrincipal": migration,
        "workerPrincipal": worker,
        "table": TABLE,
        "workspaceId": workspace,
        "acl": acl,
        "effectiveSelect": effective,
        "jobs": {
            row["id"]: {"status": row["status"], "sha256": content_hash(row["body"])}
            for row in jobs
        },
    }


def selected_grant(before: dict) -> dict:
    grants = [
        row
        for row in before["acl"]
        if row["grantee"] == before["workerPrincipal"] and row["privilege"] == "SELECT"
    ]
    require(
        len(grants) == 1
        and grants[0]["grantor"] == before["migrationPrincipal"]
        and before["effectiveSelect"],
        "one direct owner-issued worker SELECT grant required",
    )
    return grants[0]


async def restore(engine, before: dict, *, deadline: datetime) -> dict:
    selected = selected_grant(before)
    last_error = None
    while datetime.now(UTC) < deadline:
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SET LOCAL lock_timeout='5s'"))
                await connection.execute(text("SET LOCAL statement_timeout='10s'"))
                current = await snapshot(
                    connection,
                    migration=before["migrationPrincipal"],
                    worker=before["workerPrincipal"],
                    workspace=before["workspaceId"],
                    include_jobs=False,
                )
                current_selected = [
                    row
                    for row in current["acl"]
                    if row["grantee"] == before["workerPrincipal"] and row["privilege"] == "SELECT"
                ]
                require(
                    current_selected in ([], [selected]), "captured worker SELECT grant was changed"
                )
                current_other = [row for row in current["acl"] if row not in current_selected]
                if not current_selected:
                    clause = " WITH GRANT OPTION" if selected["grantable"] else ""
                    await connection.execute(
                        text(
                            f"GRANT SELECT ON TABLE {TABLE} TO "
                            f"{quote_identifier(before['workerPrincipal'])}{clause}"
                        )
                    )
                after = await snapshot(
                    connection,
                    migration=before["migrationPrincipal"],
                    worker=before["workerPrincipal"],
                    workspace=before["workspaceId"],
                    include_jobs=False,
                )
                require(
                    selected in after["acl"]
                    and after["effectiveSelect"]
                    and [row for row in after["acl"] if row != selected] == current_other,
                    "exact captured SELECT grant did not restore",
                )
            return {
                "capturedSelectRestored": True,
                "aclRestored": after["acl"] == before["acl"],
                "unrelatedGrantsPreserved": True,
                "beforeAclSha256": content_hash(before["acl"]),
                "afterAclSha256": content_hash(after["acl"]),
                "restoredAt": datetime.now(UTC).isoformat(),
            }
        except (ValueError, AssertionError):
            raise
        except Exception as error:
            last_error = type(error).__name__
            await asyncio.sleep(min(1, max(0, (deadline - datetime.now(UTC)).total_seconds())))
    raise RuntimeError("queue grant restoration deadline reached: " + str(last_error))


async def intervene(
    engine,
    *,
    migration: str,
    worker: str,
    workspace: str,
    hold_seconds: float,
    deadline: datetime,
    capture,
) -> dict:
    require(
        0 < hold_seconds <= 540
        and deadline - datetime.now(UTC) >= timedelta(seconds=hold_seconds + 30),
        "bounded hold and restoration reserve required",
    )
    async with engine.begin() as connection:
        before = await snapshot(connection, migration=migration, worker=worker, workspace=workspace)
    selected_grant(before)
    require(
        all(
            row["status"]
            not in {"claimed", "processing", "extracting", "chunking", "embedding", "indexing"}
            for row in before["jobs"].values()
        ),
        "active worker effects must quiesce before queue fault",
    )
    capture("queue-grant-before", before)
    started = time.monotonic()
    restoration_deadline = min(deadline, datetime.now(UTC) + timedelta(seconds=600))
    outcome = {}
    try:
        # Set the restoration intent before either REVOKE or COMMIT: even an
        # ambiguous commit must read back and reconcile, never assume rollback.
        capture(
            "queue-grant-revoke-intent",
            {
                "table": TABLE,
                "workerPrincipal": worker,
                "beforeAclSha256": content_hash(before["acl"]),
            },
        )
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL lock_timeout='5s'"))
            await connection.execute(text("SET LOCAL statement_timeout='10s'"))
            await connection.execute(
                text(f"REVOKE SELECT ON TABLE {TABLE} FROM {quote_identifier(worker)}")
            )
        async with engine.connect() as connection:
            denied = await snapshot(
                connection, migration=migration, worker=worker, workspace=workspace
            )
        require(not denied["effectiveSelect"], "inherited worker SELECT defeats this exact fault")
        capture(
            "queue-grant-denied",
            {
                "effectiveSelect": False,
                "aclSha256": content_hash(denied["acl"]),
                "at": datetime.now(UTC).isoformat(),
            },
        )
        await asyncio.sleep(hold_seconds)
        async with engine.connect() as connection:
            during = await snapshot(
                connection, migration=migration, worker=worker, workspace=workspace
            )
        unchanged = all(during["jobs"].get(key) == value for key, value in denied["jobs"].items())
        new_pending = all(
            value["status"] == "queued"
            for key, value in during["jobs"].items()
            if key not in denied["jobs"]
        )
        require(
            unchanged and new_pending and not during["effectiveSelect"],
            "queue worker effects changed during access denial",
        )
        outcome = {
            "workerSelectDenied": True,
            "scopedExistingJobsUnchanged": True,
            "newRowsOnlyQueued": True,
            "deniedJobHashes": denied["jobs"],
            "duringJobHashes": during["jobs"],
        }
    finally:
        restoration = await asyncio.shield(restore(engine, before, deadline=restoration_deadline))
        capture("queue-grant-restored", restoration)
    return {
        **outcome,
        **restoration,
        "elapsedSeconds": time.monotonic() - started,
        "managedAcceptance": "unproved-until-native-worker-denial-and-restored-readiness",
        "requiredIndependentEvidence": [
            "actual worker SQLSTATE 42501 in this interval",
            "no processing effect for scoped jobs",
            "fresh actual worker poll/ready after restoration",
        ],
    }


async def run(args) -> dict:
    _, plan, deadline = authorize(args.bundle, args.authorization, args.bindings, args.operation)
    require(
        args.execute and args.execution_id == os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
        "actual authorized managed execution required",
    )
    readbacks = json.loads(args.runtime_readbacks.read_text())
    admit_runtime_bindings(plan, readbacks, plan_sha256=digest(args.bindings))
    admit_runtime_job(
        plan,
        readbacks,
        key="queueGrantJobResourceId",
        role="migration",
        execution=args.execution_id,
    )
    fixture = fixture_from(args.fixture, plan)
    spec = plan["queueGrantProof"]
    require(
        spec["migrationPrincipal"] == "id-m78p-a712b8c940-migration"
        and spec["workerPrincipal"] == "id-m78o-a712b8c940-worker",
        "exact existing campaign principals required",
    )
    settings = Settings()
    settings.require_database_role(DatabaseRole.MIGRATION)
    url = make_url(settings.database_url_value)
    require(
        plan["databaseResourceId"]
        == plan["targetResourceGroupId"]
        + "/providers/Microsoft.DBforPostgreSQL/flexibleServers/pg-m78o-a712b8c940"
        and url.host == "pg-m78o-a712b8c940.postgres.database.azure.com"
        and url.username == spec["migrationPrincipal"]
        and url.database == "opencanvas"
        and settings.database_auth_mode == "entra"
        and settings.database_tls_mode == "verify-full",
        "exact managed source database/identity/TLS required",
    )
    journal = Journal(args.output, args.execution_id, args.operation, plan, deadline)

    def capture_bound(name, detail):
        return journal.step(
            name, {**journal.header, "campaignBindingsSha256": digest(args.bindings), **detail}
        )

    db = Database.from_settings(settings, expected_role=DatabaseRole.MIGRATION)
    try:
        if args.operation == "queue-grant-outage":
            return journal.finish(
                await intervene(
                    db.engine,
                    migration=spec["migrationPrincipal"],
                    worker=spec["workerPrincipal"],
                    workspace=fixture["workspaceId"],
                    hold_seconds=spec["holdSeconds"],
                    deadline=deadline,
                    capture=capture_bound,
                )
            )
        before = json.loads(args.before.read_text())
        require(
            before["migrationPrincipal"] == spec["migrationPrincipal"]
            and before["workerPrincipal"] == spec["workerPrincipal"]
            and before["workspaceId"] == fixture["workspaceId"]
            and before["table"] == TABLE
            and before["database"] == "opencanvas"
            and before["sourceCommit"] == plan["sourceCommit"]
            and before["imageDigest"] == plan["imageDigest"]
            and before["operation"] == "queue-grant-outage"
            and before["campaignBindingsSha256"] == digest(args.bindings)
            and bool(before["executionId"]),
            "captured restore scope differs",
        )
        require(
            digest(args.before) == args.before_sha256
            and spec["restoreFromSameBoundCampaign"] is True
            and selected_grant(before)["grantable"] is False,
            "approved exact restoration receipt required",
        )
        return journal.finish(await restore(db.engine, before, deadline=deadline))
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    for name in ("bundle", "authorization", "bindings", "runtime-readbacks", "fixture", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--before-sha256")
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        if not args.output.exists():
            write_new(
                args.output,
                {
                    "operation": args.operation,
                    "errorClass": type(error).__name__,
                    "managedAcceptance": "unproved",
                    "reconcileBeforeRetry": True,
                    "restoreCapturedGrantBeforeAnyNewProof": True,
                },
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

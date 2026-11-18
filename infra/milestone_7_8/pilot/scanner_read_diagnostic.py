"""Read the two native scanner sources without changing a worker or scan result.

Run in the bound worker container using its existing settings and identity.
The exact upload IDs are private synthetic fixture identities. Output contains
only those IDs, bounded result codes and a native correlation outcome.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

MARKER = "M78-SCANNER-READ:"
SAFE_CODE = re.compile(r"[a-z][a-z0-9-]{0,95}")


async def observe(bridge, version, request, now):
    from opencanvas_api.services.documents.errors import DocumentStorageError
    from opencanvas_api.services.scanner_bridge import (
        ScannerBridgeEvidenceError,
        diagnose_scan_evidence,
    )

    def failure(error):
        # ScannerBridgeEvidenceError uses fixed codes. Never export exception
        # strings from HTTP clients, DB drivers, or token providers.
        code = (
            str(error) if isinstance(error, ScannerBridgeEvidenceError) else error.code
        )
        result = {
            "status": "failed",
            "code": code if SAFE_CODE.fullmatch(code) else "read-error",
        }
        nested = (
            error.__cause__
            if isinstance(error.__cause__, DocumentStorageError)
            else error
        )
        status = getattr(nested, "provider_status_code", None)
        if type(status) is int and 100 <= status <= 599:
            result["httpStatus"] = status
        return result

    blob = logs = None
    try:
        blob = await bridge.blob_reader.read(version, observed_at=now)
        blob_result = {"status": "read", "versionBound": True}
    except (ScannerBridgeEvidenceError, DocumentStorageError) as error:
        blob_result = failure(error)

    # The exact DB row supplies the same URL/ETag even when tags cannot be read.
    uri = bridge.storage.object_url(version.physical_key)
    account = bridge.blob_reader.hostname.split(".", 1)[0]
    try:
        logs = await bridge.log_reader.read(
            account_name=account,
            object_uri=uri,
            etag=version.etag,
            requested_at=request.requested_at,
            observed_at=now,
        )
        log_result = {"status": "read", "rows": len(logs)}
    except (ScannerBridgeEvidenceError, DocumentStorageError) as error:
        log_result = failure(error)
    correlation = {"status": "unproved"}
    if blob is not None and logs is not None:
        result = diagnose_scan_evidence(
            version=version,
            request=request,
            blob=blob,
            logs=logs,
            observed_at=now,
            maximum_age=timedelta(
                seconds=bridge.settings.malware_scan_result_max_age_seconds
            ),
        )
        correlation = (
            {"status": "agreed", "verdict": result.decision.verdict}
            if result.decision
            else {"status": "unproved", "code": result.reason_code}
        )
    return {
        "blob": blob_result,
        "logAnalytics": log_result,
        "correlation": correlation,
        "requestExpired": now >= request.deadline_at,
        "managedAcceptance": "diagnostic only",
    }


async def read_worker(inputs):
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from opencanvas_api.core.config import DatabaseRole, Settings
    from opencanvas_api.db.models import (
        MalwareScanRequest,
        StorageObjectVersion,
        UploadSession,
    )
    from opencanvas_api.db.session import Database
    from opencanvas_api.services.scanner_bridge import (
        build_private_scanner_result_bridge,
    )

    settings = Settings()
    if not (
        settings.database_managed_identity_client_id == inputs["clientId"]
        and settings.azure_managed_identity_client_id == inputs["clientId"]
        and settings.database_auth_mode == "entra"
        and settings.database_tls_mode == "verify-full"
        and make_url(settings.database_url_value).host == inputs["databaseHost"]
        and str(settings.azure_log_analytics_workspace_id) == inputs["workspaceId"]
        and settings.azure_log_analytics_endpoint
        == "https://api.loganalytics.azure.com"
        and str(settings.azure_storage_account_url).rstrip("/") == inputs["storageUrl"]
        and settings.scanner_result_bridge_mode == "private_pull"
        and settings.malware_scan_timeout_seconds == 900
        and settings.scanner_result_bridge_retry_max_seconds == 20
    ):
        return {"status": "configuration-mismatch"}
    db = Database.from_settings(settings, expected_role=DatabaseRole.WORKER)
    try:
        async with db.sessions() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            row = (
                await session.execute(
                    select(StorageObjectVersion, MalwareScanRequest)
                    .join(
                        MalwareScanRequest,
                        MalwareScanRequest.object_version_id
                        == StorageObjectVersion.object_version_id,
                    )
                    .join(
                        UploadSession,
                        UploadSession.object_version_id
                        == StorageObjectVersion.object_version_id,
                    )
                    .where(
                        UploadSession.session_id == uuid.UUID(inputs["sessionId"]),
                        UploadSession.document_id == uuid.UUID(inputs["documentId"]),
                        StorageObjectVersion.object_version_id
                        == uuid.UUID(inputs["objectVersionId"]),
                        StorageObjectVersion.content_sha256 == inputs["contentSha256"],
                        StorageObjectVersion.security_class == "quarantine",
                    )
                )
            ).one_or_none()
            if row is None:
                return {"status": "exact-upload-not-found"}
            # Detach only data needed by the signed image's readers. Release DB
            # resources before either provider request, with no write/row lock.
            version, request = row
            values = SimpleNamespace(
                **{
                    k: getattr(version, k)
                    for k in (
                        "object_version_id",
                        "workspace_id",
                        "provider_name",
                        "security_class",
                        "physical_key",
                        "provider_version_id",
                        "etag",
                        "content_sha256",
                    )
                }
            )
            timing = SimpleNamespace(
                **{
                    k: getattr(request, k)
                    for k in (
                        "scan_request_id",
                        "requested_at",
                        "deadline_at",
                        "policy_version",
                        "object_version_id",
                        "workspace_id",
                    )
                }
            )
            await session.rollback()
    finally:
        await db.dispose()
    bridge = build_private_scanner_result_bridge(settings)
    if bridge is None:
        return {"status": "configuration-mismatch"}
    return {
        "status": "observed",
        **await observe(bridge, values, timing, datetime.now(UTC)),
    }


def main(inputs):
    try:
        result = asyncio.run(asyncio.wait_for(read_worker(inputs), 55))
    except Exception as error:
        # This includes DB/RBAC and transport failures before source attribution.
        result = {"status": "diagnostic-incomplete", "errorClass": type(error).__name__}
    print(
        MARKER
        + json.dumps(
            {
                **result,
                "challenge": inputs["challenge"],
                "objectVersionId": inputs["objectVersionId"],
            },
            separators=(",", ":"),
        ),
        flush=True,
    )

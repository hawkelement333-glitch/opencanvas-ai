"""Read the two native scanner sources without changing a worker or scan result.

Run as a one-shot job with the bound worker's read settings and identity.
The exact upload IDs are private synthetic fixture identities. Output contains
only those IDs, bounded result codes and a native correlation outcome.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

MARKER = "M78-SCANNER-READ:"
SAFE_CODE = re.compile(r"[a-z][a-z0-9-]{0,95}")
SOURCE_TIMEOUT = 45
PROBE_TIMEOUT = 70


async def observe(bridge, version, request, now, *, clock=lambda: datetime.now(UTC)):
    from opencanvas_api.services.documents.errors import DocumentStorageError
    from opencanvas_api.services.scanner_bridge import (
        AzureBlobScanEvidenceClient,
        ScannerBridgeEvidenceError,
        _azure_etags_equal,
        _normalize_azure_etag,
        diagnose_scan_evidence,
        log_analytics_query_sha256,
    )

    def fingerprint(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def timed(start, finish):
        return {
            "startedAt": start.isoformat(),
            "finishedAt": finish.isoformat(),
            "startSecondsAfterRequest": (start - request.requested_at).total_seconds(),
            "finishSecondsBeforeCutoff": (request.deadline_at - finish).total_seconds(),
            "window": "in-window" if finish < request.deadline_at else "post-deadline",
        }

    def failure(error):
        # ScannerBridgeEvidenceError uses fixed codes. Never export exception
        # strings from HTTP clients, DB drivers, or token providers.
        if isinstance(error, TimeoutError):
            code = "read-timeout"
        elif isinstance(error, ScannerBridgeEvidenceError):
            code = str(error)
        elif isinstance(error, DocumentStorageError):
            code = error.code
        else:
            code = "unexpected-read-error"
        result = {
            "status": "failed",
            "versionBound": None,
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

    # The exact DB row supplies the same URL/ETag even when tags cannot be read.
    uri = bridge.storage.object_url(version.physical_key)
    account = bridge.blob_reader.hostname.split(".", 1)[0]
    tag_observations = []
    bridge.blob_reader.observation_sink = tag_observations.append
    properties = {"status": "not-attempted"}
    tags_timing = {}
    if isinstance(bridge.blob_reader, AzureBlobScanEvidenceClient):
        storage = bridge.blob_reader.storage

        async def read_properties(**kwargs):
            started = clock()
            try:
                provider_version, etag = await storage.read_version_properties(**kwargs)
                properties.update(
                    status="read", providerVersionSha256=fingerprint(provider_version),
                    etagSha256=fingerprint(_normalize_azure_etag(etag)),
                    versionBound=provider_version == version.provider_version_id
                    and _azure_etags_equal(etag, version.etag),
                )
                return provider_version, etag
            except Exception as error:
                properties.update(failure(error))
                raise
            finally:
                properties["timing"] = timed(started, clock())

        async def read_tags(**kwargs):
            started = clock()
            try:
                return await storage.read_version_tags_xml(**kwargs)
            finally:
                tags_timing.update(timed(started, clock()))

        bridge.blob_reader.storage = SimpleNamespace(
            read_version_properties=read_properties,
            read_version_tags_xml=read_tags,
            object_url=storage.object_url,
        )

    timings = {}

    async def read_blob():
        started = clock()
        try:
            async with asyncio.timeout(SOURCE_TIMEOUT):
                blob = await bridge.blob_reader.read(version, observed_at=now)
        except Exception as error:
            result = failure(error)
            if tag_observations:
                tag = tag_observations[-1]
                if tag.http_status is not None:
                    result["httpStatus"] = tag.http_status
                    if 200 <= tag.http_status < 300:
                        result.update(status="read", versionBound=not tag.different_blob_version)
            return None, result
        finally:
            timings["blob"] = timed(started, clock())
        exact = (
            blob.provider_version_id == version.provider_version_id
            and _azure_etags_equal(blob.etag, version.etag)
            and blob.account_name == account
            and blob.object_uri == uri
        )
        return blob, {"status": "read", "versionBound": exact}

    async def read_logs():
        started = clock()
        try:
            async with asyncio.timeout(SOURCE_TIMEOUT):
                logs = await bridge.log_reader.read(
                    account_name=account,
                    object_uri=uri,
                    etag=version.etag,
                    requested_at=request.requested_at,
                    observed_at=started,
                )
        except Exception as error:
            return None, failure(error)
        finally:
            timings["logAnalytics"] = timed(started, clock())
        exact = [
            row for row in logs
            if row.account_name == account and row.object_uri == uri
            and _azure_etags_equal(row.etag, version.etag)
        ]
        return logs, {
            "status": "read", "rows": len(logs), "exactRows": len(exact),
            "versionBound": bool(exact),
        }

    (blob, blob_result), (logs, log_result) = await asyncio.gather(read_blob(), read_logs())
    finished = clock()
    expired = finished >= request.deadline_at
    correlation = {"status": "unproved", "code": "scanner-source-evidence-unavailable"}
    if blob is not None and logs is not None:
        result = diagnose_scan_evidence(
            version=version,
            request=request,
            blob=blob,
            logs=logs,
            observed_at=finished,
            maximum_age=timedelta(
                seconds=bridge.settings.malware_scan_result_max_age_seconds
            ),
        )
        correlation = (
            {
                "status": "late-agreement" if expired else "agreed",
                "verdict": result.decision.verdict,
            }
            if result.decision
            else {"status": "unproved", "code": result.failure_code}
        )
    tags = {"timing": tags_timing} if tags_timing else {}
    if tag_observations:
        tag = tag_observations[-1]
        tags.update({
            "httpStatus": tag.http_status,
            "identitySource": tag.version_identity_path,
            "decision": tag.exact_comparison_decision,
            "requiredKeysFound": tag.required_keys_found,
            "requiredKeysMissing": tag.required_keys_missing,
            "responseVersionSha256": tag.response_version_id_sha256,
            "responseEtagSha256": tag.response_etag_sha256,
        })
    if blob is not None:
        tags.update(scanResult=blob.scan_result, scanFinishedAt=blob.scan_finished_at.isoformat())
    max_rows = getattr(bridge.log_reader, "max_rows", None)
    return {
        "blob": blob_result,
        "logAnalytics": log_result,
        "correlation": correlation,
        "observedAt": now.isoformat(),
        "finishedAt": finished.isoformat(),
        "requestExpired": expired,
        "timing": timings,
        "requestedAt": request.requested_at.isoformat(),
        "scanDeadlineAt": request.deadline_at.isoformat(),
        "expectedProviderVersionSha256": fingerprint(version.provider_version_id),
        "blobProperties": properties,
        "blobTags": tags,
        "logQuerySha256": log_analytics_query_sha256(
            account_name=account, object_uri=uri, etag=version.etag, max_rows=max_rows
        ) if max_rows is not None else None,
        "logRows": [
            {
                "scanResult": row.scan_result,
                "scanFinishedAt": row.scan_finished_at.isoformat(),
                "timeGenerated": row.time_generated.isoformat(),
                "etagSha256": fingerprint(_normalize_azure_etag(row.etag)),
                "sameUri": row.object_uri == uri and row.account_name == account,
                "evidenceSha256": row.evidence_sha256,
            }
            for row in logs or ()
        ],
        "managedAcceptance": "diagnostic only",
    }


async def read_worker(inputs):
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url

    from opencanvas_api.core.config import DatabaseRole, Settings
    from opencanvas_api.db.models import (
        MalwareScanRequest,
        StorageObjectLifecycleTransition,
        StorageObjectVersion,
        UploadSession,
    )
    from opencanvas_api.db.session import Database
    from opencanvas_api.services.scanner_bridge import (
        build_private_scanner_result_bridge,
    )

    settings = Settings(_env_file=None)
    if not (
        settings.database_managed_identity_client_id == inputs["clientId"]
        and settings.azure_managed_identity_client_id == inputs["clientId"]
        and settings.database_auth_mode == "entra"
        and settings.database_tls_mode == "verify-full"
        and make_url(settings.database_url_value) == make_url(inputs["databaseUrl"])
        and str(settings.azure_log_analytics_workspace_id) == inputs["workspaceId"]
        and settings.azure_log_analytics_endpoint
        == "https://api.loganalytics.azure.com"
        and str(settings.azure_storage_account_url).rstrip("/") == inputs["storageUrl"].rstrip("/")
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
            if (
                request.timeout_seconds != 900
                or request.deadline_at - request.requested_at != timedelta(seconds=900)
            ):
                return {"status": "scan-window-mismatch"}
            incoming = inputs.get("serverScanDeadlineAt")
            if incoming is not None:
                if datetime.fromisoformat(incoming.replace("Z", "+00:00")) != request.deadline_at:
                    return {"status": "scan-window-mismatch"}
                current = await session.scalar(
                    select(StorageObjectLifecycleTransition.current_state)
                    .where(
                        StorageObjectLifecycleTransition.object_version_id
                        == version.object_version_id
                    )
                    .order_by(StorageObjectLifecycleTransition.sequence.desc())
                    .limit(1)
                )
                if current != "scan_pending":
                    return {"status": "primary-no-longer-pending"}
                if datetime.now(UTC) >= request.deadline_at:
                    return {"status": "probe-started-after-deadline", "requestExpired": True}
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
        result = asyncio.run(asyncio.wait_for(read_worker(inputs), PROBE_TIMEOUT))
    except Exception as error:
        # This includes DB/RBAC and transport failures before source attribution.
        result = {"status": "diagnostic-incomplete", "errorClass": type(error).__name__}
    if result["status"] != "observed":
        status = "unproved" if result["status"] == "diagnostic-incomplete" else "not-attempted"
        for key in ("blob", "logAnalytics"):
            result[key] = {"status": status, "versionBound": None}
        result["correlation"] = {"status": "unproved", "code": result["status"]}
    print(
        MARKER
        + json.dumps(
            {
                **result,
                "executionId": os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
                "challenge": inputs["challenge"],
                "objectVersionId": inputs["objectVersionId"],
            },
            separators=(",", ":"),
        ),
        flush=True,
    )

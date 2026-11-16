"""M78-D-001 only: external, hash-bound probe for the retained API image.

Run existing migrations in the disposable campaign DB first, then ``setup``.
Select one phase explicitly; accepted receipts are immutable and skipped on resume.
Raw provider identifiers remain in the private PostgreSQL journal. Stdout contains
only assertion names, hashes, campaign/execution IDs, and safe failure codes.
This file is deliberately outside every retained-image Docker input.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db import models as m
from opencanvas_api.db.session import Database
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.documents.errors import DocumentStorageError
from opencanvas_api.services.documents.storage import (
    AzureBlobVersionedObjectStorage,
    ProviderObjectVersion,
    build_versioned_object_storage,
)
from opencanvas_api.services.object_ingestion import (
    ObjectIngestionError,
    ObjectIngestionNotFoundError,
    ObjectReconciler,
    UploadLifecycleService,
)
from opencanvas_api.services.scanner_bridge import (
    ScannerBridgeEvidenceError,
    _aware_utc,
    _normalize_azure_etag,
    build_private_scanner_result_bridge,
    correlate_scan_evidence,
)

CLEAN = b"M78-D-001 managed immutable object acceptance. Exact retained bytes.\n"
# Standard non-executable antivirus test fixture; never promoted or downloaded.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
PHASES = ("upload", "scan", "delete", "recovery")
PRESERVED_UPLOAD_EXPORT_SHA256 = "47dd87d4f289fa39ab24149703faa8b26a817199dc5d1900c7973a93a767228c"
JOURNAL_DDL = """CREATE TABLE IF NOT EXISTS m78_object_probe.receipts (
campaign uuid NOT NULL, phase text NOT NULL, attempt uuid NOT NULL,
status text NOT NULL, source_sha256 text NOT NULL, result jsonb NOT NULL,
recorded_at timestamptz NOT NULL DEFAULT now(),
PRIMARY KEY(campaign, phase, attempt))"""


def digest(value: bytes | str | dict[str, Any]) -> str:
    if isinstance(value, dict):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def check(condition: bool, code: str) -> None:
    if not condition:
        raise ProbeFailure(code)


class ProbeFailure(RuntimeError):
    pass


def continuation_authority(
    environment: Any, campaign: uuid.UUID, settings: Settings
) -> dict[str, Any] | None:
    """Bind preserved evidence separately; never import its deleted fixtures."""
    encoded = environment.get("OPENCANVAS_OBJECT_PROBE_CONTINUATION_JSON")
    if encoded is None:
        return None
    manifest = json.loads(encoded)
    check(
        digest(manifest) == environment["OPENCANVAS_OBJECT_PROBE_CONTINUATION_SHA256"],
        "continuation-manifest-hash-differs",
    )
    prior = manifest["prior_upload_export"]
    check(
        manifest["schema_version"] == "m78-object-new-request-continuation-v1"
        and manifest["campaign"] == str(campaign)
        and prior["campaign"] != str(campaign)
        and digest(prior) == PRESERVED_UPLOAD_EXPORT_SHA256
        and manifest["prior_journal_sha256"]
        == "2494048a0c735a47e03b56fd01d1d6e65000a9fec24004e29a6b899bfcc8fffe"
        and manifest["prior_terminal_receipt_sha256"]
        == "674ea9a33476c4a59b80de35d8055da3709ef2c852654187e06cdc5ad3d87109",
        "continuation-prior-evidence-binding-differs",
    )
    check(
        manifest["decision_timeout_seconds"] == settings.malware_scan_timeout_seconds == 900
        and manifest["retry_max_seconds"] == settings.scanner_result_bridge_retry_max_seconds == 20
        and settings.scanner_result_bridge_retry_base_seconds == 5
        and manifest["probe_window_seconds"]
        == int(environment.get("OPENCANVAS_OBJECT_PROBE_SCAN_SECONDS", "1800"))
        == 1000
        and environment["OPENCANVAS_OBJECT_PROBE_IMAGE_DIGEST"]
        == prior["receipts"][0]["image_digest"],
        "continuation-approved-configuration-differs",
    )
    check(
        not any(
            environment.get(key)
            for key in (
                "OPENCANVAS_OBJECT_PROBE_CLEAN_REPLACEMENT_TOKEN",
                "OPENCANVAS_OBJECT_PROBE_MANAGED_RESUME_JSON",
                "OPENCANVAS_OBJECT_PROBE_WARM_SCAN_RESUME_JSON",
            )
        ),
        "continuation-old-campaign-resume-not-permitted",
    )
    return manifest


def clean_replacement_authority(environment: Any, campaign: uuid.UUID) -> dict[str, Any] | None:
    """One explicitly selected replacement for the observed expired clean fixture."""
    token = environment.get("OPENCANVAS_OBJECT_PROBE_CLEAN_REPLACEMENT_TOKEN")
    if token is None:
        return None
    check(bool(re.fullmatch(r"[a-z][a-z0-9-]{0,31}", token)), "clean-replacement-token-invalid")
    snapshot = json.loads(environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_JSON"])
    binding = environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_SHA256"]
    check(digest(snapshot) == binding, "clean-replacement-inspection-hash-differs")
    check(
        snapshot["campaign"] == str(campaign)
        and snapshot["read_only"] is True
        and snapshot["classification"] == "read-only-upload-resume-inspection"
        and snapshot["inspector_sha256"]
        == "058225ff961261e862e948f1cffec9089043017dd3f39ce37ddcfcc808f7ab49"
        and snapshot["execution_id"]
        == environment["OPENCANVAS_OBJECT_PROBE_RESUME_INSPECTION_EXECUTION"],
        "clean-replacement-inspection-binding-differs",
    )
    matches = [
        row
        for row in snapshot["sessions"]
        if row["idempotency_key_sha256"] == digest(f"{campaign}:clean")
    ]
    check(len(matches) == 1, "clean-replacement-original-session-ambiguous")
    old = matches[0]
    check(
        old["state"] == "requested"
        and old["expired"] is True
        and old["database_version_present"] is False
        and old["scan_request_count"] == old["scan_result_count"] == old["promotion_count"] == 0
        and old["provider_head_status"] == 404
        and old["provider_exact_version_count"] == 0
        and old["provider_versions"] == []
        and old["expected_sha256"] == digest(CLEAN)
        and old["expected_size_bytes"] == len(CLEAN),
        "clean-replacement-inspection-not-empty-expired",
    )
    check(
        not any(
            row["status"] == "accepted"
            and row["phase"] in {"upload-clean", "upload", "scan", "delete", "recovery"}
            for row in snapshot["journal"]
        ),
        "clean-replacement-accepted-work-present",
    )
    return {"token": token, "snapshot": snapshot, "inspection_sha256": binding, "old": old}


def require_empty_version_inventory(content: bytes, physical_key: str) -> None:
    check(len(content) <= 131072, "clean-replacement-version-inventory-too-large")
    root = ET.fromstring(content)
    check(
        root.tag.rsplit("}", 1)[-1] == "EnumerationResults",
        "clean-replacement-version-inventory-invalid",
    )
    check(
        not any(node.text for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "NextMarker"),
        "clean-replacement-version-inventory-incomplete",
    )
    expected_name = physical_key.split("/", 1)[1]
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "Blob":
            values = {child.tag.rsplit("}", 1)[-1]: child.text for child in node}
            check(values.get("Name") != expected_name, "clean-replacement-provider-residue-present")


def managed_resume_authority(environment: Any, campaign: uuid.UUID) -> dict[str, Any] | None:
    encoded = environment.get("OPENCANVAS_OBJECT_PROBE_MANAGED_RESUME_JSON")
    if encoded is None:
        return None
    manifest = json.loads(encoded)
    check(
        digest(manifest) == environment["OPENCANVAS_OBJECT_PROBE_MANAGED_RESUME_SHA256"],
        "managed-resume-manifest-hash-differs",
    )
    check(
        manifest["schema_version"] == "m78-object-managed-resume-v1"
        and manifest["campaign"] == str(campaign)
        and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", manifest["token"])
        and manifest["scanner_admission_state"] == "Succeeded"
        and manifest["event_grid_registration_state"] == "Registered",
        "managed-resume-admission-binding-invalid",
    )
    for field in ("failed_scanner_operation_receipt_sha256", "scanner_admission_receipt_sha256"):
        check(
            bool(re.fullmatch(r"[0-9a-f]{64}", manifest[field])),
            "managed-resume-receipt-hash-invalid",
        )
    for field, expected_source, classification, source_field in (
        (
            "upload_inspection",
            "058225ff961261e862e948f1cffec9089043017dd3f39ce37ddcfcc808f7ab49",
            "read-only-upload-resume-inspection",
            "inspector_sha256",
        ),
        (
            "scanner_diagnostic",
            "23cb70cee664bfa7f6f71561ee1c5afb9b109a5ecc34babbf5d1613c5a078748",
            "read-only-scanner-evidence-diagnostic",
            "diagnostic_sha256",
        ),
    ):
        evidence = manifest[field]
        check(
            digest(evidence) == manifest[f"{field}_sha256"]
            and evidence["campaign"] == str(campaign)
            and evidence["classification"] == classification
            and evidence[source_field] == expected_source
            and bool(evidence["execution_id"]),
            "managed-resume-inspection-binding-invalid",
        )
    check(
        manifest["upload_inspection"]["read_only"] is True
        and manifest["scanner_diagnostic"]["accepted"] is False
        and manifest["scanner_diagnostic"]["consumer_deadline_open"] is False
        and manifest["scanner_diagnostic"]["scan_result_count"] == 0,
        "managed-resume-original-scanner-not-unaccepted-expired",
    )
    return manifest


def warm_scan_authority(environment: Any, campaign: uuid.UUID) -> dict[str, Any] | None:
    encoded = environment.get("OPENCANVAS_OBJECT_PROBE_WARM_SCAN_RESUME_JSON")
    if encoded is None:
        return None
    manifest = json.loads(encoded)
    check(
        digest(manifest) == environment["OPENCANVAS_OBJECT_PROBE_WARM_SCAN_RESUME_SHA256"],
        "warm-scan-manifest-hash-differs",
    )
    check(
        manifest["schema_version"] == "m78-object-warm-scan-resume-v1"
        and manifest["campaign"] == str(campaign)
        and re.fullmatch(r"[a-z][a-z0-9-]{0,31}", manifest["token"])
        and manifest["scanner_admission_state"] == "Succeeded"
        and manifest["event_grid_registration_state"] == "Registered",
        "warm-scan-admission-binding-invalid",
    )
    for field in ("scanner_admission_receipt_sha256", "accepted_upload_receipt_sha256"):
        check(
            bool(re.fullmatch(r"[0-9a-f]{64}", manifest[field])), "warm-scan-receipt-hash-invalid"
        )
    logs = manifest["delayed_log_diagnostic"]
    check(
        digest(logs) == manifest["delayed_log_diagnostic_sha256"]
        and logs["campaign"] == str(campaign)
        and logs["accepted"] is False
        and logs["diagnostic_sha256"]
        == "dd28b251872406f8d36082e2e6001fcfbbd58cebc63025ba1fdcacc3367648e9"
        and logs["classification"] == "read-only-scanner-account-row-diagnostic"
        and logs["http_status"] == 200
        and logs["consumer_deadline_open"] is False
        and logs["scan_result_count"] == 0
        and 1 <= logs["row_count"] <= 20
        and len(logs["rows"]) == logs["row_count"]
        and bool(logs["execution_id"]),
        "warm-scan-delayed-evidence-binding-invalid",
    )
    return manifest


def require_possible_scan_progress(
    expected: set[uuid.UUID],
    accepted: set[uuid.UUID],
    deadlines: dict[uuid.UUID, datetime],
    now: datetime,
) -> None:
    missing = expected - accepted
    if not missing:
        return
    check(missing <= deadlines.keys(), "managed-scan-required-request-missing")
    check(
        any(deadlines[version] > now for version in missing),
        "managed-scan-windows-closed-without-results",
    )


def safe_failure(error: Exception) -> dict[str, str]:
    """Return SQLSTATE/allowlisted identifiers; never return error text or SQL."""
    diagnostic = {"code": type(error).__name__}
    if isinstance(error, ProbeFailure):
        reason = str(error)
        if re.fullmatch(r"[a-z][a-z0-9-]{0,95}", reason):
            diagnostic["code"] = reason
    tables = set(m.Base.metadata.tables)
    columns = {column.name for table in m.Base.metadata.tables.values() for column in table.columns}
    constraints = {
        str(constraint.name)
        for table in m.Base.metadata.tables.values()
        for constraint in table.constraints
        if constraint.name
    }
    # PostgreSQL names unnamed simple constraints deterministically. Only generate
    # names from shipped schema metadata, not arbitrary strings from an exception.
    for table in m.Base.metadata.tables.values():
        constraints.add(f"{table.name}_pkey")
        for column in table.columns:
            constraints.add(f"{table.name}_{column.name}_fkey")
            constraints.add(f"{table.name}_{column.name}_key")
    allowed = {"table_name": tables, "column_name": columns, "constraint_name": constraints}
    permission_objects = {
        "table": tables | {"receipts", "alembic_version"},
        "schema": {"public", "m78_object_probe"},
        "sequence": {
            f"{table.name}_{column.name}_seq"
            for table in m.Base.metadata.tables.values()
            for column in table.columns
        },
    }
    pending: list[Any] = [error]
    seen: set[int] = set()
    while pending and len(seen) < 12:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        state = getattr(current, "sqlstate", None)
        if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state):
            diagnostic["sqlstate"] = state
        if state == "42501":
            # PostgreSQL permission errors often omit structured table_name.
            # Match only its narrow English identifier clause and then require
            # shipped schema membership. Never stringify driver/SQLAlchemy errors.
            messages = [getattr(current, "message", None)]
            arguments = getattr(current, "args", ())
            if isinstance(arguments, tuple) and arguments:
                messages.append(arguments[0])
            for message in messages:
                if not isinstance(message, str) or len(message) > 8192:
                    continue
                match = re.search(
                    r"(?:^|\n|: )permission denied for (table|schema|sequence) "
                    r'"?([a-z_][a-z0-9_]{0,62})"?(?=$|\n)',
                    message,
                )
                if match and match[2] in permission_objects[match[1]]:
                    diagnostic[f"{match[1]}_name"] = match[2]
        for field, values in allowed.items():
            value = getattr(current, field, None)
            if isinstance(value, str) and value in values:
                diagnostic[field] = value
        pending.extend(
            child
            for name in ("orig", "__cause__", "__context__")
            if (child := getattr(current, name, None)) is not None
        )
    return diagnostic


def public_receipt(phase: str, result: dict[str, Any]) -> dict[str, Any]:
    """Explicit allowlist: never recursively expose private journal values."""
    return {
        "phase": phase,
        "assertions": result.get("assertions", []),
        "receipt_sha256": digest(result),
        "observations": result.get("observations", {}),
        "source_sha256": result.get("source_sha256"),
        "image_digest": result.get("image_digest"),
        "source_commit": result.get("source_commit"),
        "execution_id": result.get("execution_id"),
    }


def version_observation(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "object_version_id": version["object_version_id"],
        "provider_version_sha256": digest(version["provider_version_id"]),
        "etag_sha256": digest(version["etag"]),
        "content_sha256": version["content_sha256"],
    }


class AmbiguousDelete:
    """Inject lost response only after a real exact provider delete succeeds."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.deleted = False

    async def delete_version(self, **kwargs: Any) -> None:
        await self.storage.delete_version(**kwargs)
        self.deleted = True
        raise DocumentStorageError("Injected lost exact-delete response.")


class ReconciledUpload:
    """Return an observed immutable version after an interrupted DB transaction."""

    def __init__(self, storage: Any, observed: ProviderObjectVersion) -> None:
        self.storage, self.observed = storage, observed

    def __getattr__(self, name: str) -> Any:
        return getattr(self.storage, name)

    async def put_immutable(self, **kwargs: Any) -> ProviderObjectVersion:
        check(
            kwargs["expected_sha256"] == self.observed.content_sha256
            and digest(kwargs["content"]) == self.observed.content_sha256,
            "reconciled-upload-contract-differed",
        )
        return self.observed


class Probe:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.db = database
        self.campaign = uuid.UUID(os.environ["OPENCANVAS_OBJECT_PROBE_CAMPAIGN"])
        self.source = os.environ["OPENCANVAS_OBJECT_PROBE_SHA256"]
        check(bool(re.fullmatch(r"[0-9a-f]{64}", self.source)), "source-hash-invalid")
        self.execution = os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME", "")
        check(bool(self.execution), "execution-id-missing")
        self.image = os.environ["OPENCANVAS_OBJECT_PROBE_IMAGE_DIGEST"]
        self.source_commit = os.environ["OPENCANVAS_OBJECT_PROBE_SOURCE_COMMIT"]
        self.continuation = continuation_authority(os.environ, self.campaign, settings)
        check(
            bool(re.fullmatch(r"sha256:[0-9a-f]{64}", self.image)),
            "image-digest-invalid",
        )
        check(
            bool(re.fullmatch(r"[0-9a-f]{40}", self.source_commit)),
            "source-commit-invalid",
        )
        self.workspace = uuid.uuid5(self.campaign, "workspace")
        self.canvas = uuid.uuid5(self.campaign, "canvas")
        self.user = uuid.uuid5(self.campaign, "owner")
        self.principal = Principal(
            user_id=self.user,
            email="object-proof@mobius.invalid",
            display_name="Object proof",
            session_id=None,
            csrf_token_hash=None,
            synthetic=False,
        )
        api_id = os.environ["OPENCANVAS_OBJECT_PROBE_API_CLIENT_ID"]
        worker_id = os.environ["OPENCANVAS_OBJECT_PROBE_WORKER_CLIENT_ID"]
        check(api_id != worker_id, "storage-identities-not-distinct")
        self.api_settings = settings.model_copy(update={"azure_managed_identity_client_id": api_id})
        self.worker_settings = settings.model_copy(
            update={"azure_managed_identity_client_id": worker_id}
        )
        self.api = build_versioned_object_storage(self.api_settings)
        self.worker = build_versioned_object_storage(self.worker_settings)
        recovery_id = os.environ["OPENCANVAS_OBJECT_PROBE_RECOVERY_CLIENT_ID"]
        check(recovery_id not in {api_id, worker_id}, "recovery-identity-not-distinct")
        self.recovery_storage = build_versioned_object_storage(
            settings.model_copy(update={"azure_managed_identity_client_id": recovery_id})
        )
        check(
            isinstance(self.api, AzureBlobVersionedObjectStorage)
            and isinstance(self.worker, AzureBlobVersionedObjectStorage),
            "azure-storage-required",
        )

    def service(self, session: Any, *, worker: bool = False) -> UploadLifecycleService:
        return UploadLifecycleService(
            session, settings=self.settings, storage=self.worker if worker else self.api
        )

    def scope(self, session_id: uuid.UUID) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "workspace_id": self.workspace,
            "canvas_id": self.canvas,
            "session_id": session_id,
        }

    async def read_receipt(self, phase: str) -> dict[str, Any] | None:
        async with self.db.sessions() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT source_sha256,result FROM m78_object_probe.receipts "
                        "WHERE campaign=:campaign AND phase=:phase AND status='accepted' "
                        "ORDER BY recorded_at LIMIT 1"
                    ),
                    {"campaign": self.campaign, "phase": phase},
                )
            ).first()
            if row:
                allowed = {
                    self.source,
                    *os.environ.get("OPENCANVAS_OBJECT_PROBE_PRIOR_SHA256", "").split(","),
                }
                check(row.source_sha256 in allowed, "accepted-source-binding-changed")
                return row.result
        return None

    async def record(self, phase: str, status: str, result: dict[str, Any]) -> None:
        result = {
            **result,
            "execution_id": self.execution,
            "source_sha256": self.source,
            "image_digest": self.image,
            "source_commit": self.source_commit,
        }
        async with self.db.sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO m78_object_probe.receipts "
                    "(campaign,phase,attempt,status,source_sha256,result) "
                    "VALUES(:campaign,:phase,:attempt,:status,:source,CAST(:result AS jsonb))"
                ),
                {
                    "campaign": self.campaign,
                    "phase": phase,
                    "attempt": uuid.uuid4(),
                    "status": status,
                    "source": self.source,
                    "result": json.dumps(result, sort_keys=True),
                },
            )
            await session.commit()

    async def setup(self) -> dict[str, Any]:
        """Fixture only, after existing migrations. No PostgreSQL acceptance work."""
        async with self.db.sessions() as session:
            # Privileged external bootstrap owns DDL; runtime gets SELECT/INSERT.
            await session.execute(text("SELECT 1 FROM m78_object_probe.receipts LIMIT 1"))
        return await self.seed_fixture()

    async def seed_fixture(self) -> dict[str, Any]:
        async with self.db.sessions() as session:
            if await session.get(m.Workspace, self.workspace):
                return {"assertions": ["isolated-fixture-present"]}
            now = datetime.now(UTC)
            membership = uuid.uuid5(self.campaign, "membership")
            trace = uuid.uuid5(self.campaign, "bootstrap-trace")
            audit = uuid.uuid5(self.campaign, "bootstrap-audit")
            session.add(
                m.User(
                    id=self.user,
                    email=f"{self.user}@mobius.invalid",
                    email_normalized=f"{self.user}@mobius.invalid",
                    password_hash="!disabled-managed-proof",
                    display_name="M78 proof",
                )
            )
            await session.flush()
            session.add(
                m.Workspace(
                    id=self.workspace,
                    owner_id=self.user,
                    name="M78 object proof",
                    lifecycle_state="active",
                )
            )
            await session.flush()
            session.add_all(
                [
                    m.WorkspaceAuthorityVersion(
                        workspace_id=self.workspace,
                        authority_generation=1,
                        last_trace_id=trace,
                        updated_at=now,
                    ),
                    m.CollaborationAuditEvent(
                        audit_event_id=audit,
                        workspace_id=self.workspace,
                        actor_user_id=self.user,
                        subject_kind="workspace_membership",
                        subject_id=membership,
                        action="membership.proof_bootstrap",
                        outcome="succeeded",
                        reason_code="proof_owner_bootstrap",
                        metadata_digest=digest(str(self.campaign)),
                        trace_id=trace,
                        recorded_at=now,
                    ),
                    m.WorkspaceMembership(
                        membership_id=membership,
                        user_id=self.user,
                        workspace_id=self.workspace,
                        created_by_user_id=self.user,
                        accepted_invitation_id=None,
                        collaboration_policy_version="collaboration-policy-v1",
                        creation_trace_id=trace,
                        creation_audit_event_id=audit,
                        created_at=now,
                    ),
                    m.Canvas(
                        id=self.canvas,
                        workspace_id=self.workspace,
                        name="M78 object proof",
                    ),
                ]
            )
            await session.flush()
            session.add(
                m.WorkspaceMembershipTransition(
                    transition_id=uuid.uuid5(membership, "initial"),
                    membership_id=membership,
                    user_id=self.user,
                    workspace_id=self.workspace,
                    sequence=0,
                    previous_state=None,
                    current_state="active",
                    previous_role=None,
                    current_role="owner",
                    reason_code="proof_owner_bootstrap",
                    collaboration_policy_version="collaboration-policy-v1",
                    authority_generation=1,
                    actor_user_id=self.user,
                    trace_id=trace,
                    audit_event_id=audit,
                    recorded_at=now,
                )
            )
            await session.flush()
            # Migration 0023 atomically registers Canvas resources/ownership in
            # its AFTER INSERT trigger. Reuse that authoritative registration.
            resource = await session.get(
                m.CollaborationResource, (self.canvas, self.workspace, "canvas")
            )
            ownership = await session.scalar(
                select(m.CollaborationResourceOwnershipTransition).where(
                    m.CollaborationResourceOwnershipTransition.resource_id == self.canvas,
                    m.CollaborationResourceOwnershipTransition.sequence == 0,
                )
            )
            check(
                resource is not None and ownership is not None,
                "fixture-trigger-registration-missing",
            )
            check(
                resource.workspace_id == self.workspace
                and resource.canvas_id == self.canvas
                and resource.resource_kind == "canvas"
                and resource.creator_user_id == self.user
                and ownership.workspace_id == self.workspace
                and ownership.current_owner_kind == "workspace"
                and ownership.visibility_policy == "private"
                and ownership.authority_generation == 1,
                "fixture-trigger-registration-binding-differs",
            )
            await session.commit()
        return {"assertions": ["isolated-fixture-created"]}

    async def upload_key(self, name: str) -> str:
        original_key = f"{self.campaign}:{name}"
        warm = warm_scan_authority(os.environ, self.campaign)
        if warm is not None and name in {"warm-clean", "warm-infected"}:
            return await self.warm_scan_key(name, warm)
        resume = managed_resume_authority(os.environ, self.campaign)
        if resume is not None and name in {"infected", "scanner-clean"}:
            return await self.managed_replacement_key(name, resume)
        authority = (
            clean_replacement_authority(os.environ, self.campaign) if name == "clean" else None
        )
        if authority is None:
            return original_key
        token, snapshot, old = authority["token"], authority["snapshot"], authority["old"]
        replacement_key = f"{original_key}:{token}"
        phase = f"upload-clean-replacement:{token}"
        prior = await self.read_receipt(phase)
        if prior is not None:
            check(
                prior["inspection_sha256"] == authority["inspection_sha256"]
                and prior["replacement_key_sha256"] == digest(replacement_key),
                "clean-replacement-prior-binding-differs",
            )
            return replacement_key
        async with self.db.sessions() as session:
            alternatives = await session.scalar(
                text(
                    "SELECT count(*) FROM m78_object_probe.receipts WHERE campaign=:campaign "
                    "AND status='accepted' AND (phase LIKE 'upload-clean-replacement:%' "
                    "OR phase IN ('upload-clean','upload','scan','delete','recovery'))"
                ),
                {"campaign": self.campaign},
            )
            check(alternatives == 0, "clean-replacement-new-token-would-repeat-work")
            row = await session.get(m.UploadSession, uuid.UUID(old["session_id"]))
            check(
                row is not None
                and row.workspace_id == self.workspace
                and row.user_id == self.user
                and row.idempotency_key == original_key
                and str(row.object_version_id) == old["object_version_id"]
                and row.expected_sha256 == digest(CLEAN)
                and row.expected_size_bytes == len(CLEAN)
                and row.expires_at <= datetime.now(UTC),
                "clean-replacement-original-binding-differs",
            )
            state = await session.scalar(
                select(m.UploadSessionTransition.current_state)
                .where(m.UploadSessionTransition.session_id == row.session_id)
                .order_by(m.UploadSessionTransition.sequence.desc())
                .limit(1)
            )
            check(state == "requested", "clean-replacement-original-state-changed")
            check(
                await session.get(m.StorageObjectVersion, row.object_version_id) is None,
                "clean-replacement-database-version-present",
            )
            for model in (m.MalwareScanRequest, m.MalwareScanResult, m.ObjectPromotion):
                column = (
                    model.source_object_version_id
                    if model is m.ObjectPromotion
                    else model.object_version_id
                )
                count = await session.scalar(
                    select(func.count()).select_from(model).where(column == row.object_version_id)
                )
                check(count == 0, "clean-replacement-dependent-evidence-present")
            key = f"quarantine/{row.object_id.hex}/{row.object_version_id.hex}"
            expires_at = row.expires_at.isoformat()
            await session.rollback()
        head = await self.api._request("HEAD", key, accepted_statuses=frozenset({404}))
        check(head.status_code == 404, "clean-replacement-provider-object-present")
        inventory = await self.api._request(
            "GET",
            "quarantine",
            query={
                "restype": "container",
                "comp": "list",
                "prefix": key.split("/", 1)[1],
                "include": "versions,deleted",
                "maxresults": "100",
            },
        )
        require_empty_version_inventory(inventory.content, key)
        await self.record(
            phase,
            "accepted",
            {
                "inspection_sha256": authority["inspection_sha256"],
                "inspection_execution_id": snapshot["execution_id"],
                "original_session_id": old["session_id"],
                "original_object_version_id": old["object_version_id"],
                "original_key_sha256": digest(original_key),
                "original_expires_at": expires_at,
                "replacement_key_sha256": digest(replacement_key),
                "observations": {
                    "expired_requested_session_preserved": True,
                    "provider_head_status": head.status_code,
                    "exact_version_count": 0,
                },
            },
        )
        return replacement_key

    async def warm_scan_key(self, name: str, manifest: dict[str, Any]) -> str:
        uploads = await self.required("upload")
        check(
            digest(uploads) == manifest["accepted_upload_receipt_sha256"],
            "warm-scan-accepted-upload-binding-differs",
        )
        is_clean = name == "warm-clean"
        prior = await self.required("upload-scanner-clean") if is_clean else uploads["infected"]
        content, outcome = (CLEAN, "No threats found") if is_clean else (EICAR, "Malicious")
        key = f"{self.campaign}:{name}:{manifest['token']}"
        phase = f"warm-scan-resume:{manifest['token']}:{name}"
        previous = await self.read_receipt(phase)
        if previous is not None:
            check(
                previous["manifest_sha256"] == digest(manifest)
                and previous["replacement_key_sha256"] == digest(key),
                "warm-scan-prior-binding-differs",
            )
            return key
        async with self.db.sessions() as session:
            row = await session.get(m.UploadSession, uuid.UUID(prior["session_id"]))
            version = await session.get(
                m.StorageObjectVersion, uuid.UUID(prior["object_version_id"])
            )
            check(
                row is not None
                and version is not None
                and row.workspace_id == self.workspace
                and row.user_id == self.user
                and row.object_version_id == version.object_version_id
                and version.content_sha256 == digest(content),
                "warm-scan-original-binding-differs",
            )
            state = await session.scalar(
                select(m.UploadSessionTransition.current_state)
                .where(m.UploadSessionTransition.session_id == row.session_id)
                .order_by(m.UploadSessionTransition.sequence.desc())
                .limit(1)
            )
            check(state == "completed", "warm-scan-original-upload-not-completed")
            requests = list(
                (
                    await session.scalars(
                        select(m.MalwareScanRequest).where(
                            m.MalwareScanRequest.object_version_id == version.object_version_id
                        )
                    )
                ).all()
            )
            check(
                requests and all(request.deadline_at <= datetime.now(UTC) for request in requests),
                "warm-scan-original-window-not-closed",
            )
            for model in (m.MalwareScanResult, m.ObjectPromotion):
                column = (
                    model.source_object_version_id
                    if model is m.ObjectPromotion
                    else model.object_version_id
                )
                check(
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(column == version.object_version_id)
                    )
                    == 0,
                    "warm-scan-accepted-result-present",
                )
            exact = {
                "physical_key": version.physical_key,
                "provider_version_id": version.provider_version_id,
            }
            etag = version.etag
            uri_digest = digest(self.worker.object_url(version.physical_key))
            etag_digest = digest(_normalize_azure_etag(etag))
            matching = [
                item
                for item in manifest["delayed_log_diagnostic"]["rows"]
                if item["effective_uri_sha256"] == uri_digest
                and item["normalized_etag_sha256"] == etag_digest
                and item["scan_result"] == outcome
            ]
            check(
                matching
                and all(
                    datetime.fromisoformat(item["ingested_at"])
                    > max(request.deadline_at for request in requests)
                    for item in matching
                ),
                "warm-scan-original-delayed-log-binding-differs",
            )
            observed = {
                "session_id": str(row.session_id),
                "object_version_id": str(version.object_version_id),
                "provider_version_sha256": digest(version.provider_version_id),
                "etag_sha256": digest(etag),
                "content_sha256": version.content_sha256,
                "request_deadlines": [request.deadline_at.isoformat() for request in requests],
                "delayed_log_row_sha256": [item["row_sha256"] for item in matching],
            }
            await session.rollback()
        await self.worker.read_version_properties(**exact, expected_etag=etag)
        check(await self.worker.read_version(**exact) == content, "warm-scan-original-bytes-differ")
        await self.record(
            phase,
            "accepted",
            {
                "manifest_sha256": digest(manifest),
                "replacement_key_sha256": digest(key),
                "original": observed,
                "accepted_upload_receipt_sha256": manifest["accepted_upload_receipt_sha256"],
                "delayed_log_execution_id": manifest["delayed_log_diagnostic"]["execution_id"],
                "scanner_admission_receipt_sha256": manifest["scanner_admission_receipt_sha256"],
                "observations": {
                    "original_bytes_preserved": True,
                    "original_requests_preserved": True,
                },
            },
        )
        return key

    async def managed_replacement_key(self, name: str, manifest: dict[str, Any]) -> str:
        """Preserve failed old bytes; authorize only the explicitly selected fresh fixture."""
        token = manifest["token"]
        key = f"{self.campaign}:{name}:{token}"
        phase = f"managed-resume:{token}:{name}"
        binding = digest(manifest)
        previous = await self.read_receipt(phase)
        if previous is not None:
            check(
                previous["manifest_sha256"] == binding
                and previous["replacement_key_sha256"] == digest(key),
                "managed-resume-prior-binding-differs",
            )
            return key
        original_clean = await self.required("upload-clean")
        is_clean = name == "scanner-clean"
        candidates = [
            row
            for row in manifest["upload_inspection"]["sessions"]
            if (
                row["session_id"] == original_clean["session_id"]
                if is_clean
                else row["idempotency_key_sha256"] == digest(f"{self.campaign}:infected")
            )
        ]
        check(len(candidates) == 1, "managed-resume-original-session-ambiguous")
        old = candidates[0]
        expected_state, content = ("completed", CLEAN) if is_clean else ("uploaded", EICAR)
        check(
            old["state"] == expected_state
            and old["expired"] is True
            and old["database_version_present"] is True
            and old["scan_result_count"] == 0
            and old["promotion_count"] == 0
            and old["provider_head_status"] == 200
            and old["provider_exact_version_count"] >= 1,
            "managed-resume-original-observation-differs",
        )
        if is_clean:
            check(
                manifest["scanner_diagnostic"]["object_version_id"] == old["object_version_id"],
                "managed-resume-scanner-source-differs",
            )
        async with self.db.sessions() as session:
            row = await session.get(m.UploadSession, uuid.UUID(old["session_id"]))
            check(
                row is not None
                and row.workspace_id == self.workspace
                and row.user_id == self.user
                and str(row.object_version_id) == old["object_version_id"]
                and row.expected_sha256 == digest(content)
                and row.expected_size_bytes == len(content)
                and row.expires_at <= datetime.now(UTC),
                "managed-resume-session-binding-differs",
            )
            state = await session.scalar(
                select(m.UploadSessionTransition.current_state)
                .where(m.UploadSessionTransition.session_id == row.session_id)
                .order_by(m.UploadSessionTransition.sequence.desc())
                .limit(1)
            )
            check(state == expected_state, "managed-resume-original-state-changed")
            version = await session.get(m.StorageObjectVersion, row.object_version_id)
            check(
                version is not None
                and version.workspace_id == self.workspace
                and version.content_sha256 == digest(content)
                and digest(version.provider_version_id) == old["provider_version_sha256"]
                and digest(version.etag) == old["provider_etag_sha256"],
                "managed-resume-original-version-changed",
            )
            for model in (m.MalwareScanResult, m.ObjectPromotion):
                column = (
                    model.source_object_version_id
                    if model is m.ObjectPromotion
                    else model.object_version_id
                )
                check(
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(column == row.object_version_id)
                    )
                    == 0,
                    "managed-resume-successful-scanner-work-present",
                )
            requests = list(
                (
                    await session.scalars(
                        select(m.MalwareScanRequest).where(
                            m.MalwareScanRequest.object_version_id == row.object_version_id
                        )
                    )
                ).all()
            )
            check(
                (
                    bool(requests)
                    and all(request.deadline_at <= datetime.now(UTC) for request in requests)
                )
                if is_clean
                else not requests,
                "managed-resume-request-window-still-open",
            )
            exact = {
                "physical_key": version.physical_key,
                "provider_version_id": version.provider_version_id,
            }
            expected_etag = version.etag
            observed = {
                "session_id": str(row.session_id),
                "object_version_id": str(version.object_version_id),
                "provider_version_sha256": digest(version.provider_version_id),
                "etag_sha256": digest(version.etag),
                "content_sha256": version.content_sha256,
                "state": state,
                "expires_at": row.expires_at.isoformat(),
            }
            await session.rollback()
        await self.worker.read_version_properties(**exact, expected_etag=expected_etag)
        check(
            await self.worker.read_version(**exact) == content,
            "managed-resume-original-provider-bytes-differ",
        )
        await self.record(
            phase,
            "accepted",
            {
                "manifest_sha256": binding,
                "replacement_key_sha256": digest(key),
                "original": observed,
                "upload_inspection_execution_id": manifest["upload_inspection"]["execution_id"],
                "scanner_diagnostic_execution_id": manifest["scanner_diagnostic"]["execution_id"],
                "failed_scanner_operation_receipt_sha256": manifest[
                    "failed_scanner_operation_receipt_sha256"
                ],
                "scanner_admission_receipt_sha256": manifest["scanner_admission_receipt_sha256"],
                "observations": {
                    "original_bytes_retained": True,
                    "original_history_preserved": True,
                },
            },
        )
        return key

    async def upload_one(
        self, name: str, content: bytes, *, verify_authorization: bool = True
    ) -> dict[str, Any]:
        idempotency_key = await self.upload_key(name)
        async with self.db.sessions() as session:
            service = self.service(session)
            view = await service.initiate(
                principal=self.principal,
                workspace_id=self.workspace,
                canvas_id=self.canvas,
                file_name=f"{name}.txt",
                media_type="text/plain",
                size_bytes=len(content),
                sha256=digest(content),
                idempotency_key=idempotency_key,
            )
            sid, capability = view.session.session_id, view.capability
            # Persist deterministic idempotency binding before any provider mutation.
            await session.commit()
            if view.transition.current_state == "requested" and verify_authorization:
                await expect_denied(
                    service.get(
                        **{
                            **self.scope(sid),
                            "workspace_id": uuid.uuid5(self.campaign, "foreign"),
                        }
                    )
                )
                await expect_denied(
                    service.upload_bytes(
                        session_id=sid, capability=f"{capability}x", content=content
                    )
                )
                try:
                    await service.upload_bytes(
                        session_id=sid,
                        capability=capability,
                        content=b"different bytes",
                    )
                except ObjectIngestionError as error:
                    check(
                        error.code == "upload_contract_mismatch",
                        "checksum-wrong-failure",
                    )
                else:
                    raise ProbeFailure("checksum-substitution-accepted")
            if view.transition.current_state == "requested":
                if view.duplicate and isinstance(self.api, AzureBlobVersionedObjectStorage):
                    key = (
                        f"quarantine/{view.session.object_id.hex}/"
                        f"{view.session.object_version_id.hex}"
                    )
                    observed = await self.api._request(
                        "HEAD", key, accepted_statuses=frozenset({404})
                    )
                    if observed.status_code != 404:
                        headers = observed.headers
                        check(
                            headers.get("x-ms-meta-sha256") == digest(content)
                            and headers.get("content-length") == str(len(content))
                            and bool(headers.get("x-ms-version-id"))
                            and bool(headers.get("etag")),
                            "interrupted-upload-provider-binding-mismatch",
                        )
                        provider = ProviderObjectVersion(
                            key,
                            "azure",
                            headers["x-ms-version-id"],
                            headers["etag"],
                            len(content),
                            digest(content),
                        )
                        check(
                            await self.api.read_version(
                                physical_key=key,
                                provider_version_id=provider.provider_version_id,
                            )
                            == content,
                            "interrupted-upload-bytes-differ",
                        )
                        service.storage = ReconciledUpload(self.api, provider)
                await service.upload_bytes(session_id=sid, capability=capability, content=content)
                await session.commit()
            await service.complete(**self.scope(sid))
            await session.commit()
            await expect_denied(service.clean_bytes(**self.scope(sid)))
            version = await session.get(m.StorageObjectVersion, view.session.object_version_id)
            check(version is not None, "quarantine-version-missing")
            actual = await self.worker.read_version(
                physical_key=version.physical_key,
                provider_version_id=version.provider_version_id,
            )
            check(
                actual == content and version.content_sha256 == digest(content),
                "exact-quarantine-bytes-mismatch",
            )
            return {
                "session_id": str(sid),
                "object_version_id": str(version.object_version_id),
                "physical_key": version.physical_key,
                "provider_version_id": version.provider_version_id,
                "etag": version.etag,
                "content_sha256": version.content_sha256,
            }

    async def continuation_pair(self) -> dict[str, Any]:
        """Exactly two new fixtures; old authorization assertions stay external."""
        check(self.continuation is not None, "continuation-authority-missing")
        pair = {}
        for kind, content in (("clean", CLEAN), ("infected", EICAR)):
            phase = f"continuation-fixture-{kind}"
            fixture = await self.read_receipt(phase)
            if fixture is None:
                fixture = await self.upload_one(
                    f"continuation-{kind}", content, verify_authorization=False
                )
                await self.record(phase, "accepted", fixture)
            check(
                fixture["content_sha256"] == digest(content),
                "continuation-fixture-bytes-differ",
            )
            pair[kind] = fixture
        check(
            pair["clean"]["object_version_id"] != pair["infected"]["object_version_id"],
            "continuation-fixtures-not-distinct",
        )
        return pair

    async def continuation_gate_observation(
        self, bridge: Any, pair: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Read both native sources for both fixtures without accepting/promoting."""
        observations: dict[str, Any] = {}
        self.continuation_gate_observations = observations
        deadlines: list[datetime] = []
        missing = False
        async with self.db.sessions() as session:
            for kind, expected_verdict in (
                ("clean", "clean"),
                ("infected", "infected"),
            ):
                fixture = pair[kind]
                version_id = uuid.UUID(fixture["object_version_id"])
                version = await session.get(m.StorageObjectVersion, version_id)
                requests = list(
                    (
                        await session.scalars(
                            select(m.MalwareScanRequest).where(
                                m.MalwareScanRequest.object_version_id == version_id
                            )
                        )
                    ).all()
                )
                check(
                    version is not None and len(requests) == 1,
                    "continuation-request-missing",
                )
                request = requests[0]
                requested = _aware_utc(request.requested_at)
                deadline = _aware_utc(request.deadline_at)
                deadlines.append(deadline)
                check(
                    request.timeout_seconds == 900
                    and deadline - requested == timedelta(seconds=900)
                    and deadline > datetime.now(UTC),
                    "continuation-request-window-invalid-or-expired",
                )
                check(
                    version.workspace_id == self.workspace
                    and all(
                        getattr(version, key) == fixture[key]
                        for key in (
                            "physical_key",
                            "provider_version_id",
                            "etag",
                            "content_sha256",
                        )
                    ),
                    "continuation-request-version-binding-differs",
                )
                for model, column in (
                    (m.MalwareScanResult, m.MalwareScanResult.object_version_id),
                    (m.ObjectPromotion, m.ObjectPromotion.source_object_version_id),
                ):
                    count = await session.scalar(
                        select(func.count()).select_from(model).where(column == version_id)
                    )
                    check(count == 0, "continuation-admission-before-pair-gate")
                state = await session.scalar(
                    select(m.StorageObjectLifecycleTransition.current_state)
                    .where(m.StorageObjectLifecycleTransition.object_version_id == version_id)
                    .order_by(m.StorageObjectLifecycleTransition.sequence.desc())
                    .limit(1)
                )
                check(state == "scan_pending", "continuation-fixture-not-pending")
                tag_start = datetime.now(UTC)
                observed = {
                    **version_observation(fixture),
                    "scan_request_id": str(request.scan_request_id),
                    "requested_at": requested.isoformat(),
                    "deadline_at": deadline.isoformat(),
                    "timeout_seconds": request.timeout_seconds,
                    "blob_read_started_at": tag_start.isoformat(),
                }
                observations[kind] = observed
                try:
                    blob = await bridge.blob_reader.read(version, observed_at=tag_start)
                    tag_end = datetime.now(UTC)
                    observed.update(
                        blob_read_finished_at=tag_end.isoformat(),
                        blob_evidence_sha256=blob.evidence_sha256,
                        blob_scan_finished_at=blob.scan_finished_at.isoformat(),
                    )
                    log_start = datetime.now(UTC)
                    observed["log_query_started_at"] = log_start.isoformat()
                    logs = await bridge.log_reader.read(
                        account_name=blob.account_name,
                        object_uri=blob.object_uri,
                        etag=blob.etag,
                        requested_at=request.requested_at,
                        observed_at=log_start,
                    )
                    log_end = datetime.now(UTC)
                    observed.update(
                        log_query_finished_at=log_end.isoformat(),
                        native_log_rows=len(logs),
                        native_log_evidence_sha256=[row.evidence_sha256 for row in logs],
                    )
                except (DocumentStorageError, ScannerBridgeEvidenceError) as error:
                    observed["source_error"] = type(error).__name__
                    observed["source_error_at"] = datetime.now(UTC).isoformat()
                    missing = True
                    continue
                decision = correlate_scan_evidence(
                    version=version,
                    request=request,
                    blob=blob,
                    logs=logs,
                    observed_at=log_end,
                    maximum_age=timedelta(
                        seconds=self.settings.malware_scan_result_max_age_seconds
                    ),
                )
                if decision is None:
                    check(not logs, "continuation-scanner-evidence-mismatch")
                    missing = True
                    continue
                check(
                    decision.verdict == expected_verdict,
                    "continuation-scanner-verdict-differs",
                )
                observations[kind] = {
                    **version_observation(fixture),
                    **decision.event_evidence(),
                    "scan_request_id": str(request.scan_request_id),
                    "requested_at": requested.isoformat(),
                    "deadline_at": deadline.isoformat(),
                    "timeout_seconds": request.timeout_seconds,
                    "blob_read_started_at": tag_start.isoformat(),
                    "blob_read_finished_at": tag_end.isoformat(),
                    "log_query_started_at": log_start.isoformat(),
                    "log_query_finished_at": log_end.isoformat(),
                    "log_time_generated": _aware_utc(logs[0].time_generated).isoformat(),
                }
            await session.rollback()
        ready_at = datetime.now(UTC)
        check(
            all(deadline > ready_at for deadline in deadlines),
            "continuation-request-window-closed-during-observation",
        )
        return None if missing else {"pair_ready_at": ready_at.isoformat(), "sources": observations}

    async def require_continuation_gate(self, bridge: Any, pair: dict[str, Any]) -> dict[str, Any]:
        binding = digest({kind: version_observation(pair[kind]) for kind in ("clean", "infected")})
        manifest_hash = digest(self.continuation)
        old = await self.read_receipt("continuation-pair-gate")
        if old is not None:
            check(
                old["pair_binding_sha256"] == binding and old["manifest_sha256"] == manifest_hash,
                "continuation-accepted-pair-binding-differs",
            )
            return old
        end = asyncio.get_running_loop().time() + self.continuation["probe_window_seconds"]
        while True:
            try:
                observed = await self.continuation_gate_observation(bridge, pair)
            except Exception as error:
                await self.record(
                    "continuation-pair-observation",
                    "failed",
                    {
                        "assertions": [],
                        "diagnostic": safe_failure(error),
                        "observations": getattr(self, "continuation_gate_observations", {}),
                    },
                )
                raise
            if observed is not None:
                await self.record(
                    "continuation-pair-gate",
                    "accepted",
                    {
                        "assertions": [],
                        "classification": "both-native-source-pairs-observed-before-admission",
                        "pair_binding_sha256": binding,
                        "manifest_sha256": manifest_hash,
                        "observations": observed,
                    },
                )
                return await self.required("continuation-pair-gate")
            await self.record(
                "continuation-pair-observation",
                "observed",
                {"assertions": [], "observations": self.continuation_gate_observations},
            )
            check(
                asyncio.get_running_loop().time() < end,
                "continuation-pair-gate-wait-exhausted",
            )
            await asyncio.sleep(10)

    async def upload(self) -> dict[str, Any]:
        check(
            getattr(self, "continuation", None) is None,
            "continuation-upload-reexecution-denied",
        )
        result: dict[str, Any] = {}
        for name, content in (("clean", CLEAN), ("infected", EICAR)):
            old = await self.read_receipt(f"upload-{name}")
            if old is None:
                resume = managed_resume_authority(os.environ, self.campaign)
                old = await self.upload_one(
                    name,
                    content,
                    verify_authorization=not (name == "infected" and resume is not None),
                )
                await self.record(f"upload-{name}", "accepted", old)
            result[name] = old
        # RBAC negative uses a deterministic disposable key and a real provider
        # response. Unexpected success fails acceptance and remains cleanup scope.
        auth_key = f"clean/{self.campaign}/unauthorized.txt"
        try:
            await self.api._request(
                "PUT",
                auth_key,
                content=CLEAN,
                extra_headers={"x-ms-blob-type": "BlockBlob", "If-None-Match": "*"},
            )
        except DocumentStorageError as error:
            check(
                error.code == "storage_authorization_failed" and error.provider_status_code == 403,
                "api-write-denial-not-authoritative",
            )
        else:
            raise ProbeFailure("api-clean-write-authorized")
        result["assertions"] = [
            "cross-workspace-denied",
            "forged-capability-denied",
            "checksum-substitution-denied",
            "exact-quarantine-version-bytes",
            "pending-read-denied",
            "api-clean-write-denied-403",
        ]
        result["observations"] = {
            name: version_observation(result[name]) for name in ("clean", "infected")
        }
        result["observations"].update(
            api_clean_write_status=403,
            source_state="scan_pending",
            clean_size_bytes=len(CLEAN),
            eicar_size_bytes=len(EICAR),
        )
        return result

    async def scan(self) -> dict[str, Any]:
        continuation = getattr(self, "continuation", None)
        if continuation is not None:
            uploads = await self.continuation_pair()
            prior = continuation["prior_upload_export"]["receipts"][0]
            authorized = prior["observations"]
        else:
            uploads = await self.required("upload")
            authorized = {
                kind: version_observation(uploads[kind]) for kind in ("clean", "infected")
            }
        warm = warm_scan_authority(os.environ, self.campaign)
        resume = managed_resume_authority(os.environ, self.campaign)
        if warm is not None:
            pair = {}
            for kind, content in (("clean", CLEAN), ("infected", EICAR)):
                phase = f"upload-warm-{kind}:{warm['token']}"
                fixture = await self.read_receipt(phase)
                if fixture is None:
                    fixture = await self.upload_one(
                        f"warm-{kind}", content, verify_authorization=False
                    )
                    await self.record(phase, "accepted", fixture)
                pair[kind] = fixture
            uploads = {**uploads, **pair}
        elif resume is not None:
            scanner_clean = await self.read_receipt("upload-scanner-clean")
            if scanner_clean is None:
                scanner_clean = await self.upload_one(
                    "scanner-clean", CLEAN, verify_authorization=False
                )
                await self.record("upload-scanner-clean", "accepted", scanner_clean)
            uploads = {**uploads, "clean": scanner_clean}
        bridge = build_private_scanner_result_bridge(self.worker_settings)
        check(bridge is not None, "private-dual-source-bridge-required")
        pair_gate = (
            await self.require_continuation_gate(bridge, uploads)
            if continuation is not None
            else None
        )
        seconds = int(os.environ.get("OPENCANVAS_OBJECT_PROBE_SCAN_SECONDS", "1800"))
        check(30 <= seconds <= 3600, "scan-window-invalid")
        end = asyncio.get_running_loop().time() + seconds
        while True:
            async with self.db.sessions() as session:
                rows = list(
                    (
                        await session.scalars(
                            select(m.MalwareScanResult).where(
                                m.MalwareScanResult.object_version_id.in_(
                                    [
                                        uuid.UUID(uploads[n]["object_version_id"])
                                        for n in ("clean", "infected")
                                    ]
                                )
                            )
                        )
                    ).all()
                )
                if len(rows) == 2:
                    break
                expected = {
                    uuid.UUID(uploads[name]["object_version_id"]) for name in ("clean", "infected")
                }
                requests = list(
                    (
                        await session.scalars(
                            select(m.MalwareScanRequest).where(
                                m.MalwareScanRequest.object_version_id.in_(expected)
                            )
                        )
                    ).all()
                )
                require_possible_scan_progress(
                    expected,
                    {row.object_version_id for row in rows},
                    {request.object_version_id: request.deadline_at for request in requests},
                    datetime.now(UTC),
                )
                await bridge.consume_once(session)
                await session.commit()
            check(
                asyncio.get_running_loop().time() < end,
                "defender-evidence-not-yet-complete",
            )
            await asyncio.sleep(10)
        result: dict[str, Any] = {}
        observations: dict[str, Any] = {}
        async with self.db.sessions() as session:
            for name, outcome in (("clean", "clean"), ("infected", "infected")):
                version_id = uuid.UUID(uploads[name]["object_version_id"])
                row = next(r for r in rows if r.object_version_id == version_id)
                check(row.outcome == outcome, f"defender-{name}-unexpected-verdict")
                promotion = await session.scalar(
                    select(m.ObjectPromotion).where(
                        m.ObjectPromotion.source_object_version_id == version_id
                    )
                )
                if name == "clean":
                    check(promotion is not None, "clean-promotion-missing")
                    _, target, content = await self.service(session).clean_bytes(
                        **self.scope(uuid.UUID(uploads[name]["session_id"]))
                    )
                    check(content == CLEAN, "clean-promoted-bytes-mismatch")
                    result["target"] = {
                        "object_version_id": str(target.object_version_id),
                        "physical_key": target.physical_key,
                        "provider_version_id": target.provider_version_id,
                        "etag": target.etag,
                        "content_sha256": target.content_sha256,
                    }
                else:
                    check(promotion is None, "infected-promotion-present")
                    await expect_denied(
                        self.service(session).clean_bytes(
                            **self.scope(uuid.UUID(uploads[name]["session_id"]))
                        )
                    )
                result[name] = {
                    "outcome": row.outcome,
                    "provider_record_digest": row.provider_record_digest,
                }
                event = await session.scalar(
                    select(m.DomainEventRecord).where(
                        m.DomainEventRecord.subject_id == row.scan_result_id
                    )
                )
                check(event is not None, "scanner-domain-evidence-missing")
                evidence = {
                    key: event.payload.get(key)
                    for key in (
                        "scannerEvidenceIntegrity",
                        "scannerCorrelationSha256",
                        "scannerBlobTagEvidenceSha256",
                        "scannerLogAnalyticsEvidenceSha256",
                        "scannerBlobUriSha256",
                        "scannerEtagSha256",
                        "scannerCompletionAtUtc",
                        "scannerProvenance",
                    )
                }
                check(all(evidence.values()), "scanner-dual-source-fields-missing")
                request = await session.get(m.MalwareScanRequest, row.scan_request_id)
                check(request is not None, "accepted-scanner-request-missing")
                check(
                    _aware_utc(row.received_at) <= _aware_utc(request.deadline_at),
                    "scanner-admission-after-request-deadline",
                )
                observations[name] = {
                    **version_observation(uploads[name]),
                    **evidence,
                    "scan_result_id": str(row.scan_result_id),
                    "scan_request_id": str(row.scan_request_id),
                    "outcome": row.outcome,
                    "provider_record_digest": row.provider_record_digest,
                    "result_digest": row.result_digest,
                    "domain_event_payload_digest": event.payload_digest,
                    "promotion_id": str(promotion.promotion_id) if promotion else None,
                    "requested_at": _aware_utc(request.requested_at).isoformat(),
                    "deadline_at": _aware_utc(request.deadline_at).isoformat(),
                    "received_at": _aware_utc(row.received_at).isoformat(),
                    "timeout_seconds": request.timeout_seconds,
                }
        # Withholding consumption is a real indeterminate state, not a forged verdict.
        pending = await self.upload_one(
            "withheld", CLEAN + b"withheld evidence\n", verify_authorization=False
        )
        async with self.db.sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(m.ObjectPromotion)
                .where(
                    m.ObjectPromotion.source_object_version_id
                    == uuid.UUID(pending["object_version_id"])
                )
            )
            check(count == 0, "indeterminate-promoted")
        result["withheld"] = pending
        result["clean_upload"] = uploads["clean"]
        result["observations"] = {
            **observations,
            "authorized_clean_upload": authorized["clean"],
            "authorized_infected_upload": authorized["infected"],
            "target": version_observation(result["target"]),
            "withheld": {
                **version_observation(pending),
                "promotion_count": count,
                "state": "scan_pending",
            },
        }
        if continuation is not None:
            result["observations"]["preserved_upload_receipt_sha256"] = prior["receipt_sha256"]
            result["observations"]["pair_gate_receipt_sha256"] = digest(pair_gate)
        result["assertions"] = [
            "defender-dual-source-clean",
            "defender-dual-source-eicar",
            "clean-promotion-exact-bytes",
            "infected-no-promotion-no-read",
            "indeterminate-no-promotion-no-read",
        ]
        return result

    async def delete(self) -> dict[str, Any]:
        scanned = await self.required("scan")
        source = scanned.get("clean_upload") or (await self.required("upload"))["clean"]
        sid = uuid.UUID(source["session_id"])
        target = scanned["target"]
        exact = {k: target[k] for k in ("physical_key", "provider_version_id")}
        storage = self.worker
        async with self.db.sessions() as session:
            await self.service(session).request_deletion(
                **self.scope(sid),
                idempotency_key="managed-exact-delete",
                reason_code="managed_proof_cleanup",
            )
            await session.commit()
        if await self.read_receipt("delete-lock") is None:
            async with self.db.sessions() as owner, self.db.sessions() as competitor:
                locked = await owner.scalar(
                    select(m.ObjectDeletionRequest)
                    .where(
                        m.ObjectDeletionRequest.object_version_id
                        == uuid.UUID(target["object_version_id"])
                    )
                    .with_for_update()
                )
                check(locked is not None, "delete-request-missing")
                skipped = await ObjectReconciler(
                    competitor, settings=self.settings
                ).execute_deletion_requests(storage)
                check(skipped == 0, "concurrent-worker-did-not-skip-lock")
                await competitor.rollback()
                await owner.rollback()
            await self.record("delete-lock", "accepted", {"assertions": ["skip-locked"]})
        if await self.read_receipt("delete-rollback") is None:
            live = await storage.version_exists(**exact)
            if live:
                await self.record(
                    "delete-intent",
                    "accepted",
                    {
                        "target": target,
                        "observations": {"exact_version_live_before_delete": True},
                    },
                )
                async with self.db.sessions() as session:
                    ambiguous = AmbiguousDelete(storage)
                    try:
                        await ObjectReconciler(
                            session, settings=self.settings
                        ).execute_deletion_requests(ambiguous)
                    except DocumentStorageError:
                        await session.rollback()
                        check(ambiguous.deleted, "delete-failed-before-injection")
                    else:
                        raise ProbeFailure("ambiguous-delete-not-exercised")
            else:
                # A prior invocation may have died after the provider committed.
                # Require its durable intent, then inspect DB rather than DELETE again.
                await self.required("delete-intent")
            async with self.db.sessions() as session:
                count = await session.scalar(
                    select(func.count())
                    .select_from(m.StorageObjectLifecycleTransition)
                    .where(
                        m.StorageObjectLifecycleTransition.object_version_id
                        == uuid.UUID(target["object_version_id"]),
                        m.StorageObjectLifecycleTransition.current_state == "deleted",
                    )
                )
                check(count == 0, "failed-transaction-committed-deleted-transition")
            check(not await storage.version_exists(**exact), "exact-delete-not-observed")
            await self.record(
                "delete-rollback",
                "accepted",
                {
                    "assertions": ["provider-delete-database-rollback"],
                    "observations": {
                        "deleted_transition_count": count,
                        "exact_version_live": False,
                        "injected_response_loss_observed_this_execution": live,
                        "interrupted_provider_commit_reconciled": not live,
                    },
                },
            )
        async with self.db.sessions() as session:
            await ObjectReconciler(session, settings=self.settings).execute_deletion_requests(
                storage
            )
            await session.commit()
            second = await ObjectReconciler(
                session, settings=self.settings
            ).execute_deletion_requests(storage)
            check(second == 0, "delete-replay-did-work")
            count = await session.scalar(
                select(func.count())
                .select_from(m.StorageObjectLifecycleTransition)
                .where(
                    m.StorageObjectLifecycleTransition.object_version_id
                    == uuid.UUID(target["object_version_id"]),
                    m.StorageObjectLifecycleTransition.current_state == "deleted",
                )
            )
            check(count == 1, "delete-transition-count-not-one")
            await expect_denied(self.service(session).clean_bytes(**self.scope(sid)))
        check(not await storage.version_exists(**exact), "deleted-version-live")
        check(await storage.version_residue_exists(**exact), "retention-version-missing")
        check(
            await self.worker.read_version(**{k: source[k] for k in exact}) == CLEAN,
            "retained-source-bytes-changed",
        )
        rollback = await self.required("delete-rollback")
        return {
            "target": target,
            "observations": {
                "target": version_observation(target),
                "after_rollback": rollback["observations"],
                "final_deleted_transition_count": count,
                "second_reconcile_completed_count": second,
                "exact_version_live": False,
                "exact_version_retained": True,
                "retained_source_sha256": digest(CLEAN),
            },
            "assertions": [
                "concurrent-skip-locked",
                "failed-transaction-rollback",
                "authoritative-absence-reconciled",
                "exactly-one-deleted-transition",
                "delete-replay-noop",
                "deleted-read-denied",
                "soft-deleted-exact-version-retained",
                "retained-source-unchanged",
            ],
        }

    async def verify_recovered_policy(self, target: dict[str, Any]) -> dict[str, Any]:
        scanned = await self.required("scan")
        source = scanned.get("clean_upload") or (await self.required("upload"))["clean"]
        original = scanned["observations"]["clean"]
        async with self.db.sessions() as session:
            result = await session.get(m.MalwareScanResult, uuid.UUID(original["scan_result_id"]))
            promotion = await session.get(m.ObjectPromotion, uuid.UUID(original["promotion_id"]))
            check(
                result is not None and promotion is not None,
                "recovered-original-evidence-missing",
            )
            check(
                str(result.object_version_id) == source["object_version_id"]
                and str(result.scan_request_id) == original["scan_request_id"]
                and result.outcome == "clean"
                and result.result_digest == original["result_digest"]
                and result.provider_record_digest == original["provider_record_digest"]
                and result.provider_version_id == source["provider_version_id"]
                and result.etag == source["etag"]
                and result.content_sha256 == source["content_sha256"]
                and promotion.scan_result_id == result.scan_result_id
                and str(promotion.source_object_version_id) == source["object_version_id"]
                and str(promotion.target_object_version_id) == target["object_version_id"]
                and promotion.source_sha256 == source["content_sha256"]
                and promotion.target_sha256 == target["content_sha256"],
                "recovered-scan-promotion-binding-changed",
            )
            state = await session.scalar(
                select(m.StorageObjectLifecycleTransition.current_state)
                .where(
                    m.StorageObjectLifecycleTransition.object_version_id
                    == uuid.UUID(target["object_version_id"])
                )
                .order_by(m.StorageObjectLifecycleTransition.sequence.desc())
                .limit(1)
            )
            check(state == "deleted", "recovered-deleted-lifecycle-changed")
            await expect_denied(
                self.service(session).clean_bytes(**self.scope(uuid.UUID(source["session_id"])))
            )
            return {
                "lifecycle_state": state,
                "api_clean_read": "denied",
                "scan_result_id": str(result.scan_result_id),
                "scan_result_digest": result.result_digest,
                "promotion_id": str(promotion.promotion_id),
                "source_object_version_id": source["object_version_id"],
                "target_object_version_id": target["object_version_id"],
            }

    async def recovery(self) -> dict[str, Any]:
        deleted = await self.required("delete")
        target = deleted["target"]
        exact = {k: target[k] for k in ("physical_key", "provider_version_id")}
        storage = self.recovery_storage
        # Key belongs solely to this campaign's immutable object. Undelete restores
        # its retained version; verify exact original version, ETag and bytes.
        observed = await self.read_receipt("recovery-observed")
        fresh_observation = observed is None
        if fresh_observation:
            if not await storage.version_exists(**exact):
                await storage._request("PUT", target["physical_key"], query={"comp": "undelete"})
            properties = await storage._request(
                "HEAD",
                target["physical_key"],
                query={"versionid": target["provider_version_id"]},
                extra_headers={"If-Match": target["etag"]},
            )
            content = await storage.read_version(**exact)
            check(
                content == CLEAN and digest(content) == target["content_sha256"],
                "recovered-bytes-differ",
            )
            check(
                properties.headers.get("x-ms-version-id") == target["provider_version_id"]
                and properties.headers.get("etag") == target["etag"],
                "recovered-exact-version-properties-missing",
            )
            policy = await self.verify_recovered_policy(target)
            observed = {
                "observations": {
                    "target": version_observation(target),
                    "recovered_sha256": digest(content),
                    "recovered_size_bytes": len(content),
                    "head_status": properties.status_code,
                    "restored_object_policy": policy,
                }
            }
            await self.record("recovery-observed", "accepted", observed)
        if fresh_observation or await storage.version_exists(**exact):
            await storage.delete_version(**exact)
        check(
            not await storage.version_exists(**exact),
            "recovered-version-cleanup-unproved",
        )
        return {
            "target": target,
            "observations": {
                **observed["observations"],
                "exact_version_live_after_cleanup": False,
            },
            "assertions": [
                "retained-version-recovered",
                "original-version-etag-bytes-restored",
                "restored-provider-bytes-remain-api-denied",
                "original-scan-promotion-binding-unchanged",
                "recovered-version-soft-deleted-again",
            ],
        }

    async def required(self, phase: str) -> dict[str, Any]:
        result = await self.read_receipt(phase)
        check(result is not None, f"required-{phase}-receipt-missing")
        return result

    async def export_accepted_receipts(self, phases: tuple[str, ...]) -> list[dict[str, Any]]:
        if getattr(self, "continuation", None) is None:
            return [public_receipt(phase, await self.required(phase)) for phase in phases]
        receipts = []
        for phase in phases:
            accepted = await self.read_receipt(phase)
            if accepted is not None:
                receipts.append(public_receipt(phase, accepted))
        return receipts

    async def execute(self, phase: str) -> dict[str, Any]:
        old = await self.read_receipt(phase)
        if old is not None:
            return old
        try:
            result = await getattr(self, phase)()
        except Exception as error:
            diagnostic = safe_failure(error)
            await self.record(
                phase, "failed", {"safe_code": diagnostic["code"], "diagnostic": diagnostic}
            )
            raise
        await self.record(phase, "accepted", result)
        return await self.required(phase)


async def expect_denied(operation: Any) -> None:
    try:
        await operation
    except ObjectIngestionNotFoundError:
        return
    raise ProbeFailure("unauthorized-operation-accepted")


def selected_phases(phase: str, continuation: bool) -> tuple[str, ...]:
    if continuation:
        check(
            phase in ("setup", "continue", "scan", "delete", "recovery", "receipts"),
            "continuation-phase-selector-invalid",
        )
        return PHASES[1:] if phase in {"continue", "receipts"} else (phase,)
    check(phase in (*PHASES, "setup", "all", "receipts"), "phase-selector-invalid")
    return PHASES if phase in {"all", "receipts"} else (phase,)


async def run() -> None:
    settings = Settings()
    check(
        settings.database_url_value.startswith("postgresql")
        and settings.database_auth_mode == "entra",
        "managed-postgresql-required",
    )
    check(settings.database_tls_mode == "verify-full", "database-verified-tls-required")
    check(
        settings.object_ingestion_mode == "trusted"
        and settings.scanner_result_bridge_mode == "private_pull",
        "trusted-private-pull-required",
    )
    database = Database.from_settings(settings, expected_role=DatabaseRole.API)
    phase = os.environ["OPENCANVAS_OBJECT_PROBE_PHASE"]
    try:
        probe = Probe(settings, database)
        phases = selected_phases(phase, probe.continuation is not None)
        # Session-level lock held on a dedicated connection, outside transactions;
        # other phases can still commit journal/provider reconciliation independently.
        async with database.engine.connect() as lock:
            acquired = await lock.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:key,0))"),
                {"key": str(probe.campaign)},
            )
            check(acquired is True, "campaign-already-running")
            await lock.commit()
            try:
                if phase == "setup":
                    result = await probe.setup()
                    await probe.record("setup", "accepted", result)
                    receipts = [public_receipt("setup", result)]
                elif phase == "receipts":
                    receipts = await probe.export_accepted_receipts(phases)
                else:
                    receipts = [public_receipt(p, await probe.execute(p)) for p in phases]
                print(
                    "M78_OBJECT_PROBE="
                    + json.dumps(
                        {
                            "campaign": str(probe.campaign),
                            "execution_id": probe.execution,
                            "source_sha256": probe.source,
                            "receipts": receipts,
                            **(
                                {
                                    "preserved_upload_export": probe.continuation[
                                        "prior_upload_export"
                                    ],
                                    "not_accepted_phases": [
                                        p for p in phases if p not in {r["phase"] for r in receipts}
                                    ],
                                }
                                if probe.continuation is not None
                                else {}
                            ),
                        },
                        sort_keys=True,
                    )
                )
            finally:
                await lock.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                    {"key": str(probe.campaign)},
                )
                await lock.commit()
    finally:
        await database.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as error:
        # Never emit exception repr/traceback: provider errors can contain secrets.
        print("M78_OBJECT_PROBE_FAILURE=" + json.dumps(safe_failure(error), sort_keys=True))
        raise SystemExit(1) from None

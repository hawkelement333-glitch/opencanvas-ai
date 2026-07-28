from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    Canvas,
    Document,
    DocumentFile,
    DocumentVersion,
    MalwareScanRequest,
    MalwareScanResult,
    ObjectDeletionRequest,
    ObjectIngestionAuditEvent,
    ObjectPromotion,
    StorageObject,
    StorageObjectLifecycleTransition,
    StorageObjectVersion,
    UploadSession,
    UploadSessionTransition,
    Workspace,
)
from opencanvas_api.services.auth import Principal
from opencanvas_api.services.collaboration_resources import (
    ShareAccessLevel,
    ShareResourceKind,
    SharingService,
)
from opencanvas_api.services.documents.storage import (
    ProviderObjectVersion,
    VersionedObjectStorage,
)
from opencanvas_api.services.documents.validation import (
    validate_document_bytes,
    validate_upload_contract,
)
from opencanvas_api.services.domain_events import CreateDomainEvent, DomainEventService
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    StartTraceInput,
    TraceService,
)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_SAFE_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TERMINAL_UPLOAD_STATES = frozenset({"canceled", "expired", "error"})
_ACTIVE_UPLOAD_STATES = frozenset({"requested", "uploaded"})
_TERMINAL_OBJECT_STATES = frozenset(
    {"clean", "rejected", "retained", "deleted", "legacy_unscanned", "canceled", "error"}
)
ScanOutcome = Literal["clean", "infected", "suspicious", "unsupported", "error", "timeout"]


class ObjectIngestionError(RuntimeError):
    code = "object_ingestion_failed"
    status_code = 409
    safe_message = "The secure upload operation could not be completed."

    def __init__(
        self,
        safe_message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(safe_message or self.safe_message)
        self.safe_message = safe_message or self.safe_message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code


class ObjectIngestionNotFoundError(ObjectIngestionError):
    code = "secure_upload_not_found"
    status_code = 404
    safe_message = "The secure upload was not found."


@dataclass(frozen=True, slots=True)
class UploadSessionView:
    session: UploadSession
    transition: UploadSessionTransition
    object_transition: StorageObjectLifecycleTransition | None
    scan_request: MalwareScanRequest | None
    scan_result: MalwareScanResult | None
    promotion: ObjectPromotion | None
    capability: str | None = None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class TrustedScanResult:
    scan_request_id: uuid.UUID
    object_version_id: uuid.UUID
    workspace_id: uuid.UUID
    outcome: ScanOutcome
    scanner_identity: str
    scanner_version: str
    engine_version: str
    signature_version: str
    policy_version: str
    provider_result_id: str
    provider_record_digest: str
    provider_version_id: str
    etag: str
    content_sha256: str
    scanned_at: datetime
    safe_reason_code: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "scanRequestId": str(self.scan_request_id),
            "objectVersionId": str(self.object_version_id),
            "workspaceId": str(self.workspace_id),
            "outcome": self.outcome,
            "scannerIdentity": self.scanner_identity,
            "scannerVersion": self.scanner_version,
            "engineVersion": self.engine_version,
            "signatureVersion": self.signature_version,
            "policyVersion": self.policy_version,
            "providerResultId": self.provider_result_id,
            "providerRecordDigest": self.provider_record_digest,
            "providerVersionId": self.provider_version_id,
            "etag": self.etag,
            "contentSha256": self.content_sha256,
            "scannedAt": _aware_utc(self.scanned_at).isoformat(),
            "safeReasonCode": self.safe_reason_code,
        }


class UploadLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: VersionedObjectStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.trace = TraceService(session)
        self.events = DomainEventService(session)

    async def initiate(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        file_name: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        idempotency_key: str,
    ) -> UploadSessionView:
        self._require_enabled()
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ObjectIngestionError(
                "A valid idempotency key is required.",
                code="idempotency_key_invalid",
                status_code=422,
            )
        contract = validate_upload_contract(
            filename=file_name,
            declared_media_type=media_type,
            size_bytes=size_bytes,
            sha256=sha256,
            settings=self.settings,
        )
        await self._canvas(workspace_id, canvas_id)
        access = await SharingService(self.session).evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=ShareResourceKind.CANVAS,
            resource_id=canvas_id,
            access_level=ShareAccessLevel.CONTRIBUTE,
        )
        if (
            not access.allowed
            or access.membership_id is None
            or access.authority_generation is None
        ):
            raise ObjectIngestionNotFoundError()
        request_digest = _digest(
            {
                "userId": str(principal.user_id),
                "membershipId": str(access.membership_id),
                "workspaceId": str(workspace_id),
                "canvasId": str(canvas_id),
                "fileName": contract.file_name,
                "mediaType": contract.media_type,
                "sizeBytes": contract.size_bytes,
                "sha256": contract.sha256,
            }
        )
        existing = await self.session.scalar(
            select(UploadSession).where(
                UploadSession.user_id == principal.user_id,
                UploadSession.workspace_id == workspace_id,
                UploadSession.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise ObjectIngestionError(
                    "The idempotency key was reused for another upload.",
                    code="idempotency_conflict",
                )
            view = await self._view(existing)
            return UploadSessionView(
                view.session,
                view.transition,
                view.object_transition,
                view.scan_request,
                view.scan_result,
                view.promotion,
                capability=self._capability(existing),
                duplicate=True,
            )
        if await self._active_count(workspace_id) >= (
            self.settings.upload_max_active_sessions_per_workspace
        ):
            raise ObjectIngestionError(
                "The workspace has reached its active secure-upload limit.",
                code="upload_limit_reached",
                status_code=429,
            )
        now = datetime.now(UTC)
        session_id = uuid.uuid4()
        document_id = uuid.uuid4()
        document_version_id = uuid.uuid4()
        object_id = uuid.uuid4()
        object_version_id = uuid.uuid4()
        trace_id = uuid.uuid4()
        expires_at = now + timedelta(seconds=self.settings.upload_capability_ttl_seconds)
        expected_key = f"quarantine/{object_id.hex}/{object_version_id.hex}"
        document = Document(
            id=document_id,
            canvas_id=canvas_id,
            file_name=contract.file_name,
            file_type=contract.file_type,
            media_type=contract.media_type,
            file_size_bytes=contract.size_bytes,
            content_sha256=contract.sha256,
            status="uploaded",
            processing_stage="uploading",
            chunk_count=0,
            retry_count=0,
            version_count=1,
            current_version=1,
        )
        version = DocumentVersion(
            id=document_version_id,
            document_id=document_id,
            version=1,
            file_name=contract.file_name,
            file_type=contract.file_type,
            media_type=contract.media_type,
            file_size_bytes=contract.size_bytes,
            content_sha256=contract.sha256,
            storage_key=expected_key,
            status="uploading",
        )
        storage_object = StorageObject(
            object_id=object_id,
            creator_user_id=principal.user_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            environment=self.settings.runtime_mode.value,
            classification="private_source",
            created_at=now,
        )
        provisional = UploadSession(
            session_id=session_id,
            user_id=principal.user_id,
            membership_id=access.membership_id,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            document_id=document_id,
            document_version_id=document_version_id,
            object_id=object_id,
            object_version_id=object_version_id,
            authority_generation=access.authority_generation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            expected_sha256=contract.sha256,
            expected_size_bytes=contract.size_bytes,
            file_name=contract.file_name,
            file_type=contract.file_type,
            media_type=contract.media_type,
            extension=contract.extension,
            capability_digest="0" * 64,
            expires_at=expires_at,
            trace_id=trace_id,
            created_at=now,
        )
        capability = self._capability(provisional)
        provisional.capability_digest = hashlib.sha256(capability.encode()).hexdigest()
        transition = self._upload_transition(
            provisional,
            sequence=0,
            previous=None,
            current="requested",
            reason="upload_authorized",
            actor_kind="user",
            actor_user_id=principal.user_id,
            now=now,
        )
        await self.trace.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                event_type="object_ingestion.upload",
                actor_id=str(principal.user_id),
                actor_type="user",
                user_id=principal.user_id,
                workspace_id=workspace_id,
                object_id=session_id,
                object_type="upload_session",
                operation="upload_initiate",
                metadata={
                    "state": "requested",
                    "documentVersion": 1,
                    "policyVersion": self.settings.malware_policy_version,
                },
            )
        )
        self.session.add_all((document, version, storage_object, provisional))
        await self.session.flush()
        self.session.add(transition)
        audit = self._audit(
            session=provisional,
            action="upload.initiate",
            outcome="allowed",
            reason="upload_authorized",
            actor_user_id=principal.user_id,
            now=now,
        )
        self.session.add(audit)
        await self._event(
            session=provisional,
            event_type="upload.requested",
            subject_id=session_id,
            source=f"requested:{idempotency_key}",
            payload={
                "state": "requested",
                "documentId": str(document_id),
                "documentVersion": 1,
                "objectVersionId": str(object_version_id),
                "policyVersion": self.settings.malware_policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=principal.user_id,
        )
        return UploadSessionView(
            provisional,
            transition,
            None,
            None,
            None,
            None,
            capability=capability,
        )

    async def upload_bytes(
        self,
        *,
        session_id: uuid.UUID,
        capability: str,
        content: bytes,
    ) -> UploadSessionView:
        self._require_enabled()
        record = await self.session.scalar(
            select(UploadSession).where(UploadSession.session_id == session_id).with_for_update()
        )
        if record is None:
            raise ObjectIngestionNotFoundError()
        self._verify_capability(record, capability)
        latest = await self._latest_upload_transition(session_id)
        if latest.current_state == "uploaded":
            version = await self._object_version(record.object_version_id)
            if version.content_sha256 != hashlib.sha256(content).hexdigest():
                raise ObjectIngestionError(
                    "The upload session already contains different bytes.",
                    code="upload_already_completed",
                )
            return await self._view(record)
        if latest.current_state != "requested":
            raise ObjectIngestionError("The upload session is no longer writable.")
        now = datetime.now(UTC)
        if _aware_utc(record.expires_at) <= now:
            raise ObjectIngestionError(
                "The upload capability has expired.",
                code="upload_capability_expired",
                status_code=410,
            )
        validated = validate_document_bytes(
            filename=record.file_name,
            content=content,
            declared_media_type=record.media_type,
            settings=self.settings,
        )
        if (
            validated.size_bytes != record.expected_size_bytes
            or not hmac.compare_digest(validated.sha256, record.expected_sha256)
            or validated.media_type != record.media_type
        ):
            raise ObjectIngestionError(
                "The uploaded bytes do not match the authorized upload.",
                code="upload_contract_mismatch",
                status_code=422,
            )
        stored = await self.storage.put_immutable(
            security_class="quarantine",
            object_id=record.object_id,
            object_version_id=record.object_version_id,
            content=content,
            expected_sha256=record.expected_sha256,
        )
        version = self._version_model(record, stored, now=now, security_class="quarantine")
        object_transition = self._object_transition(
            version,
            sequence=0,
            previous=None,
            current="quarantined",
            reason="upload_bytes_verified",
            actor_kind="capability",
            actor_user_id=None,
            service_identity=None,
            trace_id=record.trace_id,
            now=now,
        )
        upload_transition = self._upload_transition(
            record,
            sequence=latest.sequence + 1,
            previous=latest.current_state,
            current="uploaded",
            reason="quarantine_write_completed",
            actor_kind="capability",
            actor_user_id=None,
            now=now,
        )
        document_version = await self.session.get(DocumentVersion, record.document_version_id)
        if document_version is None:
            raise ObjectIngestionError("The upload source version is unavailable.")
        document_version.storage_key = stored.physical_key
        document_version.status = "uploaded"
        self.session.add(version)
        await self.session.flush()
        self.session.add_all((object_transition, upload_transition))
        await self.session.flush()
        audit = self._audit(
            session=record,
            action="upload.bytes",
            outcome="succeeded",
            reason="quarantine_write_completed",
            actor_user_id=None,
            object_version_id=version.object_version_id,
            now=now,
        )
        self.session.add(audit)
        await self._event(
            session=record,
            event_type="object.quarantined",
            subject_id=version.object_version_id,
            source=f"quarantine:{stored.provider_version_id}",
            payload={
                "state": "quarantined",
                "documentId": str(record.document_id),
                "documentVersion": 1,
                "objectVersionId": str(version.object_version_id),
                "policyVersion": self.settings.malware_policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=record.user_id,
            origin_type="canonical_service",
        )
        return UploadSessionView(
            record,
            upload_transition,
            object_transition,
            None,
            None,
            None,
        )

    async def complete(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> UploadSessionView:
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.CONTRIBUTE,
            lock=True,
        )
        latest = await self._latest_upload_transition(session_id)
        if latest.current_state == "completed":
            return await self._view(record)
        if latest.current_state != "uploaded":
            raise ObjectIngestionError("Only a completed quarantine upload can be submitted.")
        now = datetime.now(UTC)
        if _aware_utc(record.expires_at) <= now:
            raise ObjectIngestionError(
                "The upload session expired before completion.",
                code="upload_session_expired",
                status_code=410,
            )
        version = await self._object_version(record.object_version_id)
        content = await self.storage.read_version(
            physical_key=version.physical_key,
            provider_version_id=version.provider_version_id,
        )
        if len(content) != version.byte_size or not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(),
            version.content_sha256,
        ):
            raise ObjectIngestionError(
                "The quarantine object failed completion integrity verification.",
                code="quarantine_integrity_failed",
            )
        scan_request = MalwareScanService(self.session, settings=self.settings)._request_model(
            record=record,
            version=version,
            now=now,
        )
        upload_transition = self._upload_transition(
            record,
            sequence=latest.sequence + 1,
            previous="uploaded",
            current="completed",
            reason="scan_requested",
            actor_kind="user",
            actor_user_id=principal.user_id,
            now=now,
        )
        object_latest = await self._latest_object_transition(version.object_version_id)
        object_transition = self._object_transition(
            version,
            sequence=object_latest.sequence + 1,
            previous=object_latest.current_state,
            current="scan_pending",
            reason="scanner_request_created",
            actor_kind="user",
            actor_user_id=principal.user_id,
            service_identity=None,
            trace_id=record.trace_id,
            now=now,
        )
        self.session.add_all((scan_request, upload_transition, object_transition))
        await self.session.flush()
        audit = self._audit(
            session=record,
            action="scan.request",
            outcome="succeeded",
            reason="scanner_request_created",
            actor_user_id=principal.user_id,
            object_version_id=version.object_version_id,
            scan_request_id=scan_request.scan_request_id,
            now=now,
        )
        self.session.add(audit)
        await self._event(
            session=record,
            event_type="upload.completed",
            subject_id=record.session_id,
            source=f"completed:{upload_transition.sequence}",
            payload={
                "state": "completed",
                "documentId": str(record.document_id),
                "documentVersion": 1,
                "objectVersionId": str(version.object_version_id),
                "scanRequestId": str(scan_request.scan_request_id),
                "policyVersion": scan_request.policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=principal.user_id,
        )
        await self._event(
            session=record,
            event_type="scan.started",
            subject_id=scan_request.scan_request_id,
            source=f"scan:{scan_request.request_digest}",
            payload={
                "state": "scan_pending",
                "documentId": str(record.document_id),
                "documentVersion": 1,
                "objectVersionId": str(version.object_version_id),
                "scanRequestId": str(scan_request.scan_request_id),
                "policyVersion": scan_request.policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=principal.user_id,
        )
        return UploadSessionView(
            record,
            upload_transition,
            object_transition,
            scan_request,
            None,
            None,
        )

    async def get(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> UploadSessionView:
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.VIEW,
        )
        return await self._view(record)

    async def cancel(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> UploadSessionView:
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.CONTRIBUTE,
            lock=True,
        )
        latest = await self._latest_upload_transition(session_id)
        if latest.current_state == "canceled":
            return await self._view(record)
        if latest.current_state in _TERMINAL_UPLOAD_STATES:
            raise ObjectIngestionError("The secure upload is already terminal.")
        now = datetime.now(UTC)
        canceled = self._upload_transition(
            record,
            sequence=latest.sequence + 1,
            previous=latest.current_state,
            current="canceled",
            reason="user_canceled",
            actor_kind="user",
            actor_user_id=principal.user_id,
            now=now,
        )
        self.session.add(canceled)
        version = await self.session.get(StorageObjectVersion, record.object_version_id)
        object_transition = None
        if version is not None:
            object_latest = await self._latest_object_transition(version.object_version_id)
            if object_latest.current_state not in _TERMINAL_OBJECT_STATES:
                object_transition = self._object_transition(
                    version,
                    sequence=object_latest.sequence + 1,
                    previous=object_latest.current_state,
                    current="canceled",
                    reason="user_canceled",
                    actor_kind="user",
                    actor_user_id=principal.user_id,
                    service_identity=None,
                    trace_id=record.trace_id,
                    now=now,
                )
                self.session.add(object_transition)
        audit = self._audit(
            session=record,
            action="upload.cancel",
            outcome="succeeded",
            reason="user_canceled",
            actor_user_id=principal.user_id,
            object_version_id=record.object_version_id,
            now=now,
        )
        self.session.add(audit)
        return UploadSessionView(record, canceled, object_transition, None, None, None)

    async def request_rescan(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> UploadSessionView:
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.CONTRIBUTE,
            lock=True,
        )
        upload_state = await self._latest_upload_transition(record.session_id)
        if upload_state.current_state != "completed":
            raise ObjectIngestionError("Only a completed upload can be rescanned.")
        version = await self._object_version(record.object_version_id)
        now = datetime.now(UTC)
        request = MalwareScanService(self.session, settings=self.settings)._request_model(
            record=record,
            version=version,
            now=now,
        )
        existing = await self.session.get(MalwareScanRequest, request.scan_request_id)
        if existing is not None:
            return await self._view(record)
        latest = await self._latest_object_transition(version.object_version_id)
        transition = self._object_transition(
            version,
            sequence=latest.sequence + 1,
            previous=latest.current_state,
            current="scan_pending",
            reason="rescan_requested",
            actor_kind="user",
            actor_user_id=principal.user_id,
            service_identity=None,
            trace_id=record.trace_id,
            now=now,
        )
        self.session.add_all((request, transition))
        await self.session.flush()
        audit = self._audit(
            session=record,
            action="scan.rescan",
            outcome="succeeded",
            reason="rescan_requested",
            actor_user_id=principal.user_id,
            object_version_id=version.object_version_id,
            scan_request_id=request.scan_request_id,
            now=now,
        )
        self.session.add(audit)
        await self._event(
            session=record,
            event_type="scan.started",
            subject_id=request.scan_request_id,
            source=f"rescan:{request.request_digest}",
            payload={
                "state": "scan_pending",
                "documentId": str(record.document_id),
                "documentVersion": 1,
                "objectVersionId": str(version.object_version_id),
                "scanRequestId": str(request.scan_request_id),
                "policyVersion": request.policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=principal.user_id,
        )
        return UploadSessionView(
            record,
            upload_state,
            transition,
            request,
            None,
            None,
        )

    async def request_deletion(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
        idempotency_key: str,
        reason_code: str,
    ) -> UploadSessionView:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ObjectIngestionError(
                "A valid idempotency key is required.",
                code="idempotency_key_invalid",
                status_code=422,
            )
        if not _SAFE_REASON_CODE.fullmatch(reason_code):
            raise ObjectIngestionError(
                "A valid deletion reason is required.",
                code="deletion_reason_invalid",
                status_code=422,
            )
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.MANAGE,
            lock=True,
        )
        promotion = await self.session.scalar(
            select(ObjectPromotion).where(
                ObjectPromotion.source_object_version_id == record.object_version_id
            )
        )
        object_version_id = (
            promotion.target_object_version_id if promotion else record.object_version_id
        )
        version = await self._object_version(object_version_id)
        existing = await self.session.scalar(
            select(ObjectDeletionRequest).where(
                ObjectDeletionRequest.object_version_id == object_version_id,
                ObjectDeletionRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return await self._view(record)
        latest = await self._latest_object_transition(object_version_id)
        if latest.current_state == "deleted":
            raise ObjectIngestionNotFoundError()
        now = datetime.now(UTC)
        deletion = ObjectDeletionRequest(
            deletion_request_id=uuid.uuid5(
                object_version_id,
                f"deletion:{idempotency_key}",
            ),
            object_version_id=object_version_id,
            workspace_id=workspace_id,
            requester_user_id=principal.user_id,
            idempotency_key=idempotency_key,
            reason_code=reason_code,
            trace_id=record.trace_id,
            requested_at=now,
        )
        transition = self._object_transition(
            version,
            sequence=latest.sequence + 1,
            previous=latest.current_state,
            current="deletion_requested",
            reason=reason_code,
            actor_kind="user",
            actor_user_id=principal.user_id,
            service_identity=None,
            trace_id=record.trace_id,
            now=now,
        )
        self.session.add_all((deletion, transition))
        await self.session.flush()
        audit = self._audit(
            session=record,
            action="object.deletion_request",
            outcome="succeeded",
            reason=reason_code,
            actor_user_id=principal.user_id,
            object_version_id=object_version_id,
            now=now,
        )
        self.session.add(audit)
        await self._event(
            session=record,
            event_type="object.deletion_requested",
            subject_id=object_version_id,
            source=f"deletion:{deletion.deletion_request_id}",
            payload={
                "state": "deletion_requested",
                "documentId": str(record.document_id),
                "documentVersion": 1,
                "objectVersionId": str(object_version_id),
                "policyVersion": self.settings.malware_policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=principal.user_id,
        )
        view = await self._view(record)
        return UploadSessionView(
            view.session,
            view.transition,
            transition,
            view.scan_request,
            view.scan_result,
            view.promotion,
        )

    async def clean_bytes(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
    ) -> tuple[UploadSession, StorageObjectVersion, bytes]:
        record = await self._authorized_session(
            principal=principal,
            workspace_id=workspace_id,
            canvas_id=canvas_id,
            session_id=session_id,
            level=ShareAccessLevel.VIEW,
        )
        promotion = await self.session.scalar(
            select(ObjectPromotion).where(
                ObjectPromotion.source_object_version_id == record.object_version_id
            )
        )
        if promotion is None:
            raise ObjectIngestionNotFoundError()
        version = await self._object_version(promotion.target_object_version_id)
        latest = await self._latest_object_transition(version.object_version_id)
        if latest.current_state != "clean":
            raise ObjectIngestionNotFoundError()
        content = await self.storage.read_version(
            physical_key=version.physical_key,
            provider_version_id=version.provider_version_id,
        )
        if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), version.content_sha256):
            raise ObjectIngestionError(
                "The clean object failed integrity verification.",
                code="clean_integrity_failed",
                status_code=503,
            )
        return record, version, content

    def _require_enabled(self) -> None:
        if self.settings.object_ingestion_mode == "disabled":
            raise ObjectIngestionError(
                "Secure object ingestion is disabled.",
                code="secure_ingestion_disabled",
                status_code=503,
            )

    async def _canvas(self, workspace_id: uuid.UUID, canvas_id: uuid.UUID) -> Canvas:
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if canvas is None:
            raise ObjectIngestionNotFoundError()
        return canvas

    async def _authorized_session(
        self,
        *,
        principal: Principal,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        session_id: uuid.UUID,
        level: ShareAccessLevel,
        lock: bool = False,
    ) -> UploadSession:
        query = select(UploadSession).where(
            UploadSession.session_id == session_id,
            UploadSession.workspace_id == workspace_id,
            UploadSession.canvas_id == canvas_id,
        )
        if lock:
            query = query.with_for_update()
        record = await self.session.scalar(query)
        if record is None:
            raise ObjectIngestionNotFoundError()
        access = await SharingService(self.session).evaluate_access(
            principal=principal,
            workspace_id=workspace_id,
            resource_kind=ShareResourceKind.CANVAS,
            resource_id=canvas_id,
            access_level=level,
            expected_authority_generation=record.authority_generation,
        )
        if not access.allowed or access.membership_id != record.membership_id:
            raise ObjectIngestionNotFoundError()
        return record

    async def _active_count(self, workspace_id: uuid.UUID) -> int:
        latest_sequence = (
            select(func.max(UploadSessionTransition.sequence))
            .where(UploadSessionTransition.session_id == UploadSession.session_id)
            .correlate(UploadSession)
            .scalar_subquery()
        )
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(UploadSession)
                .join(
                    UploadSessionTransition,
                    (UploadSessionTransition.session_id == UploadSession.session_id)
                    & (UploadSessionTransition.sequence == latest_sequence),
                )
                .where(
                    UploadSession.workspace_id == workspace_id,
                    UploadSessionTransition.current_state.in_(_ACTIVE_UPLOAD_STATES),
                )
            )
            or 0
        )

    async def _view(self, record: UploadSession) -> UploadSessionView:
        transition = await self._latest_upload_transition(record.session_id)
        object_transition = (
            await self._latest_object_transition(record.object_version_id)
            if await self.session.get(StorageObjectVersion, record.object_version_id)
            else None
        )
        scan_request = await self.session.scalar(
            select(MalwareScanRequest)
            .where(MalwareScanRequest.object_version_id == record.object_version_id)
            .order_by(MalwareScanRequest.requested_at.desc())
            .limit(1)
        )
        scan_result = (
            await self.session.scalar(
                select(MalwareScanResult).where(
                    MalwareScanResult.scan_request_id == scan_request.scan_request_id
                )
            )
            if scan_request
            else None
        )
        promotion = (
            await self.session.scalar(
                select(ObjectPromotion).where(
                    ObjectPromotion.scan_result_id == scan_result.scan_result_id
                )
            )
            if scan_result
            else None
        )
        if promotion is not None:
            object_transition = await self._latest_object_transition(
                promotion.target_object_version_id
            )
        return UploadSessionView(
            record,
            transition,
            object_transition,
            scan_request,
            scan_result,
            promotion,
        )

    async def _latest_upload_transition(self, session_id: uuid.UUID) -> UploadSessionTransition:
        transition = await self.session.scalar(
            select(UploadSessionTransition)
            .where(UploadSessionTransition.session_id == session_id)
            .order_by(UploadSessionTransition.sequence.desc())
            .limit(1)
        )
        if transition is None:
            raise ObjectIngestionError("The upload lifecycle evidence is incomplete.")
        return transition

    async def _latest_object_transition(
        self, object_version_id: uuid.UUID
    ) -> StorageObjectLifecycleTransition:
        transition = await self.session.scalar(
            select(StorageObjectLifecycleTransition)
            .where(StorageObjectLifecycleTransition.object_version_id == object_version_id)
            .order_by(StorageObjectLifecycleTransition.sequence.desc())
            .limit(1)
        )
        if transition is None:
            raise ObjectIngestionError("The object lifecycle evidence is incomplete.")
        return transition

    async def _object_version(self, object_version_id: uuid.UUID) -> StorageObjectVersion:
        version = await self.session.get(StorageObjectVersion, object_version_id)
        if version is None:
            raise ObjectIngestionError("The object version evidence is unavailable.")
        return version

    def _capability(self, record: UploadSession) -> str:
        payload = _canonical_json(
            {
                "exp": int(_aware_utc(record.expires_at).timestamp()),
                "method": "PUT",
                "objectVersionId": str(record.object_version_id),
                "sessionId": str(record.session_id),
                "sha256": record.expected_sha256,
                "size": record.expected_size_bytes,
            }
        ).encode()
        encoded = _b64(payload)
        signature = hmac.new(
            self.settings.upload_capability_secret.encode(),
            encoded.encode(),
            hashlib.sha256,
        ).digest()
        return f"{encoded}.{_b64(signature)}"

    def _verify_capability(self, record: UploadSession, capability: str) -> None:
        expected = self._capability(record)
        if not hmac.compare_digest(expected, capability) or not hmac.compare_digest(
            hashlib.sha256(capability.encode()).hexdigest(),
            record.capability_digest,
        ):
            raise ObjectIngestionNotFoundError()

    @staticmethod
    def _upload_transition(
        record: UploadSession,
        *,
        sequence: int,
        previous: str | None,
        current: str,
        reason: str,
        actor_kind: str,
        actor_user_id: uuid.UUID | None,
        now: datetime,
    ) -> UploadSessionTransition:
        return UploadSessionTransition(
            transition_id=uuid.uuid5(record.session_id, f"transition:{sequence}:{current}"),
            session_id=record.session_id,
            workspace_id=record.workspace_id,
            sequence=sequence,
            previous_state=previous,
            current_state=current,
            reason_code=reason,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            trace_id=record.trace_id,
            recorded_at=now,
        )

    @staticmethod
    def _version_model(
        record: UploadSession,
        stored: ProviderObjectVersion,
        *,
        now: datetime,
        security_class: str,
        object_version_id: uuid.UUID | None = None,
    ) -> StorageObjectVersion:
        return StorageObjectVersion(
            object_version_id=object_version_id or record.object_version_id,
            object_id=record.object_id,
            workspace_id=record.workspace_id,
            document_version_id=record.document_version_id,
            security_class=security_class,
            physical_key=stored.physical_key,
            provider_name=stored.provider_name,
            provider_version_id=stored.provider_version_id,
            etag=stored.etag,
            byte_size=stored.byte_size,
            content_sha256=stored.content_sha256,
            media_type=record.media_type,
            created_at=now,
        )

    @staticmethod
    def _object_transition(
        version: StorageObjectVersion,
        *,
        sequence: int,
        previous: str | None,
        current: str,
        reason: str,
        actor_kind: str,
        actor_user_id: uuid.UUID | None,
        service_identity: str | None,
        trace_id: uuid.UUID,
        now: datetime,
    ) -> StorageObjectLifecycleTransition:
        return StorageObjectLifecycleTransition(
            transition_id=uuid.uuid5(version.object_version_id, f"transition:{sequence}:{current}"),
            object_version_id=version.object_version_id,
            workspace_id=version.workspace_id,
            sequence=sequence,
            previous_state=previous,
            current_state=current,
            reason_code=reason,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            service_identity=service_identity,
            trace_id=trace_id,
            recorded_at=now,
        )

    @staticmethod
    def _audit(
        *,
        session: UploadSession,
        action: str,
        outcome: str,
        reason: str,
        actor_user_id: uuid.UUID | None,
        now: datetime,
        object_version_id: uuid.UUID | None = None,
        scan_request_id: uuid.UUID | None = None,
        scan_result_id: uuid.UUID | None = None,
        promotion_id: uuid.UUID | None = None,
    ) -> ObjectIngestionAuditEvent:
        identity = _digest(
            {
                "sessionId": str(session.session_id),
                "action": action,
                "outcome": outcome,
                "reason": reason,
                "objectVersionId": str(object_version_id) if object_version_id else None,
                "scanRequestId": str(scan_request_id) if scan_request_id else None,
                "scanResultId": str(scan_result_id) if scan_result_id else None,
                "promotionId": str(promotion_id) if promotion_id else None,
            }
        )
        return ObjectIngestionAuditEvent(
            audit_event_id=uuid.uuid5(session.trace_id, identity),
            actor_user_id=actor_user_id,
            workspace_id=session.workspace_id,
            canvas_id=session.canvas_id,
            upload_session_id=session.session_id,
            object_version_id=object_version_id,
            scan_request_id=scan_request_id,
            scan_result_id=scan_result_id,
            promotion_id=promotion_id,
            action=action,
            outcome=outcome,
            reason_code=reason,
            safe_metadata={"documentVersion": 1},
            trace_id=session.trace_id,
            recorded_at=now,
        )

    async def _event(
        self,
        *,
        session: UploadSession,
        event_type: str,
        subject_id: uuid.UUID,
        source: str,
        payload: dict[str, JsonValue],
        audit_event_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        origin_type: Literal["authenticated_user", "canonical_service"] = "authenticated_user",
    ) -> None:
        await self.events.record(
            CreateDomainEvent(
                event_type=event_type,
                user_id=session.user_id,
                workspace_id=session.workspace_id,
                canvas_id=session.canvas_id,
                subject_id=subject_id,
                actor_user_id=actor_user_id,
                source_identity=source,
                trace_id=session.trace_id,
                payload=payload,
                origin_type=origin_type,
                audit_event_id=audit_event_id,
            )
        )


class MalwareScanService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: VersionedObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage

    def _request_model(
        self,
        *,
        record: UploadSession,
        version: StorageObjectVersion,
        now: datetime,
    ) -> MalwareScanRequest:
        request_digest = _digest(
            {
                "objectVersionId": str(version.object_version_id),
                "providerVersionId": version.provider_version_id,
                "etag": version.etag,
                "sha256": version.content_sha256,
                "scannerIdentity": self.settings.malware_scanner_identity,
                "scannerVersion": self.settings.malware_scanner_version,
                "policyVersion": self.settings.malware_policy_version,
            }
        )
        request_id = uuid.uuid5(version.object_version_id, request_digest)
        return MalwareScanRequest(
            scan_request_id=request_id,
            object_version_id=version.object_version_id,
            workspace_id=version.workspace_id,
            requested_by_user_id=record.user_id,
            scanner_identity=self.settings.malware_scanner_identity,
            scanner_version=self.settings.malware_scanner_version,
            policy_version=self.settings.malware_policy_version,
            request_digest=request_digest,
            timeout_seconds=self.settings.malware_scan_timeout_seconds,
            trace_id=record.trace_id,
            requested_at=now,
            deadline_at=now + timedelta(seconds=self.settings.malware_scan_timeout_seconds),
        )

    def verify_signature(self, result: TrustedScanResult, signature: str) -> None:
        expected = hmac.new(
            self.settings.scanner_result_secret.encode(),
            _canonical_json(result.canonical_payload()).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ObjectIngestionNotFoundError()

    async def record_result(
        self,
        *,
        result: TrustedScanResult,
        signature: str,
    ) -> UploadSessionView:
        if self.settings.object_ingestion_mode == "disabled":
            raise ObjectIngestionError(
                "Secure object ingestion is disabled.",
                code="secure_ingestion_disabled",
                status_code=503,
            )
        self.verify_signature(result, signature)
        request = await self.session.scalar(
            select(MalwareScanRequest)
            .where(MalwareScanRequest.scan_request_id == result.scan_request_id)
            .with_for_update()
        )
        if request is None:
            raise ObjectIngestionNotFoundError()
        version = await self.session.get(StorageObjectVersion, request.object_version_id)
        upload = await self.session.scalar(
            select(UploadSession).where(
                UploadSession.object_version_id == request.object_version_id
            )
        )
        if version is None or upload is None:
            raise ObjectIngestionError("The scan source evidence is incomplete.")
        result_digest = _digest(result.canonical_payload())
        existing = await self.session.scalar(
            select(MalwareScanResult).where(
                MalwareScanResult.scan_request_id == request.scan_request_id
            )
        )
        if existing is not None:
            if existing.result_digest != result_digest:
                raise ObjectIngestionError(
                    "The scanner returned conflicting evidence.",
                    code="scanner_result_conflict",
                )
            return await UploadLifecycleService(
                self.session,
                settings=self.settings,
                storage=self._storage(),
            )._view(upload)
        now = datetime.now(UTC)
        latest_upload = await UploadLifecycleService(
            self.session,
            settings=self.settings,
            storage=self._storage(),
        )._latest_upload_transition(upload.session_id)
        access = await SharingService(self.session).evaluate_access(
            principal=Principal(
                user_id=upload.user_id,
                email="",
                display_name="",
                session_id=None,
                csrf_token_hash=None,
                synthetic=True,
            ),
            workspace_id=upload.workspace_id,
            resource_kind=ShareResourceKind.CANVAS,
            resource_id=upload.canvas_id,
            access_level=ShareAccessLevel.CONTRIBUTE,
            expected_authority_generation=upload.authority_generation,
        )
        if (
            latest_upload.current_state != "completed"
            or not access.allowed
            or access.membership_id != upload.membership_id
            or request.scanner_identity != self.settings.malware_scanner_identity
            or request.scanner_version != self.settings.malware_scanner_version
            or request.policy_version != self.settings.malware_policy_version
            or result.object_version_id != version.object_version_id
            or result.workspace_id != version.workspace_id
            or result.scanner_identity != request.scanner_identity
            or result.scanner_version != request.scanner_version
            or result.policy_version != request.policy_version
            or result.provider_version_id != version.provider_version_id
            or result.etag != version.etag
            or not hmac.compare_digest(result.content_sha256, version.content_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", result.provider_record_digest)
            or not _SAFE_REASON_CODE.fullmatch(result.safe_reason_code)
            or _aware_utc(result.scanned_at)
            < _aware_utc(request.requested_at) - timedelta(seconds=60)
            or _aware_utc(result.scanned_at) > now + timedelta(seconds=60)
            or _aware_utc(result.scanned_at) > _aware_utc(request.deadline_at)
            or now > _aware_utc(request.deadline_at)
            or now - _aware_utc(result.scanned_at)
            > timedelta(seconds=self.settings.malware_scan_result_max_age_seconds)
        ):
            raise ObjectIngestionError(
                "The scanner evidence does not match the immutable object.",
                code="scanner_result_mismatch",
            )
        scan_result = MalwareScanResult(
            scan_result_id=uuid.uuid5(request.scan_request_id, result_digest),
            scan_request_id=request.scan_request_id,
            object_version_id=version.object_version_id,
            workspace_id=version.workspace_id,
            outcome=result.outcome,
            scanner_identity=result.scanner_identity,
            scanner_version=result.scanner_version,
            engine_version=result.engine_version,
            signature_version=result.signature_version,
            policy_version=result.policy_version,
            provider_result_id=result.provider_result_id,
            provider_record_digest=result.provider_record_digest,
            provider_version_id=result.provider_version_id,
            etag=result.etag,
            content_sha256=result.content_sha256,
            result_digest=result_digest,
            safe_reason_code=result.safe_reason_code,
            scanned_at=_aware_utc(result.scanned_at),
            received_at=now,
        )
        self.session.add(scan_result)
        await self.session.flush()
        lifecycle = UploadLifecycleService(
            self.session,
            settings=self.settings,
            storage=self._storage(),
        )
        if result.outcome == "clean":
            promotion, object_transition = await ObjectPromotionService(
                self.session,
                settings=self.settings,
                storage=self._storage(),
            ).promote(
                upload=upload,
                source=version,
                result=scan_result,
                now=now,
            )
            event_type = "scan.passed"
            audit_reason = "clean_verdict_verified"
        else:
            latest = await lifecycle._latest_object_transition(version.object_version_id)
            object_transition = lifecycle._object_transition(
                version,
                sequence=latest.sequence + 1,
                previous=latest.current_state,
                current="rejected",
                reason=f"scan_{result.outcome}",
                actor_kind="service",
                actor_user_id=None,
                service_identity=result.scanner_identity,
                trace_id=upload.trace_id,
                now=now,
            )
            self.session.add(object_transition)
            document = await self.session.get(Document, upload.document_id)
            document_version = await self.session.get(DocumentVersion, upload.document_version_id)
            if document is None or document_version is None:
                raise ObjectIngestionError("The scan source document is unavailable.")
            document.status = "failed"
            document.processing_stage = "failed"
            document.safe_error_category = f"scan_{result.outcome}"
            document.error_message = "The document failed secure content validation."
            document_version.status = "rejected"
            promotion = None
            event_type = "scan.rejected"
            audit_reason = f"scan_{result.outcome}"
        audit = lifecycle._audit(
            session=upload,
            action="scan.result",
            outcome="succeeded",
            reason=audit_reason,
            actor_user_id=None,
            object_version_id=version.object_version_id,
            scan_request_id=request.scan_request_id,
            scan_result_id=scan_result.scan_result_id,
            promotion_id=promotion.promotion_id if promotion else None,
            now=now,
        )
        self.session.add(audit)
        await lifecycle._event(
            session=upload,
            event_type=event_type,
            subject_id=scan_result.scan_result_id,
            source=f"scanner:{result.provider_result_id}",
            payload={
                "state": object_transition.current_state,
                "documentId": str(upload.document_id),
                "documentVersion": 1,
                "objectVersionId": str(version.object_version_id),
                "scanRequestId": str(request.scan_request_id),
                "scanResultId": str(scan_result.scan_result_id),
                "outcome": result.outcome,
                "policyVersion": result.policy_version,
            },
            audit_event_id=audit.audit_event_id,
            actor_user_id=upload.user_id,
            origin_type="canonical_service",
        )
        if promotion is not None:
            await lifecycle._event(
                session=upload,
                event_type="object.promoted",
                subject_id=promotion.promotion_id,
                source=f"promotion:{promotion.target_object_version_id}",
                payload={
                    "state": "clean",
                    "documentId": str(upload.document_id),
                    "documentVersion": 1,
                    "objectVersionId": str(promotion.target_object_version_id),
                    "scanRequestId": str(request.scan_request_id),
                    "scanResultId": str(scan_result.scan_result_id),
                    "promotionId": str(promotion.promotion_id),
                    "outcome": "clean",
                    "policyVersion": result.policy_version,
                },
                audit_event_id=audit.audit_event_id,
                actor_user_id=upload.user_id,
                origin_type="canonical_service",
            )
        await TraceService(self.session).complete_trace(
            CompleteTraceInput(
                trace_id=upload.trace_id,
                event_type="object_ingestion.upload",
                actor_id=result.scanner_identity,
                actor_type="service",
                user_id=upload.user_id,
                workspace_id=upload.workspace_id,
                object_id=upload.session_id,
                object_type="upload_session",
                operation="scan_result_recorded",
                metadata={
                    "state": object_transition.current_state,
                    "outcome": result.outcome,
                    "policyVersion": result.policy_version,
                },
            )
        )
        return UploadSessionView(
            upload,
            await lifecycle._latest_upload_transition(upload.session_id),
            object_transition,
            request,
            scan_result,
            promotion,
        )

    def _storage(self) -> VersionedObjectStorage:
        if self.storage is None:
            raise ObjectIngestionError(
                "The secure object store is unavailable.",
                code="object_store_unavailable",
                status_code=503,
            )
        return self.storage


class ObjectPromotionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        storage: VersionedObjectStorage,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage

    async def promote(
        self,
        *,
        upload: UploadSession,
        source: StorageObjectVersion,
        result: MalwareScanResult,
        now: datetime,
    ) -> tuple[ObjectPromotion, StorageObjectLifecycleTransition]:
        existing = await self.session.scalar(
            select(ObjectPromotion).where(ObjectPromotion.scan_result_id == result.scan_result_id)
        )
        lifecycle = UploadLifecycleService(
            self.session,
            settings=self.settings,
            storage=self.storage,
        )
        if existing is not None:
            return (
                existing,
                await lifecycle._latest_object_transition(existing.target_object_version_id),
            )
        source_bytes = await self.storage.read_version(
            physical_key=source.physical_key,
            provider_version_id=source.provider_version_id,
        )
        if not hmac.compare_digest(
            hashlib.sha256(source_bytes).hexdigest(),
            source.content_sha256,
        ):
            raise ObjectIngestionError(
                "The quarantine object changed before promotion.",
                code="promotion_source_mismatch",
            )
        target_id = uuid.uuid5(result.scan_result_id, "clean-object-version")
        target_provider = await self.storage.copy_immutable(
            source=ProviderObjectVersion(
                physical_key=source.physical_key,
                provider_name=source.provider_name,
                provider_version_id=source.provider_version_id,
                etag=source.etag,
                byte_size=source.byte_size,
                content_sha256=source.content_sha256,
            ),
            target_security_class="clean",
            object_id=source.object_id,
            target_object_version_id=target_id,
        )
        target_bytes = await self.storage.read_version(
            physical_key=target_provider.physical_key,
            provider_version_id=target_provider.provider_version_id,
        )
        target_sha256 = hashlib.sha256(target_bytes).hexdigest()
        if not hmac.compare_digest(target_sha256, source.content_sha256):
            raise ObjectIngestionError(
                "The promoted object checksum does not match quarantine.",
                code="promotion_target_mismatch",
            )
        target = lifecycle._version_model(
            upload,
            target_provider,
            now=now,
            security_class="clean",
            object_version_id=target_id,
        )
        target_transition = lifecycle._object_transition(
            target,
            sequence=0,
            previous=None,
            current="clean",
            reason="clean_copy_verified",
            actor_kind="service",
            actor_user_id=None,
            service_identity=self.settings.object_promotion_service_identity,
            trace_id=upload.trace_id,
            now=now,
        )
        source_latest = await lifecycle._latest_object_transition(source.object_version_id)
        source_transition = lifecycle._object_transition(
            source,
            sequence=source_latest.sequence + 1,
            previous=source_latest.current_state,
            current="retained",
            reason="clean_copy_promoted",
            actor_kind="service",
            actor_user_id=None,
            service_identity=self.settings.object_promotion_service_identity,
            trace_id=upload.trace_id,
            now=now,
        )
        promotion = ObjectPromotion(
            promotion_id=uuid.uuid5(result.scan_result_id, "promotion"),
            scan_result_id=result.scan_result_id,
            source_object_version_id=source.object_version_id,
            target_object_version_id=target.object_version_id,
            workspace_id=source.workspace_id,
            source_sha256=source.content_sha256,
            target_sha256=target_sha256,
            service_identity=self.settings.object_promotion_service_identity,
            trace_id=upload.trace_id,
            promoted_at=now,
        )
        document = await self.session.get(Document, upload.document_id)
        document_version = await self.session.get(DocumentVersion, upload.document_version_id)
        if document is None or document_version is None:
            raise ObjectIngestionError("The promoted document source is unavailable.")
        document_file = await self.session.scalar(
            select(DocumentFile).where(DocumentFile.document_id == document.id)
        )
        if document_file is None:
            document_file = DocumentFile(
                document_id=document.id,
                storage_key=target.physical_key,
                byte_size=target.byte_size,
                sha256=target.content_sha256,
                media_type=target.media_type,
            )
            self.session.add(document_file)
        else:
            document_file.storage_key = target.physical_key
            document_file.byte_size = target.byte_size
            document_file.sha256 = target.content_sha256
            document_file.media_type = target.media_type
        document_version.storage_key = target.physical_key
        document_version.status = "uploaded"
        document.status = "queued"
        document.processing_stage = "queued"
        document.safe_error_category = None
        document.error_message = None
        self.session.add(target)
        await self.session.flush()
        self.session.add_all((target_transition, source_transition, promotion))
        await self.session.flush()
        return promotion, target_transition


class ObjectReconciler:
    """Bounded database-side expiry; provider cleanup stays exact-version only."""

    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def expire_sessions(self, *, now: datetime | None = None, limit: int = 100) -> int:
        current = _aware_utc(now or datetime.now(UTC))
        sessions = list(
            (
                await self.session.scalars(
                    select(UploadSession)
                    .where(UploadSession.expires_at <= current)
                    .order_by(UploadSession.expires_at)
                    .limit(max(1, min(limit, 500)))
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        service = UploadLifecycleService(
            self.session,
            settings=self.settings,
            storage=cast(VersionedObjectStorage, None),
        )
        expired = 0
        for record in sessions:
            latest = await service._latest_upload_transition(record.session_id)
            if latest.current_state in _TERMINAL_UPLOAD_STATES:
                continue
            self.session.add(
                service._upload_transition(
                    record,
                    sequence=latest.sequence + 1,
                    previous=latest.current_state,
                    current="expired",
                    reason="session_expired",
                    actor_kind="service",
                    actor_user_id=None,
                    now=current,
                )
            )
            version = await self.session.get(StorageObjectVersion, record.object_version_id)
            if version is not None:
                object_latest = await service._latest_object_transition(version.object_version_id)
                if object_latest.current_state not in _TERMINAL_OBJECT_STATES:
                    self.session.add(
                        service._object_transition(
                            version,
                            sequence=object_latest.sequence + 1,
                            previous=object_latest.current_state,
                            current="error",
                            reason="session_expired",
                            actor_kind="service",
                            actor_user_id=None,
                            service_identity="mobius-object-reconciler",
                            trace_id=record.trace_id,
                            now=current,
                        )
                    )
            expired += 1
        return expired

    async def expire_scan_requests(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> int:
        current = _aware_utc(now or datetime.now(UTC))
        requests = list(
            (
                await self.session.scalars(
                    select(MalwareScanRequest)
                    .where(
                        MalwareScanRequest.deadline_at <= current,
                        ~MalwareScanRequest.scan_request_id.in_(
                            select(MalwareScanResult.scan_request_id)
                        ),
                    )
                    .order_by(MalwareScanRequest.deadline_at)
                    .limit(max(1, min(limit, 500)))
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        service = UploadLifecycleService(
            self.session,
            settings=self.settings,
            storage=cast(VersionedObjectStorage, None),
        )
        expired = 0
        for request in requests:
            version = await self.session.get(StorageObjectVersion, request.object_version_id)
            if version is None:
                continue
            latest = await service._latest_object_transition(version.object_version_id)
            if latest.current_state != "scan_pending":
                continue
            upload = await self.session.scalar(
                select(UploadSession).where(
                    UploadSession.object_version_id == request.object_version_id
                )
            )
            if upload is None:
                continue
            self.session.add(
                service._object_transition(
                    version,
                    sequence=latest.sequence + 1,
                    previous=latest.current_state,
                    current="error",
                    reason="scan_timeout",
                    actor_kind="service",
                    actor_user_id=None,
                    service_identity="mobius-object-reconciler",
                    trace_id=upload.trace_id,
                    now=current,
                )
            )
            document = await self.session.get(Document, upload.document_id)
            document_version = await self.session.get(DocumentVersion, upload.document_version_id)
            if document is not None:
                document.status = "failed"
                document.processing_stage = "failed"
                document.safe_error_category = "scan_timeout"
                document.error_message = "Secure content validation timed out."
            if document_version is not None:
                document_version.status = "rejected"
            expired += 1
        return expired


def scanner_result_signature(result: TrustedScanResult, secret: str) -> str:
    return hmac.new(
        secret.encode(),
        _canonical_json(result.canonical_payload()).encode(),
        hashlib.sha256,
    ).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "MalwareScanService",
    "ObjectIngestionError",
    "ObjectIngestionNotFoundError",
    "ObjectPromotionService",
    "ObjectReconciler",
    "TrustedScanResult",
    "UploadLifecycleService",
    "UploadSessionView",
    "scanner_result_signature",
]

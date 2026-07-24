from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import (
    AIClaim,
    AIExecutionChunk,
    AIExecutionCitation,
    AIExecutionNode,
    AIRequest,
    AIResponse,
    Canvas,
    CanvasDocumentNode,
    CanvasNode,
    Citation,
    Document,
    DocumentChunk,
    DocumentVersion,
    UsageRecord,
    Workspace,
)
from opencanvas_api.services.agents.contracts import (
    AgentRole,
    ApprovalDecision,
    ApprovalRecord,
    Capability,
    CapabilityGrant,
    ContextResource,
    ContextSnapshot,
    ExecutionRecord,
    ExecutionStateRecord,
    ExecutionStatus,
    PlanAction,
    PlanSnapshot,
    ResourceKind,
    ResourceScope,
    RiskClass,
    contract_digest,
)
from opencanvas_api.services.agents.execution import (
    AuthorityPreflightDenied,
    ControlledAction,
    ControlledExecutionLifecycle,
    ControlledExecutionRequest,
    ExecutionAuthorityPreflight,
    ExecutionRequestRegistry,
    ImmutableContextDenied,
    ImmutableSelectedContextResolver,
    ResolvedContextResource,
    ResolvedSelectedContext,
    ResultAcceptanceRequest,
    resolved_resource_digest,
)
from opencanvas_api.services.agents.persistence import (
    AgentPersistenceNotFound,
    AgentStateTransitionError,
    ControlledAgentRepository,
)
from opencanvas_api.services.ai import (
    AIProvider,
    AIProviderError,
    GroundedAIResult,
    GroundedCitation,
    GroundedSource,
    model_configuration,
    validate_grounded_result,
)
from opencanvas_api.services.context import ContextBundle
from opencanvas_api.services.trace import (
    CompleteTraceInput,
    FailTraceInput,
    StartTraceInput,
    TraceErrorInfo,
    TraceService,
)


class ControlledDraftError(RuntimeError):
    """Stable, safe application-layer failure for a controlled draft."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ControlledDraftCitation:
    source_id: str
    document_id: uuid.UUID
    document_version: int
    chunk_id: uuid.UUID
    claim: str
    quote: str


@dataclass(frozen=True, slots=True)
class ControlledDraftResult:
    execution_id: uuid.UUID
    trace_id: uuid.UUID
    response_id: uuid.UUID
    text: str
    insufficient_evidence: bool
    citations: tuple[ControlledDraftCitation, ...]
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class PreparedControlledDraft:
    request: ControlledExecutionRequest
    created: bool


class ControlledGroundedDraftService:
    """Synchronous Terra bridge for one already-authorized controlled draft.

    The service intentionally performs no workspace mutation.  Its only durable output is an
    evidence-backed AI execution/Trace record, and publication is accepted exclusively through
    the Sol lifecycle boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        provider: AIProvider,
        settings: Settings,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings
        self.repository = ControlledAgentRepository(session)
        self._now = now or (lambda: datetime.now(UTC))

    async def prepare(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        workspace_id: uuid.UUID,
        canvas_id: uuid.UUID,
        selected_node_ids: list[uuid.UUID],
        instruction: str,
        idempotency_key: str,
        correlation_id: str,
        client_request_id: str | None = None,
    ) -> PreparedControlledDraft:
        """Create or reload the one server-owned authority package for a user request."""

        execution_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"opencanvas:controlled-draft:{authenticated_user_id}:{workspace_id}:"
            f"{canvas_id}:{idempotency_key}",
        )
        try:
            inspection = await self.repository.inspect_execution(
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                execution_id=execution_id,
                limit=100,
                offset=0,
            )
        except AgentPersistenceNotFound:
            inspection = None
        if inspection is not None:
            stored_context = self.repository._load_contract(
                ContextSnapshot,
                inspection.context.payload,
                inspection.context.payload_digest,
            )
            stored_node_ids = tuple(
                resource.scope.resource_id
                for resource in stored_context.resources
                if resource.scope.kind is ResourceKind.NODE
            )
            if stored_node_ids != tuple(selected_node_ids):
                raise ControlledDraftError(
                    "idempotency_conflict",
                    "The idempotency key was already used for a different request.",
                )
            stored_grant = next(
                (row for row in inspection.grants if row.grant_id == inspection.execution.grant_id),
                None,
            )
            stored_approval = next(
                (
                    row
                    for row in inspection.approvals
                    if row.grant_id == inspection.execution.grant_id
                ),
                None,
            )
            if stored_grant is None or stored_approval is None:
                raise ControlledDraftError(
                    "agent_authorization_denied", "The controlled execution is not available."
                )
            return PreparedControlledDraft(
                request=ControlledExecutionRequest(
                    user_id=authenticated_user_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    execution_id=execution_id,
                    context_snapshot_id=inspection.context.snapshot_id,
                    expected_context_digest=inspection.context.payload_digest,
                    plan_id=inspection.plan.plan_id,
                    expected_plan_digest=inspection.plan.payload_digest,
                    action=ControlledAction.GENERATE_GROUNDED_DRAFT,
                    grant_id=stored_grant.grant_id,
                    approval_id=stored_approval.approval_id,
                    idempotency_key=idempotency_key,
                    instruction=instruction,
                    client_request_id=client_request_id,
                    correlation_id=correlation_id,
                ),
                created=False,
            )

        now = self._now()
        canvas = await self.session.scalar(
            select(Canvas)
            .join(Workspace, Workspace.id == Canvas.workspace_id)
            .where(
                Canvas.id == canvas_id,
                Canvas.workspace_id == workspace_id,
                Workspace.owner_id == authenticated_user_id,
                Workspace.deleted_at.is_(None),
                Workspace.lifecycle_state != "deleted",
            )
        )
        if canvas is None:
            raise ControlledDraftError("canvas_not_found", "Canvas not found.", status_code=404)
        nodes = tuple(
            (
                await self.session.scalars(
                    select(CanvasNode).where(
                        CanvasNode.canvas_id == canvas_id,
                        CanvasNode.id.in_(selected_node_ids),
                    )
                )
            ).all()
        )
        by_id = {node.id: node for node in nodes}
        if len(by_id) != len(selected_node_ids):
            raise ControlledDraftError(
                "invalid_selected_nodes",
                "Every selected node must belong to this canvas.",
                status_code=400,
            )
        ordered_nodes = [by_id[node_id] for node_id in selected_node_ids]
        resources = [
            ResolvedContextResource(
                scope=ResourceScope(
                    kind=ResourceKind.CANVAS, resource_id=canvas.id, version=canvas.revision
                ),
                canvas_id=canvas.id,
                title=canvas.name,
                content=f"Canvas revision {canvas.revision}",
            )
        ]
        for node in ordered_nodes:
            resources.append(
                ResolvedContextResource(
                    scope=ResourceScope(
                        kind=ResourceKind.NODE, resource_id=node.id, version=node.revision
                    ),
                    canvas_id=canvas.id,
                    title=node.title,
                    content=node.text,
                )
            )
        document_node_ids = [node.id for node in ordered_nodes if node.type == "document"]
        references = (
            tuple(
                (
                    await self.session.scalars(
                        select(CanvasDocumentNode).where(
                            CanvasDocumentNode.canvas_id == canvas_id,
                            CanvasDocumentNode.node_id.in_(document_node_ids),
                        )
                    )
                ).all()
            )
            if document_node_ids
            else ()
        )
        if len(references) != len(document_node_ids):
            raise ControlledDraftError(
                "document_reference_missing",
                "A selected document is missing its stored-document reference.",
            )
        remaining_chunks = self.settings.document_retrieval_top_k
        for reference in references:
            document = await self.session.scalar(
                select(Document).where(
                    Document.id == reference.document_id,
                    Document.canvas_id == canvas_id,
                    Document.status == "ready",
                    Document.deleted_at.is_(None),
                )
            )
            if document is None:
                raise ControlledDraftError(
                    "documents_not_ready",
                    "Selected documents must finish processing successfully before querying.",
                )
            version = await self.session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version == document.current_version,
                    DocumentVersion.status == "ready",
                    DocumentVersion.deleted_at.is_(None),
                )
            )
            if version is None or not version.extracted_text:
                raise ControlledDraftError(
                    "immutable_context_unavailable", "The selected evidence is unavailable."
                )
            resources.append(
                ResolvedContextResource(
                    scope=ResourceScope(
                        kind=ResourceKind.DOCUMENT_VERSION,
                        resource_id=version.id,
                        version=version.version,
                    ),
                    canvas_id=canvas.id,
                    title=version.file_name,
                    content=version.extracted_text,
                    document_id=document.id,
                    document_version=version.version,
                )
            )
            if remaining_chunks:
                chunks = tuple(
                    (
                        await self.session.scalars(
                            select(DocumentChunk)
                            .where(
                                DocumentChunk.document_id == document.id,
                                DocumentChunk.document_version == version.version,
                            )
                            .order_by(DocumentChunk.chunk_index)
                            .limit(remaining_chunks)
                        )
                    ).all()
                )
                remaining_chunks -= len(chunks)
                resources.extend(
                    ResolvedContextResource(
                        scope=ResourceScope(
                            kind=ResourceKind.CHUNK,
                            resource_id=chunk.id,
                            version=chunk.document_version,
                        ),
                        canvas_id=canvas.id,
                        title=chunk.heading or f"Chunk {chunk.chunk_index + 1}",
                        content=chunk.content,
                        document_id=document.id,
                        document_version=chunk.document_version,
                    )
                    for chunk in chunks
                )
        context = ContextSnapshot(
            snapshot_id=uuid.uuid4(),
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            captured_at=now,
            resources=tuple(
                ContextResource(scope=item.scope, content_digest=resolved_resource_digest(item))
                for item in resources
            ),
        )
        action_scope = ResourceScope(kind=ResourceKind.CANVAS, resource_id=canvas_id)
        plan = PlanSnapshot(
            plan_id=uuid.uuid4(),
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            role=AgentRole.DRAFTING_ASSISTANT,
            created_at=now,
            actions=(
                PlanAction(
                    action_id=uuid.uuid4(),
                    ordinal=0,
                    capability=Capability.DRAFT_ANSWER_CREATE,
                    resource=action_scope,
                    risk_class=RiskClass.R1_DRAFT,
                ),
            ),
        )
        context_digest = contract_digest(context)
        plan_digest = contract_digest(plan)
        approval_id = uuid.uuid4()
        grant = CapabilityGrant(
            grant_id=uuid.uuid4(),
            policy_version="controlled-agent-policy-v1",
            issuing_service="controlled-grounded-draft-service",
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            role=AgentRole.DRAFTING_ASSISTANT,
            capabilities=(Capability.DRAFT_ANSWER_CREATE,),
            resources=(action_scope,),
            context_digest=context_digest,
            plan_digest=plan_digest,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
            approval_required=True,
            approval_id=approval_id,
        )
        approval = ApprovalRecord(
            approval_id=approval_id,
            session_id=uuid.uuid4(),
            policy_version=grant.policy_version,
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            grant_id=grant.grant_id,
            decision=ApprovalDecision.APPROVED,
            capabilities=grant.capabilities,
            resources=grant.resources,
            context_digest=context_digest,
            plan_digest=plan_digest,
            decided_at=now,
            expires_at=grant.expires_at,
        )
        execution = ExecutionRecord(
            execution_id=execution_id,
            user_id=authenticated_user_id,
            workspace_id=workspace_id,
            role=AgentRole.DRAFTING_ASSISTANT,
            context_snapshot_id=context.snapshot_id,
            context_digest=context_digest,
            plan_id=plan.plan_id,
            plan_digest=plan_digest,
            grant_id=grant.grant_id,
            created_at=now,
        )
        try:
            await self.repository.append_bundle(
                execution=execution,
                context=context,
                plan=plan,
                grant=grant,
                approval=approval,
            )
        except IntegrityError:
            await self.session.rollback()
            return await self.prepare(
                authenticated_user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                selected_node_ids=selected_node_ids,
                instruction=instruction,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                client_request_id=client_request_id,
            )
        return PreparedControlledDraft(
            request=ControlledExecutionRequest(
                user_id=authenticated_user_id,
                workspace_id=workspace_id,
                canvas_id=canvas_id,
                execution_id=execution_id,
                context_snapshot_id=context.snapshot_id,
                expected_context_digest=context_digest,
                plan_id=plan.plan_id,
                expected_plan_digest=plan_digest,
                action=ControlledAction.GENERATE_GROUNDED_DRAFT,
                grant_id=grant.grant_id,
                approval_id=approval_id,
                idempotency_key=idempotency_key,
                instruction=instruction,
                client_request_id=client_request_id,
                correlation_id=correlation_id,
            ),
            created=True,
        )

    async def execute(
        self,
        *,
        authenticated_user_id: uuid.UUID,
        request: ControlledExecutionRequest,
    ) -> ControlledDraftResult:
        if authenticated_user_id != request.user_id:
            raise ControlledDraftError(
                "agent_authorization_denied", "The controlled execution is not available."
            )
        started_at = self._now()
        reservation = await ExecutionRequestRegistry(self.session).reserve(
            authenticated_user_id=authenticated_user_id,
            request=request,
            created_at=started_at,
        )
        if not reservation.created:
            return await self._existing_result(request.execution_id)

        await self._enforce_workspace_budget(request.workspace_id)
        try:
            authorized = await ExecutionAuthorityPreflight(self.session).authorize(
                authenticated_user_id=authenticated_user_id,
                request=request,
                evaluated_at=started_at,
            )
            resolved = await ImmutableSelectedContextResolver(self.session).resolve(
                authenticated_user_id=authenticated_user_id,
                authorized=authorized,
            )
        except AuthorityPreflightDenied as exc:
            raise ControlledDraftError(
                "agent_authorization_denied", "The controlled execution was not authorized."
            ) from exc
        except ImmutableContextDenied as exc:
            raise ControlledDraftError(
                "immutable_context_unavailable",
                "The selected evidence changed or is no longer available.",
            ) from exc

        await self._append_running_states(request, started_at)
        trace_id = uuid.uuid4()
        request_record = AIRequest(
            id=request.execution_id,
            trace_id=trace_id,
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            canvas_id=request.canvas_id,
            instruction=self._instruction_from_request(request),
            selected_node_ids=[
                str(resource.scope.resource_id)
                for resource in resolved.resources
                if resource.scope.kind is ResourceKind.NODE
            ],
            context_snapshot=self._context_snapshot(resolved),
            provider=self.provider.name,
            model=self.provider.model,
            status="pending",
            model_configuration={
                **model_configuration(self.provider, grounded=True),
                "controlledExecutionId": str(request.execution_id),
                "contextSnapshotId": str(resolved.snapshot_id),
                "contextDigest": resolved.context_digest,
                "resolutionDigest": resolved.resolution_digest,
            },
            retrieval_configuration={
                "mode": "immutable_selected_chunks",
                "candidateLimit": self.settings.document_retrieval_top_k,
                "embeddingProvider": None,
                "embeddingModel": None,
            },
            prompt_version="grounded-block-citations-v1",
            provider_configuration_version=getattr(
                self.provider, "configuration_version", "unspecified-provider-contract-v1"
            ),
            execution_mode="controlled_immutable_context",
            started_at=started_at,
        )
        self.session.add(request_record)
        # Snapshot tables intentionally use scalar foreign keys rather than ORM relationships.
        # Flush the authoritative execution record before adding its immutable evidence rows.
        await self.session.flush()
        self.session.add_all(self._execution_nodes(request.execution_id, resolved))
        sources = self._grounded_sources(resolved)
        self.session.add_all(self._execution_chunks(request.execution_id, sources))
        trace_service = TraceService(self.session)
        await trace_service.start_trace(
            StartTraceInput(
                trace_id=trace_id,
                parent_trace_id=None,
                event_type="controlled_agent.execution",
                actor_id=str(authenticated_user_id),
                actor_type="user",
                user_id=authenticated_user_id,
                workspace_id=request.workspace_id,
                object_id=request.execution_id,
                object_type="controlled_agent_execution",
                operation="generate_grounded_draft",
                metadata={
                    "canvasId": str(request.canvas_id),
                    "contextSnapshotId": str(resolved.snapshot_id),
                    "contextDigest": resolved.context_digest,
                    "resolutionDigest": resolved.resolution_digest,
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "providerConfigurationVersion": getattr(
                        self.provider, "configuration_version", "unspecified-provider-contract-v1"
                    ),
                },
            )
        )
        await self.session.commit()

        running_state_id = await self._running_state_id(request)
        generated_at = self._now()
        monotonic_started = time.perf_counter()
        try:
            result = await self._generate(request, resolved, sources)
        except AIProviderError as exc:
            safe_message = "The configured reasoning provider could not complete the draft."
            await self._record_failure(
                request=request,
                trace_id=trace_id,
                started_at=started_at,
                generated_at=generated_at,
                code="provider_failure",
                message=safe_message,
            )
            raise ControlledDraftError("provider_failure", safe_message) from exc

        response_text = self._response_text(result)
        result_digest = self._result_digest(result, sources)
        acceptance = await ControlledExecutionLifecycle(self.session).accept_result(
            authenticated_user_id=authenticated_user_id,
            authorized=authorized,
            resolved=resolved,
            request=ResultAcceptanceRequest(
                delivery_id=uuid.uuid4(),
                execution_id=request.execution_id,
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                running_state_id=running_state_id,
                context_snapshot_id=resolved.snapshot_id,
                context_digest=resolved.context_digest,
                resolution_digest=resolved.resolution_digest,
                result_digest=result_digest,
                produced_at=generated_at,
            ),
            accepted_at=self._now(),
            trace_id=trace_id,
        )
        if not acceptance.accepted:
            await self.session.execute(
                update(AIRequest)
                .where(AIRequest.id == request.execution_id)
                .values(
                    status="failed",
                    error="The controlled draft result was not accepted.",
                    safe_error_category=acceptance.reason_code,
                    completed_at=self._now(),
                    updated_at=func.now(),
                )
            )
            await trace_service.fail_trace(
                FailTraceInput(
                    trace_id=trace_id,
                    parent_trace_id=None,
                    event_type="controlled_agent.execution",
                    actor_id=str(authenticated_user_id),
                    actor_type="user",
                    user_id=authenticated_user_id,
                    workspace_id=request.workspace_id,
                    object_id=request.execution_id,
                    object_type="controlled_agent_execution",
                    operation="publish_grounded_draft",
                    metadata={"resultDigest": result_digest},
                    error=TraceErrorInfo(
                        code=acceptance.reason_code,
                        message="The controlled draft result was not accepted.",
                    ),
                )
            )
            await self.session.commit()
            raise ControlledDraftError(
                "result_not_accepted", "The controlled draft result was not accepted."
            )

        response = AIResponse(
            request_id=request.execution_id,
            node_id=None,
            content=response_text,
            provider_response_id=result.provider_response_id,
            grounded=bool(result.citations) and not result.insufficient_evidence,
            insufficient_evidence=result.insufficient_evidence,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )
        self.session.add(response)
        await self.session.flush()
        citations = self._citations(response.id, result.citations, sources)
        self.session.add_all(citations)
        self.session.add_all(
            self._execution_citations(request.execution_id, response.id, result.citations, sources)
        )
        self.session.add_all(self._claims(request.execution_id, response.id, result, sources))
        input_tokens = result.input_tokens or 0
        output_tokens = result.output_tokens or 0
        estimated_cost = self._estimated_cost(input_tokens, output_tokens)
        self.session.add(
            UsageRecord(
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                operation="controlled_agent_draft",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=estimated_cost,
                metadata_payload={
                    "executionId": str(request.execution_id),
                    "provider": self.provider.name,
                    "model": self.provider.model,
                },
            )
        )
        latency_ms = int((time.perf_counter() - monotonic_started) * 1_000)
        await self.session.execute(
            update(AIRequest)
            .where(AIRequest.id == request.execution_id)
            .values(
                status="completed",
                completed_at=self._now(),
                latency_ms=latency_ms,
                estimated_cost_usd=estimated_cost,
                updated_at=func.now(),
            )
        )
        await trace_service.complete_trace(
            CompleteTraceInput(
                trace_id=trace_id,
                parent_trace_id=None,
                event_type="controlled_agent.execution",
                actor_id=str(authenticated_user_id),
                actor_type="user",
                user_id=authenticated_user_id,
                workspace_id=request.workspace_id,
                object_id=request.execution_id,
                object_type="controlled_agent_execution",
                operation="publish_grounded_draft",
                metadata={
                    "requestId": str(request.execution_id),
                    "responseId": str(response.id),
                    "contextSnapshotId": str(resolved.snapshot_id),
                    "contextDigest": resolved.context_digest,
                    "resolutionDigest": resolved.resolution_digest,
                    "citationValidation": "passed",
                    "insufficientEvidence": result.insufficient_evidence,
                    "citations": [citation.source_id for citation in result.citations],
                    "inputTokens": result.input_tokens,
                    "outputTokens": result.output_tokens,
                    "totalTokens": result.total_tokens,
                    "latencyMs": latency_ms,
                    "estimatedCostUsd": estimated_cost,
                },
            )
        )
        await self.session.commit()
        return ControlledDraftResult(
            execution_id=request.execution_id,
            trace_id=trace_id,
            response_id=response.id,
            text=response_text,
            insufficient_evidence=result.insufficient_evidence,
            citations=tuple(
                ControlledDraftCitation(
                    source_id=citation.identifier,
                    document_id=citation.document_id,
                    document_version=citation.document_version,
                    chunk_id=citation.chunk_id,
                    claim=citation.claim,
                    quote=citation.quote,
                )
                for citation in citations
            ),
        )

    async def _existing_result(self, execution_id: uuid.UUID) -> ControlledDraftResult:
        request = await self.session.get(AIRequest, execution_id)
        response = await self.session.scalar(
            select(AIResponse).where(AIResponse.request_id == execution_id)
        )
        if request is None or response is None or request.status != "completed":
            raise ControlledDraftError(
                "execution_in_progress", "The controlled execution is already in progress."
            )
        rows = tuple(
            (
                await self.session.scalars(
                    select(Citation)
                    .where(Citation.ai_response_id == response.id)
                    .order_by(Citation.ordinal)
                )
            ).all()
        )
        return ControlledDraftResult(
            execution_id=execution_id,
            trace_id=request.trace_id,
            response_id=response.id,
            text=response.content,
            insufficient_evidence=response.insufficient_evidence,
            citations=tuple(
                ControlledDraftCitation(
                    source_id=row.identifier,
                    document_id=row.document_id,
                    document_version=row.document_version,
                    chunk_id=row.chunk_id,
                    claim=row.claim,
                    quote=row.quote,
                )
                for row in rows
            ),
            duplicate=True,
        )

    async def _enforce_workspace_budget(self, workspace_id: uuid.UUID) -> None:
        month_start = self._now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = await self.session.scalar(
            select(
                func.coalesce(
                    func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens),
                    0,
                )
            ).where(UsageRecord.workspace_id == workspace_id, UsageRecord.created_at >= month_start)
        )
        if int(spent or 0) >= self.settings.monthly_token_budget_per_workspace:
            raise ControlledDraftError(
                "workspace_token_budget_exhausted",
                "This workspace has reached its monthly AI token budget.",
                status_code=429,
            )

    async def _append_running_states(
        self, request: ControlledExecutionRequest, recorded_at: datetime
    ) -> None:
        for status in (ExecutionStatus.PROPOSED, ExecutionStatus.READY, ExecutionStatus.RUNNING):
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=request.execution_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    status=status,
                    recorded_at=recorded_at,
                )
            )

    async def _generate(
        self,
        request: ControlledExecutionRequest,
        resolved: ResolvedSelectedContext,
        sources: list[GroundedSource],
    ) -> GroundedAIResult:
        if not sources:
            return GroundedAIResult(
                text="The selected sources lack sufficient evidence to answer this question.",
                insufficient_evidence=True,
                citations=[],
                general_analysis=None,
                provider_response_id=None,
            )
        result = await self.provider.generate_grounded(
            self._instruction_from_request(request), self._notes_context(resolved), sources
        )
        return validate_grounded_result(result, sources)

    async def _running_state_id(self, request: ControlledExecutionRequest) -> uuid.UUID:
        state = await self.repository.current_state(
            user_id=request.user_id,
            workspace_id=request.workspace_id,
            execution_id=request.execution_id,
        )
        if state is None or state.status != ExecutionStatus.RUNNING.value:
            raise ControlledDraftError(
                "execution_not_running", "The controlled execution is not running."
            )
        return state.state_id

    async def _record_failure(
        self,
        *,
        request: ControlledExecutionRequest,
        trace_id: uuid.UUID,
        started_at: datetime,
        generated_at: datetime,
        code: str,
        message: str,
    ) -> None:
        latency_ms = max(0, int((generated_at - started_at).total_seconds() * 1_000))
        try:
            await self.repository.append_state(
                ExecutionStateRecord(
                    state_id=uuid.uuid4(),
                    execution_id=request.execution_id,
                    user_id=request.user_id,
                    workspace_id=request.workspace_id,
                    status=ExecutionStatus.FAILED,
                    recorded_at=generated_at,
                    safe_reason_code=code,
                )
            )
        except AgentStateTransitionError:
            current = await self.repository.current_state(
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                execution_id=request.execution_id,
            )
            if current is None or current.status != ExecutionStatus.CANCELLED.value:
                raise
        await self.session.execute(
            update(AIRequest)
            .where(AIRequest.id == request.execution_id)
            .values(
                status="failed",
                error=message,
                safe_error_category=code,
                completed_at=generated_at,
                latency_ms=latency_ms,
                updated_at=func.now(),
            )
        )
        await TraceService(self.session).fail_trace(
            FailTraceInput(
                trace_id=trace_id,
                parent_trace_id=None,
                event_type="controlled_agent.execution",
                actor_id=str(request.user_id),
                actor_type="user",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_id=request.execution_id,
                object_type="controlled_agent_execution",
                operation="generate_grounded_draft",
                metadata={"latencyMs": latency_ms},
                error=TraceErrorInfo(code=code, message=message),
            )
        )
        await self.session.commit()

    def _instruction_from_request(self, request: ControlledExecutionRequest) -> str:
        return request.client_request_id or "Create a grounded draft from the selected evidence."

    def _notes_context(self, resolved: ResolvedSelectedContext) -> ContextBundle:
        entries = [
            resource for resource in resolved.resources if resource.scope.kind is ResourceKind.NODE
        ]
        remaining = self.settings.ai_context_character_limit
        snapshot: list[dict[str, str]] = []
        rendered: list[str] = []
        for resource in entries:
            title = resource.title[:500]
            prefix = f"Node\nTitle: {title}\nContent:\n"
            text = resource.content[: max(0, remaining - len(prefix))]
            remaining -= len(prefix) + len(text)
            snapshot.append(
                {"nodeId": str(resource.scope.resource_id), "title": title, "text": text}
            )
            rendered.append(prefix + text)
            if remaining <= 0:
                break
        return ContextBundle(
            node_ids=[resource.scope.resource_id for resource in entries],
            snapshot=snapshot,
            rendered="\n\n".join(rendered),
        )

    @staticmethod
    def _grounded_sources(resolved: ResolvedSelectedContext) -> list[GroundedSource]:
        sources: list[GroundedSource] = []
        for rank, resource in enumerate(
            (item for item in resolved.resources if item.scope.kind is ResourceKind.CHUNK), start=1
        ):
            if resource.document_id is None or resource.document_version is None:
                raise ControlledDraftError(
                    "immutable_context_unavailable", "The selected evidence is incomplete."
                )
            sources.append(
                GroundedSource(
                    source_id=f"chunk:{resource.scope.resource_id}",
                    chunk_id=resource.scope.resource_id,
                    document_id=resource.document_id,
                    document_title=resource.title,
                    text=resource.content,
                    page_number=None,
                    heading=resource.title,
                    chunk_index=rank - 1,
                    char_start=0,
                    char_end=len(resource.content),
                    score=1.0,
                    document_version=resource.document_version,
                )
            )
        return sources

    @staticmethod
    def _context_snapshot(resolved: ResolvedSelectedContext) -> list[dict[str, str]]:
        return [
            {
                "resourceId": str(resource.scope.resource_id),
                "resourceKind": resource.scope.kind.value,
                "title": resource.title,
                "text": resource.content,
            }
            for resource in resolved.resources
        ]

    @staticmethod
    def _execution_nodes(
        execution_id: uuid.UUID, resolved: ResolvedSelectedContext
    ) -> list[AIExecutionNode]:
        return [
            AIExecutionNode(
                request_id=execution_id,
                node_id=resource.scope.resource_id,
                node_id_snapshot=resource.scope.resource_id,
                selected_order=ordinal,
                node_type="note",
                node_revision=resource.scope.version or 1,
                title_snapshot=resource.title[:160],
                content_snapshot=resource.content,
                document_id=None,
                document_id_snapshot=None,
            )
            for ordinal, resource in enumerate(
                item for item in resolved.resources if item.scope.kind is ResourceKind.NODE
            )
        ]

    @staticmethod
    def _execution_chunks(
        execution_id: uuid.UUID, sources: list[GroundedSource]
    ) -> list[AIExecutionChunk]:
        return [
            AIExecutionChunk(
                request_id=execution_id,
                chunk_id=source.chunk_id,
                chunk_id_snapshot=source.chunk_id,
                document_id=source.document_id,
                document_id_snapshot=source.document_id,
                document_version_snapshot=source.document_version,
                chunk_index_snapshot=source.chunk_index,
                rank=rank,
                score=source.score,
                included_in_context=True,
                exclusion_reason=None,
                source_id_snapshot=source.source_id,
                document_name_snapshot=source.document_title,
                content_snapshot=source.text,
                page_number_snapshot=source.page_number,
                heading_snapshot=source.heading,
                char_start_snapshot=source.char_start,
                char_end_snapshot=source.char_end,
            )
            for rank, source in enumerate(sources, start=1)
        ]

    @staticmethod
    def _citations(
        response_id: uuid.UUID,
        result_citations: list[GroundedCitation],
        sources: list[GroundedSource],
    ) -> list[Citation]:
        by_id = {source.source_id: source for source in sources}
        return [
            Citation(
                ai_response_id=response_id,
                document_id=by_id[citation.source_id].document_id,
                document_version=by_id[citation.source_id].document_version,
                chunk_id=by_id[citation.source_id].chunk_id,
                identifier=citation.source_id,
                claim=citation.claim,
                quote=by_id[citation.source_id].text,
                ordinal=ordinal,
            )
            for ordinal, citation in enumerate(result_citations, start=1)
        ]

    @staticmethod
    def _execution_citations(
        execution_id: uuid.UUID,
        response_id: uuid.UUID,
        result_citations: list[GroundedCitation],
        sources: list[GroundedSource],
    ) -> list[AIExecutionCitation]:
        by_id = {source.source_id: source for source in sources}
        return [
            AIExecutionCitation(
                request_id=execution_id,
                ai_response_id_snapshot=response_id,
                ordinal=ordinal,
                source_id_snapshot=citation.source_id,
                claim_snapshot=citation.claim,
                excerpt_snapshot=by_id[citation.source_id].text[:1_200],
                document_id_snapshot=by_id[citation.source_id].document_id,
                document_version_snapshot=by_id[citation.source_id].document_version,
                chunk_id_snapshot=by_id[citation.source_id].chunk_id,
                document_name_snapshot=by_id[citation.source_id].document_title,
                page_number_snapshot=by_id[citation.source_id].page_number,
                heading_snapshot=by_id[citation.source_id].heading,
                char_start_snapshot=by_id[citation.source_id].char_start,
                char_end_snapshot=by_id[citation.source_id].char_end,
            )
            for ordinal, citation in enumerate(result_citations, start=1)
        ]

    @staticmethod
    def _claims(
        execution_id: uuid.UUID,
        response_id: uuid.UUID,
        result: GroundedAIResult,
        sources: list[GroundedSource],
    ) -> list[AIClaim]:
        if result.insufficient_evidence:
            return [
                AIClaim(
                    request_id=execution_id,
                    ai_response_id=response_id,
                    ordinal=1,
                    claim=result.text[:4_000],
                    evidence_status="insufficient_evidence",
                    evidence_snapshot=[],
                )
            ]
        by_id = {source.source_id: source for source in sources}
        return [
            AIClaim(
                request_id=execution_id,
                ai_response_id=response_id,
                ordinal=ordinal,
                claim=citation.claim,
                evidence_status="supported",
                evidence_snapshot=[
                    {
                        "sourceId": citation.source_id,
                        "documentId": str(by_id[citation.source_id].document_id),
                        "documentVersion": by_id[citation.source_id].document_version,
                        "chunkId": str(by_id[citation.source_id].chunk_id),
                    }
                ],
            )
            for ordinal, citation in enumerate(result.citations, start=1)
        ]

    def _estimated_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.settings.estimated_input_cost_per_million_tokens
            + output_tokens * self.settings.estimated_output_cost_per_million_tokens
        ) / 1_000_000

    @staticmethod
    def _response_text(result: GroundedAIResult) -> str:
        if not result.general_analysis:
            return result.text
        return (
            f"{result.text}\n\n---\n\n### General analysis (not source-grounded)\n\n"
            f"{result.general_analysis}"
        )

    @staticmethod
    def _result_digest(result: GroundedAIResult, sources: list[GroundedSource]) -> str:
        payload = {
            "text": result.text,
            "insufficientEvidence": result.insufficient_evidence,
            "generalAnalysis": result.general_analysis,
            "citations": [
                {"sourceId": citation.source_id, "claim": citation.claim}
                for citation in result.citations
            ],
            "sources": [
                {
                    "sourceId": source.source_id,
                    "documentId": str(source.document_id),
                    "documentVersion": source.document_version,
                    "chunkId": str(source.chunk_id),
                }
                for source in sources
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


__all__ = [
    "ControlledDraftCitation",
    "ControlledDraftError",
    "ControlledDraftResult",
    "ControlledGroundedDraftService",
]

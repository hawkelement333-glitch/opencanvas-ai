from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from opencanvas_api.db.models import (
    SYSTEM_USER_ID,
    SYSTEM_WORKSPACE_ID,
    Base,
    CanvasNode,
    ControlledAgentAuditEvent,
    ControlledWorkflowEvidenceLink,
    ControlledWorkflowExecution,
    ControlledWorkflowPlanSnapshot,
    ControlledWorkflowStep,
    ControlledWorkflowStepAttempt,
    ControlledWorkflowStepExecution,
    DomainEventOutbox,
    DomainEventRecord,
    TraceEvent,
    User,
    Workspace,
)
from opencanvas_api.db.session import Database
from opencanvas_api.services.agents.contracts import ApprovalDecision
from opencanvas_api.services.ai import AIProviderError, MockAIProvider
from opencanvas_api.services.documents.embeddings import MockEmbeddingProvider
from opencanvas_api.services.workflows import (
    MAX_DEPENDENCIES_PER_STEP,
    MAX_WORKFLOW_STEPS,
    OUTPUT_SCHEMA_VERSION,
    RETRYABLE_FAILURES,
    STEP_TYPE_REGISTRY,
    VERSION_TRANSITIONS,
    CompensationOutcome,
    ControlledWorkflowService,
    CreateWorkflowDraft,
    CreateWorkflowVersion,
    StartWorkflow,
    WorkflowConflictError,
    WorkflowExecutionStatus,
    WorkflowFailureClass,
    WorkflowKind,
    WorkflowOutcome,
    WorkflowStepInput,
    WorkflowStepStatus,
    WorkflowStepType,
    WorkflowStorageError,
    WorkflowValidationError,
    WorkflowVersionInput,
)
from tests.test_graph_retrieval import _retrieval_foundation


def _version(*, include_bundle: bool = True) -> WorkflowVersionInput:
    steps = [
        WorkflowStepInput(step_key="validate", step_type=WorkflowStepType.VALIDATE_INPUT),
        WorkflowStepInput(
            step_key="context",
            step_type=WorkflowStepType.CAPTURE_CONTEXT,
            depends_on=("validate",),
        ),
        WorkflowStepInput(
            step_key="retrieve",
            step_type=WorkflowStepType.GRAPH_RETRIEVAL,
            depends_on=("context",),
        ),
        WorkflowStepInput(
            step_key="evaluate",
            step_type=WorkflowStepType.EVALUATE_EVIDENCE,
            depends_on=("retrieve",),
        ),
        WorkflowStepInput(
            step_key="answer",
            step_type=WorkflowStepType.GROUNDED_MODEL,
            depends_on=("evaluate",),
        ),
        WorkflowStepInput(
            step_key="citations",
            step_type=WorkflowStepType.RENDER_CITATIONS,
            depends_on=("answer",),
        ),
    ]
    if include_bundle:
        steps.append(
            WorkflowStepInput(
                step_key="bundle",
                step_type=WorkflowStepType.EVIDENCE_BUNDLE,
                depends_on=("citations",),
            )
        )
    steps.append(
        WorkflowStepInput(
            step_key="output",
            step_type=WorkflowStepType.RECORD_OUTPUT,
            depends_on=(("bundle",) if include_bundle else ("citations",)),
        )
    )
    return WorkflowVersionInput(steps=tuple(steps))


def _service(session: object) -> ControlledWorkflowService:
    return ControlledWorkflowService(
        session,  # type: ignore[arg-type]
        embedding_provider=MockEmbeddingProvider(),
        ai_provider=MockAIProvider(),
    )


async def _activate(
    database: Database,
    *,
    kind: WorkflowKind,
    version: WorkflowVersionInput,
    key: str,
) -> tuple[uuid.UUID, dict[str, uuid.UUID], uuid.UUID]:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = _service(session)
        record = await service.create_draft(
            CreateWorkflowDraft(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                kind=kind,
                name=key,
                description="Focused controlled workflow test.",
                version=version,
                idempotency_key=key,
            )
        )
        workflow_version = record.versions[0]
        await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=workflow_version.version_id,
        )
        await service.activate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=workflow_version.version_id,
        )
        await session.commit()
    return canvas_id, objects, workflow_version.version_id


async def _active_workflow(
    database: Database,
    *,
    include_bundle: bool = True,
) -> tuple[uuid.UUID, dict[str, uuid.UUID], uuid.UUID]:
    canvas_id, objects = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = _service(session)
        created = await service.create_draft(
            CreateWorkflowDraft(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                kind=WorkflowKind.GROUNDED_ANSWER,
                name="Grounded answer",
                description="A bounded selected-context workflow.",
                version=_version(include_bundle=include_bundle),
                idempotency_key="workflow-definition-one",
            )
        )
        version = created.versions[0]
        await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version.version_id,
        )
        await service.activate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            version_id=version.version_id,
        )
        await session.commit()
    return canvas_id, objects, version.version_id


def test_closed_workflow_registries_and_schema_contracts() -> None:
    assert set(WorkflowKind) == {
        WorkflowKind.GROUNDED_ANSWER,
        WorkflowKind.EVIDENCE_PACKAGE,
        WorkflowKind.APPROVED_REVERSIBLE_NOTE,
    }
    assert set(STEP_TYPE_REGISTRY) == set(WorkflowStepType)
    assert WorkflowExecutionStatus.COMPLETED.value == "completed"
    assert WorkflowStepStatus.AWAITING_APPROVAL.value == "awaiting_approval"
    assert WorkflowOutcome.BOUNDED_RESULT.value == "bounded_result"
    assert WorkflowFailureClass.RETRYABLE_PROVIDER in RETRYABLE_FAILURES
    assert VERSION_TRANSITIONS
    assert set(CompensationOutcome)
    assert OUTPUT_SCHEMA_VERSION == "controlled-workflow-output-v1"
    assert MAX_WORKFLOW_STEPS == 32
    assert MAX_DEPENDENCIES_PER_STEP == 8
    with pytest.raises(ValidationError):
        WorkflowStepInput.model_validate({"stepKey": "unsafe", "stepType": "shell", "config": {}})


@pytest.mark.anyio
async def test_immutable_version_and_dag_validation(database: Database) -> None:
    canvas_id, _ = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = _service(session)
        command = CreateWorkflowDraft(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            kind=WorkflowKind.GROUNDED_ANSWER,
            name="Versioned",
            description="Immutable workflow",
            version=_version(),
            idempotency_key="versioned-workflow",
        )
        first = await service.create_draft(command)
        duplicate = await service.create_draft(command)
        assert duplicate.duplicate is True
        assert first.versions[0].content_digest == duplicate.versions[0].content_digest
        updated = await service.create_version(
            CreateWorkflowVersion(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                definition_id=first.definition.definition_id,
                version=_version(include_bundle=False),
                idempotency_key="version-two",
            )
        )
        assert [item.version_number for item in updated.versions] == [1, 2]
        assert updated.versions[0].version_id != updated.versions[1].version_id
        with pytest.raises(WorkflowConflictError):
            await service.create_version(
                CreateWorkflowVersion(
                    user_id=SYSTEM_USER_ID,
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    canvas_id=canvas_id,
                    definition_id=first.definition.definition_id,
                    version=_version(),
                    idempotency_key="version-two",
                )
            )
        cyclic = WorkflowVersionInput(
            steps=(
                WorkflowStepInput(
                    step_key="a",
                    step_type=WorkflowStepType.GRAPH_RETRIEVAL,
                    depends_on=("output",),
                ),
                WorkflowStepInput(
                    step_key="evaluate",
                    step_type=WorkflowStepType.EVALUATE_EVIDENCE,
                    depends_on=("a",),
                ),
                WorkflowStepInput(
                    step_key="output",
                    step_type=WorkflowStepType.RECORD_OUTPUT,
                    depends_on=("evaluate",),
                ),
            )
        )
        with pytest.raises(WorkflowValidationError):
            await service.create_version(
                CreateWorkflowVersion(
                    user_id=SYSTEM_USER_ID,
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    canvas_id=canvas_id,
                    definition_id=first.definition.definition_id,
                    version=cyclic,
                    idempotency_key="cycle-version",
                )
            )


@pytest.mark.anyio
async def test_grounded_workflow_completes_once_with_exact_evidence(database: Database) -> None:
    canvas_id, objects, version_id = await _active_workflow(database)
    command = StartWorkflow(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        version_id=version_id,
        query="First",
        selected_object_ids=(objects["note_one"], objects["note_two"]),
        seed_object_ids=(objects["note_one"],),
        idempotency_key="workflow-run-one",
    )
    async with database.sessions() as session:
        service = _service(session)
        first = await service.start(command)
        assert first.execution.status == WorkflowExecutionStatus.COMPLETED, [
            (item.status, item.safe_failure_class) for item in first.steps
        ]
        assert first.execution.outcome == WorkflowOutcome.SUPPORTED
        assert first.execution.output is not None
        assert first.execution.output["schemaVersion"] == OUTPUT_SCHEMA_VERSION
        assert first.execution.output["citationIds"]
        assert first.execution.output["evidenceBundleId"]
        assert all(item.status == WorkflowStepStatus.SUCCEEDED for item in first.steps)
        replay = await service.start(command)
        assert replay.duplicate is True
        assert replay.execution.execution_id == first.execution.execution_id
        with pytest.raises(WorkflowConflictError):
            await service.start(replace(command, query="Changed"))
        await session.commit()

    async with database.sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ControlledWorkflowExecution)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledWorkflowPlanSnapshot))
            == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledWorkflowStepAttempt))
            == 8
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledWorkflowEvidenceLink))
            >= 4
        )
        assert (
            await session.scalar(select(func.count()).select_from(ControlledAgentAuditEvent)) >= 8
        )
        assert await session.scalar(select(func.count()).select_from(DomainEventRecord)) >= 20
        assert await session.scalar(select(func.count()).select_from(DomainEventOutbox)) >= 20
        traces = (
            await session.scalars(
                select(TraceEvent).where(
                    TraceEvent.trace_id
                    == uuid.uuid5(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"mobius:workflow-execution:{SYSTEM_USER_ID}:"
                            f"{SYSTEM_WORKSPACE_ID}:{canvas_id}:workflow-run-one",
                        ),
                        "trace",
                    )
                )
            )
        ).all()
        assert [item.status for item in traces] == ["started", "succeeded"]


@pytest.mark.anyio
async def test_workflow_api_rejects_authority_and_worker_injection(
    database: Database,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    canvas_id, objects, version_id = await _active_workflow(database, include_bundle=False)
    endpoint = (
        f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/canvases/{canvas_id}/workflows/executions"
    )
    payload = {
        "versionId": str(version_id),
        "query": "First",
        "selectedObjectIds": [str(objects["note_one"]), str(objects["note_two"])],
        "seedObjectIds": [str(objects["note_one"])],
        "idempotencyKey": "workflow-api-run",
    }
    response = await client.post(endpoint, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["outcome"] == "supported"
    assert body["output"]["citationIds"]
    serialized = str(body)
    for forbidden in (
        "leaseOwner",
        "leaseGeneration",
        "grant",
        "policyDecision",
        "chain of thought",
    ):
        assert forbidden not in serialized

    rejected = await client.post(
        endpoint,
        json={
            **payload,
            "idempotencyKey": "workflow-api-injection",
            "controlledExecutionId": str(uuid.uuid4()),
            "status": "completed",
        },
    )
    assert rejected.status_code == 422
    probing = await client.get(
        f"{api_prefix}/workspaces/{uuid.uuid4()}/canvases/{canvas_id}/workflows/"
        f"executions/{body['executionId']}"
    )
    assert probing.status_code == 404


@pytest.mark.anyio
async def test_exact_human_approval_pauses_consumes_once_and_denial_fails(
    database: Database,
) -> None:
    version = WorkflowVersionInput(
        steps=(
            WorkflowStepInput(
                step_key="retrieve",
                step_type=WorkflowStepType.GRAPH_RETRIEVAL,
            ),
            WorkflowStepInput(
                step_key="evaluate",
                step_type=WorkflowStepType.EVALUATE_EVIDENCE,
                depends_on=("retrieve",),
            ),
            WorkflowStepInput(
                step_key="approve",
                step_type=WorkflowStepType.HUMAN_APPROVAL,
                depends_on=("evaluate",),
            ),
            WorkflowStepInput(
                step_key="output",
                step_type=WorkflowStepType.RECORD_OUTPUT,
                depends_on=("approve",),
            ),
        )
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.GROUNDED_ANSWER,
        version=version,
        key="approval-workflow",
    )
    command = StartWorkflow(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        version_id=version_id,
        query="First",
        selected_object_ids=(objects["note_one"], objects["note_two"]),
        seed_object_ids=(objects["note_one"],),
        idempotency_key="approval-run",
    )
    async with database.sessions() as session:
        service = _service(session)
        paused = await service.start(command)
        assert paused.execution.status == WorkflowExecutionStatus.AWAITING_APPROVAL
        approval_step = next(
            item for item in paused.steps if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        assert approval_step.approval_id is not None
        completed = await service.decide_approval(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=paused.execution.execution_id,
            step_execution_id=approval_step.step_execution_id,
            decision=ApprovalDecision.APPROVED,
            session_id=uuid.uuid4(),
        )
        assert completed.execution.status == WorkflowExecutionStatus.COMPLETED
        with pytest.raises(WorkflowConflictError):
            await service.decide_approval(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                execution_id=paused.execution.execution_id,
                step_execution_id=approval_step.step_execution_id,
                decision=ApprovalDecision.APPROVED,
                session_id=uuid.uuid4(),
            )
        await session.commit()

    async with database.sessions() as session:
        service = _service(session)
        denied = await service.start(replace(command, idempotency_key="approval-denied"))
        assert denied.execution.status == WorkflowExecutionStatus.AWAITING_APPROVAL, [
            (item.status, item.safe_failure_class) for item in denied.steps
        ]
        denied_step = next(
            item for item in denied.steps if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        result = await service.decide_approval(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=denied.execution.execution_id,
            step_execution_id=denied_step.step_execution_id,
            decision=ApprovalDecision.DENIED,
            session_id=uuid.uuid4(),
        )
        assert result.execution.status == WorkflowExecutionStatus.FAILED
        assert result.execution.outcome == WorkflowOutcome.FAILED


@pytest.mark.anyio
async def test_approved_reversible_effect_commits_once_and_duplicate_start_is_safe(
    database: Database,
) -> None:
    version = WorkflowVersionInput(
        steps=(
            WorkflowStepInput(
                step_key="effect",
                step_type=WorkflowStepType.CONTROLLED_EFFECT,
                config={"action": "note.create", "title": "Workflow note", "text": "Created once"},
            ),
            WorkflowStepInput(
                step_key="output",
                step_type=WorkflowStepType.RECORD_OUTPUT,
                depends_on=("effect",),
            ),
        )
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.APPROVED_REVERSIBLE_NOTE,
        version=version,
        key="effect-workflow",
    )
    command = StartWorkflow(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        version_id=version_id,
        query="Create the approved note",
        selected_object_ids=(objects["note_one"],),
        seed_object_ids=(objects["note_one"],),
        idempotency_key="effect-run",
    )
    async with database.sessions() as session:
        service = _service(session)
        paused = await service.start(command)
        assert paused.execution.status == WorkflowExecutionStatus.AWAITING_APPROVAL
        effect_step = next(
            item for item in paused.steps if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        completed = await service.decide_approval(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=paused.execution.execution_id,
            step_execution_id=effect_step.step_execution_id,
            decision=ApprovalDecision.APPROVED,
            session_id=uuid.uuid4(),
        )
        assert completed.execution.status == WorkflowExecutionStatus.COMPLETED
        assert completed.execution.output is not None
        effects = cast(list[dict[str, object]], completed.execution.output["effects"])
        assert len(effects) == 1
        created_id = uuid.UUID(cast(str, effects[0]["resourceId"]))
        replay = await service.start(command)
        assert replay.duplicate is True
        assert replay.execution.output == completed.execution.output
        await session.commit()

    async with database.sessions() as session:
        created = await session.get(CanvasNode, created_id)
        assert created is not None
        assert created.title == "Workflow note"
        assert created.text == "Created once"


class _FlakyProvider(MockAIProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_grounded(
        self, instruction: object, notes_context: object, sources: object
    ) -> object:
        self.calls += 1
        if self.calls == 1:
            raise AIProviderError("transient test provider failure")
        return await super().generate_grounded(  # type: ignore[arg-type, no-any-return]
            instruction,
            notes_context,
            sources,
        )


@pytest.mark.anyio
async def test_bounded_retry_succeeds_once_and_attempts_remain_truthful(database: Database) -> None:
    retry_version = _version(include_bundle=False)
    retry_version = retry_version.model_copy(
        update={
            "steps": tuple(
                item.model_copy(update={"max_attempts": 2})
                if item.step_type is WorkflowStepType.GROUNDED_MODEL
                else item
                for item in retry_version.steps
            )
        }
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.GROUNDED_ANSWER,
        version=retry_version,
        key="retry-workflow",
    )
    provider = _FlakyProvider()
    command = StartWorkflow(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        version_id=version_id,
        query="First",
        selected_object_ids=(objects["note_one"], objects["note_two"]),
        seed_object_ids=(objects["note_one"],),
        idempotency_key="retry-run",
    )
    async with database.sessions() as session:
        service = ControlledWorkflowService(
            session,
            embedding_provider=MockEmbeddingProvider(),
            ai_provider=provider,
        )
        waiting = await service.start(command)
        assert waiting.execution.status == WorkflowExecutionStatus.READY
        retry_step = next(
            item for item in waiting.steps if item.status == WorkflowStepStatus.RETRY_WAITING
        )
        assert retry_step.attempt_count == 1
        completed = await service.run_until_pause(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=waiting.execution.execution_id,
            now=datetime.now(UTC) + timedelta(seconds=3),
        )
        assert completed.execution.status == WorkflowExecutionStatus.COMPLETED
        assert provider.calls == 2
        retried = next(
            item
            for item in completed.steps
            if item.step_execution_id == retry_step.step_execution_id
        )
        assert retried.attempt_count == 2
        attempts = (
            await session.scalars(
                select(ControlledWorkflowStepAttempt)
                .where(
                    ControlledWorkflowStepAttempt.step_execution_id == retry_step.step_execution_id
                )
                .order_by(ControlledWorkflowStepAttempt.attempt_number)
            )
        ).all()
        assert [(item.outcome, item.failure_class) for item in attempts] == [
            ("retry_scheduled", "retryable_provider_failure"),
            ("succeeded", None),
        ]


@pytest.mark.anyio
async def test_cancel_fences_pending_approval_and_is_idempotent(database: Database) -> None:
    version = WorkflowVersionInput(
        steps=(
            WorkflowStepInput(
                step_key="retrieve",
                step_type=WorkflowStepType.GRAPH_RETRIEVAL,
            ),
            WorkflowStepInput(
                step_key="evaluate",
                step_type=WorkflowStepType.EVALUATE_EVIDENCE,
                depends_on=("retrieve",),
            ),
            WorkflowStepInput(
                step_key="approve",
                step_type=WorkflowStepType.HUMAN_APPROVAL,
                depends_on=("evaluate",),
            ),
            WorkflowStepInput(
                step_key="output",
                step_type=WorkflowStepType.RECORD_OUTPUT,
                depends_on=("approve",),
            ),
        )
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.GROUNDED_ANSWER,
        version=version,
        key="cancel-workflow",
    )
    async with database.sessions() as session:
        service = _service(session)
        paused = await service.start(
            StartWorkflow(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version_id,
                query="First",
                selected_object_ids=(objects["note_one"], objects["note_two"]),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="cancel-run",
            )
        )
        approval_step = next(
            item for item in paused.steps if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        canceled = await service.request_cancellation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=paused.execution.execution_id,
        )
        assert canceled.execution.status == WorkflowExecutionStatus.CANCELED
        assert canceled.execution.outcome == WorkflowOutcome.CANCELED
        duplicate = await service.request_cancellation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=paused.execution.execution_id,
        )
        assert duplicate.execution.status == WorkflowExecutionStatus.CANCELED
        with pytest.raises(WorkflowConflictError):
            await service.decide_approval(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                execution_id=paused.execution.execution_id,
                step_execution_id=approval_step.step_execution_id,
                decision=ApprovalDecision.APPROVED,
                session_id=uuid.uuid4(),
            )


@pytest.mark.anyio
@pytest.mark.parametrize("failure_point", ["version", "execution", "plan"])
async def test_failure_injection_leaves_no_partial_workflow_evidence(
    database: Database,
    failure_point: str,
) -> None:
    canvas_id, objects = await _retrieval_foundation(database)

    def fail() -> None:
        raise WorkflowStorageError()

    async with database.sessions() as session:
        service = ControlledWorkflowService(
            session,
            embedding_provider=MockEmbeddingProvider(),
            ai_provider=MockAIProvider(),
            after_version=fail if failure_point == "version" else None,
            after_execution=fail if failure_point == "execution" else None,
            after_plan=fail if failure_point == "plan" else None,
        )
        if failure_point == "version":
            with pytest.raises(WorkflowStorageError):
                await service.create_draft(
                    CreateWorkflowDraft(
                        user_id=SYSTEM_USER_ID,
                        workspace_id=SYSTEM_WORKSPACE_ID,
                        canvas_id=canvas_id,
                        kind=WorkflowKind.GROUNDED_ANSWER,
                        name="Failure",
                        description="Injected",
                        version=_version(),
                        idempotency_key="failure-version",
                    )
                )
        else:
            created = await service.create_draft(
                CreateWorkflowDraft(
                    user_id=SYSTEM_USER_ID,
                    workspace_id=SYSTEM_WORKSPACE_ID,
                    canvas_id=canvas_id,
                    kind=WorkflowKind.GROUNDED_ANSWER,
                    name="Failure",
                    description="Injected",
                    version=_version(),
                    idempotency_key=f"failure-{failure_point}-definition",
                )
            )
            version = created.versions[0]
            await service.validate_version(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version.version_id,
            )
            await service.activate_version(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version.version_id,
            )
            with pytest.raises(WorkflowStorageError):
                await service.start(
                    StartWorkflow(
                        user_id=SYSTEM_USER_ID,
                        workspace_id=SYSTEM_WORKSPACE_ID,
                        canvas_id=canvas_id,
                        version_id=version.version_id,
                        query="First",
                        selected_object_ids=(objects["note_one"], objects["note_two"]),
                        seed_object_ids=(objects["note_one"],),
                        idempotency_key=f"failure-{failure_point}-run",
                    )
                )
        await session.commit()

    async with database.sessions() as session:
        if failure_point == "version":
            assert (
                await session.scalar(select(func.count()).select_from(ControlledWorkflowStep)) == 0
            )
        else:
            assert (
                await session.scalar(select(func.count()).select_from(ControlledWorkflowExecution))
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(ControlledWorkflowPlanSnapshot)
                )
                == 0
            )


@pytest.mark.anyio
async def test_workflow_evidence_is_append_only(database: Database) -> None:
    canvas_id, objects, version_id = await _active_workflow(database, include_bundle=False)
    async with database.sessions() as session:
        result = await _service(session).start(
            StartWorkflow(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version_id,
                query="First",
                selected_object_ids=(objects["note_one"], objects["note_two"]),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="immutable-workflow-run",
            )
        )
        await session.commit()
        plan = await session.get(ControlledWorkflowPlanSnapshot, result.execution.plan_id)
        assert plan is not None
        plan.plan_digest = "0" * 64
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()
        await session.rollback()
        attempt = await session.scalar(select(ControlledWorkflowStepAttempt))
        assert attempt is not None
        await session.delete(attempt)
        with pytest.raises(ValueError, match="append-only"):
            await session.flush()


@pytest.mark.anyio
async def test_predefined_compensation_requires_approval_and_removes_created_note(
    database: Database,
) -> None:
    version = WorkflowVersionInput(
        compensation_policy="predefined_saga",
        steps=(
            WorkflowStepInput(
                step_key="effect",
                step_type=WorkflowStepType.CONTROLLED_EFFECT,
                config={"action": "note.create", "title": "Compensate", "text": "Remove me"},
                compensation_step_key="rollback",
            ),
            WorkflowStepInput(
                step_key="gate",
                step_type=WorkflowStepType.HUMAN_APPROVAL,
                depends_on=("effect",),
            ),
            WorkflowStepInput(
                step_key="output",
                step_type=WorkflowStepType.RECORD_OUTPUT,
                depends_on=("gate",),
            ),
            WorkflowStepInput(
                step_key="rollback",
                step_type=WorkflowStepType.COMPENSATION,
                config={"effectStepKey": "effect"},
            ),
        ),
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.APPROVED_REVERSIBLE_NOTE,
        version=version,
        key="compensation-workflow",
    )
    async with database.sessions() as session:
        service = _service(session)
        first_pause = await service.start(
            StartWorkflow(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version_id,
                query="Create then compensate",
                selected_object_ids=(objects["note_one"],),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="compensation-run",
            )
        )
        effect_step = next(
            item
            for item in first_pause.steps
            if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        second_pause = await service.decide_approval(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=first_pause.execution.execution_id,
            step_execution_id=effect_step.step_execution_id,
            decision=ApprovalDecision.APPROVED,
            session_id=uuid.uuid4(),
        )
        assert second_pause.execution.status == WorkflowExecutionStatus.AWAITING_APPROVAL
        effect_result = next(item for item in second_pause.steps if item.effect_id is not None)
        effect_row = await session.get(
            ControlledWorkflowStepExecution,
            effect_result.step_execution_id,
        )
        assert effect_row is not None and effect_row.output is not None
        created_id = uuid.UUID(cast(str, effect_row.output["resourceId"]))
        assert await session.get(CanvasNode, created_id) is not None

        compensation_pause = await service.request_cancellation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=first_pause.execution.execution_id,
        )
        assert compensation_pause.execution.status == WorkflowExecutionStatus.AWAITING_APPROVAL, [
            (item.status, item.safe_failure_class) for item in compensation_pause.steps
        ]
        compensation_step = next(
            item
            for item in compensation_pause.steps
            if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        compensated = await service.decide_approval(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=first_pause.execution.execution_id,
            step_execution_id=compensation_step.step_execution_id,
            decision=ApprovalDecision.APPROVED,
            session_id=uuid.uuid4(),
        )
        assert compensated.execution.status == WorkflowExecutionStatus.COMPENSATED
        assert compensated.execution.outcome == WorkflowOutcome.COMPENSATED
        assert await session.get(CanvasNode, created_id) is None
        duplicate = await service.request_cancellation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=first_pause.execution.execution_id,
        )
        assert duplicate.execution.status == WorkflowExecutionStatus.COMPENSATED


@pytest.mark.anyio
async def test_cancellation_generation_fences_stale_step_completion(database: Database) -> None:
    version = WorkflowVersionInput(
        steps=(
            WorkflowStepInput(
                step_key="effect",
                step_type=WorkflowStepType.CONTROLLED_EFFECT,
                config={"action": "note.create", "title": "Fence", "text": "No commit"},
            ),
            WorkflowStepInput(
                step_key="output",
                step_type=WorkflowStepType.RECORD_OUTPUT,
                depends_on=("effect",),
            ),
        )
    )
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.APPROVED_REVERSIBLE_NOTE,
        version=version,
        key="fence-workflow",
    )
    async with database.sessions() as session:
        service = _service(session)
        paused = await service.start(
            StartWorkflow(
                user_id=SYSTEM_USER_ID,
                workspace_id=SYSTEM_WORKSPACE_ID,
                canvas_id=canvas_id,
                version_id=version_id,
                query="Fence stale completion",
                selected_object_ids=(objects["note_one"],),
                seed_object_ids=(objects["note_one"],),
                idempotency_key="fence-run",
            )
        )
        row = next(
            item for item in paused.steps if item.status == WorkflowStepStatus.AWAITING_APPROVAL
        )
        owner = "stale-worker"
        generation = row.lease_generation
        await session.execute(
            update(ControlledWorkflowStepExecution)
            .where(ControlledWorkflowStepExecution.step_execution_id == row.step_execution_id)
            .values(
                status=WorkflowStepStatus.RUNNING.value,
                lease_owner_id=owner,
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
            )
            .execution_options(synchronize_session=False)
        )
        canceled = await service.request_cancellation(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas_id,
            execution_id=paused.execution.execution_id,
        )
        assert canceled.execution.status == WorkflowExecutionStatus.CANCELED
        stale = await session.scalar(
            update(ControlledWorkflowStepExecution)
            .where(
                ControlledWorkflowStepExecution.step_execution_id == row.step_execution_id,
                ControlledWorkflowStepExecution.status == WorkflowStepStatus.RUNNING.value,
                ControlledWorkflowStepExecution.lease_owner_id == owner,
                ControlledWorkflowStepExecution.lease_generation == generation,
            )
            .values(
                status=WorkflowStepStatus.SUCCEEDED.value,
                output={"unsafe": "stale"},
            )
            .execution_options(synchronize_session=False)
            .returning(ControlledWorkflowStepExecution.step_execution_id)
        )
        assert stale is None
        persisted = await session.get(ControlledWorkflowStepExecution, row.step_execution_id)
        assert persisted is not None
        await session.refresh(persisted)
        assert persisted.status == WorkflowStepStatus.CANCELED
        assert persisted.output is None


@pytest.mark.anyio
async def test_competing_identical_workflow_starts_converge_on_one_execution(
    tmp_path: Path,
) -> None:
    path = tmp_path / "workflow-contention.db"
    database = Database(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.sessions() as session:
        session.add(
            User(
                id=SYSTEM_USER_ID,
                email="workflow-contention@mobius.invalid",
                email_normalized="workflow-contention@mobius.invalid",
                password_hash="test-only",
                display_name="Workflow contention",
                email_verified=True,
            )
        )
        session.add(
            Workspace(
                id=SYSTEM_WORKSPACE_ID,
                owner_id=SYSTEM_USER_ID,
                name="Workflow contention",
            )
        )
        await session.commit()
    canvas_id, objects, version_id = await _activate(
        database,
        kind=WorkflowKind.GROUNDED_ANSWER,
        version=_version(include_bundle=False),
        key="contention-workflow",
    )
    command = StartWorkflow(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        canvas_id=canvas_id,
        version_id=version_id,
        query="First",
        selected_object_ids=(objects["note_one"], objects["note_two"]),
        seed_object_ids=(objects["note_one"],),
        idempotency_key="contention-run",
    )

    async def start() -> uuid.UUID | None:
        async with database.sessions() as session:
            try:
                result = await _service(session).start(command)
                await session.commit()
                return result.execution.execution_id
            except WorkflowStorageError:
                await session.rollback()
                return None

    try:
        results = await asyncio.gather(start(), start())
        async with database.sessions() as session:
            replay = await _service(session).start(command)
            await session.commit()
            authoritative = replay.execution.execution_id
        assert {item for item in results if item is not None} <= {authoritative}
        async with database.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(ControlledWorkflowExecution))
                == 1
            )
    finally:
        await database.dispose()

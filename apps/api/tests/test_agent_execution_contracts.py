from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from opencanvas_api.services.agents.contracts import Capability, RiskClass, contract_digest
from opencanvas_api.services.agents.execution import (
    ACTION_REGISTRY,
    GROUND_DRAFT_STAGES,
    ControlledAction,
    ControlledExecutionPlan,
    ControlledExecutionRequest,
    ExecutionStage,
    idempotency_digest,
)

NOW = datetime(2026, 7, 21, 18, tzinfo=UTC)


def make_request(**updates: object) -> ControlledExecutionRequest:
    values: dict[str, object] = {
        "user_id": uuid.UUID("10000000-0000-0000-0000-000000000001"),
        "workspace_id": uuid.UUID("20000000-0000-0000-0000-000000000002"),
        "canvas_id": uuid.UUID("30000000-0000-0000-0000-000000000003"),
        "execution_id": uuid.UUID("80000000-0000-0000-0000-000000000008"),
        "context_snapshot_id": uuid.UUID("40000000-0000-0000-0000-000000000004"),
        "expected_context_digest": "a" * 64,
        "plan_id": uuid.UUID("50000000-0000-0000-0000-000000000005"),
        "expected_plan_digest": "b" * 64,
        "action": ControlledAction.GENERATE_GROUNDED_DRAFT,
        "grant_id": uuid.UUID("60000000-0000-0000-0000-000000000006"),
        "approval_id": uuid.UUID("70000000-0000-0000-0000-000000000007"),
        "idempotency_key": "grounded-draft:request-1",
        "client_request_id": "browser-request-1",
        "correlation_id": "correlation-1",
    }
    values.update(updates)
    return ControlledExecutionRequest(**values)


def make_plan(**updates: object) -> ControlledExecutionPlan:
    request = make_request()
    values: dict[str, object] = {
        "plan_id": request.plan_id,
        "execution_id": request.execution_id,
        "user_id": request.user_id,
        "workspace_id": request.workspace_id,
        "canvas_id": request.canvas_id,
        "action": request.action,
        "created_at": NOW,
    }
    values.update(updates)
    return ControlledExecutionPlan(**values)


def test_registry_contains_only_the_closed_read_only_draft_action() -> None:
    assert tuple(ACTION_REGISTRY) == (ControlledAction.GENERATE_GROUNDED_DRAFT,)
    boundary = ACTION_REGISTRY[ControlledAction.GENERATE_GROUNDED_DRAFT]
    assert boundary.maximum_risk is RiskClass.R1_DRAFT
    assert boundary.allows_workspace_mutation is False
    assert boundary.allows_external_effects is False
    assert boundary.allows_delegation is False
    assert Capability.CANVAS_NOTE_CREATE not in boundary.allowed_capabilities
    assert Capability.CANVAS_NOTE_UPDATE not in boundary.allowed_capabilities


def test_unknown_actions_and_client_authority_injection_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_request(action="send_external_message")
    with pytest.raises(ValidationError):
        ControlledExecutionRequest.model_validate(
            {
                **make_request().model_dump(),
                "raw_grant": {"capabilities": ["canvas.note.create"]},
            }
        )


def test_plan_has_exactly_the_fixed_six_stages_and_stable_hash() -> None:
    plan = make_plan()
    assert plan.stages == GROUND_DRAFT_STAGES
    assert plan.stages == (
        ExecutionStage.VALIDATE_AUTHORITY,
        ExecutionStage.LOAD_IMMUTABLE_CONTEXT,
        ExecutionStage.RETRIEVE_SELECTED_EVIDENCE,
        ExecutionStage.GENERATE_GROUNDED_DRAFT,
        ExecutionStage.VALIDATE_CITATIONS,
        ExecutionStage.RECORD_AND_RETURN,
    )
    assert contract_digest(plan) == contract_digest(make_plan())


def test_plan_rejects_dynamic_or_reordered_stages() -> None:
    with pytest.raises(ValidationError, match="fixed and ordered"):
        make_plan(stages=tuple(reversed(GROUND_DRAFT_STAGES)))
    with pytest.raises(ValidationError):
        make_plan(stages=(*GROUND_DRAFT_STAGES, "delegate"))


def test_idempotency_fingerprint_ignores_transport_metadata_but_binds_authority() -> None:
    request = make_request()
    retry = request.model_copy(
        update={"client_request_id": "browser-request-2", "correlation_id": "correlation-2"}
    )
    conflict = request.model_copy(update={"expected_context_digest": "c" * 64})
    changed_instruction = request.model_copy(update={"instruction": "Different grounded question"})

    assert idempotency_digest(request) == idempotency_digest(retry)
    assert idempotency_digest(request) != idempotency_digest(conflict)
    assert idempotency_digest(request) != idempotency_digest(changed_instruction)


def test_request_and_plan_are_immutable() -> None:
    request = make_request()
    plan = make_plan()
    with pytest.raises(ValidationError):
        request.__setattr__("action", ControlledAction.GENERATE_GROUNDED_DRAFT)
    with pytest.raises(ValidationError):
        plan.__setattr__("stages", GROUND_DRAFT_STAGES)

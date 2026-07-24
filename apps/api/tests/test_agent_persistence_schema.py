from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect

from opencanvas_api.db.models import (
    ControlledAgentApproval,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
    ControlledAgentCapabilityGrant,
    ControlledAgentContextSnapshot,
    ControlledAgentExecution,
    ControlledAgentExecutionState,
    ControlledAgentGrantRevocation,
    ControlledAgentPlanSnapshot,
    ControlledAgentPolicyDecision,
    ControlledAgentStateTransition,
)

AGENT_MODELS = (
    ControlledAgentExecution,
    ControlledAgentExecutionState,
    ControlledAgentStateTransition,
    ControlledAgentContextSnapshot,
    ControlledAgentPlanSnapshot,
    ControlledAgentCapabilityGrant,
    ControlledAgentGrantRevocation,
    ControlledAgentApproval,
    ControlledAgentPolicyDecision,
    ControlledAgentApprovalConsumption,
    ControlledAgentAuditEvent,
)


def _unique_columns(model: type[object]) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.columns.keys())
        for constraint in inspect(model).local_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_key_names(model: type[object]) -> set[str | None]:
    return {
        constraint.name
        for constraint in inspect(model).local_table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def test_all_controlled_agent_tables_pin_schema_version_and_ownership() -> None:
    for model in AGENT_MODELS:
        table = inspect(model).local_table
        assert {"user_id", "workspace_id"} <= set(table.c.keys())
        checks = " ".join(
            str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
        assert "controlled-agent-v1" in checks


def test_execution_children_use_composite_owner_scope_foreign_keys() -> None:
    assert "uq_agent_execution_scope" in {
        constraint.name for constraint in inspect(ControlledAgentExecution).local_table.constraints
    }
    assert "fk_agent_state_execution_scope" in _foreign_key_names(ControlledAgentExecutionState)
    assert "fk_agent_transition_execution_scope" in _foreign_key_names(
        ControlledAgentStateTransition
    )
    assert "fk_agent_context_execution_scope" in _foreign_key_names(ControlledAgentContextSnapshot)
    assert "fk_agent_plan_execution_scope" in _foreign_key_names(ControlledAgentPlanSnapshot)
    assert "fk_agent_grant_execution_scope" in _foreign_key_names(ControlledAgentCapabilityGrant)


def test_revocation_and_consumption_are_separate_one_time_records() -> None:
    assert ("grant_id",) in _unique_columns(ControlledAgentGrantRevocation)
    assert ("approval_id",) in _unique_columns(ControlledAgentApprovalConsumption)
    assert {
        "fk_agent_consumption_approval_scope",
        "fk_agent_consumption_policy_scope",
    } <= _foreign_key_names(ControlledAgentApprovalConsumption)


def test_state_transitions_have_database_compare_and_set_boundaries() -> None:
    assert {
        ("state_id",),
        ("execution_id", "sequence"),
        ("execution_id", "predecessor_token"),
    } <= _unique_columns(ControlledAgentStateTransition)

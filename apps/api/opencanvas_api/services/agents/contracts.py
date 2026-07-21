from __future__ import annotations

import hashlib
import json
import math
import unicodedata
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Literal["controlled-agent-v1"] = "controlled-agent-v1"
Digest = str


class AgentRole(StrEnum):
    UNIVERSE_COORDINATOR = "universe_coordinator"
    GALAXY_ANALYST = "galaxy_analyst"
    SOLAR_SYSTEM_RESEARCHER = "solar_system_researcher"
    PLANET_SPECIALIST = "planet_specialist"
    EVIDENCE_VERIFIER = "evidence_verifier"
    DRAFTING_ASSISTANT = "drafting_assistant"
    CONTROLLED_ACTION_EXECUTOR = "controlled_action_executor"


class Capability(StrEnum):
    WORKSPACE_METADATA_READ = "workspace.metadata.read"
    CANVAS_SNAPSHOT_READ = "canvas.snapshot.read"
    CONTEXT_SELECTED_READ = "context.selected.read"
    DOCUMENT_VERSION_READ = "document.version.read"
    TRACE_SCOPED_READ = "trace.scoped.read"
    RETRIEVAL_SELECTED_SEARCH = "retrieval.selected.search"
    DRAFT_NOTE_CREATE = "draft.note.create"
    DRAFT_ANSWER_CREATE = "draft.answer.create"
    CANVAS_NOTE_CREATE = "canvas.note.create"
    CANVAS_NOTE_UPDATE = "canvas.note.update"
    EXECUTION_CANCEL = "execution.cancel"


class ResourceKind(StrEnum):
    WORKSPACE = "workspace"
    CANVAS = "canvas"
    NODE = "node"
    DOCUMENT_VERSION = "document_version"
    CHUNK = "chunk"
    TRACE = "trace"


class RiskClass(StrEnum):
    R0_OBSERVATION = "r0_observation"
    R1_DRAFT = "r1_draft"
    R2_TRANSIENT_ACTION = "r2_transient_action"
    R3_DURABLE_WRITE = "r3_durable_write"
    R4_PROHIBITED = "r4_prohibited"


class ExecutionStatus(StrEnum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DENIED = "denied"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class ContractModel(BaseModel):
    """Frozen, strict value object suitable for an append-only persistence boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return value.astimezone(UTC)


class ResourceScope(ContractModel):
    kind: ResourceKind
    resource_id: uuid.UUID
    version: int | None = Field(default=None, ge=1)


class ContextResource(ContractModel):
    scope: ResourceScope
    content_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")


class ContextSnapshot(ContractModel):
    contract_kind: Literal["context_snapshot"] = "context_snapshot"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    snapshot_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    captured_at: datetime
    resources: tuple[ContextResource, ...] = Field(min_length=1)
    exclusions: tuple[ResourceScope, ...] = ()

    _captured_at_is_utc = field_validator("captured_at")(_require_aware_utc)


class PlanAction(ContractModel):
    action_id: uuid.UUID
    ordinal: int = Field(ge=0)
    capability: Capability
    resource: ResourceScope
    risk_class: RiskClass
    expected_result_digest: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PlanSnapshot(ContractModel):
    contract_kind: Literal["plan_snapshot"] = "plan_snapshot"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    plan_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    role: AgentRole
    created_at: datetime
    actions: tuple[PlanAction, ...] = Field(min_length=1)

    _created_at_is_utc = field_validator("created_at")(_require_aware_utc)

    @model_validator(mode="after")
    def actions_are_unique_and_ordered(self) -> Self:
        ids = tuple(action.action_id for action in self.actions)
        ordinals = tuple(action.ordinal for action in self.actions)
        if len(set(ids)) != len(ids):
            raise ValueError("plan action IDs must be unique")
        if ordinals != tuple(range(len(self.actions))):
            raise ValueError("plan action ordinals must be contiguous and ordered")
        return self


class CapabilityGrant(ContractModel):
    contract_kind: Literal["capability_grant"] = "capability_grant"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    grant_id: uuid.UUID
    policy_version: str = Field(min_length=1, max_length=64)
    issuing_service: str = Field(min_length=1, max_length=128)
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    role: AgentRole
    capabilities: tuple[Capability, ...] = Field(min_length=1)
    resources: tuple[ResourceScope, ...] = Field(min_length=1)
    context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    approval_required: bool = False
    approval_id: uuid.UUID | None = None

    _grant_times_are_utc = field_validator("issued_at", "expires_at")(_require_aware_utc)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_canonical(cls, value: tuple[Capability, ...]) -> tuple[Capability, ...]:
        return tuple(sorted(set(value), key=str))

    @field_validator("resources")
    @classmethod
    def resources_are_canonical(cls, value: tuple[ResourceScope, ...]) -> tuple[ResourceScope, ...]:
        return tuple(sorted(set(value), key=_resource_sort_key))

    @model_validator(mode="after")
    def validity_and_approval_are_coherent(self) -> Self:
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must follow issuance")
        if self.approval_required != (self.approval_id is not None):
            raise ValueError("approval-required grants must bind exactly one approval ID")
        return self


class ApprovalRecord(ContractModel):
    contract_kind: Literal["approval_record"] = "approval_record"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    approval_id: uuid.UUID
    session_id: uuid.UUID
    policy_version: str = Field(min_length=1, max_length=64)
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    grant_id: uuid.UUID
    decision: ApprovalDecision
    capabilities: tuple[Capability, ...] = Field(min_length=1)
    resources: tuple[ResourceScope, ...] = Field(min_length=1)
    context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    decided_at: datetime
    expires_at: datetime

    _approval_times_are_utc = field_validator("decided_at", "expires_at")(_require_aware_utc)

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_canonical(cls, value: tuple[Capability, ...]) -> tuple[Capability, ...]:
        return tuple(sorted(set(value), key=str))

    @field_validator("resources")
    @classmethod
    def resources_are_canonical(cls, value: tuple[ResourceScope, ...]) -> tuple[ResourceScope, ...]:
        return tuple(sorted(set(value), key=_resource_sort_key))

    @model_validator(mode="after")
    def expiry_follows_decision(self) -> Self:
        if self.expires_at <= self.decided_at:
            raise ValueError("approval expiry must follow its decision")
        return self


class RevocationRecord(ContractModel):
    contract_kind: Literal["revocation_record"] = "revocation_record"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    revocation_id: uuid.UUID
    subject_kind: Literal["grant", "approval"]
    subject_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    execution_id: uuid.UUID
    revoked_at: datetime
    reason_code: str = Field(min_length=1, max_length=64)

    _revoked_at_is_utc = field_validator("revoked_at")(_require_aware_utc)


class ExecutionRecord(ContractModel):
    contract_kind: Literal["execution_record"] = "execution_record"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: AgentRole
    context_snapshot_id: uuid.UUID
    context_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    plan_id: uuid.UUID
    plan_digest: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    grant_id: uuid.UUID
    created_at: datetime

    _created_at_is_utc = field_validator("created_at")(_require_aware_utc)


class ExecutionStateRecord(ContractModel):
    contract_kind: Literal["execution_state_record"] = "execution_state_record"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    state_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    status: ExecutionStatus
    recorded_at: datetime
    safe_reason_code: str | None = Field(default=None, max_length=64)

    _recorded_at_is_utc = field_validator("recorded_at")(_require_aware_utc)


class AuditAttribute(ContractModel):
    key: str = Field(min_length=1, max_length=64)
    value: str | int | bool | None


class AuditEvent(ContractModel):
    contract_kind: Literal["audit_event"] = "audit_event"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    event_id: uuid.UUID
    trace_id: uuid.UUID
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: str = Field(min_length=1, max_length=128)
    recorded_at: datetime
    attributes: tuple[AuditAttribute, ...] = ()

    _recorded_at_is_utc = field_validator("recorded_at")(_require_aware_utc)


class PolicyDecision(ContractModel):
    contract_kind: Literal["policy_decision"] = "policy_decision"
    schema_version: Literal["controlled-agent-v1"] = SCHEMA_VERSION
    decision_id: uuid.UUID
    policy_version: str = Field(min_length=1, max_length=64)
    execution_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    outcome: PolicyOutcome
    reason_code: str = Field(min_length=1, max_length=64)
    evaluated_at: datetime
    grant_id: uuid.UUID | None = None
    approval_id: uuid.UUID | None = None
    context_digest: Digest
    plan_digest: Digest

    _evaluated_at_is_utc = field_validator("evaluated_at")(_require_aware_utc)


def _resource_sort_key(scope: ResourceScope) -> tuple[str, str, int]:
    return (scope.kind.value, str(scope.resource_id), scope.version or 0)


def canonical_json(contract: ContractModel) -> str:
    """Return a stable, UTF-8 JSON representation of a controlled-agent contract."""

    normalized = _normalize(contract.model_dump(mode="python"))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_digest(contract: ContractModel) -> Digest:
    """Hash a contract with explicit schema and kind domain separation."""

    kind = str(getattr(contract, "contract_kind", contract.__class__.__name__))
    version = str(getattr(contract, "schema_version", SCHEMA_VERSION))
    payload = f"opencanvas:{version}:{kind}\n{canonical_json(contract)}".encode()
    return hashlib.sha256(payload).hexdigest()


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return unicodedata.normalize("NFC", value) if isinstance(value, str) else value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical payloads cannot contain non-finite numbers")
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        utc_value = _require_aware_utc(value)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {_normalize(str(key)): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


__all__ = [
    "AgentRole",
    "ApprovalDecision",
    "ApprovalRecord",
    "AuditAttribute",
    "AuditEvent",
    "Capability",
    "CapabilityGrant",
    "ContextResource",
    "ContextSnapshot",
    "ContractModel",
    "ExecutionRecord",
    "ExecutionStateRecord",
    "ExecutionStatus",
    "PlanAction",
    "PlanSnapshot",
    "PolicyDecision",
    "PolicyOutcome",
    "ResourceKind",
    "ResourceScope",
    "RevocationRecord",
    "RiskClass",
    "canonical_json",
    "contract_digest",
]

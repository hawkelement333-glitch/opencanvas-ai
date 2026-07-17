from __future__ import annotations

from enum import StrEnum


class LifecycleState(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.CREATED: frozenset({LifecycleState.ACTIVE, LifecycleState.DELETED}),
    LifecycleState.ACTIVE: frozenset({LifecycleState.ARCHIVED, LifecycleState.DELETED}),
    LifecycleState.ARCHIVED: frozenset({LifecycleState.ACTIVE, LifecycleState.DELETED}),
    LifecycleState.DELETED: frozenset(),
}


class CanonicalDomainError(RuntimeError):
    """Safe base error for canonical-domain operations."""

    code = "canonical_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = message
        self.code = code or type(self).code


class CanonicalValidationError(CanonicalDomainError):
    code = "canonical_validation_failed"


class CanonicalNotFoundError(CanonicalDomainError):
    code = "canonical_not_found"


class WorkspaceBoundaryError(CanonicalNotFoundError):
    """Uses not-found semantics so cross-workspace identifiers are not disclosed."""

    code = "canonical_not_found"


class CanonicalConflictError(CanonicalDomainError):
    code = "canonical_conflict"


class CanonicalStorageError(CanonicalDomainError):
    code = "canonical_storage_failed"


class InvalidLifecycleTransition(CanonicalConflictError):
    code = "invalid_lifecycle_transition"

    def __init__(self, current: LifecycleState, target: LifecycleState) -> None:
        super().__init__(f"Cannot transition a canonical object from {current} to {target}.")
        self.current = current
        self.target = target


def allowed_transitions(state: LifecycleState | str) -> frozenset[LifecycleState]:
    try:
        normalized = LifecycleState(state)
    except ValueError as exc:
        raise CanonicalValidationError(f"Unknown canonical lifecycle state: {state!s}.") from exc
    return _TRANSITIONS[normalized]


def ensure_transition(
    current: LifecycleState | str,
    target: LifecycleState | str,
) -> LifecycleState:
    try:
        normalized_current = LifecycleState(current)
        normalized_target = LifecycleState(target)
    except ValueError as exc:
        raise CanonicalValidationError("Canonical lifecycle state is invalid.") from exc
    if normalized_target not in _TRANSITIONS[normalized_current]:
        raise InvalidLifecycleTransition(normalized_current, normalized_target)
    return normalized_target

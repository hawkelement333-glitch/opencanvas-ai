"""The single ordered publication contract used by Milestone 7.7 production code."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final, NoReturn


class PublicationState(str, Enum):
    IMAGE_ADMITTED = "IMAGE_ADMITTED"
    LOCAL_IMAGE_VERIFIED = "LOCAL_IMAGE_VERIFIED"
    PUBLICATION_PATH_PROVED = "PUBLICATION_PATH_PROVED"
    ALREADY_PUSHED_RECONCILED = "ALREADY_PUSHED_RECONCILED"
    PUBLISHER_CREATED = "PUBLISHER_CREATED"
    UPLOAD_AUTHORITY_READY = "UPLOAD_AUTHORITY_READY"
    IMAGE_PUSHED = "IMAGE_PUSHED"
    IMMUTABLE_MANIFEST_PROVED = "IMMUTABLE_MANIFEST_PROVED"
    UPLOAD_AUTHORITY_REVOKED = "UPLOAD_AUTHORITY_REVOKED"
    FINALIZER_AUTHORITY_READY = "FINALIZER_AUTHORITY_READY"
    FINALIZER_AUTHENTICATION_PROVED = "FINALIZER_AUTHENTICATION_PROVED"
    SOURCE_TAG_REMOVED = "SOURCE_TAG_REMOVED"
    IMMUTABLE_MANIFEST_REPROVED = "IMMUTABLE_MANIFEST_REPROVED"
    PUBLISHER_FINALIZER_REVOKED = "PUBLISHER_FINALIZER_REVOKED"
    PUBLICATION_EVIDENCE_PERSISTED = "PUBLICATION_EVIDENCE_PERSISTED"
    PUBLICATION_COMPLETE = "PUBLICATION_COMPLETE"


class PublicationStateError(RuntimeError):
    """Sanitized fail-closed state-machine error."""


def _fail(code: str) -> NoReturn:
    raise PublicationStateError(code)


class PublicationMode(str, Enum):
    FRESH_UPLOAD = "FRESH_UPLOAD"
    ALREADY_PUSHED_RECONCILIATION = "ALREADY_PUSHED_RECONCILIATION"


FRESH_UPLOAD_ORDER: Final = tuple(
    state
    for state in PublicationState
    if state is not PublicationState.ALREADY_PUSHED_RECONCILED
)
ALREADY_PUSHED_RECONCILIATION_ORDER: Final = (
    PublicationState.IMAGE_ADMITTED,
    PublicationState.PUBLICATION_PATH_PROVED,
    PublicationState.ALREADY_PUSHED_RECONCILED,
    PublicationState.IMMUTABLE_MANIFEST_PROVED,
    PublicationState.UPLOAD_AUTHORITY_REVOKED,
    PublicationState.FINALIZER_AUTHORITY_READY,
    PublicationState.FINALIZER_AUTHENTICATION_PROVED,
    PublicationState.SOURCE_TAG_REMOVED,
    PublicationState.IMMUTABLE_MANIFEST_REPROVED,
    PublicationState.PUBLISHER_FINALIZER_REVOKED,
    PublicationState.PUBLICATION_EVIDENCE_PERSISTED,
    PublicationState.PUBLICATION_COMPLETE,
)
ALREADY_PUSHED_SOURCE_ABSENT_ORDER: Final = (
    PublicationState.IMAGE_ADMITTED,
    PublicationState.PUBLICATION_PATH_PROVED,
    PublicationState.ALREADY_PUSHED_RECONCILED,
    PublicationState.IMMUTABLE_MANIFEST_PROVED,
    PublicationState.UPLOAD_AUTHORITY_REVOKED,
    PublicationState.SOURCE_TAG_REMOVED,
    PublicationState.IMMUTABLE_MANIFEST_REPROVED,
    PublicationState.PUBLISHER_FINALIZER_REVOKED,
    PublicationState.PUBLICATION_EVIDENCE_PERSISTED,
    PublicationState.PUBLICATION_COMPLETE,
)
# Compatibility alias for fresh-upload regression fixtures.
ORDER: Final = FRESH_UPLOAD_ORDER
CANONICAL_PUBLICATION_ENTRY_POINTS: Final = {
    "publish-api-image": "api_image_publication._publish_api_image_stage",
    "post-secret-provisioning": "requires-published-manifest-state",
    "downstream-deployment": "requires-published-manifest-state",
    "reconcile-already-pushed-publication": "api_image_publication._publish_api_image",
    "paused-preserved": "reconcile-already-pushed-publication",
    "failure-closeout": "outermost-revocation-and-cleanup",
    "cleanup-only": "no-publication-transition",
}


@dataclass
class PublicationStateMachine:
    """Reject skipped, duplicate, or out-of-order publication transitions."""

    completed: list[PublicationState] = field(default_factory=list)
    mode: PublicationMode = PublicationMode.FRESH_UPLOAD
    source_tag_present: bool = True

    @property
    def order(self) -> tuple[PublicationState, ...]:
        if self.mode is PublicationMode.FRESH_UPLOAD:
            return FRESH_UPLOAD_ORDER
        return (
            ALREADY_PUSHED_RECONCILIATION_ORDER
            if self.source_tag_present
            else ALREADY_PUSHED_SOURCE_ABSENT_ORDER
        )

    def advance(self, state: PublicationState) -> None:
        expected_index = len(self.completed)
        if expected_index >= len(self.order):
            _fail("publication-transition-duplicate")
        if state is not self.order[expected_index]:
            _fail("publication-transition-out-of-order")
        self.completed.append(state)

    def assert_complete(self) -> None:
        if tuple(self.completed) != self.order:
            _fail("publication-transition-incomplete")


def simulate_current_image_publication(
    *, oauth_responses: tuple[int, ...], post_delete_tags: object
) -> tuple[PublicationState, ...]:
    """Pure local regression fixture for the canonical current-image path."""
    if not oauth_responses or oauth_responses[-1] != 200:
        _fail("finalizer-oauth-propagation-unproved")
    if any(status not in {200, 401, 403} for status in oauth_responses):
        _fail("finalizer-oauth-response-invalid")
    if post_delete_tags is not None and post_delete_tags not in ((), []):
        _fail("post-delete-tags-normalization-invalid")
    machine = PublicationStateMachine()
    for state in ORDER[:9]:
        machine.advance(state)
    # The same finalizer identity remains in use while transient 401/403
    # responses converge.  Only the later 200 may enter authenticated state.
    machine.advance(PublicationState.FINALIZER_AUTHENTICATION_PROVED)
    for state in ORDER[10:]:
        machine.advance(state)
    machine.assert_complete()
    return tuple(machine.completed)

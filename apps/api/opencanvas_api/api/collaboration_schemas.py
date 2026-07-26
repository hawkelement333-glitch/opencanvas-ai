from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr, field_validator

from opencanvas_api.api.schemas import ApiModel

WorkspaceRole = Literal["owner", "administrator", "editor", "approver", "member", "viewer"]
InvitationRole = Literal["administrator", "editor", "approver", "member", "viewer"]
MembershipState = Literal["active", "suspended", "removed"]
InvitationState = Literal["pending", "accepted", "declined", "expired", "revoked"]

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9._:-]+$"


class InvitationCreate(ApiModel):
    recipient_email: str = Field(min_length=3, max_length=320)
    intended_role: InvitationRole
    expires_in_days: int = Field(default=7, ge=1, le=30)
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )

    @field_validator("recipient_email")
    @classmethod
    def trim_recipient_email(cls, value: str) -> str:
        return value.strip()


class InvitationCommand(ApiModel):
    idempotency_key: str = Field(
        min_length=8,
        max_length=128,
        pattern=IDEMPOTENCY_PATTERN,
    )


class InvitationCredentialCommand(InvitationCommand):
    token: SecretStr


class MembershipOut(ApiModel):
    membership_id: uuid.UUID
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: WorkspaceRole
    state: MembershipState
    authority_generation: int = Field(ge=1)
    accepted_invitation_id: uuid.UUID | None
    created_at: datetime
    state_recorded_at: datetime


class InvitationOut(ApiModel):
    invitation_id: uuid.UUID
    workspace_id: uuid.UUID
    recipient_email_masked: str
    intended_role: InvitationRole
    state: InvitationState
    expires_at: datetime
    created_at: datetime
    state_recorded_at: datetime
    duplicate: bool = False
    development_token: str | None = None


__all__ = [
    "InvitationCommand",
    "InvitationCreate",
    "InvitationCredentialCommand",
    "InvitationOut",
    "InvitationRole",
    "InvitationState",
    "MembershipOut",
    "MembershipState",
    "WorkspaceRole",
]

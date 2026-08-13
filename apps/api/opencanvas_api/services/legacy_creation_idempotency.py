from __future__ import annotations

import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from opencanvas_api.db.models import LegacyCreationRequestIdentity


class LegacyCreationOperation(StrEnum):
    CANVAS_CREATE = "canvas.create"
    NODE_CREATE = "node.create"
    NODE_DUPLICATE = "node.duplicate"
    EDGE_CREATE = "edge.create"


def request_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_request_identity(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    operation: LegacyCreationOperation,
    idempotency_key: str,
) -> LegacyCreationRequestIdentity | None:
    identity = await session.scalar(
        select(LegacyCreationRequestIdentity).where(
            LegacyCreationRequestIdentity.actor_user_id == actor_user_id,
            LegacyCreationRequestIdentity.operation == operation.value,
            LegacyCreationRequestIdentity.idempotency_key == idempotency_key,
        )
    )
    return identity


async def claim_request_identity(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    canvas_id: uuid.UUID | None,
    operation: LegacyCreationOperation,
    idempotency_key: str,
    digest: str,
    result_kind: str,
    result_id: uuid.UUID,
) -> bool:
    values = {
        "request_id": uuid.uuid4(),
        "actor_user_id": actor_user_id,
        "workspace_id": workspace_id,
        "canvas_id": canvas_id,
        "operation": operation.value,
        "idempotency_key": idempotency_key,
        "request_digest": digest,
        "result_kind": result_kind,
        "result_id": result_id,
    }
    if session.get_bind().dialect.name == "postgresql":
        postgresql_statement = (
            postgresql_insert(LegacyCreationRequestIdentity)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["actor_user_id", "operation", "idempotency_key"]
            )
            .returning(LegacyCreationRequestIdentity.request_id)
        )
        return await session.scalar(postgresql_statement) is not None
    sqlite_statement = (
        sqlite_insert(LegacyCreationRequestIdentity)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["actor_user_id", "operation", "idempotency_key"])
        .returning(LegacyCreationRequestIdentity.request_id)
    )
    return await session.scalar(sqlite_statement) is not None

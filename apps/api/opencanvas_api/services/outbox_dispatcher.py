"""Production runner for the existing activity-v1 consumer, not an external event bus.

The claim, consumer effect and acknowledgment use separate durable transactions.
This makes a lost acknowledgment observable without treating it as a lost effect.
No event payload leaves the database and no new receiver/product action is added.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from opencanvas_api.db.models import DomainActivityEntry, DomainEventOutbox, DomainEventRecord
from opencanvas_api.services.domain_events import (
    ACTIVITY_PROJECTION_VERSION,
    DomainEventConflictError,
    DomainEventOutboxService,
    DomainEventValidationError,
    OutboxClaim,
    OutboxOwnershipError,
)
from opencanvas_api.services.observability import OperationalTelemetry
from opencanvas_api.services.operational_observations import bind_operational_telemetry


@dataclass(frozen=True, slots=True)
class ActivityAcknowledgment:
    event_id: uuid.UUID
    activity_id: uuid.UUID


class DeliveryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    protocol: str = Field(pattern=r"^mobius-activity-delivery-v1$")
    outbox_id: uuid.UUID
    event_id: uuid.UUID
    owner_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=1)
    attempt_number: int = Field(ge=1, le=10)
    lease_expires_at: AwareDatetime

    def claim(self) -> OutboxClaim:
        return OutboxClaim(
            outbox_id=self.outbox_id,
            event_id=self.event_id,
            owner_id=self.owner_id,
            generation=self.generation,
            attempt_number=self.attempt_number,
            lease_expires_at=self.lease_expires_at,
        )


def delivery_bytes(claim: OutboxClaim) -> bytes:
    return (
        DeliveryEnvelope(
            protocol="mobius-activity-delivery-v1",
            outbox_id=claim.outbox_id,
            event_id=claim.event_id,
            owner_id=claim.owner_id,
            generation=claim.generation,
            attempt_number=claim.attempt_number,
            lease_expires_at=claim.lease_expires_at,
        )
        .model_dump_json()
        .encode()
    )


def acknowledgment_bytes(claim: OutboxClaim, receipt: ActivityAcknowledgment) -> bytes:
    return json.dumps(
        {
            "protocol": "mobius-activity-ack-v1",
            "outboxId": str(claim.outbox_id),
            "eventId": str(receipt.event_id),
            "generation": claim.generation,
            "activityId": str(receipt.activity_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def acknowledgment_signature(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class HttpActivityConsumer:
    """One exact private TLS receiver; no redirects, fallback, or transport retries."""

    def __init__(
        self, url: str, secret: str, *, timeout: float = 10, allow_loopback_http: bool = False
    ) -> None:
        parsed = urlparse(url)
        local = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/v1/activity-deliveries"
            or (
                parsed.scheme != "https"
                and not (allow_loopback_http and local and parsed.scheme == "http")
            )
            or len(secret) < 32
            or any(ord(character) < 33 or ord(character) > 126 for character in secret)
            or not 0 < timeout <= 20
        ):
            raise ValueError("Exact private TLS activity receiver and dedicated secret required.")
        self.url, self.secret, self.timeout = url, secret, timeout
        self.observations: deque[dict[str, int | str | None]] = deque(maxlen=32)

    async def deliver(self, claim: OutboxClaim) -> ActivityAcknowledgment:
        parsed = urlparse(self.url)
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or 443)
        if not addresses or any(
            not ipaddress.ip_address(str(row[4][0])).is_private for row in addresses
        ):
            raise DomainEventValidationError("Activity receiver must resolve privately.")
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self.timeout, trust_env=False, follow_redirects=False
                ) as client,
                client.stream(
                    "POST",
                    self.url,
                    content=delivery_bytes(claim),
                    headers={
                        "Authorization": "Bearer " + self.secret,
                        "Content-Type": "application/json",
                    },
                ) as response,
            ):
                response_content = bytearray()
                self.observations.append(
                    {"httpStatus": response.status_code, "transport": "response"}
                )
                if response.status_code == 200:
                    async for chunk in response.aiter_bytes():
                        response_content.extend(chunk)
                        if len(response_content) > 1024:
                            raise DomainEventValidationError("Activity response exceeds its bound.")
        except httpx.TransportError as exc:
            self.observations.append({"httpStatus": None, "transport": "connection_error"})
            raise OSError("Activity transport outcome requires reconciliation.") from exc
        if response.status_code == 409:
            raise OutboxOwnershipError()
        # Exact configured route only: private ACA ingress can return404 while
        # the stopped service is unavailable. Retry remains capped by the outbox;
        # absence is never an acknowledgment or a reason to switch destinations.
        if response.status_code == 404 or response.status_code >= 500:
            raise OSError("Activity receiver temporarily unavailable.")
        if response.status_code != 200 or len(response_content) > 1024:
            raise DomainEventValidationError("Activity receiver rejected delivery.")
        expected = ActivityAcknowledgment(
            claim.event_id, uuid.uuid5(claim.event_id, ACTIVITY_PROJECTION_VERSION)
        )
        raw = acknowledgment_bytes(claim, expected)
        if response_content != raw or not hmac.compare_digest(
            response.headers.get("X-Activity-Acknowledgment", "").encode("utf-8"),
            acknowledgment_signature(raw, self.secret).encode("ascii"),
        ):
            raise DomainEventConflictError("Activity acknowledgment is not bound to this claim.")
        return expected


class ActivityConsumer(Protocol):
    async def deliver(self, claim: OutboxClaim) -> ActivityAcknowledgment: ...


class DurableActivityConsumer:
    """The established projection owns its durable receipt; delivery is idempotent."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions = sessions
        self.clock = clock

    async def deliver(self, claim: OutboxClaim) -> ActivityAcknowledgment:
        async with self.sessions() as session:
            service = DomainEventOutboxService(session, clock=self.clock)
            await service.validate_claim(claim)
            await service.project_activity(claim)
            # Keep the projection transactional if its SQL work crossed expiry.
            # No acknowledgment can escape for an effect rolled back here.
            await service.validate_claim(claim)
            await session.commit()
        return ActivityAcknowledgment(
            event_id=claim.event_id,
            activity_id=uuid.uuid5(claim.event_id, ACTIVITY_PROJECTION_VERSION),
        )


class OutboxDispatcher:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        owner_id: str,
        consumer: ActivityConsumer | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        lease_seconds: int = 30,
        delivery_timeout_seconds: float = 10,
        telemetry: OperationalTelemetry | None = None,
    ) -> None:
        if not 0 < delivery_timeout_seconds < lease_seconds <= 300:
            raise ValueError("Delivery timeout must fit within the bounded lease.")
        self.sessions = sessions
        self.owner_id = owner_id
        self.clock = clock
        self.lease_seconds = lease_seconds
        self.delivery_timeout_seconds = delivery_timeout_seconds
        self.consumer = consumer or DurableActivityConsumer(sessions, clock=clock)
        self.telemetry = telemetry

    async def run_once(self, *, outbox_id: uuid.UUID | None = None) -> bool:
        with bind_operational_telemetry(self.telemetry):
            return await self._run_once(outbox_id=outbox_id)

    async def _run_once(self, *, outbox_id: uuid.UUID | None = None) -> bool:
        async with self.sessions() as session:
            service = DomainEventOutboxService(session, clock=self.clock)
            reconciled = await service.expire_exhausted(outbox_id=outbox_id)
            if reconciled is not None:
                await session.commit()
                if reconciled == "terminal_failure":
                    self._counter("mobius.outbox.terminal_failure")
                await self.observe()
                return True
            claim = await service.claim_one(
                owner_id=self.owner_id,
                lease_seconds=self.lease_seconds,
                outbox_id=outbox_id,
            )
            await session.commit()
        if claim is None:
            await self.observe()
            return False
        self._counter("mobius.outbox.attempts")
        try:
            async with asyncio.timeout(self.delivery_timeout_seconds):
                acknowledgment = await self.consumer.deliver(claim)
            async with self.sessions() as session:
                service = DomainEventOutboxService(session, clock=self.clock)
                await service.validate_claim(claim)
                await self._verify_receipt(session, claim, acknowledgment)
                await service.complete(claim)
                await session.commit()
        except OutboxOwnershipError:
            # A newer owner or expiry owns recovery. Never overwrite its state.
            pass
        except (DomainEventValidationError, DomainEventConflictError):
            await self._fail(claim, retryable=False)
        except (TimeoutError, OSError):
            # Consumer may already have committed. The next claim reconciles its
            # deterministic activity receipt before acknowledging the event.
            await self._fail(claim, retryable=True)
        await self.observe()
        return True

    async def _fail(self, claim: OutboxClaim, *, retryable: bool) -> None:
        async with self.sessions() as session:
            try:
                service = DomainEventOutboxService(session, clock=self.clock)
                await service.validate_claim(claim)
                row = await session.get(DomainEventOutbox, claim.outbox_id)
                if retryable and row is not None and row.attempt_count >= row.max_attempts:
                    expected = ActivityAcknowledgment(
                        claim.event_id, uuid.uuid5(claim.event_id, ACTIVITY_PROJECTION_VERSION)
                    )
                    try:
                        await self._verify_receipt(session, claim, expected)
                    except DomainEventConflictError:
                        pass
                    else:
                        await service.complete(claim)
                        await session.commit()
                        return
                state = await service.fail(
                    claim,
                    failure_classification="consumer_retryable"
                    if retryable
                    else "consumer_rejected",
                    retryable=retryable,
                )
                await session.commit()
                if state == "terminal_failure":
                    self._counter("mobius.outbox.terminal_failure")
            except OutboxOwnershipError:
                await session.rollback()

    @staticmethod
    async def _verify_receipt(
        session: AsyncSession, claim: OutboxClaim, acknowledgment: ActivityAcknowledgment
    ) -> None:
        expected_id = uuid.uuid5(claim.event_id, ACTIVITY_PROJECTION_VERSION)
        if acknowledgment.event_id != claim.event_id or acknowledgment.activity_id != expected_id:
            raise DomainEventConflictError("Consumer acknowledgment binding differs.")
        activity = await session.get(DomainActivityEntry, expected_id)
        event = await session.get(DomainEventRecord, claim.event_id)
        if activity is None or event is None:
            raise DomainEventConflictError("Consumer acknowledgment is not durable.")
        fields = (
            "event_id",
            "user_id",
            "workspace_id",
            "canvas_id",
            "sequence",
            "event_type",
            "subject_kind",
            "subject_id",
            "actor_user_id",
            "trace_id",
            "occurred_at",
        )
        if activity.projection_version != ACTIVITY_PROJECTION_VERSION or any(
            getattr(activity, field) != getattr(event, field) for field in fields
        ):
            raise DomainEventConflictError("Durable projection conflicts with its event.")

    def _counter(self, name: str) -> None:
        if self.telemetry is not None:
            self.telemetry.record_metric(
                name, 1, labels={"component": "outbox", "outcome": "success"}
            )

    async def observe(self) -> None:
        if self.telemetry is None:
            return
        async with self.sessions() as session:
            oldest = await session.scalar(
                select(func.min(DomainEventOutbox.created_at)).where(
                    DomainEventOutbox.delivery_state.in_(("pending", "delivering", "retry_wait"))
                )
            )
            backlog = await session.scalar(
                select(func.count())
                .select_from(DomainEventOutbox)
                .where(
                    DomainEventOutbox.delivery_state.in_(("pending", "delivering", "retry_wait"))
                )
            )
        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        age = 0.0 if oldest is None else max(0.0, (self.clock() - oldest).total_seconds())
        labels = {"component": "outbox", "outcome": "success"}
        self.telemetry.record_metric("mobius.outbox.oldest_age", age, labels=labels)
        self.telemetry.record_metric("mobius.outbox.backlog", backlog or 0, labels=labels)
        self.telemetry.schedule_flush()

    async def run_forever(self, *, poll_seconds: float, stop: asyncio.Event) -> None:
        if not 0.1 <= poll_seconds <= 60:
            raise ValueError("Outbox polling interval is outside the existing worker bound.")
        while not stop.is_set():
            await self.run_once()
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)

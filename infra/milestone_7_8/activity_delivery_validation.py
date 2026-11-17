"""Bounded actual-transport observations for the existing activity-v1 receiver.

The separately deployed dispatcher must be paused for these selected-row fault
fixtures. The receiver remains independent; no test endpoint or fabricated ACK
is added to production. Each operation requires the shared source-bound authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import ssl
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

import anyio
from sqlalchemy import func, select

from infra.milestone_7_8.pilot.helper_job_patch import admit_runtime_job
from infra.milestone_7_8.pilot_application_probe import (
    Journal,
    database,
    fixture_from,
    production_operation_telemetry,
    require,
)
from infra.milestone_7_8.pilot_validation import (
    _private_host,
    admit_runtime_bindings,
    authorize,
    digest,
    write_new,
)
from opencanvas_api.db.models import (
    DomainActivityEntry,
    DomainEventDeliveryAttempt,
    DomainEventOutbox,
)
from opencanvas_api.services.domain_events import (
    ACTIVITY_PROJECTION_VERSION,
    DomainEventOutboxService,
    OutboxOwnershipError,
)
from opencanvas_api.services.operational_observations import current_telemetry
from opencanvas_api.services.outbox_dispatcher import (
    ActivityAcknowledgment,
    HttpActivityConsumer,
    OutboxDispatcher,
    acknowledgment_bytes,
    acknowledgment_signature,
    delivery_bytes,
)

OPERATIONS = (
    "activity-delivery-happy",
    "activity-delivery-lost-ack",
    "activity-delivery-stale",
    "activity-delivery-outage",
    "activity-delivery-final-recovery",
    "activity-delivery-delay",
    "activity-delivery-partial-response",
    "activity-delivery-retry-load",
    "activity-delivery-network-delay",
)


def admit_component(plan: dict, readbacks: dict, key: str, *, state: str) -> str:
    expected = plan[key]
    require(
        expected.lower().startswith(
            plan["targetResourceGroupId"].lower() + "/providers/microsoft.app/containerapps/"
        ),
        "activity component outside approved scope",
    )
    records = [
        row
        for row in readbacks["resources"]
        if row.get("request", {}).get("resourceId", "").lower() == expected.lower()
    ]
    require(len(records) == 1, "one exact native activity component readback required")
    row = records[0]
    require(
        row["request"]["method"] == "GET"
        and row["request"]["apiVersion"] == "2025-01-01"
        and row["response"]["status"] == 200,
        "activity readback method/version/status differs",
    )
    body = row["response"]["body"]
    props = body["properties"]
    require(
        body["id"].lower() == expected.lower()
        and props.get("managedEnvironmentId", props.get("environmentId", "")).lower()
        == plan["managedEnvironmentResourceId"].lower()
        and props["runningStatus"] == state
        and bool(props["template"]["containers"])
        and all(
            c["image"].endswith("@" + plan["imageDigest"]) for c in props["template"]["containers"]
        ),
        "activity component state/environment/image is not the approved fixture",
    )
    if key == "activityDispatcherResourceId":
        return ""
    environment = next(
        row["response"]["body"]["properties"]
        for row in readbacks["resources"]
        if row["request"]["resourceId"].lower() == plan["managedEnvironmentResourceId"].lower()
    )
    ingress = props["configuration"]["ingress"]
    fqdn = ingress["fqdn"]
    name = expected.rsplit("/", 1)[-1]
    require(
        fqdn
        in {
            name + "." + environment["defaultDomain"],
            name + ".internal." + environment["defaultDomain"],
        }
        and ingress.get("allowInsecure") is not True,
        "receiver ingress not exact private HTTPS",
    )
    return "https://" + fqdn + "/v1/activity-deliveries"


async def pending_fixture(db, workspace: str, journal: Journal) -> uuid.UUID:
    async with db.sessions() as session:
        row = await session.scalar(
            select(DomainEventOutbox)
            .where(
                DomainEventOutbox.workspace_id == uuid.UUID(workspace),
                DomainEventOutbox.delivery_state == "pending",
                DomainEventOutbox.attempt_count == 0,
                DomainEventOutbox.max_attempts == 3,
            )
            .order_by(DomainEventOutbox.created_at, DomainEventOutbox.outbox_id)
            .limit(1)
        )
        require(
            row is not None,
            "core fixture lacks an unused actual production event with three attempts",
        )
        journal.step(
            "selected-existing-event",
            {"outboxId": str(row.outbox_id), "eventId": str(row.event_id)},
        )
        return row.outbox_id


async def claim_exact(db, outbox_id: uuid.UUID, owner: str, *, lease_seconds: int = 30):
    async with db.sessions() as session:
        claim = await DomainEventOutboxService(session).claim_one(
            owner_id=owner,
            outbox_id=outbox_id,
            lease_seconds=lease_seconds,
        )
        require(
            claim is not None and claim.outbox_id == outbox_id,
            "exact fixture no longer eligible",
        )
        await session.commit()
        return claim


async def state_of(db, outbox_id: uuid.UUID) -> dict:
    async with db.sessions() as session:
        row = await session.get(DomainEventOutbox, outbox_id)
        require(row is not None, "selected outbox vanished")
        count = await session.scalar(
            select(func.count())
            .select_from(DomainActivityEntry)
            .where(DomainActivityEntry.event_id == row.event_id)
        )
        attempts = (
            await session.scalars(
                select(DomainEventDeliveryAttempt.outcome)
                .where(DomainEventDeliveryAttempt.outbox_id == outbox_id)
                .order_by(DomainEventDeliveryAttempt.lease_generation)
            )
        ).all()
        return {
            "outboxId": str(outbox_id),
            "eventId": str(row.event_id),
            "state": row.delivery_state,
            "attemptCount": row.attempt_count,
            "receiptCount": count,
            "attemptOutcomes": list(attempts),
        }


async def disconnected_delivery(
    url: str, secret: str, claim, *, tls_context: ssl.SSLContext | None = None
) -> None:
    """Write a real authenticated TLS request, close without reading any ACK."""
    target = urlparse(url)
    require(
        target.scheme == "https" and target.hostname is not None,
        "verified TLS receiver required",
    )
    assert target.hostname is not None
    _private_host(target.hostname)
    raw = delivery_bytes(claim)
    async with asyncio.timeout(10):
        _, writer = await asyncio.open_connection(
            target.hostname,
            target.port or 443,
            ssl=tls_context or ssl.create_default_context(),
            server_hostname=target.hostname,
        )
        try:
            writer.write(
                (
                    f"POST {target.path} HTTP/1.1\r\nHost: {target.netloc}\r\n"
                    f"Authorization: Bearer {secret}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + raw
            )
            await writer.drain()
        finally:
            writer.close()
            with suppress(ConnectionError, ssl.SSLError):
                await writer.wait_closed()


async def partial_delivery(
    url: str, secret: str, claim, *, tls_context: ssl.SSLContext | None = None
) -> dict:
    """Read only a prefix of a real bound ACK; never accept partial delivery."""
    target = urlparse(url)
    require(
        target.scheme == "https"
        and target.hostname is not None
        and target.path == "/v1/activity-deliveries"
        and not target.query
        and not target.fragment
        and not target.username,
        "exact private verified TLS receiver required",
    )
    assert target.hostname is not None
    _private_host(target.hostname)
    expected = ActivityAcknowledgment(
        claim.event_id, uuid.uuid5(claim.event_id, ACTIVITY_PROJECTION_VERSION)
    )
    expected_body = acknowledgment_bytes(claim, expected)
    raw = delivery_bytes(claim)
    started = time.monotonic()
    async with asyncio.timeout(10):
        reader, writer = await asyncio.open_connection(
            target.hostname,
            target.port or 443,
            ssl=tls_context or ssl.create_default_context(),
            server_hostname=target.hostname,
            limit=8192,
        )
        try:
            writer.write(
                (
                    f"POST {target.path} HTTP/1.1\r\nHost: {target.netloc}\r\n"
                    f"Authorization: Bearer {secret}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                ).encode()
                + raw
            )
            await writer.drain()
            headers = await reader.readuntil(b"\r\n\r\n")
            require(len(headers) <= 8192, "response headers exceed bound")
            lines = headers.decode("ascii").split("\r\n")
            require(lines[0].split(" ")[1] == "200", "native receiver did not acknowledge")
            pairs = [line.split(":", 1) for line in lines[1:] if line]
            require(all(len(pair) == 2 for pair in pairs), "malformed response headers")
            fields = {name.lower(): value.strip() for name, value in pairs}
            require(len(fields) == len(pairs), "duplicate response headers")
            length = int(fields["content-length"])
            require(
                32 < length <= 1024
                and length == len(expected_body)
                and "transfer-encoding" not in fields,
                "bound ACK length required",
            )
            require(
                hmac.compare_digest(
                    fields.get("x-activity-acknowledgment", "").encode(),
                    acknowledgment_signature(expected_body, secret).encode(),
                ),
                "ACK binding differs",
            )
            prefix = await reader.readexactly(32)
            require(prefix == expected_body[:32], "actual ACK prefix differs")
            return {
                "faultScope": "client-response-truncation",
                "httpStatus": 200,
                "headerBytes": len(headers),
                "declaredBodyBytes": length,
                "receivedBodyBytes": len(prefix),
                "unreadBodyBytes": length - len(prefix),
                "receivedPrefixSha256": hashlib.sha256(prefix).hexdigest(),
                "elapsedSeconds": time.monotonic() - started,
                "deliveryAcceptance": "unproved-until-durable-reconciliation",
            }
        finally:
            writer.close()
            with suppress(ConnectionError, ssl.SSLError):
                await writer.wait_closed()


class DelayedAcknowledgment:
    """Finite client-side delay around the unmodified production transport."""

    def __init__(self, transport, *, delay_seconds: float, observations: list):
        require(0 < delay_seconds < 20, "client ACK delay must be below twenty seconds")
        self.transport, self.delay_seconds, self.observations = (
            transport,
            delay_seconds,
            observations,
        )

    async def deliver(self, claim):
        started = time.monotonic()
        ack = await self.transport.deliver(claim)
        acknowledged = time.monotonic()
        timed_out = False
        try:
            await asyncio.sleep(self.delay_seconds)
            return ack
        except asyncio.CancelledError:
            timed_out = True
            raise
        finally:
            self.observations.append(
                {
                    "faultScope": "client-verified-ack-delay",
                    "transportElapsedSeconds": acknowledged - started,
                    "actualAckHoldSeconds": time.monotonic() - acknowledged,
                    "requestedHoldSeconds": self.delay_seconds,
                    "cancelled": timed_out,
                    "serverLatencyClaim": False,
                }
            )


class PartialAcknowledgment:
    def __init__(self, transport, *, observations: list, tls_context=None):
        self.transport, self.observations, self.tls_context = transport, observations, tls_context

    async def deliver(self, claim):
        self.observations.append(
            await partial_delivery(
                self.transport.url, self.transport.secret, claim, tls_context=self.tls_context
            )
        )
        raise OSError("Actual ACK was only partially consumed; reconcile before retry.")


@asynccontextmanager
async def delayed_receiver_tcp(url: str, *, delay_seconds: float, observations: list):
    """One exclusive probe's opaque TLS relay; never terminate or re-sign TLS."""
    target = urlparse(url)
    require(
        target.scheme == "https"
        and target.hostname is not None
        and target.path == "/v1/activity-deliveries"
        and not target.query
        and not target.fragment
        and not target.username
        and 0 < delay_seconds < 20,
        "exact TLS endpoint and bounded delay required",
    )
    assert target.hostname is not None
    hostname, port = target.hostname, target.port or 443
    original_resolve = socket.getaddrinfo
    original_connect = anyio.connect_tcp
    addresses = await asyncio.to_thread(original_resolve, hostname, port, type=socket.SOCK_STREAM)
    require(
        bool(addresses)
        and all(ipaddress.ip_address(str(row[4][0])).is_private for row in addresses),
        "receiver resolution must be private",
    )
    family, _, _, _, address = next(
        (row for row in addresses if row[0] == socket.AF_INET), addresses[0]
    )
    began = time.monotonic()
    connection_count, byte_count, reserved_bytes = 0, 0, 0
    tasks = set()
    failure_classes = []

    async def relay(reader, writer):
        nonlocal connection_count, byte_count
        task = asyncio.current_task()
        tasks.add(task)
        connection_count += 1
        upstream_writer = None
        pumps = []
        try:
            require(connection_count <= 3, "relay connection cap exceeded")
            raw_socket = socket.socket(family, socket.SOCK_STREAM)
            raw_socket.setblocking(False)
            try:
                # Numeric sockaddr bypasses DNS; the upstream cannot loop back
                # through the temporary exact-host resolver hook.
                await asyncio.get_running_loop().sock_connect(raw_socket, address)
                upstream_reader, upstream_writer = await asyncio.open_connection(sock=raw_socket)
            except BaseException:
                raw_socket.close()
                raise

            async def forward(source, destination, direction):
                nonlocal byte_count, reserved_bytes
                while True:
                    allowance = min(4096, 65536 - byte_count - reserved_bytes)
                    require(allowance > 0 and len(observations) < 128, "relay read cap exhausted")
                    reserved_bytes += allowance
                    try:
                        chunk = await source.read(allowance)
                    finally:
                        reserved_bytes -= allowance
                    if not chunk:
                        return
                    received = time.monotonic()
                    byte_count += len(chunk)
                    require(
                        byte_count <= 65536 and len(observations) < 128,
                        "relay byte/observation cap exceeded",
                    )
                    sample = {
                        "direction": direction,
                        "bytes": len(chunk),
                        "receivedOffsetSeconds": received - began,
                        "forwardedOffsetSeconds": None,
                        "heldSeconds": 0.0,
                    }
                    observations.append(sample)
                    try:
                        if direction == "receiver-to-client":
                            await asyncio.sleep(delay_seconds)
                        destination.write(chunk)
                        await destination.drain()
                        sample["forwardedOffsetSeconds"] = time.monotonic() - began
                    finally:
                        sample["heldSeconds"] = time.monotonic() - received

            pumps = [
                asyncio.create_task(forward(reader, upstream_writer, "client-to-receiver")),
                asyncio.create_task(forward(upstream_reader, writer, "receiver-to-client")),
            ]
            done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
        except Exception as error:
            failure_classes.append(type(error).__name__)
        finally:
            for pump in pumps:
                pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream_writer):
                if stream is not None:
                    stream.close()
                    with suppress(ConnectionError, TimeoutError, ssl.SSLError):
                        await asyncio.wait_for(stream.wait_closed(), timeout=1)
            tasks.discard(task)

    server = await asyncio.start_server(relay, "127.0.0.1", 0)
    relay_port = server.sockets[0].getsockname()[1]

    def exact_resolve(host, service, family=0, type=0, proto=0, flags=0):
        decoded = host.decode("ascii") if isinstance(host, bytes) else host
        if decoded == hostname and service in (port, str(port)):
            return original_resolve("127.0.0.1", relay_port, family, type, proto, flags)
        return original_resolve(host, service, family, type, proto, flags)

    async def exact_connect(remote_host, remote_port, **kwargs):
        # AnyIO deliberately ignores sockaddr ports returned by getaddrinfo.
        # Redirect only this connection, leaving HTTPcore's original-host TLS
        # handshake intact. Direct AnyIO TLS callers retain that hostname too.
        if str(remote_host) == hostname and remote_port == port:
            if kwargs.get("tls") or kwargs.get("ssl_context") or kwargs.get("tls_hostname"):
                kwargs["tls_hostname"] = hostname
            return await original_connect("127.0.0.1", relay_port, **kwargs)
        return await original_connect(remote_host, remote_port, **kwargs)

    summary = {
        "faultScope": "opaque-tcp-receiver-to-client-delay",
        "requestedDelaySeconds": delay_seconds,
        "maximumConnections": 3,
        "maximumBytes": 65536,
        "maximumLifetimeSeconds": 20,
        "tlsTerminated": False,
        "serverLatencyClaim": False,
    }
    socket.getaddrinfo = exact_resolve
    anyio.connect_tcp = exact_connect
    try:
        async with asyncio.timeout(20):
            yield summary
    finally:
        socket.getaddrinfo = original_resolve
        anyio.connect_tcp = original_connect
        server.close()
        active = list(tasks)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        await asyncio.wait_for(server.wait_closed(), timeout=1)
        summary.update(
            {
                "actualConnections": connection_count,
                "actualBytes": byte_count,
                "elapsedSeconds": time.monotonic() - began,
                "resolverRestored": socket.getaddrinfo is original_resolve,
                "connectorRestored": anyio.connect_tcp is original_connect,
                "listenerClosed": not server.is_serving(),
                "failureClasses": failure_classes,
            }
        )


async def exercise(
    db, fixture: dict, journal: Journal, transport: HttpActivityConsumer, operation: str
) -> dict:
    journal.check_time()
    selected = await pending_fixture(db, fixture["workspaceId"], journal)
    worker = OutboxDispatcher(
        db.sessions,
        owner_id="proof-" + journal.header["executionId"],
        consumer=transport,
        telemetry=current_telemetry(),
    )
    if operation == "activity-delivery-retry-load":
        async with db.sessions() as session:
            selected_rows = list(
                await session.scalars(
                    select(DomainEventOutbox.outbox_id)
                    .where(
                        DomainEventOutbox.workspace_id == uuid.UUID(fixture["workspaceId"]),
                        DomainEventOutbox.delivery_state == "pending",
                        DomainEventOutbox.attempt_count == 0,
                        DomainEventOutbox.max_attempts == 3,
                    )
                    .order_by(DomainEventOutbox.created_at, DomainEventOutbox.outbox_id)
                    .limit(3)
                )
            )
        require(len(selected_rows) == 3, "three exact unused production events required")
        journal.step(
            "retry-load-selected",
            {
                "outboxIds": [str(item) for item in selected_rows],
                "concurrency": 3,
                "maximumAttemptsEach": 3,
            },
        )
        return await retry_load(db, selected_rows, transport, journal)
    if operation == "activity-delivery-network-delay":
        packet_observations: list[dict] = []
        async with delayed_receiver_tcp(
            transport.url, delay_seconds=11, observations=packet_observations
        ) as relay:
            await worker.run_once(outbox_id=selected)
        before = await state_of(db, selected)
        require(
            before["state"] == "retry_wait"
            and before["attemptCount"] == 1
            and before["receiptCount"] in (0, 1),
            "delayed transport was not fail-closed",
        )
        require(
            relay["resolverRestored"]
            and relay["connectorRestored"]
            and relay["elapsedSeconds"] <= 20
            and relay["listenerClosed"]
            and not relay["failureClasses"]
            and any(
                item["direction"] == "receiver-to-client" and item["heldSeconds"] > 0
                for item in packet_observations
            ),
            "actual bounded network delay absent",
        )
        journal.step(
            "network-delay-reconciled",
            {"observed": before, "relay": relay, "packetTimings": packet_observations},
        )
        await asyncio.sleep(1.1)
        await worker.run_once(outbox_id=selected)
        after = await state_of(db, selected)
        require(
            after["state"] == "delivered"
            and after["receiptCount"] == 1
            and after["attemptCount"] == 2,
            "normal delivery did not recover one exact effect",
        )
        return {
            "assertions": {operation: "accepted"},
            "observed": after,
            "relay": relay,
            "packetTimings": packet_observations,
            "scope": "actual opaque TCP delay at client boundary",
        }
    if operation in {"activity-delivery-delay", "activity-delivery-partial-response"}:
        observations: list[dict] = []
        fault = (
            DelayedAcknowledgment(transport, delay_seconds=11, observations=observations)
            if operation == "activity-delivery-delay"
            else PartialAcknowledgment(transport, observations=observations)
        )
        affected = OutboxDispatcher(
            db.sessions, owner_id="proof-fault", consumer=fault, telemetry=current_telemetry()
        )
        await affected.run_once(outbox_id=selected)
        before = await state_of(db, selected)
        require(
            before["state"] == "retry_wait" and before["receiptCount"] == 1,
            "fault did not preserve one durable effect awaiting acknowledgment",
        )
        require(bool(observations), "actual transport fault observation absent")
        journal.step(
            "uncertain-transport-reconciled", {"observed": before, "transportFault": observations}
        )
        await asyncio.sleep(1.1)
        await worker.run_once(outbox_id=selected)
        after = await state_of(db, selected)
        require(
            after["state"] == "delivered"
            and after["receiptCount"] == 1
            and after["attemptCount"] == 2,
            "recovery duplicated effect or did not acknowledge",
        )
        return {
            "assertions": {operation: "accepted"},
            "observed": after,
            "transportFault": observations,
            "scope": "client transport boundary only",
        }
    if operation == "activity-delivery-happy":
        claim = await claim_exact(db, selected, "proof-happy")
        first, again = await transport.deliver(claim), await transport.deliver(claim)
        require(first == again, "duplicate transport returned another receipt")
        async with db.sessions() as session:
            await worker._verify_receipt(session, claim, first)
            await DomainEventOutboxService(session).complete(claim)
            await session.commit()
    elif operation == "activity-delivery-lost-ack":
        claim = await claim_exact(db, selected, "proof-lost-ack")
        journal.step("disconnect-before-ack", {"outboxId": str(selected)})
        await disconnected_delivery(transport.url, transport.secret, claim)
        for _ in range(20):
            if (await state_of(db, selected))["receiptCount"] == 1:
                break
            await asyncio.sleep(0.25)
        require(
            (await state_of(db, selected))["receiptCount"] == 1,
            "receiver did not durably commit after disconnected request; loss case unproved",
        )
        async with db.sessions() as session:
            await DomainEventOutboxService(session).fail(
                claim, failure_classification="consumer_retryable", retryable=True
            )
            await session.commit()
        await asyncio.sleep(1.1)
        await worker.run_once(outbox_id=selected)
    elif operation == "activity-delivery-stale":
        stale = await claim_exact(db, selected, "proof-stale", lease_seconds=1)
        await asyncio.sleep(1.1)
        current = await claim_exact(db, selected, "proof-current")
        try:
            await transport.deliver(stale)
        except OutboxOwnershipError:
            pass
        else:
            raise ValueError("receiver accepted an obsolete claim")
        require(
            (await state_of(db, selected))["receiptCount"] == 0,
            "obsolete claim produced an effect",
        )
        ack = await transport.deliver(current)
        async with db.sessions() as session:
            await worker._verify_receipt(session, current, ack)
            await DomainEventOutboxService(session).complete(current)
            await session.commit()
    elif operation == "activity-delivery-outage":
        # Receiver is natively read back Stopped. Its actual routing response,
        # not a stubbed exception, must drive the production retry policy.
        for delay in (1.1, 2.1, 0):
            journal.check_time()
            await worker.run_once(outbox_id=selected)
            if delay:
                await asyncio.sleep(delay)
        state = await state_of(db, selected)
        require(
            state["state"] == "terminal_failure"
            and state["attemptCount"] == 3
            and state["receiptCount"] == 0
            and state["attemptOutcomes"]
            == ["retry_scheduled", "retry_scheduled", "terminal_failure"],
            "actual outage did not demonstrate the bounded retry/terminal contract",
        )
        return {
            "assertions": {"actualTransportRetryAndTerminal": "accepted"},
            "observed": state,
        }
    else:
        results = []
        for committed in (False, True):
            if committed:
                selected = await pending_fixture(db, fixture["workspaceId"], journal)
            for attempt in range(3):
                claim = await claim_exact(db, selected, "proof-abandoned-final", lease_seconds=5)
                if committed and attempt == 2:
                    await transport.deliver(claim)
                await asyncio.sleep(5.1)
                journal.check_time()
            await worker.run_once(outbox_id=selected)
            state = await state_of(db, selected)
            require(
                state["attemptCount"] == 3
                and state["receiptCount"] == int(committed)
                and state["state"] == ("delivered" if committed else "terminal_failure"),
                "abandoned final attempt was not reconciled against its actual durable effect",
            )
            results.append(state)
        return {
            "assertions": {"abandonedFinalAttemptRecovery": "accepted"},
            "observed": results,
        }
    state = await state_of(db, selected)
    require(
        state["state"] == "delivered" and state["receiptCount"] == 1,
        "delivery did not produce exactly one durable acknowledged activity",
    )
    return {"assertions": {operation: "accepted"}, "observed": state}


async def retry_load(db, selected_rows: list, transport, journal) -> dict:
    require(
        len(selected_rows) == len(set(selected_rows)) == 3, "exact three-event retry load required"
    )
    workers = [
        OutboxDispatcher(
            db.sessions,
            owner_id=f"proof-load-{index}",
            consumer=transport,
            telemetry=current_telemetry(),
        )
        for index in range(3)
    ]
    started = time.monotonic()
    rounds = []
    for index, delay in enumerate((1.1, 2.1, 0)):
        journal.check_time()
        began = time.monotonic()
        active, peak = 0, 0
        operation_times: list[dict] = []

        async def invoke(worker, selected, *, timings=operation_times, round_started=began):
            nonlocal active, peak
            entered = time.monotonic()
            active += 1
            peak = max(peak, active)
            try:
                return await worker.run_once(outbox_id=selected)
            finally:
                active -= 1
                timings.append(
                    {
                        "outboxId": str(selected),
                        "startedOffsetSeconds": entered - round_started,
                        "elapsedSeconds": time.monotonic() - entered,
                    }
                )

        values = await asyncio.gather(
            *(
                invoke(worker, selected)
                for worker, selected in zip(workers, selected_rows, strict=True)
            )
        )
        require(all(values), "exact retry-load event could not be claimed")
        require(1 < peak <= 3, "concurrent delivery operations were not observed")
        rounds.append(
            {
                "round": index + 1,
                "concurrentEvents": 3,
                "observedPeakDeliveryOperations": peak,
                "operationTimings": operation_times,
                "elapsedSeconds": time.monotonic() - began,
            }
        )
        if delay:
            await asyncio.sleep(delay)
    states = [await state_of(db, item) for item in selected_rows]
    require(
        all(
            state["state"] == "terminal_failure"
            and state["attemptCount"] == 3
            and state["receiptCount"] == 0
            and state["attemptOutcomes"]
            == ["retry_scheduled", "retry_scheduled", "terminal_failure"]
            for state in states
        ),
        "bounded concurrent retry load did not retain exact terminal effects",
    )
    return {
        "assertions": {"boundedConcurrentTransportRetries": "accepted"},
        "observed": states,
        "rounds": rounds,
        "elapsedSeconds": time.monotonic() - started,
        "attemptBudget": 9,
        "scope": "three concurrent delivery operations; no population extrapolation",
    }


async def run(args: argparse.Namespace) -> dict:
    _, plan, deadline = authorize(args.bundle, args.authorization, args.bindings, args.operation)
    require(
        args.execute and args.execution_id == os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
        "actual authorized managed execution required",
    )
    readbacks = json.loads(args.runtime_readbacks.read_text())
    admit_runtime_bindings(plan, readbacks, plan_sha256=digest(args.bindings))
    job_binding = admit_runtime_job(
        plan,
        readbacks,
        key="activityDeliveryJobResourceId",
        role="worker",
        execution=args.execution_id,
    )
    admit_component(plan, readbacks, "activityDispatcherResourceId", state="Stopped")
    url = admit_component(
        plan,
        readbacks,
        "activityReceiverResourceId",
        state="Stopped"
        if args.operation in {"activity-delivery-outage", "activity-delivery-retry-load"}
        else "Running",
    )
    journal = Journal(args.output, args.execution_id, args.operation, plan, deadline)
    fixture = fixture_from(args.fixture, plan)
    db, settings = database(plan, restored=False, worker=True)
    require(
        settings.outbox_delivery_secret is not None,
        "dedicated delivery credential missing",
    )
    transport = HttpActivityConsumer(url, settings.outbox_delivery_secret.get_secret_value())
    try:
        async with production_operation_telemetry(settings, plan):
            result = await exercise(db, fixture, journal, transport, args.operation)
        result["jobBinding"] = job_binding
        result["telemetrySource"] = {
            "sourceKind": "source-bound-production-service-probe",
            "service": "mobius-worker",
            "destinationAcceptance": "unproved",
        }
        result["nativeHttpObservations"] = list(transport.observations)
        return journal.finish(result)
    finally:
        await db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    for name in (
        "bundle",
        "authorization",
        "bindings",
        "runtime-readbacks",
        "output",
        "fixture",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as error:
        if not args.output.exists():
            write_new(
                args.output,
                {
                    "operation": args.operation,
                    "status": "failed",
                    "errorClass": type(error).__name__,
                    "managedAcceptance": "unproved",
                    "reconcileBeforeRetry": True,
                },
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

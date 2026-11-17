from __future__ import annotations

import asyncio
import os
import shutil
import socket
import ssl
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from apps.api.tests.test_domain_events import _command, _scope
from sqlalchemy import func, select

from opencanvas_api.core.config import DatabaseRole, Settings
from opencanvas_api.db.models import (
    DomainActivityEntry,
    DomainEventDeliveryAttempt,
    DomainEventOutbox,
)
from opencanvas_api.db.role_privileges import RUNTIME_TABLE_PRIVILEGES
from opencanvas_api.services.domain_events import DomainEventOutboxService, DomainEventService
from opencanvas_api.services.outbox_dispatcher import (
    ActivityAcknowledgment,
    DurableActivityConsumer,
    HttpActivityConsumer,
    OutboxDispatcher,
    delivery_bytes,
)

SECRET = "local-receiver-test-authority-2026-separate-secret"


async def seed(database, *, attempts=3):
    canvas, execution = await _scope(database)
    async with database.sessions() as session:
        result = await DomainEventService(session).record(
            _command(
                "graph.relationship.created",
                canvas_id=canvas,
                execution_id=execution,
                max_attempts=attempts,
            )
        )
        await session.commit()
        return result.outbox.outbox_id


@asynccontextmanager
async def receiver(database, *, certificate=None, private_key=None):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("OPENCANVAS_")}
    env.update(
        {
            "OPENCANVAS_APP_MODE": "test",
            "OPENCANVAS_ENVIRONMENT": "test",
            "OPENCANVAS_DATABASE_URL": str(database.engine.url),
            "OPENCANVAS_DATABASE_ROLE": "worker",
            "OPENCANVAS_OUTBOX_DELIVERY_SECRET": SECRET,
        }
    )
    process = await asyncio.to_thread(
        subprocess.Popen,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scripts.activity_receiver:application",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "error",
            *(
                []
                if certificate is None
                else ["--ssl-certfile", str(certificate), "--ssl-keyfile", str(private_key)]
            ),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    origin = f"{'http' if certificate is None else 'https'}://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=1,
            verify=True
            if certificate is None
            else ssl.create_default_context(cafile=str(certificate)),
        ) as client:
            for _ in range(150):
                if process.poll() is not None:
                    raise AssertionError(process.stderr.read().decode())
                try:
                    if (await client.get(origin + "/health/ready")).status_code == 204:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.05)
            else:
                raise AssertionError("owned receiver failed to become ready")
        yield origin
    finally:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
        process.stderr.close()


async def test_independent_process_transport_requires_auth_and_deduplicates_durable_receipt(
    database,
):
    outbox_id = await seed(database)
    async with database.sessions() as session:
        service = DomainEventOutboxService(session)
        claim = await service.claim_one(owner_id="separate-dispatcher")
        await session.commit()
    assert claim is not None
    async with receiver(database) as origin:
        url = origin + "/v1/activity-deliveries"
        transport = HttpActivityConsumer(url, SECRET, allow_loopback_http=True)
        async with httpx.AsyncClient() as client:
            denied = await client.post(url, content=delivery_bytes(claim))
            assert denied.status_code == 401
            malformed = await client.post(
                url, content=delivery_bytes(claim), headers=[(b"Authorization", b"Bearer \xff")]
            )
            assert malformed.status_code == 401
        first, duplicate = await transport.deliver(claim), await transport.deliver(claim)
        assert first == duplicate
        async with database.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 1
            # The receiver commits its receipt before source acknowledgment.
            assert (await session.get(DomainEventOutbox, outbox_id)).delivery_state == "delivering"
            await OutboxDispatcher._verify_receipt(session, claim, first)
            await DomainEventOutboxService(session).complete(claim)
            await session.commit()
            assert (await session.get(DomainEventOutbox, outbox_id)).delivery_state == "delivered"


async def test_lost_network_ack_retries_without_duplicate_effect(database):
    outbox_id = await seed(database)
    clock = [datetime.now(UTC)]
    async with receiver(database) as origin:
        transport = HttpActivityConsumer(
            origin + "/v1/activity-deliveries", SECRET, allow_loopback_http=True
        )

        class LoseFirstAck:
            calls = 0

            async def deliver(self, claim):
                result = await transport.deliver(claim)
                self.calls += 1
                if self.calls == 1:
                    raise OSError("synthetic lost response after committed receiver effect")
                return result

        consumer = LoseFirstAck()
        worker = OutboxDispatcher(
            database.sessions, owner_id="sender", consumer=consumer, clock=lambda: clock[0]
        )
        assert await worker.run_once()
        async with database.sessions() as session:
            assert (await session.get(DomainEventOutbox, outbox_id)).delivery_state == "retry_wait"
            assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 1
        clock[0] += timedelta(seconds=2)
        assert await worker.run_once()
        async with database.sessions() as session:
            assert (await session.get(DomainEventOutbox, outbox_id)).delivery_state == "delivered"
            assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 1
            outcomes = (await session.scalars(select(DomainEventDeliveryAttempt.outcome))).all()
            assert sorted(outcomes) == ["delivered", "retry_scheduled"]


@pytest.mark.parametrize("effect_committed", [False, True])
async def test_abandoned_final_attempt_reconciles_actual_effect_without_reopening(
    database, effect_committed
):
    outbox_id = await seed(database, attempts=1)
    clock = [datetime.now(UTC)]
    async with database.sessions() as session:
        claim = await DomainEventOutboxService(session).claim_one(
            owner_id="crashed", now=clock[0], lease_seconds=2
        )
        await session.commit()
    if effect_committed:
        await DurableActivityConsumer(database.sessions, clock=lambda: clock[0]).deliver(claim)
    clock[0] += timedelta(seconds=3)
    worker = OutboxDispatcher(database.sessions, owner_id="recovery", clock=lambda: clock[0])
    assert await worker.run_once()
    assert not await worker.run_once()
    async with database.sessions() as session:
        row = await session.get(DomainEventOutbox, outbox_id)
        assert row.attempt_count == 1
        assert row.delivery_state == ("delivered" if effect_committed else "terminal_failure")
        assert (
            await session.scalar(select(func.count()).select_from(DomainEventDeliveryAttempt)) == 1
        )


async def test_stale_claim_is_rejected_across_transport_without_effect(database):
    await seed(database)
    async with database.sessions() as session:
        old = await DomainEventOutboxService(session).claim_one(
            owner_id="expired",
            now=datetime.now(UTC) - timedelta(seconds=5),
            lease_seconds=1,
        )
        new = await DomainEventOutboxService(session).claim_one(owner_id="current")
        await session.commit()
    assert old and new and new.generation > old.generation
    async with receiver(database) as origin, httpx.AsyncClient() as client:
        denied = await client.post(
            origin + "/v1/activity-deliveries",
            content=delivery_bytes(old),
            headers={"Authorization": "Bearer " + SECRET, "Content-Type": "application/json"},
        )
        assert denied.status_code == 409
    async with database.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 0


async def test_non_durable_or_wrong_ack_never_marks_delivery_success(database):
    outbox_id = await seed(database)

    class Forged:
        async def deliver(self, claim):
            return ActivityAcknowledgment(claim.event_id, uuid.uuid4())

    assert await OutboxDispatcher(
        database.sessions, owner_id="sender", consumer=Forged()
    ).run_once()
    async with database.sessions() as session:
        row = await session.get(DomainEventOutbox, outbox_id)
        assert row.delivery_state == "terminal_failure"
        assert row.completed_at is None
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 0


async def test_retry_budget_exhausts_once_and_graceful_stop_does_not_claim(database):
    outbox_id = await seed(database, attempts=3)
    clock = [datetime.now(UTC)]

    class Unavailable:
        async def deliver(self, claim):
            raise OSError("local receiver connection failure")

    worker = OutboxDispatcher(
        database.sessions, owner_id="bounded", consumer=Unavailable(), clock=lambda: clock[0]
    )
    for _ in range(3):
        assert await worker.run_once()
        clock[0] += timedelta(seconds=10)
    assert not await worker.run_once()
    async with database.sessions() as session:
        row = await session.get(DomainEventOutbox, outbox_id)
        assert row.attempt_count == 3 and row.delivery_state == "terminal_failure"
        attempts = (await session.scalars(select(DomainEventDeliveryAttempt.outcome))).all()
        assert attempts.count("retry_scheduled") == 2 and attempts.count("terminal_failure") == 1
    stop = asyncio.Event()
    stop.set()
    await worker.run_forever(poll_seconds=0.1, stop=stop)


async def test_final_attempt_lost_ack_reconciles_committed_receipt(database):
    outbox_id = await seed(database, attempts=1)
    underlying = DurableActivityConsumer(database.sessions)

    class LostAck:
        async def deliver(self, claim):
            await underlying.deliver(claim)
            raise OSError("local response loss after final allowed delivery")

    assert await OutboxDispatcher(
        database.sessions, owner_id="final", consumer=LostAck()
    ).run_once()
    async with database.sessions() as session:
        row = await session.get(DomainEventOutbox, outbox_id)
        assert row.delivery_state == "delivered" and row.attempt_count == 1
        assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 1


def test_worker_has_only_append_capability_for_existing_consumer_receipts():
    privileges = RUNTIME_TABLE_PRIVILEGES[DatabaseRole.WORKER]
    for table in ("domain_activity_entries", "domain_event_delivery_attempts"):
        assert table in privileges["SELECT"] and table in privileges["INSERT"]
        assert table not in privileges["UPDATE"] and table not in privileges["DELETE"]


def test_receiver_configuration_does_not_admit_public_plaintext_or_weak_authority():
    with pytest.raises(ValueError):
        Settings(environment="test", outbox_delivery_secret="short")
    with pytest.raises(ValueError):
        Settings(
            environment="test",
            outbox_delivery_secret=SECRET,
            outbox_receiver_url="http://public.example/v1/activity-deliveries",
        )


async def test_verified_tls_disconnect_before_ack_preserves_receiver_commit(database, tmp_path):
    from infra.milestone_7_8.activity_delivery_validation import disconnected_delivery

    binary = shutil.which("openssl") or str(
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
    )
    if not await asyncio.to_thread(Path(binary).is_file):
        pytest.skip("OpenSSL is required for this isolated TLS transport fixture")
    certificate, private_key = tmp_path / "local.crt", tmp_path / "local.key"
    generated = await asyncio.to_thread(
        subprocess.run,
        [
            binary,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
            "-out",
            str(certificate),
            "-keyout",
            str(private_key),
        ],
        capture_output=True,
    )
    assert generated.returncode == 0
    outbox_id = await seed(database)
    async with database.sessions() as session:
        claim = await DomainEventOutboxService(session).claim_one(
            owner_id="tls-disconnect", outbox_id=outbox_id
        )
        await session.commit()
    async with receiver(database, certificate=certificate, private_key=private_key) as origin:
        await disconnected_delivery(
            origin + "/v1/activity-deliveries",
            SECRET,
            claim,
            tls_context=ssl.create_default_context(cafile=str(certificate)),
        )
        for _ in range(40):
            async with database.sessions() as session:
                count = await session.scalar(select(func.count()).select_from(DomainActivityEntry))
                row = await session.get(DomainEventOutbox, outbox_id)
            if count == 1:
                break
            await asyncio.sleep(0.05)
        assert count == 1 and row.delivery_state == "delivering"


async def test_scoped_dispatch_never_claims_another_pending_event(database):
    first = await seed(database)
    second = await seed(database)
    worker = OutboxDispatcher(database.sessions, owner_id="scoped")
    assert await worker.run_once(outbox_id=second)
    async with database.sessions() as session:
        assert (await session.get(DomainEventOutbox, first)).delivery_state == "pending"
        assert (await session.get(DomainEventOutbox, second)).delivery_state == "delivered"


async def test_private_ingress_404_uses_bounded_retry_without_reading_error_body(database):
    outbox_id = await seed(database)
    clock = [datetime.now(UTC)]

    async def unavailable(reader, writer):
        request = await reader.readuntil(b"\r\n\r\n")
        assert b"POST /v1/activity-deliveries HTTP/1.1" in request
        writer.write(
            b"HTTP/1.1 404 Not Found\r\nContent-Length: 8192\r\nConnection: close\r\n\r\n"
            + b"x" * 8192
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(unavailable, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = HttpActivityConsumer(
        f"http://127.0.0.1:{port}/v1/activity-deliveries", SECRET, allow_loopback_http=True
    )
    worker = OutboxDispatcher(
        database.sessions, owner_id="ingress-outage", consumer=transport, clock=lambda: clock[0]
    )
    try:
        for _ in range(3):
            assert await worker.run_once(outbox_id=outbox_id)
            clock[0] += timedelta(seconds=10)
        async with database.sessions() as session:
            row = await session.get(DomainEventOutbox, outbox_id)
            assert row.delivery_state == "terminal_failure" and row.attempt_count == 3
            assert await session.scalar(select(func.count()).select_from(DomainActivityEntry)) == 0
        assert [row["httpStatus"] for row in transport.observations] == [404, 404, 404]
    finally:
        server.close()
        await server.wait_closed()


def test_managed_probe_requires_exact_native_receiver_state_and_nonempty_image_binding():
    from copy import deepcopy

    from infra.milestone_7_8.activity_delivery_validation import admit_component

    scope = "/subscriptions/local-proof/resourceGroups/local-proof"
    environment = scope + "/providers/Microsoft.App/managedEnvironments/private-proof"
    receiver_id = scope + "/providers/Microsoft.App/containerApps/activity-proof"
    plan = {
        "targetResourceGroupId": scope,
        "managedEnvironmentResourceId": environment,
        "activityReceiverResourceId": receiver_id,
        "imageDigest": "sha256:" + "1" * 64,
    }
    component = {
        "request": {"resourceId": receiver_id, "method": "GET", "apiVersion": "2025-01-01"},
        "response": {
            "status": 200,
            "body": {
                "id": receiver_id,
                "properties": {
                    "managedEnvironmentId": environment,
                    "runningStatus": "Running",
                    "template": {"containers": [{"image": "private/api@" + plan["imageDigest"]}]},
                    "configuration": {
                        "ingress": {
                            "fqdn": "activity-proof.internal.private.example",
                            "allowInsecure": False,
                        }
                    },
                },
            },
        },
    }
    readbacks = {
        "resources": [
            component,
            {
                "request": {"resourceId": environment},
                "response": {"body": {"properties": {"defaultDomain": "private.example"}}},
            },
        ]
    }
    assert admit_component(plan, readbacks, "activityReceiverResourceId", state="Running") == (
        "https://activity-proof.internal.private.example/v1/activity-deliveries"
    )
    for field, value in (("runningStatus", "Stopped"), ("template", {"containers": []})):
        invalid = deepcopy(readbacks)
        invalid["resources"][0]["response"]["body"]["properties"][field] = value
        with pytest.raises(ValueError, match="state/environment/image"):
            admit_component(plan, invalid, "activityReceiverResourceId", state="Running")


async def transport_tls_material(tmp_path):
    binary = shutil.which("openssl") or str(
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
    )
    assert await asyncio.to_thread(Path(binary).is_file), "OpenSSL fixture dependency required"
    certificate, private_key = tmp_path / "fault.crt", tmp_path / "fault.key"
    generated = await asyncio.to_thread(
        subprocess.run,
        [
            binary,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
            "-out",
            str(certificate),
            "-keyout",
            str(private_key),
        ],
        capture_output=True,
    )
    assert generated.returncode == 0
    return certificate, private_key


@pytest.mark.parametrize("fault_kind", ["delay", "partial"])
async def test_actual_verified_tls_fault_reconciles_one_effect(
    database, tmp_path, monkeypatch, fault_kind
):
    from infra.milestone_7_8.activity_delivery_validation import (
        DelayedAcknowledgment,
        PartialAcknowledgment,
        state_of,
    )

    certificate, key = await transport_tls_material(tmp_path)
    selected = await seed(database)
    observations = []
    clock = [datetime.now(UTC)]
    async with receiver(database, certificate=certificate, private_key=key) as origin:
        trusted = ssl.create_default_context(cafile=str(certificate))
        original_client = httpx.AsyncClient
        # Only the test trusts its ephemeral local CA; real network/TLS/hostname
        # checks and production request/ACK processing remain enabled.
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kwargs: original_client(verify=trusted, **kwargs)
        )
        transport = HttpActivityConsumer(origin + "/v1/activity-deliveries", SECRET)
        fault = (
            DelayedAcknowledgment(transport, delay_seconds=3, observations=observations)
            if fault_kind == "delay"
            else PartialAcknowledgment(transport, observations=observations, tls_context=trusted)
        )
        worker = OutboxDispatcher(
            database.sessions,
            owner_id="fault",
            consumer=fault,
            delivery_timeout_seconds=2,
            clock=lambda: clock[0],
        )
        assert await worker.run_once(outbox_id=selected)
        uncertain = await state_of(database, selected)
        assert uncertain["state"] == "retry_wait" and uncertain["receiptCount"] == 1
        assert observations
        if fault_kind == "delay":
            assert observations[0]["cancelled"] and observations[0]["actualAckHoldSeconds"] > 0
        else:
            assert observations[0]["receivedBodyBytes"] == 32
            assert observations[0]["unreadBodyBytes"] > 0
        clock[0] += timedelta(seconds=5)
        worker.consumer = transport
        assert await worker.run_once(outbox_id=selected)
        final = await state_of(database, selected)
        assert (
            final["state"] == "delivered"
            and final["attemptCount"] == 2
            and final["receiptCount"] == 1
        )


async def test_real_stopped_receiver_concurrent_retry_load_is_nine_attempts(database, tmp_path):
    from types import SimpleNamespace

    from infra.milestone_7_8.activity_delivery_validation import retry_load

    from opencanvas_api.core.config import Settings
    from opencanvas_api.services.observability import InMemoryTelemetrySink, build_observability
    from opencanvas_api.services.operational_observations import bind_operational_telemetry

    certificate, key = await transport_tls_material(tmp_path)
    selected = [await seed(database) for _ in range(3)]
    async with receiver(database, certificate=certificate, private_key=key) as origin:
        endpoint = origin + "/v1/activity-deliveries"
    transport = HttpActivityConsumer(endpoint, SECRET)
    sink = InMemoryTelemetrySink()
    telemetry = build_observability(
        Settings(
            app_mode="test",
            telemetry_enabled=True,
            telemetry_exporter="memory",
            telemetry_pseudonymization_secret="p" * 48,
            telemetry_service_name="mobius-worker",
            telemetry_buffer_size=1024,
            telemetry_batch_size=512,
        ),
        sink=sink,
    )
    with bind_operational_telemetry(telemetry):
        result = await retry_load(
            database, selected, transport, SimpleNamespace(check_time=lambda: None)
        )
    await telemetry.flush()
    await telemetry.close()
    assert result["attemptBudget"] == 9
    assert len(transport.observations) == 9
    assert all(row["transport"] == "connection_error" for row in transport.observations)
    assert len(result["observed"]) == 3
    assert sum(s.payload["value"] for s in sink.signals if s.name == "mobius.outbox.attempts") == 9
    assert (
        sum(s.payload["value"] for s in sink.signals if s.name == "mobius.outbox.terminal_failure")
        == 3
    )


async def test_opaque_tcp_delay_preserves_tls_and_recovers_after_measured_timeout(
    database, tmp_path, monkeypatch
):
    from infra.milestone_7_8.activity_delivery_validation import delayed_receiver_tcp, state_of

    certificate, key = await transport_tls_material(tmp_path)
    selected = await seed(database)
    clock = [datetime.now(UTC)]
    async with receiver(database, certificate=certificate, private_key=key) as origin:
        trusted = ssl.create_default_context(cafile=str(certificate))
        original_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kwargs: original_client(verify=trusted, **kwargs)
        )
        transport = HttpActivityConsumer(
            origin.replace("127.0.0.1", "localhost") + "/v1/activity-deliveries", SECRET
        )
        worker = OutboxDispatcher(
            database.sessions,
            owner_id="tcp-delay",
            consumer=transport,
            delivery_timeout_seconds=1,
            clock=lambda: clock[0],
        )
        original_resolve = socket.getaddrinfo
        observations = []
        async with delayed_receiver_tcp(
            transport.url, delay_seconds=2, observations=observations
        ) as relay:
            assert await worker.run_once(outbox_id=selected)
        assert socket.getaddrinfo is original_resolve
        assert relay["elapsedSeconds"] < 20
        assert relay["resolverRestored"] and relay["listenerClosed"] and not relay["failureClasses"]
        assert 0 < relay["actualBytes"] <= 65536 and relay["actualConnections"] <= 3
        assert any(
            item["direction"] == "receiver-to-client" and item["heldSeconds"] > 0.1
            for item in observations
        )
        uncertain = await state_of(database, selected)
        assert uncertain["state"] == "retry_wait" and uncertain["receiptCount"] == 0
        clock[0] = datetime.now(UTC) + timedelta(seconds=2)
        assert await worker.run_once(outbox_id=selected)
        recovered = await state_of(database, selected)
        assert recovered["state"] == "delivered" and recovered["receiptCount"] == 1
        assert recovered["attemptCount"] == 2


async def test_opaque_tcp_relay_forwards_verified_tls_with_measured_small_delay(
    database, tmp_path, monkeypatch
):
    from infra.milestone_7_8.activity_delivery_validation import delayed_receiver_tcp

    certificate, key = await transport_tls_material(tmp_path)
    selected = await seed(database)
    async with receiver(database, certificate=certificate, private_key=key) as origin:
        trusted = ssl.create_default_context(cafile=str(certificate))
        original_client = httpx.AsyncClient
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kwargs: original_client(verify=trusted, **kwargs)
        )
        transport = HttpActivityConsumer(
            origin.replace("127.0.0.1", "localhost") + "/v1/activity-deliveries", SECRET
        )
        worker = OutboxDispatcher(database.sessions, owner_id="tcp-forward", consumer=transport)
        observations = []
        async with delayed_receiver_tcp(
            transport.url, delay_seconds=0.02, observations=observations
        ) as relay:
            assert await worker.run_once(outbox_id=selected)
        assert relay["tlsTerminated"] is False and relay["resolverRestored"]
        forwarded = [
            item
            for item in observations
            if item["direction"] == "receiver-to-client"
            and item["forwardedOffsetSeconds"] is not None
        ]
        assert forwarded and all(item["heldSeconds"] >= 0.02 for item in forwarded)
        async with database.sessions() as session:
            assert (await session.get(DomainEventOutbox, selected)).delivery_state == "delivered"

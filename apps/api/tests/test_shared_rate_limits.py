from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx
import pytest
from fastapi import FastAPI

from opencanvas_api.services.rate_limits import (
    AtomicLimit,
    InMemoryAtomicRateLimitStore,
    RateLimitDimension,
    SharedRateLimitService,
    SharedRateLimitUnavailable,
    StoreDecision,
)


class UnavailableStore(InMemoryAtomicRateLimitStore):
    async def consume(
        self,
        limits: Sequence[AtomicLimit],
        *,
        cost: int,
    ) -> StoreDecision:
        del limits, cost
        raise SharedRateLimitUnavailable("unavailable")


def _service(
    store: InMemoryAtomicRateLimitStore,
    *,
    deployment: str = "test",
    emergency_limit: int = 10_000,
) -> SharedRateLimitService:
    return SharedRateLimitService(
        store=store,
        hmac_secret="test-rate-limit-secret-that-is-long-enough",
        namespace="mobius",
        deployment=deployment,
        emergency_limit=emergency_limit,
        emergency_window_seconds=60,
    )


@pytest.mark.security
async def test_independent_clients_consume_one_atomic_shared_budget() -> None:
    store = InMemoryAtomicRateLimitStore()
    first = _service(store)
    second = _service(store)
    dimensions = [
        RateLimitDimension("network", "203.0.113.1", 4),
        RateLimitDimension("user", "user-a", 3),
        RateLimitDimension("workspace", "workspace-a", 10),
        RateLimitDimension("resource", "document-a", 10),
        RateLimitDimension("operation", "index", 10),
        RateLimitDimension("provider", "embedding", 10),
    ]
    decisions = await asyncio.gather(
        *[
            (first if index % 2 else second).consume(
                operation="index",
                dimensions=dimensions,
            )
            for index in range(12)
        ]
    )
    assert sum(decision.allowed for decision in decisions) == 3
    assert sum(not decision.allowed for decision in decisions) == 9
    assert all(decision.retry_after_seconds >= 1 for decision in decisions if not decision.allowed)


@pytest.mark.security
async def test_denial_does_not_partially_consume_other_dimensions() -> None:
    store = InMemoryAtomicRateLimitStore()
    service = _service(store)
    tight = [
        RateLimitDimension("user", "user-a", 1),
        RateLimitDimension("workspace", "workspace-a", 2),
    ]
    assert (await service.consume(operation="mutate", dimensions=tight)).allowed
    assert not (await service.consume(operation="mutate", dimensions=tight)).allowed
    other_user = [
        RateLimitDimension("user", "user-b", 1),
        RateLimitDimension("workspace", "workspace-a", 2),
    ]
    assert (await service.consume(operation="mutate", dimensions=other_user)).allowed


@pytest.mark.security
async def test_ttl_reset_burst_and_tenant_isolation() -> None:
    now = 1_000_000
    store = InMemoryAtomicRateLimitStore(clock_ms=lambda: now)
    service = _service(store)
    alice = [RateLimitDimension("workspace", "alice-private-workspace", 2, burst=1)]
    bob = [RateLimitDimension("workspace", "bob-private-workspace", 2, burst=1)]
    for _ in range(3):
        assert (await service.consume(operation="retrieve", dimensions=alice)).allowed
    assert not (await service.consume(operation="retrieve", dimensions=alice)).allowed
    assert (await service.consume(operation="retrieve", dimensions=bob)).allowed
    keys = tuple(store._buckets)
    assert all("alice-private-workspace" not in key for key in keys)
    now += 61_000
    assert (await service.consume(operation="retrieve", dimensions=alice)).allowed


@pytest.mark.security
async def test_store_concurrency_has_no_lost_updates() -> None:
    store = InMemoryAtomicRateLimitStore()
    limit = AtomicLimit(
        key="mobius:rl:v1:{limits}:test:concurrency:user:opaque",
        limit=25,
        window_ms=60_000,
        burst=0,
    )
    decisions = await asyncio.gather(*[store.consume([limit], cost=1) for _ in range(100)])
    assert sum(decision.allowed for decision in decisions) == 25


@pytest.mark.security
async def test_store_outage_fails_closed() -> None:
    service = _service(UnavailableStore())
    with pytest.raises(SharedRateLimitUnavailable):
        await service.consume(
            operation="upload",
            dimensions=[RateLimitDimension("user", "user-a", 10)],
        )


@pytest.mark.security
async def test_emergency_ceiling_and_deployment_namespace_are_authoritative() -> None:
    store = InMemoryAtomicRateLimitStore()
    first = _service(store, deployment="test-a", emergency_limit=2)
    second = _service(store, deployment="test-b", emergency_limit=2)
    dimensions = [RateLimitDimension("user", "same-user", 20)]
    assert (await first.consume(operation="upload", dimensions=dimensions)).allowed
    assert (await first.consume(operation="upload", dimensions=dimensions)).allowed
    assert not (await first.consume(operation="upload", dimensions=dimensions)).allowed
    assert (await second.consume(operation="upload", dimensions=dimensions)).allowed
    assert first.metrics.denied == 1
    assert first.metrics.saturation == 1
    assert first.metrics.consumed_cost_units == 2


@pytest.mark.security
async def test_protected_http_operation_returns_503_when_store_is_indeterminate(
    app: FastAPI,
    client: httpx.AsyncClient,
    api_prefix: str,
) -> None:
    app.state.shared_rate_limiter = _service(UnavailableStore())
    response = await client.post(
        f"{api_prefix}/auth/signin",
        json={"email": "nobody@example.test", "password": "Wrong-Password-2026"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "rate_limit_unavailable"
    assert response.headers["Retry-After"] == "1"

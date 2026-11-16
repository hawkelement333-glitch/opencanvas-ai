"""New probe contracts only; these local tests do not claim managed acceptance."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from opencanvas_api.core.config import AppMode
from opencanvas_api.services.rate_limits import (
    InMemoryAtomicRateLimitStore,
    RateLimitDimension,
    RedisAtomicRateLimitStore,
    SharedRateLimitService,
    SharedRateLimitUnavailable,
    build_shared_rate_limit_service,
)

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "managed_redis_probe", ROOT / "infra/milestone_7_8/managed_redis_probe.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def environment():
    values = {
        "PROVIDER": "redis",
        "AUTH_MODE": "entra",
        "REDIS_URL": "rediss://redis.example.invalid:10000/0",
        "REDIS_USERNAME": str(uuid.uuid4()),
        "IDENTITY_CLIENT_ID": str(uuid.uuid4()),
        "HMAC_SECRET": "local-test-only-secret-" + "x" * 32,
        "NAMESPACE": "m78test",
        "DEPLOYMENT": "m78test",
    }
    return {
        **{"OPENCANVAS_SHARED_RATE_LIMIT_" + key: value for key, value in values.items()},
        "IDENTITY_ENDPOINT": "http://127.0.0.1:42342/msi/token",
        "IDENTITY_HEADER": "test-only-identity-header",
    }


def test_real_staging_validators_and_factory_without_unrelated_clients():
    settings = probe.validated_settings(environment())
    assert settings.runtime_mode is AppMode.STAGING
    assert settings.shared_rate_limit_auth_mode == "entra"
    assert settings.database_url_value.endswith("@unused.invalid/unused")
    service = build_shared_rate_limit_service(settings)
    assert isinstance(service.store, RedisAtomicRateLimitStore)
    assert service.store._client is None
    assert service.store.tls_ca_file is None
    assert settings.shared_rate_limit_operation_timeout_seconds == 1
    assert settings.shared_rate_limit_connect_timeout_seconds == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("PROVIDER", "memory"),
        ("AUTH_MODE", "acl"),
        ("REDIS_URL", "redis://redis.example.invalid"),
        ("REDIS_URL", "rediss://user:private@redis.example.invalid/0"),
        ("HMAC_SECRET", "short"),
        ("NAMESPACE", "unsafe:*keys"),
    ],
)
def test_prepared_settings_reject_unsafe_limiter_configuration(field, value):
    env = environment()
    env["OPENCANVAS_SHARED_RATE_LIMIT_" + field] = value
    with pytest.raises((ValueError, probe.ProbeFailure)):
        probe.validated_settings(env)


def pair():
    return [
        {
            "campaign": "campaign",
            "run_id": "run",
            "source_sha256": "a" * 64,
            "image_digest": "sha256:" + "b" * 64,
            "source_commit": "c" * 40,
            "replica": role,
            "execution_id": "job-" + role,
            "identity_sha256": probe.digest(role),
            "case": "user",
            "attempted": 25,
            "allowed": 9 if role == "leader" else 8,
            "denied": 16 if role == "leader" else 17,
            "errors": 0,
            "started_ms": 1000,
            "finished_ms": 1100,
        }
        for role in ("leader", "follower")
    ]


@pytest.mark.parametrize(
    "change",
    [
        None,
        "same-execution",
        "same-identity",
        "foreign-run",
        "over-budget",
        "missing-decision",
        "error",
        "refill-overlap",
    ],
)
def test_pair_validator_requires_real_independent_bound_complete_atomic_results(change):
    rows = pair()
    if change == "same-execution":
        rows[1]["execution_id"] = rows[0]["execution_id"]
    elif change == "same-identity":
        rows[1]["identity_sha256"] = rows[0]["identity_sha256"]
    elif change == "foreign-run":
        rows[1]["run_id"] = "different"
    elif change == "over-budget":
        rows[1].update(allowed=9, denied=16)
    elif change == "missing-decision":
        rows[1]["attempted"] = 24
    elif change == "error":
        rows[1]["errors"] = 1
    elif change == "refill-overlap":
        rows[1]["finished_ms"] = 86400000
    args = {
        "case": "user",
        "campaign": "campaign",
        "run_id": "run",
        "source": "a" * 64,
        "image": "sha256:" + "b" * 64,
    }
    if change is None:
        assert probe.validate_pair(rows, **args)["allowed"] == 17
    else:
        with pytest.raises(probe.ProbeFailure):
            probe.validate_pair(rows, **args)


def test_global_whole_ceiling_cost_requires_exactly_one_winner_before_refill():
    rows = pair()
    for index, row in enumerate(rows):
        row.update(case="global", allowed=1 - index, denied=24 + index)
    args = {
        "case": "global",
        "campaign": "campaign",
        "run_id": "run",
        "source": "a" * 64,
        "image": "sha256:" + "b" * 64,
        "expected_allowed": 1,
        "refill_window_ms": 60000,
    }
    assert probe.validate_pair(rows, **args)["allowed"] == 1
    rows[1]["finished_ms"] = 61000
    with pytest.raises(probe.ProbeFailure, match="refill"):
        probe.validate_pair(rows, **args)


@pytest.mark.parametrize("outcome", ["created", "ambiguous-same", "ambiguous-missing", "conflict"])
async def test_immutable_receipt_reconciles_uncertain_set_without_resubmitting(outcome):
    instance = object.__new__(probe.Probe)
    instance.prefix = "m78test:control:{limits}:campaign:run"
    value = {"accepted": True, "assertions": ["example"]}
    client = SimpleNamespace(set=AsyncMock(return_value=outcome == "created"))
    if outcome.startswith("ambiguous"):
        client.set.side_effect = TimeoutError("private provider error")
    instance.client = AsyncMock(return_value=client)
    instance.read = AsyncMock(return_value=value if outcome == "ambiguous-same" else None)
    if outcome in {"created", "ambiguous-same"}:
        assert await instance.immutable("receipt:healthy:leader", value) == value
    else:
        with pytest.raises(probe.ProbeFailure):
            await instance.immutable("receipt:healthy:leader", value)
    client.set.assert_awaited_once()
    assert client.set.await_args.kwargs == {"nx": True, "ex": 86400}


class Unavailable(InMemoryAtomicRateLimitStore):
    async def consume(self, limits, *, cost):
        raise SharedRateLimitUnavailable("private details not HTTP output")


@pytest.mark.parametrize("unavailable", [False, True])
async def test_synthetic_http_runs_production_enforcer_and_never_applies_denied_effect(unavailable):
    service = SharedRateLimitService(
        store=Unavailable() if unavailable else InMemoryAtomicRateLimitStore(),
        hmac_secret="test-secret-" + "x" * 32,
        namespace="test",
        deployment="test",
        emergency_limit=100,
        emergency_window_seconds=60,
    )
    app, effects = probe.synthetic_http(
        service, "upload", [RateLimitDimension("user", "private-user", 1)]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://fixture.invalid"
    ) as client:
        responses = [await client.post("/protected") for _ in range(2)]
    assert [response.status_code for response in responses] == (
        [503, 503] if unavailable else [200, 429]
    )
    assert effects["count"] == (0 if unavailable else 1)
    assert responses[-1].json()["code"] == (
        "rate_limit_unavailable" if unavailable else "rate_limit_exceeded"
    )
    assert 1 <= int(responses[-1].headers["retry-after"]) <= 60
    assert "private" not in responses[-1].text


@pytest.mark.parametrize("change", [None, "truncated", "foreign-execution", "wrong-hash"])
def test_receipt_chunk_transport_roundtrip_and_rejects_truncation(change):
    value = {
        "campaign": "campaign",
        "execution_id": "actual-job",
        "observations": [probe.digest(str(index)) for index in range(500)],
    }
    chunks, header = probe.receipt_transport(value)
    assert len(chunks) > 1 and all(len(chunk["data"]) <= 3000 for chunk in chunks)
    if change == "truncated":
        chunks.pop()
    elif change == "foreign-execution":
        chunks[0]["execution_id"] = "foreign"
    elif change == "wrong-hash":
        header["raw_sha256"] = "0" * 64
    if change is None:
        assert probe.restore_transport(chunks, header) == value
        assert header["raw_sha256"] == probe.digest(value)
    else:
        with pytest.raises(probe.ProbeFailure):
            probe.restore_transport(chunks, header)


def test_assertion_inventory_is_unique_and_contains_only_required_surfaces():
    assertions = [item for phase in probe.ASSERTIONS.values() for item in phase]
    assert len(assertions) == len(set(assertions)) == 17
    assert all("postgres" not in item and "scanner" not in item for item in assertions)
    assert "password" not in json.dumps(probe.ASSERTIONS)

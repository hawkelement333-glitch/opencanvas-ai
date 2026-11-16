"""M78-D-002 external probe; real Redis only, two independent managed jobs.

No deployment or fault mutation lives here. The operator records a network
fault/readback and restores it between explicit fault/recovery executions.
Accepted receipts are immutable SET NX values plus sanitized stdout. Uncertain
workload outcomes require inspection; this probe never generates another run ID.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import NoPermissionError

from opencanvas_api.api.dependencies import _enforce_shared
from opencanvas_api.api.errors import ApiError
from opencanvas_api.core.config import AppMode, Settings
from opencanvas_api.services.rate_limits import (
    EntraRedisAuthentication,
    RateLimitDimension,
    RedisAtomicRateLimitStore,
    SharedRateLimitService,
    build_shared_rate_limit_service,
)

DIMENSIONS = ("network", "user", "workspace", "resource", "operation", "provider")
PHASES = ("admission", "healthy", "fault", "recovery", "receipts")
ASSERTIONS = {
    "admission": ["managed-entra-private-tls", "foreign-prefix-acl-denied"],
    "healthy": [
        *[f"replica-atomic-{kind}" for kind in (*DIMENSIONS, "global")],
        "denial-all-or-nothing",
        "burst-refill-bounded-expiry",
        "workspace-deployment-isolation",
        "opaque-versioned-keys",
        "http-429-retry-after",
    ],
    "fault": ["dependency-failure-http-503-no-effect", "dependency-health-degraded-no-fallback"],
    "recovery": ["dependency-restored-health-and-decision"],
}


class ProbeFailure(RuntimeError):
    pass


def check(condition: Any, code: str) -> None:
    if not condition:
        raise ProbeFailure(code)


def digest(value: Any) -> str:
    if not isinstance(value, bytes):
        value = (
            value
            if isinstance(value, str)
            else json.dumps(value, sort_keys=True, separators=(",", ":"))
        ).encode()
    return hashlib.sha256(value).hexdigest()


def receipt_transport(value: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    check(len(raw) <= 1000000, "receipt-size-bound-exceeded")
    encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode()
    parts = [encoded[offset : offset + 3000] for offset in range(0, len(encoded), 3000)]
    binding = {
        key: value[key]
        for key in (
            "campaign",
            "run_id",
            "replica",
            "phase",
            "execution_id",
            "source_sha256",
            "image_digest",
            "source_commit",
        )
        if key in value
    }
    chunks = [
        {**binding, "index": index, "total": len(parts), "raw_sha256": digest(raw), "data": part}
        for index, part in enumerate(parts)
    ]
    header = {
        **binding,
        "classification": "chunked-receipt",
        "chunk_count": len(parts),
        "raw_sha256": digest(raw),
        "raw_bytes": len(raw),
    }
    return chunks, header


def restore_transport(chunks: list[dict[str, Any]], header: dict[str, Any]) -> dict[str, Any]:
    """Local verification helper shared with focused transport tests."""
    check(
        len(chunks) == header["chunk_count"]
        and {part["index"] for part in chunks} == set(range(header["chunk_count"])),
        "receipt-chunks-incomplete",
    )
    for part in chunks:
        check(
            part["total"] == header["chunk_count"] and part["raw_sha256"] == header["raw_sha256"],
            "receipt-chunk-binding-differs",
        )
        check(
            all(
                part.get(key) == header.get(key)
                for key in (
                    "campaign",
                    "run_id",
                    "replica",
                    "phase",
                    "execution_id",
                    "source_sha256",
                    "image_digest",
                    "source_commit",
                )
            ),
            "receipt-chunk-identity-differs",
        )
    raw = gzip.decompress(
        base64.b64decode(
            "".join(part["data"] for part in sorted(chunks, key=lambda part: part["index"])),
            validate=True,
        )
    )
    check(
        len(raw) == header["raw_bytes"] and digest(raw) == header["raw_sha256"],
        "receipt-raw-integrity-differs",
    )
    return json.loads(raw)


def validated_settings(
    environment: Any, *, deployment: str | None = None, emergency: int = 10000
) -> Settings:
    """Run all deployed validators; unrelated .invalid settings never get clients."""
    prefix = "OPENCANVAS_SHARED_RATE_LIMIT_"
    check(
        environment[prefix + "PROVIDER"] == "redis"
        and environment[prefix + "AUTH_MODE"] == "entra",
        "explicit-redis-entra-configuration-required",
    )
    values = {
        key: environment[prefix + key]
        for key in (
            "REDIS_URL",
            "REDIS_USERNAME",
            "IDENTITY_CLIENT_ID",
            "HMAC_SECRET",
            "NAMESPACE",
            "DEPLOYMENT",
        )
    }
    endpoint = environment.get(prefix + "IDENTITY_ENDPOINT") or environment["IDENTITY_ENDPOINT"]
    header = environment.get(prefix + "IDENTITY_HEADER") or environment["IDENTITY_HEADER"]
    # Explicit inert values satisfy unrelated staging contracts, without opening
    # another service, using its credentials, or bypassing Settings validation.
    settings = Settings(
        _env_file=None,
        app_mode="staging",
        environment="staging",
        demo_mode=False,
        database_url="postgresql+asyncpg://unused@unused.invalid/unused",
        database_auth_mode="entra",
        database_tls_mode="verify-full",
        database_managed_identity_client_id=values["IDENTITY_CLIENT_ID"],
        database_managed_identity_endpoint=endpoint,
        database_managed_identity_header=header,
        app_url="https://unused.invalid",
        cors_origins=["https://unused.invalid"],
        auth_enabled=True,
        auth_test_bypass=False,
        password_reset_provider="smtp",
        smtp_host="unused.invalid",
        smtp_from_address="unused@unused.invalid",
        session_secret=secrets.token_hex(32),
        invitation_secret=secrets.token_hex(32),
        ai_provider="openai",
        embedding_provider="openai",
        openai_api_key="unused-" + secrets.token_hex(32),
        storage_provider="azure",
        azure_storage_account_url="https://unused.invalid",
        azure_managed_identity_endpoint=endpoint,
        azure_managed_identity_header=header,
        azure_managed_identity_client_id=values["IDENTITY_CLIENT_ID"],
        object_ingestion_mode="trusted",
        scanner_result_bridge_mode="private_pull",
        azure_log_analytics_workspace_id=str(uuid.UUID(int=1)),
        malware_scanner_identity="azure-defender-for-storage",
        malware_scanner_version="defender-storage-dual-source-v1",
        upload_capability_secret=secrets.token_hex(32),
        scanner_result_secret=secrets.token_hex(32),
        job_provider="database",
        shared_rate_limit_provider="redis",
        shared_rate_limit_auth_mode="entra",
        shared_rate_limit_redis_url=values["REDIS_URL"],
        shared_rate_limit_redis_username=values["REDIS_USERNAME"],
        shared_rate_limit_identity_client_id=values["IDENTITY_CLIENT_ID"],
        shared_rate_limit_identity_endpoint=endpoint,
        shared_rate_limit_identity_header=header,
        shared_rate_limit_hmac_secret=values["HMAC_SECRET"],
        shared_rate_limit_namespace=values["NAMESPACE"],
        shared_rate_limit_deployment=deployment or values["DEPLOYMENT"],
        shared_rate_limit_connect_timeout_seconds=2,
        shared_rate_limit_operation_timeout_seconds=1,
        shared_rate_limit_emergency_requests_per_minute=emergency,
        shared_rate_limit_acl_username_file=None,
        shared_rate_limit_acl_password_file=None,
        shared_rate_limit_tls_ca_file=None,
        shared_rate_limit_recovery_epoch=None,
        telemetry_enabled=True,
        telemetry_exporter="http",
        telemetry_endpoint="https://unused.invalid",
        telemetry_tls_verify=True,
        telemetry_auth_secret_reference="env://M78_UNUSED_TELEMETRY",
        telemetry_pseudonymization_secret=secrets.token_hex(32),
        telemetry_release="m78-redis-probe",
        telemetry_deployment="m78-redis-probe",
        observability_operator_user_ids=[uuid.UUID(int=1)],
        indexer_publication_mode="disabled",
    )
    check(settings.runtime_mode is AppMode.STAGING, "staging-settings-required")
    return settings


def synthetic_http(
    service: SharedRateLimitService, operation: str, dimensions: list[RateLimitDimension]
) -> tuple[FastAPI, dict[str, int]]:
    """Production enforcement; fixture HTTP serialization, no application lifespan."""
    app = FastAPI()
    app.state.shared_rate_limiter = service
    effects = {"count": 0}

    @app.exception_handler(ApiError)
    async def error_handler(request: Request, error: ApiError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=error.status_code,
            content={"code": error.code, "detail": error.message},
            headers=error.headers,
        )

    @app.post("/protected")
    async def protected(request: Request) -> dict[str, bool]:
        await _enforce_shared(request, operation=operation, dimensions=dimensions)
        effects["count"] += 1
        return {"ok": True}

    return app, effects


def validate_pair(
    results: list[dict[str, Any]],
    *,
    case: str,
    campaign: str,
    run_id: str,
    source: str,
    image: str,
    expected_allowed: int = 17,
    refill_window_ms: int = 86400000,
) -> dict[str, Any]:
    check(
        len(results) == 2 and {row["replica"] for row in results} == {"leader", "follower"},
        "two-replicas-required",
    )
    check(
        len({row["execution_id"] for row in results}) == 2
        and len({row["identity_sha256"] for row in results}) == 2,
        "independent-executions-and-identities-required",
    )
    for row in results:
        check(
            row["campaign"] == campaign
            and row["run_id"] == run_id
            and row["source_sha256"] == source
            and row["image_digest"] == image
            and row["case"] == case,
            "replica-binding-differs",
        )
        check(
            row["attempted"] == 25
            and 0 <= row["allowed"] <= 25
            and 0 <= row["denied"] <= 25
            and row["allowed"] + row["denied"] == 25
            and row["errors"] == 0,
            "replica-workload-incomplete",
        )
    allowed = sum(row["allowed"] for row in results)
    check(allowed == expected_allowed, "atomic-shared-budget-differs")
    check(
        max(row["finished_ms"] for row in results) - min(row["started_ms"] for row in results)
        < refill_window_ms / expected_allowed,
        "workload-window-allows-refill-token",
    )
    return {"attempted": 50, "allowed": allowed, "denied": 50 - allowed, "replicas": results}


class Probe:
    def __init__(self, environment: Any = os.environ):
        self.env = environment
        self.campaign = str(uuid.UUID(environment["OPENCANVAS_REDIS_PROBE_CAMPAIGN"]))
        self.run_id = str(uuid.UUID(environment["OPENCANVAS_REDIS_PROBE_RUN_ID"]))
        self.replica = environment["OPENCANVAS_REDIS_PROBE_REPLICA"]
        self.phase = environment["OPENCANVAS_REDIS_PROBE_PHASE"]
        check(
            self.replica in {"leader", "follower"} and self.phase in PHASES,
            "phase-or-replica-invalid",
        )
        self.source = environment["OPENCANVAS_REDIS_PROBE_SHA256"]
        self.image = environment["OPENCANVAS_REDIS_PROBE_IMAGE_DIGEST"]
        self.commit = environment["OPENCANVAS_REDIS_PROBE_SOURCE_COMMIT"]
        check(
            bool(re.fullmatch(r"[0-9a-f]{64}", self.source))
            and bool(re.fullmatch(r"sha256:[0-9a-f]{64}", self.image))
            and bool(re.fullmatch(r"[0-9a-f]{40}", self.commit)),
            "artifact-binding-invalid",
        )
        self.execution = environment["CONTAINER_APP_JOB_EXECUTION_NAME"]
        check(bool(re.fullmatch(r"[a-z0-9-]{1,160}", self.execution)), "actual-execution-required")
        self.settings = validated_settings(environment)
        self.service = build_shared_rate_limit_service(self.settings)
        check(
            isinstance(self.service.store, RedisAtomicRateLimitStore)
            and isinstance(self.service.store.authentication, EntraRedisAuthentication),
            "real-entra-redis-store-required",
        )
        self.identity_hash = digest(self.settings.shared_rate_limit_redis_username)
        self.prefix = (
            f"{self.settings.shared_rate_limit_namespace}:control:{{limits}}:"
            f"{self.campaign}:{self.run_id}"
        )
        self.work_deadline = datetime.fromisoformat(
            environment["OPENCANVAS_REDIS_PROBE_WORK_DEADLINE_UTC"].replace("Z", "+00:00")
        )
        check(self.work_deadline.tzinfo is not None, "work-deadline-timezone-required")
        remaining = (self.work_deadline - datetime.now(UTC)).total_seconds()
        check(remaining > 130, "insufficient-proof-window")
        self.deadline = time.monotonic() + min(900, remaining - 120)
        self.services = [self.service]

    def binding(self) -> dict[str, Any]:
        return {
            "campaign": self.campaign,
            "run_id": self.run_id,
            "replica": self.replica,
            "execution_id": self.execution,
            "source_sha256": self.source,
            "image_digest": self.image,
            "source_commit": self.commit,
            "identity_sha256": self.identity_hash,
        }

    def key(self, suffix: str) -> str:
        check(bool(re.fullmatch(r"[a-z0-9:._-]{1,150}", suffix)), "control-suffix-invalid")
        return f"{self.prefix}:{suffix}"

    async def client(self) -> Any:
        return await self.service.store._get_client()

    async def read(self, suffix: str) -> dict[str, Any] | None:
        value = await (await self.client()).get(self.key(suffix))
        return None if value is None else json.loads(value)

    async def immutable(self, suffix: str, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        try:
            created = await (await self.client()).set(self.key(suffix), encoded, nx=True, ex=86400)
        except Exception:
            # Reconcile the exact value after an ambiguous SET, never resubmit it.
            prior = await self.read(suffix)
            check(
                prior is not None and digest(prior) == digest(value),
                "immutable-write-outcome-unresolved",
            )
            return prior
        if not created:
            prior = await self.read(suffix)
            check(
                prior is not None and digest(prior) == digest(value), "immutable-control-conflict"
            )
        return value

    async def wait(self, suffix: str) -> dict[str, Any]:
        while time.monotonic() < self.deadline:
            value = await self.read(suffix)
            if value is not None:
                return value
            await asyncio.sleep(0.25)
        raise ProbeFailure("bounded-replica-barrier-expired")

    async def server_ms(self) -> int:
        seconds, micros = await (await self.client()).time()
        return seconds * 1000 + micros // 1000

    def separate_service(
        self, *, deployment: str, emergency: int = 10000
    ) -> SharedRateLimitService:
        service = build_shared_rate_limit_service(
            validated_settings(self.env, deployment=deployment, emergency=emergency)
        )
        self.services.append(service)
        return service

    async def admission(self) -> dict[str, Any]:
        parsed = urlparse(self.settings.shared_rate_limit_redis_url or "")
        check(parsed.port == 10000, "exact-managed-port-required")
        host = parsed.hostname
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, 10000, type=socket.SOCK_STREAM
        )
        ips = {row[4][0] for row in addresses}
        check(
            ips
            and all(
                ipaddress.ip_address(value).version == 4
                and ipaddress.ip_address(value).is_private
                and not ipaddress.ip_address(value).is_loopback
                for value in ips
            ),
            "private-redis-dns-required",
        )
        check(await self.service.health(), "managed-redis-health-unavailable")
        client = await self.client()
        options = client.connection_pool.connection_kwargs
        check(
            options["ssl_cert_reqs"] == "required"
            and options["host"] == host
            and options["port"] == parsed.port
            and options["username"] == self.settings.shared_rate_limit_redis_username,
            "verified-tls-identity-binding-differs",
        )
        try:
            await client.get(f"outside-{self.campaign}:forbidden")
        except NoPermissionError:
            denied = True
        else:
            denied = False
        check(denied, "foreign-prefix-not-denied")
        return {
            "assertions": ASSERTIONS["admission"],
            "observations": {
                "redis_host_sha256": digest(host),
                "redis_port": parsed.port,
                "private_dns_address_count": len(ips),
                "private_dns_addresses_sha256": digest(sorted(ips)),
                "limiter_health": True,
                "authentication": "entra",
                "tls_certificate_validation": "required",
                "foreign_prefix_error": "NOPERM",
                "settings_mode": "staging",
            },
        }

    async def concurrent_case(self, case: str) -> dict[str, Any]:
        suffix = f"case:{case}:{self.replica}"
        previous = await self.read(suffix)
        if previous is not None:
            return previous
        # The intent is written before budget consumption. If this process dies
        # after it, a new execution refuses to repeat uncertain successful calls.
        intent_key = f"intent:{suffix}"
        old_intent = await self.read(intent_key)
        check(old_intent is None, "uncertain-case-requires-operator-reconciliation")
        await self.immutable(intent_key, self.binding())
        await self.immutable(f"ready:{case}:{self.replica}", self.binding())
        if self.replica == "leader":
            await self.wait(f"ready:{case}:follower")
            await self.immutable(f"start:{case}", {"start_ms": await self.server_ms() + 1000})
        start = (await self.wait(f"start:{case}"))["start_ms"]
        await asyncio.sleep(max(0, (start - await self.server_ms()) / 1000))
        check(await self.server_ms() >= start, "provider-clock-moved-backwards")
        service = self.service
        dimensions = [
            RateLimitDimension(
                kind, f"{self.run_id}:{kind}", 17 if kind == case else 100000, window_seconds=86400
            )
            for kind in DIMENSIONS
        ]
        if case == "global":
            service = self.separate_service(
                deployment=f"g{uuid.UUID(self.run_id).hex}", emergency=17
            )
            # Factory fixes global window60s. Increase workload token cost to the
            # whole ceiling; a single decision across replicas must win before
            # refill. This branch reports its actual distinct expectation.
        operation = f"replica-{case}"
        before = await self.server_ms()
        cost = 17 if case == "global" else 1
        decisions = await asyncio.gather(
            *[
                service.consume(operation=operation, dimensions=dimensions, cost=cost)
                for _ in range(25)
            ]
        )
        after = await self.server_ms()
        result = {
            **self.binding(),
            "case": case,
            "attempted": len(decisions),
            "allowed": sum(item.allowed for item in decisions),
            "denied": sum(not item.allowed for item in decisions),
            "errors": 0,
            "cost_units_per_decision": cost,
            "started_ms": before,
            "finished_ms": after,
            "retry_after_max_seconds": max(item.retry_after_seconds for item in decisions),
        }
        await self.immutable(suffix, result)
        return result

    async def http_decision(
        self,
        service: SharedRateLimitService,
        operation: str,
        dimensions: list[RateLimitDimension],
        requests: int = 1,
    ) -> dict[str, Any]:
        app, effects = synthetic_http(service, operation, dimensions)
        started = time.monotonic()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://fixture.invalid"
        ) as client:
            responses = [await client.post("/protected") for _ in range(requests)]
        return {
            "statuses": [item.status_code for item in responses],
            "codes": [item.json().get("code") for item in responses],
            "retry_after": [item.headers.get("retry-after") for item in responses],
            "protected_effect_count": effects["count"],
            "elapsed_seconds": round(time.monotonic() - started, 6),
        }

    async def sequential_cases(self) -> dict[str, Any]:
        service = self.service
        subject = self.run_id
        tight = [
            RateLimitDimension("user", subject + ":a", 1, window_seconds=86400),
            RateLimitDimension("workspace", subject, 2, window_seconds=86400),
        ]
        first = await service.consume(operation="all-or-nothing", dimensions=tight)
        denied = await service.consume(operation="all-or-nothing", dimensions=tight)
        other = await service.consume(
            operation="all-or-nothing",
            dimensions=[
                RateLimitDimension("user", subject + ":b", 1, window_seconds=86400),
                tight[1],
            ],
        )
        check(
            first.allowed and not denied.allowed and other.allowed,
            "denial-partially-consumed-budget",
        )
        burst = RateLimitDimension("workspace", subject + ":burst", 2, window_seconds=2, burst=1)
        burst_decisions = [
            await service.consume(operation="burst", dimensions=[burst]) for _ in range(4)
        ]
        check(
            [item.allowed for item in burst_decisions] == [True, True, True, False],
            "burst-capacity-differs",
        )
        key = service._key("burst", burst)
        ttl = await (await self.client()).pttl(key)
        check(0 < ttl <= 4000, "provider-expiry-unbounded")
        await asyncio.sleep(1.1)
        check(
            (await service.consume(operation="burst", dimensions=[burst])).allowed,
            "provider-refill-unproved",
        )
        await asyncio.sleep(4.2)
        check(await (await self.client()).exists(key) == 0, "provider-expiry-unproved")
        check(
            (await service.consume(operation="burst", dimensions=[burst])).allowed,
            "provider-reset-unproved",
        )
        isolated = RateLimitDimension("workspace", subject + ":isolation", 1, window_seconds=86400)
        check(
            (await service.consume(operation="isolation", dimensions=[isolated])).allowed,
            "isolation-first-denied",
        )
        check(
            not (await service.consume(operation="isolation", dimensions=[isolated])).allowed,
            "isolation-exhaustion-unproved",
        )
        check(
            (
                await service.consume(
                    operation="isolation",
                    dimensions=[
                        RateLimitDimension("workspace", subject + ":other", 1, window_seconds=86400)
                    ],
                )
            ).allowed,
            "workspace-isolation-failed",
        )
        alternate = self.separate_service(deployment=f"d{uuid.UUID(self.run_id).hex}")
        check(
            (await alternate.consume(operation="isolation", dimensions=[isolated])).allowed,
            "deployment-isolation-failed",
        )
        keys = [
            service._key("opaque", RateLimitDimension(kind, subject + ":private:" + kind, 1))
            for kind in DIMENSIONS
        ]
        check(
            all(
                subject not in item and ":private:" not in item and ":rl:v1:{limits}:" in item
                for item in keys
            ),
            "private-subject-in-key",
        )
        http = await self.http_decision(
            service, "http-denial", [RateLimitDimension("user", subject, 1, window_seconds=60)], 2
        )
        check(
            http["statuses"] == [200, 429]
            and http["codes"][1] == "rate_limit_exceeded"
            and 1 <= int(http["retry_after"][1]) <= 60
            and http["protected_effect_count"] == 1,
            "http-429-contract-differs",
        )
        return {
            "all_or_nothing": [first.allowed, denied.allowed, other.allowed],
            "burst_allowed": [item.allowed for item in burst_decisions],
            "provider_ttl_ms": ttl,
            "refill_allowed": True,
            "expired_before_reset": True,
            "workspace_isolated": True,
            "deployment_isolated": True,
            "opaque_key_count": len(keys),
            "opaque_key_hashes": [digest(key) for key in keys],
            "http_429": http,
        }

    async def healthy(self) -> dict[str, Any]:
        for role in ("leader", "follower"):
            admission = await self.wait(f"receipt:admission:{role}")
            check(
                admission["assertions"] == ASSERTIONS["admission"]
                and admission["accepted"] is True
                and admission["phase"] == "admission"
                and admission["replica"] == role
                and admission["campaign"] == self.campaign
                and admission["run_id"] == self.run_id
                and admission["source_sha256"] == self.source
                and admission["image_digest"] == self.image,
                "admission-not-accepted",
            )
        cases = {}
        for case in (*DIMENSIONS, "global"):
            own = await self.concurrent_case(case)
            peer = await self.wait(
                f"case:{case}:{'follower' if self.replica == 'leader' else 'leader'}"
            )
            pair = [own, peer]
            if case == "global":
                # Bind both real result sets; one whole-ceiling cost wins.
                validate_pair(
                    pair,
                    case=case,
                    campaign=self.campaign,
                    run_id=self.run_id,
                    source=self.source,
                    image=self.image,
                    expected_allowed=1,
                    refill_window_ms=60000,
                )
                check(
                    sum(row["allowed"] for row in pair) == 1
                    and max(row["finished_ms"] for row in pair)
                    - min(row["started_ms"] for row in pair)
                    < 60000,
                    "emergency-ceiling-refill-overlap",
                )
                cases[case] = {
                    "attempted": 50,
                    "allowed": 1,
                    "denied": 49,
                    "cost_units": 17,
                    "replicas": pair,
                }
            else:
                cases[case] = validate_pair(
                    pair,
                    case=case,
                    campaign=self.campaign,
                    run_id=self.run_id,
                    source=self.source,
                    image=self.image,
                )
        if self.replica == "leader":
            seq = await self.read("sequential-result")
            if seq is None:
                check(
                    await self.read("sequential-intent") is None,
                    "uncertain-sequential-work-requires-reconciliation",
                )
                await self.immutable("sequential-intent", self.binding())
                seq = await self.sequential_cases()
                await self.immutable("sequential-result", seq)
        else:
            seq = await self.wait("sequential-result")
        health = await self.service.health()
        check(health, "healthy-phase-final-health-failed")
        return {
            "assertions": ASSERTIONS["healthy"],
            "observations": {
                "cases": cases,
                "sequential": seq,
                "limiter_health": health,
            },
        }

    async def fault(self) -> dict[str, Any]:
        binding = self.env["OPENCANVAS_REDIS_PROBE_FAULT_BINDING_SHA256"]
        check(bool(re.fullmatch(r"[0-9a-f]{64}", binding)), "external-fault-binding-required")
        http = await self.http_decision(
            self.service, "fault", [RateLimitDimension("user", self.run_id, 10)]
        )
        check(
            http["statuses"] == [503]
            and http["codes"] == ["rate_limit_unavailable"]
            and http["retry_after"] == ["1"]
            and http["protected_effect_count"] == 0,
            "dependency-failure-not-fail-closed",
        )
        check(http["elapsed_seconds"] < 6, "dependency-failure-not-bounded")
        check(not await self.service.health(), "fault-health-not-degraded")
        check(
            isinstance(self.service.store, RedisAtomicRateLimitStore)
            and self.service.metrics.allowed == 0,
            "fault-local-fallback-or-allow",
        )
        return {
            "assertions": ASSERTIONS["fault"],
            "observations": {
                "fault_binding_sha256": binding,
                "http": http,
                "limiter_health": False,
                "store": "RedisAtomicRateLimitStore",
                "unavailable_decisions": self.service.metrics.unavailable,
            },
        }

    async def recovery(self) -> dict[str, Any]:
        fault = json.loads(self.env["OPENCANVAS_REDIS_PROBE_FAULT_RECEIPT_JSON"])
        check(
            digest(fault) == self.env["OPENCANVAS_REDIS_PROBE_FAULT_RECEIPT_SHA256"],
            "fault-receipt-hash-differs",
        )
        check(
            fault["campaign"] == self.campaign
            and fault["run_id"] == self.run_id
            and fault["replica"] == self.replica
            and fault["source_sha256"] == self.source
            and fault["image_digest"] == self.image
            and fault["phase"] == "fault"
            and fault["assertions"] == ASSERTIONS["fault"]
            and fault["accepted"] is True,
            "accepted-fault-binding-differs",
        )
        restored = self.env["OPENCANVAS_REDIS_PROBE_RECOVERY_BINDING_SHA256"]
        check(
            bool(re.fullmatch(r"[0-9a-f]{64}", restored)), "external-restoration-binding-required"
        )
        check(await self.service.health(), "restored-dependency-unhealthy")
        http = await self.http_decision(
            self.service, "recovery", [RateLimitDimension("user", self.run_id, 10)]
        )
        check(
            http["statuses"] == [200] and http["protected_effect_count"] == 1,
            "restored-protected-decision-failed",
        )
        await self.immutable(f"receipt:fault:{self.replica}", fault)
        return {
            "assertions": ASSERTIONS["recovery"],
            "observations": {
                "fault_receipt_sha256": digest(fault),
                "restoration_binding_sha256": restored,
                "limiter_health": True,
                "http": http,
            },
        }

    async def run(self) -> dict[str, Any]:
        try:
            if self.phase == "receipts":
                return {
                    **self.binding(),
                    "phase": "receipts",
                    "classification": "retained-receipts-export",
                    "receipts": [
                        receipt
                        for phase in ASSERTIONS
                        for role in ("leader", "follower")
                        if (receipt := await self.read(f"receipt:{phase}:{role}")) is not None
                    ],
                    "case_records": {
                        f"{case}:{role}": {
                            "intent": await self.read(f"intent:case:{case}:{role}"),
                            "result": await self.read(f"case:{case}:{role}"),
                        }
                        for case in (*DIMENSIONS, "global")
                        for role in ("leader", "follower")
                    },
                    "sequential_intent": await self.read("sequential-intent"),
                    "sequential_result": await self.read("sequential-result"),
                }
            if self.phase != "fault":
                previous = await self.read(f"receipt:{self.phase}:{self.replica}")
                if previous is not None:
                    check(
                        previous["source_sha256"] == self.source
                        and previous["image_digest"] == self.image,
                        "accepted-receipt-source-differs",
                    )
                    return {
                        **self.binding(),
                        "phase": self.phase,
                        "classification": "accepted-receipt-reused",
                        "receipt": previous,
                    }
            result = await getattr(self, self.phase)()
            receipt = {
                **self.binding(),
                "phase": self.phase,
                "status": "accepted",
                "accepted": True,
                "observed_at": datetime.now(UTC).isoformat(),
                **result,
            }
            if self.phase != "fault":
                await self.immutable(f"receipt:{self.phase}:{self.replica}", receipt)
            return receipt
        finally:
            for service in self.services:
                await service.close()


async def receipt_grace() -> None:
    grace = int(os.environ.get("OPENCANVAS_REDIS_PROBE_RECEIPT_GRACE_SECONDS", "120"))
    check(0 <= grace <= 120, "receipt-grace-invalid")
    deadline = datetime.fromisoformat(
        os.environ["OPENCANVAS_REDIS_PROBE_WORK_DEADLINE_UTC"].replace("Z", "+00:00")
    )
    await asyncio.sleep(max(0, min(grace, (deadline - datetime.now(UTC)).total_seconds())))


async def main() -> None:
    probe = Probe()
    async with asyncio.timeout(max(1, probe.deadline - time.monotonic())):
        result = await probe.run()
    chunks, header = receipt_transport(result)
    for chunk in chunks:
        print("M78_REDIS_PROBE_CHUNK=" + json.dumps(chunk, sort_keys=True), flush=True)
    print("M78_REDIS_PROBE=" + json.dumps(header, sort_keys=True), flush=True)
    await receipt_grace()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        code = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,100}", code):
            code = "unsafe-error-detail-withheld"
        print(
            "M78_REDIS_PROBE_FAILURE="
            + json.dumps(
                {
                    "accepted": False,
                    "status": "failed",
                    "campaign": os.environ.get("OPENCANVAS_REDIS_PROBE_CAMPAIGN"),
                    "run_id": os.environ.get("OPENCANVAS_REDIS_PROBE_RUN_ID"),
                    "image_digest": os.environ.get("OPENCANVAS_REDIS_PROBE_IMAGE_DIGEST"),
                    "source_commit": os.environ.get("OPENCANVAS_REDIS_PROBE_SOURCE_COMMIT"),
                    "code": code,
                    "execution_id": os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
                    "source_sha256": os.environ.get("OPENCANVAS_REDIS_PROBE_SHA256"),
                    "phase": os.environ.get("OPENCANVAS_REDIS_PROBE_PHASE"),
                    "replica": os.environ.get("OPENCANVAS_REDIS_PROBE_REPLICA"),
                }
            ),
            flush=True,
        )
        with suppress(Exception):
            asyncio.run(receipt_grace())
        raise SystemExit(1) from None

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlparse

import httpx
from redis.asyncio import Redis

from opencanvas_api.core.config import AppMode, Settings

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_TOKEN_AUDIENCE = "https://redis.azure.com"

_TOKEN_BUCKET_SCRIPT = """
local now_reply = redis.call('TIME')
local now_ms = (tonumber(now_reply[1]) * 1000) + math.floor(tonumber(now_reply[2]) / 1000)
local cost = tonumber(ARGV[1])
local minimum_remaining = nil
local retry_after_ms = 0
local states = {}

for index, key in ipairs(KEYS) do
  local offset = 2 + ((index - 1) * 3)
  local rate = tonumber(ARGV[offset])
  local window_ms = tonumber(ARGV[offset + 1])
  local burst = tonumber(ARGV[offset + 2])
  local capacity = rate + burst
  local values = redis.call('HMGET', key, 'tokens', 'updated_ms')
  local tokens = tonumber(values[1])
  local updated_ms = tonumber(values[2])
  if tokens == nil or updated_ms == nil then
    tokens = capacity
    updated_ms = now_ms
  else
    local elapsed = math.max(0, now_ms - updated_ms)
    tokens = math.min(capacity, tokens + ((elapsed * rate) / window_ms))
  end
  states[index] = {tokens, now_ms, window_ms}
  if tokens < cost then
    local wait_ms = math.ceil(((cost - tokens) * window_ms) / rate)
    retry_after_ms = math.max(retry_after_ms, wait_ms)
  end
end

if retry_after_ms > 0 then
  return {0, retry_after_ms, 0, now_ms}
end

for index, key in ipairs(KEYS) do
  local state = states[index]
  local remaining = state[1] - cost
  redis.call('HSET', key, 'tokens', tostring(remaining), 'updated_ms', tostring(state[2]))
  redis.call('PEXPIRE', key, math.max(1000, state[3] * 2))
  if minimum_remaining == nil or remaining < minimum_remaining then
    minimum_remaining = remaining
  end
end

return {1, 0, math.floor(minimum_remaining or 0), now_ms}
"""


class SharedRateLimitError(RuntimeError):
    """Base error with no provider or subject details."""


class SharedRateLimitUnavailable(SharedRateLimitError):
    """The shared store could not establish an authoritative decision."""


@dataclass(frozen=True, slots=True)
class RateLimitDimension:
    kind: str
    subject: str
    limit: int
    window_seconds: int = 60
    burst: int = 0

    def validate(self) -> None:
        if not _SAFE_NAME.fullmatch(self.kind):
            raise ValueError("Rate-limit dimension kind is invalid.")
        if not self.subject or len(self.subject) > 512:
            raise ValueError("Rate-limit dimension subject is invalid.")
        if not 1 <= self.limit <= 10_000_000:
            raise ValueError("Rate-limit capacity is invalid.")
        if not 1 <= self.window_seconds <= 86_400:
            raise ValueError("Rate-limit window is invalid.")
        if not 0 <= self.burst <= self.limit:
            raise ValueError("Rate-limit burst is invalid.")


@dataclass(frozen=True, slots=True)
class AtomicLimit:
    key: str
    limit: int
    window_ms: int
    burst: int


@dataclass(frozen=True, slots=True)
class StoreDecision:
    allowed: bool
    retry_after_ms: int
    remaining: int
    decided_at_ms: int


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int
    operation: str


@dataclass(slots=True)
class SharedRateLimitMetrics:
    decisions: int = 0
    allowed: int = 0
    denied: int = 0
    unavailable: int = 0
    saturation: int = 0
    bypass_attempts: int = 0
    responses_429: int = 0
    responses_503: int = 0
    consumed_cost_units: int = 0
    latency_ms_total: float = 0.0


class AtomicRateLimitStore(Protocol):
    async def consume(self, limits: Sequence[AtomicLimit], *, cost: int) -> StoreDecision: ...

    async def health(self) -> bool: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RedisCredentials:
    username: str
    password: str
    expires_at: int | None


class RedisAuthentication(Protocol):
    async def credentials(self) -> RedisCredentials: ...


@dataclass(frozen=True, slots=True)
class EntraRedisAuthentication:
    """Azure Managed Redis authentication using the existing Entra audience."""

    username: str
    managed_identity_endpoint: str
    managed_identity_header: str | None
    operation_timeout_seconds: float
    managed_identity_client_id: str | None = None

    async def credentials(self) -> RedisCredentials:
        headers = {"Metadata": "true"}
        if self.managed_identity_header:
            headers["X-IDENTITY-HEADER"] = self.managed_identity_header
        parameters = {
            "api-version": "2019-08-01",
            "resource": _TOKEN_AUDIENCE,
        }
        if self.managed_identity_client_id:
            parameters["client_id"] = self.managed_identity_client_id
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.operation_timeout_seconds),
            ) as client:
                response = await client.get(
                    self.managed_identity_endpoint,
                    headers=headers,
                    params=parameters,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SharedRateLimitUnavailable(
                "Managed identity could not authenticate the shared limiter."
            ) from exc
        token = payload.get("access_token")
        expires_on = payload.get("expires_on")
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise SharedRateLimitUnavailable("Managed identity returned an invalid token.")
        try:
            expires_at = int(expires_on)
        except (TypeError, ValueError) as exc:
            raise SharedRateLimitUnavailable(
                "Managed identity returned an invalid expiry."
            ) from exc
        return RedisCredentials(
            username=self.username,
            password=token,
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class RecoveryAclRedisAuthentication:
    """Recovery-only local TLS Valkey ACL authentication; never contacts Entra."""

    username: str
    password: str

    async def credentials(self) -> RedisCredentials:
        return RedisCredentials(
            username=self.username,
            password=self.password,
            expires_at=None,
        )


@dataclass(slots=True)
class _MemoryBucket:
    tokens: float
    updated_ms: int
    expires_at_ms: int


class InMemoryAtomicRateLimitStore:
    """Explicit test/demo fake. Never selected in staging or production."""

    def __init__(self, *, clock_ms: Callable[[], int] | None = None) -> None:
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1_000))
        self._buckets: dict[str, _MemoryBucket] = {}
        self._lock = asyncio.Lock()

    async def consume(self, limits: Sequence[AtomicLimit], *, cost: int) -> StoreDecision:
        if cost < 0:
            raise ValueError("Rate-limit cost cannot be negative.")
        now_ms = int(self._clock_ms())
        async with self._lock:
            expired = [
                key for key, bucket in self._buckets.items() if bucket.expires_at_ms <= now_ms
            ]
            for key in expired:
                del self._buckets[key]
            states: list[tuple[AtomicLimit, float]] = []
            retry_after_ms = 0
            for limit in limits:
                bucket = self._buckets.get(limit.key)
                capacity = limit.limit + limit.burst
                tokens = float(capacity)
                if bucket is not None:
                    elapsed = max(0, now_ms - bucket.updated_ms)
                    tokens = min(
                        float(capacity),
                        bucket.tokens + ((elapsed * limit.limit) / limit.window_ms),
                    )
                states.append((limit, tokens))
                if tokens < cost:
                    wait_ms = math.ceil(((cost - tokens) * limit.window_ms) / limit.limit)
                    retry_after_ms = max(retry_after_ms, wait_ms)
            if retry_after_ms:
                return StoreDecision(False, retry_after_ms, 0, now_ms)
            remaining = min(math.floor(tokens - cost) for _, tokens in states)
            for limit, tokens in states:
                self._buckets[limit.key] = _MemoryBucket(
                    tokens=tokens - cost,
                    updated_ms=now_ms,
                    expires_at_ms=now_ms + (limit.window_ms * 2),
                )
            return StoreDecision(True, 0, remaining, now_ms)

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def key_count(self) -> int:
        return len(self._buckets)


class RedisAtomicRateLimitStore:
    """TLS Redis-compatible adapter with an explicit Entra or sealed recovery ACL boundary."""

    def __init__(
        self,
        *,
        redis_url: str,
        authentication: RedisAuthentication,
        connect_timeout_seconds: float,
        operation_timeout_seconds: float,
        tls_ca_file: str | None = None,
    ) -> None:
        parsed = urlparse(redis_url)
        if (
            parsed.scheme != "rediss"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Shared Redis requires a credential-free rediss URL.")
        if parsed.path not in {"", "/", "/0"}:
            raise ValueError("Shared Redis must use database zero.")
        self.redis_url = redis_url
        self.authentication = authentication
        self.connect_timeout_seconds = connect_timeout_seconds
        self.operation_timeout_seconds = operation_timeout_seconds
        self.tls_ca_file = tls_ca_file
        self._client: Redis | None = None
        self._credentials_expires_at: int | None = None
        self._lock = asyncio.Lock()

    async def consume(self, limits: Sequence[AtomicLimit], *, cost: int) -> StoreDecision:
        client = await self._get_client()
        arguments: list[int] = [cost]
        for limit in limits:
            arguments.extend((limit.limit, limit.window_ms, limit.burst))
        try:
            evaluation = client.eval(
                _TOKEN_BUCKET_SCRIPT,
                len(limits),
                *(limit.key for limit in limits),
                *(str(argument) for argument in arguments),
            )
            result = await asyncio.wait_for(
                cast(Awaitable[object], evaluation),
                timeout=self.operation_timeout_seconds,
            )
        except Exception as exc:
            await self._drop_client()
            raise SharedRateLimitUnavailable(
                "The shared rate-limit dependency is unavailable."
            ) from exc
        if (
            not isinstance(result, (list, tuple))
            or len(result) != 4
            or any(not isinstance(value, int) for value in result)
        ):
            raise SharedRateLimitUnavailable(
                "The shared rate-limit dependency returned an invalid decision."
            )
        return StoreDecision(
            allowed=bool(result[0]),
            retry_after_ms=max(0, result[1]),
            remaining=max(0, result[2]),
            decided_at_ms=result[3],
        )

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            response = await asyncio.wait_for(
                client.ping(),
                timeout=self.operation_timeout_seconds,
            )
            return bool(response)
        except Exception:
            await self._drop_client()
            return False

    async def close(self) -> None:
        await self._drop_client()

    async def _get_client(self) -> Redis:
        now = int(time.time())
        if self._client is not None and self._credentials_are_current(now):
            return self._client
        async with self._lock:
            now = int(time.time())
            if self._client is not None and self._credentials_are_current(now):
                return self._client
            credentials = await self.authentication.credentials()
            if not credentials.username or len(credentials.username) > 128:
                raise SharedRateLimitUnavailable("Shared Redis authentication is invalid.")
            if not credentials.password or len(credentials.password) > 16_384:
                raise SharedRateLimitUnavailable("Shared Redis authentication is invalid.")
            parsed = urlparse(self.redis_url)
            if self.tls_ca_file is not None:
                client = Redis(
                    host=parsed.hostname or "",
                    port=parsed.port or 10000,
                    username=credentials.username,
                    password=credentials.password,
                    ssl=True,
                    ssl_cert_reqs="required",
                    ssl_ca_certs=self.tls_ca_file,
                    socket_connect_timeout=self.connect_timeout_seconds,
                    socket_timeout=self.operation_timeout_seconds,
                    health_check_interval=15,
                    decode_responses=False,
                )
            else:
                client = Redis(
                    host=parsed.hostname or "",
                    port=parsed.port or 10000,
                    username=credentials.username,
                    password=credentials.password,
                    ssl=True,
                    ssl_cert_reqs="required",
                    socket_connect_timeout=self.connect_timeout_seconds,
                    socket_timeout=self.operation_timeout_seconds,
                    health_check_interval=15,
                    decode_responses=False,
                )
            await self._drop_client()
            self._client = client
            self._credentials_expires_at = credentials.expires_at
            return client

    def _credentials_are_current(self, now: int) -> bool:
        return self._credentials_expires_at is None or now < self._credentials_expires_at - 300

    async def _drop_client(self) -> None:
        client = self._client
        self._client = None
        self._credentials_expires_at = None
        if client is not None:
            await client.aclose()


class SharedRateLimitService:
    """Atomic multi-dimensional limiter with opaque, versioned server-owned keys."""

    def __init__(
        self,
        *,
        store: AtomicRateLimitStore,
        hmac_secret: str,
        namespace: str,
        deployment: str,
        emergency_limit: int,
        emergency_window_seconds: int,
        metrics: SharedRateLimitMetrics | None = None,
    ) -> None:
        if len(hmac_secret.encode()) < 32:
            raise ValueError("Shared rate-limit HMAC secret must be at least 32 bytes.")
        if not _SAFE_NAME.fullmatch(namespace) or not _SAFE_NAME.fullmatch(deployment):
            raise ValueError("Shared rate-limit namespace is invalid.")
        if not 1 <= emergency_limit <= 10_000_000:
            raise ValueError("Emergency rate-limit ceiling is invalid.")
        self.store = store
        self._secret = hmac_secret.encode()
        self.namespace = namespace
        self.deployment = deployment
        self.emergency_limit = emergency_limit
        self.emergency_window_seconds = emergency_window_seconds
        self.metrics = metrics or SharedRateLimitMetrics()

    async def consume(
        self,
        *,
        operation: str,
        dimensions: Sequence[RateLimitDimension],
        cost: int = 1,
    ) -> RateLimitDecision:
        if not _SAFE_NAME.fullmatch(operation):
            raise ValueError("Rate-limit operation is invalid.")
        if not 1 <= cost <= 1_000_000:
            raise ValueError("Rate-limit cost is invalid.")
        if not dimensions:
            raise ValueError("At least one rate-limit dimension is required.")
        all_dimensions = [
            *dimensions,
            RateLimitDimension(
                kind="global",
                subject=self.deployment,
                limit=self.emergency_limit,
                window_seconds=self.emergency_window_seconds,
            ),
        ]
        keys: set[str] = set()
        limits: list[AtomicLimit] = []
        for dimension in all_dimensions:
            dimension.validate()
            key = self._key(operation, dimension)
            if key in keys:
                continue
            keys.add(key)
            limits.append(
                AtomicLimit(
                    key=key,
                    limit=dimension.limit,
                    window_ms=dimension.window_seconds * 1_000,
                    burst=dimension.burst,
                )
            )
        started = time.perf_counter()
        self.metrics.decisions += 1
        try:
            store_decision = await self.store.consume(limits, cost=cost)
        except SharedRateLimitUnavailable:
            self.metrics.unavailable += 1
            raise
        except Exception as exc:
            self.metrics.unavailable += 1
            raise SharedRateLimitUnavailable(
                "The shared rate-limit dependency is unavailable."
            ) from exc
        finally:
            self.metrics.latency_ms_total += (time.perf_counter() - started) * 1_000
        if store_decision.allowed:
            self.metrics.allowed += 1
            self.metrics.consumed_cost_units += cost
        else:
            self.metrics.denied += 1
            if store_decision.remaining == 0:
                self.metrics.saturation += 1
        return RateLimitDecision(
            allowed=store_decision.allowed,
            retry_after_seconds=max(1, math.ceil(store_decision.retry_after_ms / 1_000)),
            remaining=store_decision.remaining,
            operation=operation,
        )

    async def health(self) -> bool:
        return await self.store.health()

    async def close(self) -> None:
        await self.store.close()

    def _key(self, operation: str, dimension: RateLimitDimension) -> str:
        deployment_digest = self._digest(f"deployment:{self.deployment}")[:24]
        subject_digest = self._digest(f"{dimension.kind}:{dimension.subject}")[:32]
        return (
            f"{self.namespace}:rl:v1:{{limits}}:{deployment_digest}:"
            f"{operation}:{dimension.kind}:{subject_digest}"
        )

    def _digest(self, value: str) -> str:
        return hmac.new(self._secret, value.encode(), hashlib.sha256).hexdigest()


def build_shared_rate_limit_service(settings: Settings) -> SharedRateLimitService:
    if settings.shared_rate_limit_provider == "memory":
        if settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION}:
            raise RuntimeError("Deployed modes refuse process-local rate limits.")
        store: AtomicRateLimitStore = InMemoryAtomicRateLimitStore()
    else:
        authentication: RedisAuthentication
        tls_ca_file: str | None = None
        if settings.shared_rate_limit_auth_mode == "entra":
            required = {
                "Redis URL": settings.shared_rate_limit_redis_url,
                "Redis username": settings.shared_rate_limit_redis_username,
                "managed identity endpoint": settings.shared_rate_limit_identity_endpoint,
            }
            if missing := [name for name, value in required.items() if not value]:
                raise RuntimeError(f"Shared rate limiter is missing: {', '.join(missing)}")
            authentication = EntraRedisAuthentication(
                username=settings.shared_rate_limit_redis_username or "",
                managed_identity_endpoint=settings.shared_rate_limit_identity_endpoint or "",
                managed_identity_header=settings.shared_rate_limit_identity_header,
                managed_identity_client_id=settings.shared_rate_limit_identity_client_id,
                operation_timeout_seconds=settings.shared_rate_limit_operation_timeout_seconds,
            )
        else:
            if settings.runtime_mode is not AppMode.RECOVERY:
                raise RuntimeError("ACL shared Redis authentication is limited to recovery mode.")
            authentication = RecoveryAclRedisAuthentication(
                username=settings.recovery_rate_limit_acl_username,
                password=settings.recovery_rate_limit_acl_password,
            )
            if settings.shared_rate_limit_tls_ca_file is None:
                raise RuntimeError("Recovery ACL shared Redis requires TLS trust configuration.")
            tls_ca_file = str(settings.shared_rate_limit_tls_ca_file)
        store = RedisAtomicRateLimitStore(
            redis_url=settings.shared_rate_limit_redis_url or "",
            authentication=authentication,
            connect_timeout_seconds=settings.shared_rate_limit_connect_timeout_seconds,
            operation_timeout_seconds=settings.shared_rate_limit_operation_timeout_seconds,
            tls_ca_file=tls_ca_file,
        )
    return SharedRateLimitService(
        store=store,
        hmac_secret=settings.shared_rate_limit_hmac_secret,
        namespace=settings.shared_rate_limit_namespace,
        deployment=(
            f"{settings.shared_rate_limit_deployment}.{settings.shared_rate_limit_recovery_epoch}"
            if settings.runtime_mode is AppMode.RECOVERY
            else settings.shared_rate_limit_deployment
        ),
        emergency_limit=settings.shared_rate_limit_emergency_requests_per_minute,
        emergency_window_seconds=60,
    )


__all__ = [
    "AtomicLimit",
    "AtomicRateLimitStore",
    "EntraRedisAuthentication",
    "InMemoryAtomicRateLimitStore",
    "RateLimitDecision",
    "RateLimitDimension",
    "RecoveryAclRedisAuthentication",
    "RedisAtomicRateLimitStore",
    "RedisCredentials",
    "SharedRateLimitMetrics",
    "SharedRateLimitService",
    "SharedRateLimitUnavailable",
    "StoreDecision",
    "build_shared_rate_limit_service",
]

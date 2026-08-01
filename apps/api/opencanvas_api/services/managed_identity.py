from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx


class ManagedIdentityUnavailable(RuntimeError):
    """A bounded managed-identity token could not be obtained."""


@dataclass(slots=True)
class ManagedIdentityTokenProvider:
    endpoint: str
    resource: str
    client_id: str
    identity_header: str | None = None
    timeout_seconds: float = 5.0
    _token: str | None = field(default=None, init=False, repr=False)
    _expires_at: int = field(default=0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def token(self) -> str:
        now = int(time.time())
        if self._token is not None and now < self._expires_at - 300:
            return self._token
        async with self._lock:
            now = int(time.time())
            if self._token is not None and now < self._expires_at - 300:
                return self._token
            headers = {"Metadata": "true"}
            if self.identity_header:
                headers["X-IDENTITY-HEADER"] = self.identity_header
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
                    response = await client.get(
                        self.endpoint,
                        headers=headers,
                        params={
                            "api-version": "2019-08-01",
                            "resource": self.resource,
                            "client_id": self.client_id,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                token = payload.get("access_token")
                expires_at = int(payload.get("expires_on"))
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise ManagedIdentityUnavailable("Managed identity authentication failed.") from exc
            if not isinstance(token, str) or not token or len(token) > 16_384:
                raise ManagedIdentityUnavailable("Managed identity returned an invalid token.")
            self._token = token
            self._expires_at = expires_at
            return token


__all__ = ["ManagedIdentityTokenProvider", "ManagedIdentityUnavailable"]

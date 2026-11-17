from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from scripts.telemetry_destination import AzureLogsDestination, DestinationError

MAXIMUM_BODY_BYTES = 512 * 1024
MAXIMUM_SIGNALS = 512
EXPECTED_SCHEMA = "mobius-operational-v1"
AUTH_ENVIRONMENT_VARIABLE = "OPENCANVAS_TELEMETRY_GATEWAY_TOKEN"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("mobius.telemetry-gateway")
application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


def _destination() -> AzureLogsDestination | None:
    mode = os.getenv("OPENCANVAS_TELEMETRY_GATEWAY_DESTINATION", "receipt_only")
    if mode == "receipt_only":
        # Historical 7.7 receiver, explicitly not destination acceptance.
        return None
    if mode != "azure_logs":
        raise DestinationError("telemetry_destination_not_configured")
    return AzureLogsDestination.from_environment()


def _authentication_token() -> str:
    token = os.getenv(AUTH_ENVIRONMENT_VARIABLE, "")
    if len(token.encode("utf-8")) < 32:
        raise RuntimeError("Telemetry gateway authentication is not configured.")
    return token


def _authorize(authorization: str | None) -> None:
    expected = f"Bearer {_authentication_token()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")


def _validate_payload(payload: object) -> tuple[int, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"resource", "signals"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid")
    resource = payload["resource"]
    signals = payload["signals"]
    if not isinstance(resource, Mapping) or resource != {"schema": EXPECTED_SCHEMA}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid")
    if not isinstance(signals, list) or not 1 <= len(signals) <= MAXIMUM_SIGNALS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid")
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return len(signals), hashlib.sha256(canonical).hexdigest()


@application.get("/health")
async def health() -> dict[str, str]:
    _authentication_token()
    try:
        _destination()
    except DestinationError as exc:
        raise HTTPException(status_code=503, detail="destination_not_configured") from exc
    return {"status": "healthy"}


@application.post("/v1/signals", status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    _authorize(authorization)
    body = bytearray()
    async for part in request.stream():
        if len(body) + len(part) > MAXIMUM_BODY_BYTES:
            raise HTTPException(status_code=413, detail="bounded")
        body.extend(part)
    if not body or len(body) > MAXIMUM_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="bounded")
    try:
        payload: Any = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid"
        ) from exc
    signal_count, digest = _validate_payload(payload)
    try:
        destination = _destination()
        if destination is not None:
            await destination.export(payload)
    except DestinationError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=422 if code == "invalid_operational_signal" else 503,
            detail="invalid" if code == "invalid_operational_signal" else "destination_unavailable",
        ) from None
    logger.info(
        json.dumps(
            {
                "event": "telemetry-batch-accepted",
                "payloadSha256": digest,
                "signalCount": signal_count,
                "destinationAcknowledged": destination is not None,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


def main() -> None:
    import uvicorn

    uvicorn.run(application, host="0.0.0.0", port=4318, access_log=False)


if __name__ == "__main__":
    main()

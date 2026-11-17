"""Validate and optionally export approved native provider readbacks; never query Azure.

The campaign's separately authorized execution wrapper binds these private file
hashes and exact resource IDs. --validate performs no export. A native response
accepted here is still not a managed assertion acceptance receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from opencanvas_api.core.config import Settings
from opencanvas_api.services.observability import InMemoryTelemetrySink, build_observability
from opencanvas_api.services.operational_observations import (
    bind_operational_telemetry,
    record_provider_observation,
)


def bound_document(path: Path, expected: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > 524288 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("readback file binding or bound mismatch")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("readback document required")
    return result


async def observe(args: argparse.Namespace) -> dict[str, Any]:
    bindings = bound_document(args.bindings, args.bindings_sha256)
    observation = bound_document(args.readback, args.readback_sha256)
    resources = bindings["resourceIds"]
    if (
        not isinstance(resources, list)
        or not 1 <= len(resources) <= 8
        or not all(
            isinstance(item, str) and item.startswith("/subscriptions/") for item in resources
        )
    ):
        raise ValueError("exact bounded provider resource allowlist required")
    settings = Settings()
    if (
        settings.telemetry_release != bindings["release"]
        or settings.telemetry_deployment != bindings["deployment"]
    ):
        raise ValueError("runtime release/deployment differs from bound observation")
    if args.emit and (not settings.telemetry_enabled or settings.telemetry_exporter != "http"):
        raise ValueError("live observation requires enabled authenticated HTTP telemetry")
    telemetry = build_observability(settings, sink=None if args.emit else InMemoryTelemetrySink())
    try:
        with bind_operational_telemetry(telemetry):
            name = record_provider_observation(
                observation,
                expected_resource_ids=frozenset(resources),
                expected_release=bindings["release"],
                expected_deployment=bindings["deployment"],
            )
        flushed = await telemetry.flush()
        if args.emit and not flushed:
            raise ValueError("provider observation export not acknowledged")
        return {
            "schema": "mobius-provider-observation-receipt-v1",
            "metric": name,
            "readbackSha256": args.readback_sha256,
            "bindingsSha256": args.bindings_sha256,
            "exported": bool(args.emit and flushed),
            "managedAcceptance": "unproved",
        }
    finally:
        await telemetry.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readback", type=Path, required=True)
    parser.add_argument("--readback-sha256", required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--bindings-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    intent = args.output.with_suffix(".intent.json")
    if args.output.exists() or intent.exists():
        raise ValueError("existing observation attempt must be reconciled")
    with intent.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "readbackSha256": args.readback_sha256,
                "bindingsSha256": args.bindings_sha256,
                "emit": args.emit,
            },
            handle,
        )
    try:
        result = asyncio.run(observe(args))
    except Exception as error:
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "errorClass": type(error).__name__,
                    "managedAcceptance": "unproved",
                    "reconcileBeforeRetry": True,
                },
                handle,
            )
        return 1
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

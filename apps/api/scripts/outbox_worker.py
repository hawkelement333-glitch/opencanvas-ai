"""Separately deployed bounded dispatcher for the private activity-v1 receiver."""

from __future__ import annotations

import argparse
import asyncio
import signal
import uuid
from contextlib import suppress

from opencanvas_api.core.config import AppMode, DatabaseRole, get_settings
from opencanvas_api.db.runtime import validate_database_runtime
from opencanvas_api.db.session import Database
from opencanvas_api.services.observability import build_observability
from opencanvas_api.services.outbox_dispatcher import HttpActivityConsumer, OutboxDispatcher


async def run(*, once: bool) -> int:
    settings = get_settings()
    if (
        settings.runtime_mode is AppMode.DEMO
        or settings.outbox_receiver_url is None
        or settings.outbox_delivery_secret is None
    ):
        raise ValueError("Outbox worker requires the exact receiver and dedicated authority.")
    database = Database.from_settings(settings, expected_role=DatabaseRole.WORKER)
    telemetry = build_observability(settings)
    consumer = HttpActivityConsumer(
        settings.outbox_receiver_url,
        settings.outbox_delivery_secret.get_secret_value(),
        allow_loopback_http=settings.runtime_mode is AppMode.TEST,
    )
    worker = OutboxDispatcher(
        database.sessions,
        owner_id="outbox-" + str(uuid.uuid4()),
        consumer=consumer,
        telemetry=telemetry,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    try:
        await validate_database_runtime(
            database.engine, settings, expected_role=DatabaseRole.WORKER
        )
        if once:
            await worker.run_once()
        else:
            await worker.run_forever(poll_seconds=settings.worker_poll_interval_seconds, stop=stop)
    finally:
        await telemetry.close()
        await database.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    return asyncio.run(run(once=parser.parse_args().once))


if __name__ == "__main__":
    raise SystemExit(main())

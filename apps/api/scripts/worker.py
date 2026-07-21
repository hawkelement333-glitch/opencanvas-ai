from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from opencanvas_api.core.config import AppMode, get_settings
from opencanvas_api.db.models import WorkerHeartbeat
from opencanvas_api.db.session import Database
from opencanvas_api.services.jobs import DocumentWorker


async def run(*, once: bool, healthcheck: bool) -> int:
    settings = get_settings()
    if settings.runtime_mode is AppMode.DEMO:
        raise RuntimeError("Demo mode does not start the production document worker.")
    database = Database(settings.database_url)
    worker = DocumentWorker(settings=settings, sessions=database.sessions)
    try:
        if healthcheck:
            async with database.sessions() as session:
                heartbeat = await session.scalar(
                    select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1)
                )
            cutoff = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)
            if heartbeat is None:
                return 1
            last_seen = heartbeat.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            return 0 if last_seen >= cutoff else 1
        if once:
            await worker.run_once()
            return 0
        await worker.run_forever()
    finally:
        await database.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SolarPlexus Mobius document worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    parser.add_argument(
        "--healthcheck", action="store_true", help="Exit zero when a worker heartbeat is fresh"
    )
    arguments = parser.parse_args()
    return asyncio.run(run(once=arguments.once, healthcheck=arguments.healthcheck))


if __name__ == "__main__":
    raise SystemExit(main())

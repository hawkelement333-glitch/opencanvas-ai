from __future__ import annotations

import argparse
import asyncio

from opencanvas_api.core.config import AppMode, get_settings
from opencanvas_api.db.session import Database
from opencanvas_api.services.jobs import DocumentWorker


async def run(*, once: bool) -> int:
    settings = get_settings()
    if settings.runtime_mode is AppMode.DEMO:
        raise RuntimeError("Demo mode does not start the production document worker.")
    database = Database(settings.database_url)
    worker = DocumentWorker(settings=settings, sessions=database.sessions)
    try:
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
    arguments = parser.parse_args()
    return asyncio.run(run(once=arguments.once))


if __name__ == "__main__":
    raise SystemExit(main())

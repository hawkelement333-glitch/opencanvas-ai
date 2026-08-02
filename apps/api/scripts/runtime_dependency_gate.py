from __future__ import annotations

import argparse
import asyncio

from opencanvas_api.core.config import DatabaseRole, get_settings
from opencanvas_api.db.runtime import DatabaseRuntimeError, validate_database_runtime
from opencanvas_api.db.session import Database


async def run(*, attempts: int, delay_seconds: float) -> int:
    settings = get_settings()
    role = settings.database_role
    if role not in {DatabaseRole.API, DatabaseRole.WORKER}:
        raise RuntimeError("runtime dependency gate refuses a non-runtime database role")
    database = Database.from_settings(settings, expected_role=role)
    try:
        for attempt in range(attempts):
            try:
                await validate_database_runtime(database.engine, settings, expected_role=role)
                return 0
            except DatabaseRuntimeError:
                if attempt + 1 == attempts:
                    raise
                await asyncio.sleep(delay_seconds)
    finally:
        await database.dispose()
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    arguments = parser.parse_args()
    if not 1 <= arguments.attempts <= 120 or not 0.1 <= arguments.delay_seconds <= 10:
        raise SystemExit("runtime dependency gate bounds are invalid")
    return asyncio.run(run(attempts=arguments.attempts, delay_seconds=arguments.delay_seconds))


if __name__ == "__main__":
    raise SystemExit(main())

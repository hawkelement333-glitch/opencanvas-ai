from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from opencanvas_api.core.config import (
    EXPECTED_DATABASE_REVISION,
    AppMode,
    DatabaseRole,
    get_settings,
)


def run(*, expected_current: str | None, target: str) -> int:
    settings = get_settings()
    settings.require_database_role(DatabaseRole.MIGRATION)
    if settings.runtime_mode in {AppMode.STAGING, AppMode.PRODUCTION} and expected_current is None:
        raise RuntimeError("deployed migrations require an explicit expected current revision")

    api_root = Path(__file__).resolve().parents[1]
    config = Config(api_root / "alembic.ini")
    config.set_main_option("script_location", str(api_root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url_value.replace("%", "%%"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if heads != [EXPECTED_DATABASE_REVISION]:
        raise RuntimeError("repository migration head does not match the release contract")
    if target not in {"head", EXPECTED_DATABASE_REVISION}:
        raise RuntimeError("migration target does not match the release contract")

    config.attributes["managed_migration"] = True
    config.attributes["expected_current_revision"] = expected_current
    config.attributes["expected_target_revision"] = EXPECTED_DATABASE_REVISION
    command.upgrade(config, EXPECTED_DATABASE_REVISION)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one guarded SolarPlexus database migration")
    parser.add_argument(
        "--expected-current",
        help="Required in staging/production; use 'base' for an empty database.",
    )
    parser.add_argument("--target", default="head")
    arguments = parser.parse_args()
    try:
        return run(expected_current=arguments.expected_current, target=arguments.target)
    except Exception:
        print(
            "Migration failed safely. Verify the declared role, expected revision, "
            "target release, and protected operational database diagnostics.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

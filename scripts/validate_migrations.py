"""Exercise the complete Alembic migration cycle in an isolated database."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from alembic import command
from alembic.config import Config

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
EXPECTED_HEAD = "20260721_0008"
PREVIOUS_REVISION = "20260721_0007"


def revision(database_path: Path) -> str:
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None or not isinstance(row[0], str):
        raise RuntimeError("Alembic did not record a valid database revision.")
    return row[0]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="opencanvas-migrations-") as temporary:
        database_path = Path(temporary) / "migration-validation.db"
        config = Config(API_ROOT / "alembic.ini")
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        config.set_main_option(
            "sqlalchemy.url",
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
        )

        command.upgrade(config, "head")
        if revision(database_path) != EXPECTED_HEAD:
            raise RuntimeError(f"Migration upgrade did not reach {EXPECTED_HEAD}.")

        command.downgrade(config, PREVIOUS_REVISION)
        if revision(database_path) != PREVIOUS_REVISION:
            raise RuntimeError(
                f"Migration downgrade did not reach {PREVIOUS_REVISION}."
            )

        command.upgrade(config, "head")
        if revision(database_path) != EXPECTED_HEAD:
            raise RuntimeError(f"Migration re-upgrade did not reach {EXPECTED_HEAD}.")

    print(
        f"Migration validation passed: upgrade {EXPECTED_HEAD}, downgrade "
        f"{PREVIOUS_REVISION}, re-upgrade {EXPECTED_HEAD}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

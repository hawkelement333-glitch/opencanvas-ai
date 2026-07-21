from __future__ import annotations

import pytest

from tests.postgres_support import validate_postgres_test_url


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://user:placeholder@localhost/opencanvas",
        "postgresql+asyncpg://user:placeholder@localhost/opencanvas_production_test",
        "postgresql+asyncpg://user:placeholder@db.example.test/opencanvas_test",
    ],
)
def test_postgres_test_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_postgres_test_url(url)


def test_postgres_test_url_accepts_explicit_loopback_test_database() -> None:
    result = validate_postgres_test_url(
        "postgresql+asyncpg://opencanvas:placeholder@127.0.0.1:55432/opencanvas_test_admin"
    )
    assert result.database == "opencanvas_test_admin"

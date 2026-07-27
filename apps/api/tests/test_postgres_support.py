from __future__ import annotations

import pytest
from sqlalchemy.engine import URL

from tests.postgres_support import _RedactedPostgresTestUrl, validate_postgres_test_url


def _postgres_url(*, host: str, database: str) -> str:
    return URL.create(
        drivername="postgresql+asyncpg",
        username="opencanvas",
        password="placeholder",
        host=host,
        port=55432,
        database=database,
    ).render_as_string(hide_password=False)


@pytest.mark.parametrize(
    "url",
    [
        URL.create(drivername="sqlite+aiosqlite", database=":memory:").render_as_string(),
        _postgres_url(host="localhost", database="opencanvas"),
        _postgres_url(host="localhost", database="opencanvas_production_test"),
        _postgres_url(host="db.example.test", database="opencanvas_test"),
    ],
)
def test_postgres_test_url_rejects_unsafe_targets(url: str) -> None:
    with pytest.raises(ValueError):
        validate_postgres_test_url(url)


def test_postgres_test_url_accepts_explicit_loopback_test_database() -> None:
    result = validate_postgres_test_url(
        _postgres_url(host="127.0.0.1", database="opencanvas_test_admin")
    )
    assert result.database == "opencanvas_test_admin"


def test_postgres_test_url_repr_never_exposes_connection_details() -> None:
    value = _RedactedPostgresTestUrl(
        _postgres_url(host="127.0.0.1", database="opencanvas_test_admin")
    )

    assert repr(value) == "<redacted PostgreSQL test URL>"
    assert "placeholder" not in repr(value)
    assert "127.0.0.1" not in repr(value)

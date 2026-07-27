from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

MIGRATIONS = (
    "20260725_0023_resource_sharing_ownership_revocation.py",
    "20260725_0024_comments_collaboration_activity.py",
)


def _migration_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename


def _load_migration(filename: str) -> ModuleType:
    path = _migration_path(filename)
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_the_four_approved_trigger_function_references_are_present() -> None:
    sources = [_migration_path(filename).read_text(encoding="utf-8") for filename in MIGRATIONS]

    assert all("reject_controlled_agent_security_mutation" not in source for source in sources)
    assert (
        sum(
            source.count("EXECUTE FUNCTION reject_controlled_agent_mutation()")
            for source in sources
        )
        == 4
    )


@pytest.mark.parametrize("filename", MIGRATIONS)
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "event_type IN ('value_a', 'value_b', 'value_c')",
            ("value_a", "value_b", "value_c"),
        ),
        (
            "event_type::text = ANY "
            "(ARRAY['value_a'::character varying, 'value_b'::character varying, "
            "'value_c'::character varying]::text[])",
            ("value_a", "value_b", "value_c"),
        ),
        (
            "event_type::character varying = ANY "
            "(ARRAY['value_a'::text, 'value_b'::character varying]::text[])",
            ("value_a", "value_b"),
        ),
        (
            " ((( event_type :: text = ANY "
            "(( ARRAY [ 'value_a' :: character varying, 'value_b' :: text ] "
            ":: character varying [] )) ))) ",
            ("value_a", "value_b"),
        ),
        (
            "((event_type))::text = ANY "
            "(((ARRAY['value_a'::character varying, 'value_b'::text])::text[]))",
            ("value_a", "value_b"),
        ),
        (
            "event_type::text = ANY "
            "((ARRAY['value_a'::character varying, 'value_b'::text]"
            "::character varying[])::text[])",
            ("value_a", "value_b"),
        ),
        (
            "event_type IN ('can''t', 'comma,value', 'plain'::text)",
            ("can't", "comma,value", "plain"),
        ),
    ],
)
def test_closed_check_parser_accepts_only_supported_sql_shapes(
    filename: str,
    expression: str,
    expected: tuple[str, ...],
) -> None:
    migration = _load_migration(filename)

    assert migration._parse_check_values(expression, column="event_type") == expected


@pytest.mark.parametrize("filename", MIGRATIONS)
@pytest.mark.parametrize(
    "expression",
    [
        "event_type = 'value_a'",
        "event_type IN ('value_a') OR TRUE",
        "event_type = ANY (SELECT event_type FROM domain_events)",
        "event_type = ANY (ARRAY['value_a'::text, now()]::text[])",
        "event_type = ANY (ARRAY['value_a'::integer]::text[])",
        "(event_type)::integer = ANY (ARRAY['value_a'::text]::text[])",
        "event_type::text = ANY ((ARRAY['value_a'::text])::integer[])",
        "event_type IN ()",
        "event_type IN ('unterminated)",
        "other_column IN ('value_a')",
        "event_type IN ('value_a'); SELECT pg_sleep(10)",
    ],
)
def test_closed_check_parser_fails_closed_without_executing_unknown_sql(
    filename: str,
    expression: str,
) -> None:
    migration = _load_migration(filename)

    with pytest.raises(RuntimeError, match="unsupported check constraint expression"):
        migration._parse_check_values(expression, column="event_type")


@pytest.mark.parametrize("filename", MIGRATIONS)
def test_registry_fingerprint_rejects_duplicates_or_widening(filename: str) -> None:
    migration = _load_migration(filename)
    values = ("value_a", "value_b")
    fingerprint = (2, migration._registry_digest(values))

    assert (
        migration._require_expected_registry(
            values,
            fingerprint=fingerprint,
            constraint="ck_domain_events_type",
        )
        == values
    )

    with pytest.raises(RuntimeError, match="unexpected closed registry"):
        migration._require_expected_registry(
            (*values, "unapproved"),
            fingerprint=fingerprint,
            constraint="ck_domain_events_type",
        )
    with pytest.raises(RuntimeError, match="unexpected closed registry"):
        migration._require_expected_registry(
            ("value_a", "value_a"),
            fingerprint=fingerprint,
            constraint="ck_domain_events_type",
        )


def test_embedded_registries_match_the_immutable_migration_history() -> None:
    migration_0022 = _load_migration("20260725_0022_collaboration_roles_permission_authority.py")
    migration_0023 = _load_migration(MIGRATIONS[0])
    migration_0024 = _load_migration(MIGRATIONS[1])
    before_0023 = {
        "ck_domain_events_type": (migration_0022.BASE_EVENT_TYPES + migration_0022.NEW_EVENT_TYPES),
        "ck_domain_events_subject_kind": (
            *migration_0022.BASE_SUBJECT_KINDS,
            migration_0022.NEW_SUBJECT_KIND,
        ),
        "ck_collaboration_request_operation": (
            migration_0022.BASE_REQUEST_OPERATIONS + migration_0022.NEW_REQUEST_OPERATIONS
        ),
        "ck_collaboration_request_result_kind": (
            "workspace_invitation",
            "workspace_membership",
            "approval_authority_assignment",
        ),
        "ck_collaboration_audit_subject_kind": (
            "workspace_membership",
            "workspace_invitation",
            "approval_authority_assignment",
        ),
    }

    assert before_0023 == migration_0023._REGISTRIES_BEFORE
    assert migration_0024._REGISTRIES_BEFORE == migration_0023._REGISTRIES_AFTER
    assert {
        constraint: len(values) for constraint, values in migration_0024._REGISTRIES_AFTER.items()
    } == {
        "ck_domain_events_type": 91,
        "ck_domain_events_subject_kind": 27,
        "ck_collaboration_request_operation": 26,
        "ck_collaboration_request_result_kind": 12,
        "ck_collaboration_audit_subject_kind": 11,
    }


class _CapturingBind:
    def __init__(self, dialect: str) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.statements: list[str] = []

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


def _captured_resource_backfills(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dialect: str,
) -> list[str]:
    migration = _load_migration(MIGRATIONS[0])
    bind = _CapturingBind(dialect)
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)

    migration._backfill_resources()

    return [
        statement
        for statement in bind.statements
        if statement.startswith("INSERT INTO collaboration_resources ")
    ]


def test_postgresql_resource_backfill_types_all_twelve_uuid_nulls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements = _captured_resource_backfills(monkeypatch, dialect="postgresql")

    assert len(statements) == 4
    assert [statement.count("NULL::uuid") for statement in statements] == [4, 4, 2, 2]
    assert sum(statement.count("NULL::uuid") for statement in statements) == 12
    for statement in statements:
        assert re.search(r"\bNULL\b", statement.replace("NULL::uuid", "")) is None


def test_sqlite_resource_backfill_keeps_existing_null_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements = _captured_resource_backfills(monkeypatch, dialect="sqlite")

    assert len(statements) == 4
    assert [len(re.findall(r"\bNULL\b", statement)) for statement in statements] == [4, 4, 2, 2]
    assert all("NULL::uuid" not in statement for statement in statements)

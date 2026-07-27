from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest


def _load_validator() -> ModuleType:
    repository_root = Path(__file__).resolve().parents[3]
    path = repository_root / "scripts" / "validate_migrations.py"
    spec = importlib.util.spec_from_file_location(
        "validate_migrations_identifier_safety",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _violations(source: str) -> tuple[object, ...]:
    return VALIDATOR.find_postgresql_identifier_violations(
        source,
        source_name="fixture.py",
    )


@pytest.mark.parametrize(
    "identifier",
    sorted(VALIDATOR.POSTGRESQL_UNSAFE_IDENTIFIERS),
)
def test_guard_rejects_sensitive_identifiers_in_textual_constraints(
    identifier: str,
) -> None:
    source = f"""
from sqlalchemy import CheckConstraint

constraint = CheckConstraint("{identifier} IN ('allowed')")
"""

    violations = _violations(source)

    assert [(item.context, item.identifier) for item in violations] == [
        ("textual check constraint", identifier)
    ]


def test_guard_rejects_bare_current_role_in_insert_target_list() -> None:
    source = """
from sqlalchemy import text

def upgrade():
    bind.execute(text(
        "INSERT INTO transitions "
        "(transition_id, current_role, reason_code) "
        "VALUES (:transition_id, 'owner', :reason_code)"
    ))
"""

    violations = _violations(source)

    assert [(item.context, item.identifier) for item in violations] == [
        ("INSERT target list", "current_role")
    ]


@pytest.mark.parametrize(
    ("statement", "context", "identifier"),
    [
        (
            "INSERT INTO snapshots (snapshot_id) VALUES (current_user)",
            "INSERT source expression",
            "current_user",
        ),
        (
            "INSERT INTO user (user_id) VALUES (:user_id)",
            "INSERT target",
            "user",
        ),
        (
            "INSERT INTO snapshots (snapshot_id) SELECT current_role FROM transitions",
            "SELECT expression",
            "current_role",
        ),
        (
            "SELECT current_role FROM transitions",
            "SELECT expression",
            "current_role",
        ),
        ("SELECT group FROM records", "SELECT expression", "group"),
        ("SELECT order FROM records", "SELECT expression", "order"),
        ("SELECT limit FROM records", "SELECT expression", "limit"),
        ("SELECT value, limit FROM records", "SELECT expression", "limit"),
        ("SELECT value AS limit FROM records", "SELECT expression", "limit"),
        (
            "UPDATE transitions SET current_role = 'owner' WHERE transition_id = :id",
            "UPDATE assignment",
            "current_role",
        ),
        (
            "DELETE FROM user WHERE user_id = :id",
            "DELETE target",
            "user",
        ),
        (
            "DELETE FROM transitions WHERE current_role = 'owner'",
            "DELETE expression",
            "current_role",
        ),
    ],
)
def test_guard_rejects_sensitive_identifiers_in_raw_sql_expressions(
    statement: str,
    context: str,
    identifier: str,
) -> None:
    source = f"""
from sqlalchemy import text

def upgrade():
    bind.execute(text({statement!r}))
"""

    violations = _violations(source)

    assert [(item.context, item.identifier) for item in violations] == [(context, identifier)]


def test_guard_accepts_quoted_identifiers_and_string_values() -> None:
    source = """
from sqlalchemy import CheckConstraint, text

constraint = CheckConstraint(
    "\\"current_role\\" IN ('current_role', 'owner')"
)

def upgrade():
    bind.execute(text(
        'INSERT INTO transitions '
        '(transition_id, "current_role", reason_code) '
        "VALUES (:transition_id, 'current_role', :reason_code)"
    ))
"""

    assert _violations(source) == ()


def test_guard_accepts_quoted_or_qualified_raw_sql_expressions() -> None:
    source = """
from sqlalchemy import text

def upgrade():
    bind.execute(text('INSERT INTO "user" (user_id) VALUES (:user_id)'))
    bind.execute(text(
        'INSERT INTO snapshots (snapshot_id, "current_role") '
        "SELECT source.snapshot_id, source.current_role FROM source"
    ))
    bind.execute(text(
        'UPDATE transitions AS transition '
        'SET "current_role" = \\'current_role\\' '
        "WHERE transition.current_role = 'owner'"
    ))
    bind.execute(text(
        "DELETE FROM transitions AS transition "
        "WHERE transition.current_role = 'owner' "
        "RETURNING transition.current_role"
    ))
    bind.execute(text(
        "SELECT CASE WHEN (SELECT source.current_role FROM source "
        "ORDER BY source.sequence DESC LIMIT 1) = 'owner' THEN 1 END"
    ))
    bind.execute(text("SELECT 1 GROUP BY 1"))
    bind.execute(text("SELECT 1 ORDER BY 1 LIMIT 1"))
"""

    assert _violations(source) == ()


def test_guard_accepts_qualified_fields_and_sql_clause_keywords() -> None:
    source = """
from sqlalchemy import text

def upgrade():
    bind.execute(text(
        "CREATE FUNCTION validate_transition() RETURNS trigger AS $$ "
        "BEGIN IF NEW.current_role = 'owner' THEN RETURN NEW; END IF; END; $$ "
        "LANGUAGE plpgsql"
    ))
    bind.execute(text(
        "SELECT t.current_role FROM transitions AS t "
        "GROUP BY t.current_role ORDER BY t.current_role LIMIT 1"
    ))
"""

    assert _violations(source) == ()


def test_guard_ignores_python_attributes_column_declarations_comments_and_binds() -> None:
    source = """
import sqlalchemy as sa

# current_role is a Python comment, not SQL.
current_role = sa.Column("current_role", sa.String(24))
value = model.current_role

def upgrade():
    bind.execute(sa.text(
        "INSERT INTO transitions (transition_id, reason_code) "
        "VALUES (:current_role, 'current_role')"
    ))
"""

    assert _violations(source) == ()


def test_role_is_inspected_but_not_rejected_because_postgresql_does_not_reserve_it() -> None:
    assert "role" in VALIDATOR.POSTGRESQL_SENSITIVE_IDENTIFIER_CANDIDATES
    assert "role" not in VALIDATOR.POSTGRESQL_UNSAFE_IDENTIFIERS
    source = """
from sqlalchemy import CheckConstraint, text

constraint = CheckConstraint("role IN ('owner', 'viewer')")

def upgrade():
    bind.execute(text(
        "INSERT INTO snapshots (snapshot_id, role) VALUES (:snapshot_id, 'viewer')"
    ))
"""

    assert _violations(source) == ()


def test_guard_scans_upgrade_and_downgrade_functions() -> None:
    source = """
from sqlalchemy import text

def upgrade():
    bind.execute(text(
        "INSERT INTO transitions (id, current_role) VALUES (:id, 'owner')"
    ))

def downgrade():
    bind.execute(text(
        "INSERT INTO archived_transitions (id, current_user) VALUES (:id, 'owner')"
    ))
"""

    violations = _violations(source)

    assert [(item.function, item.identifier) for item in violations] == [
        ("upgrade", "current_role"),
        ("downgrade", "current_user"),
    ]


def test_guard_scans_the_corrected_repository() -> None:
    VALIDATOR.validate_postgresql_identifier_safety()


def test_migration_0021_preserves_the_exact_quoted_owner_backfill_target() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    migration_path = (
        repository_root
        / "apps"
        / "api"
        / "alembic"
        / "versions"
        / "20260725_0021_workspace_memberships_invitations.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    fragments = [
        fragment
        for fragment in VALIDATOR.collect_sql_fragments(
            source,
            source_name=migration_path.relative_to(repository_root).as_posix(),
        )
        if "INSERT INTO workspace_membership_transitions" in fragment.sql
        and "workspace_owner_backfill" in fragment.sql
    ]

    assert len(fragments) == 1
    statement = re.sub(r"\s+", " ", fragments[0].sql)
    assert (
        "(transition_id, membership_id, user_id, workspace_id, sequence, "
        'previous_state, current_state, previous_role, "current_role", reason_code, '
        "collaboration_policy_version, authority_generation, actor_user_id, trace_id, "
        "audit_event_id, recorded_at)"
    ) in statement
    assert "'active', NULL, 'owner', 'workspace_owner_backfill'" in statement
    assert (
        VALIDATOR.find_postgresql_identifier_violations(
            source,
            source_name=migration_path.relative_to(repository_root).as_posix(),
        )
        == ()
    )

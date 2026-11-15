from __future__ import annotations

import pytest

from infra.milestone_7_8.managed_objects_bootstrap import fixture_grants
from infra.milestone_7_8.managed_objects_lock_grants import (
    LOCK_COLUMNS,
    grant_statements,
    require_guards,
    require_reviewed_inventory,
)
from opencanvas_api.core.config import DatabaseRole
from opencanvas_api.db.role_privileges import (
    RUNTIME_ROW_LOCK_COLUMNS,
    RUNTIME_TABLE_PRIVILEGES,
    runtime_privilege_statements,
)


def test_runtime_row_locks_get_only_role_specific_identity_columns() -> None:
    statements = runtime_privilege_statements(
        api_principal="api",
        worker_principal="worker",
        migration_principal="migration",
        application_routines=(),
    )
    column_grants = [
        statement for statement in statements if statement.startswith("GRANT UPDATE (")
    ]
    assert column_grants == [
        'GRANT UPDATE ("session_id") ON TABLE public."upload_sessions" TO "api"',
        'GRANT UPDATE ("scan_request_id") ON TABLE public."malware_scan_requests" TO "worker"',
        'GRANT UPDATE ("deletion_request_id") ON TABLE '
        'public."object_deletion_requests" TO "worker"',
        'GRANT UPDATE ("session_id") ON TABLE public."upload_sessions" TO "worker"',
    ]
    for role in (DatabaseRole.API, DatabaseRole.WORKER):
        assert not set(dict(LOCK_COLUMNS)) & RUNTIME_TABLE_PRIVILEGES[role]["UPDATE"]
    assert RUNTIME_ROW_LOCK_COLUMNS[DatabaseRole.API] == {"upload_sessions": "session_id"}
    assert RUNTIME_ROW_LOCK_COLUMNS[DatabaseRole.WORKER] == dict(LOCK_COLUMNS)


def test_external_bootstrap_and_one_off_action_match_reviewed_production_union() -> None:
    require_reviewed_inventory()
    production_union = {
        (table, column)
        for columns in RUNTIME_ROW_LOCK_COLUMNS.values()
        for table, column in columns.items()
    }
    assert production_union == set(LOCK_COLUMNS)
    assert tuple(
        statement for statement in fixture_grants("probe") if statement.startswith("GRANT UPDATE (")
    ) == grant_statements("probe")
    assert all(statement.startswith("GRANT UPDATE (") for statement in grant_statements("probe"))
    assert all("ON TABLE public." in statement for statement in grant_statements("probe"))


def guards() -> list[dict[str, object]]:
    return [
        {
            "table_name": table,
            "trigger_name": f"trg_{table}_{operation}_blocked",
            "trigger_type": kind,
            "enabled": "O",
            "function_schema": "public",
            "function_name": "reject_controlled_agent_mutation",
        }
        for table, _ in LOCK_COLUMNS
        for operation, kind in (("update", 19), ("delete", 11))
    ]


def test_one_off_grant_requires_all_six_original_immutable_guards() -> None:
    require_guards(guards())
    with pytest.raises(RuntimeError, match="inventory incomplete"):
        require_guards(guards()[:-1])
    for key, wrong in (
        ("enabled", "D"),
        ("trigger_type", 17),
        ("function_name", "different_function"),
        ("function_schema", "other"),
    ):
        altered = guards()
        altered[0][key] = wrong
        with pytest.raises(RuntimeError, match="guard differs"):
            require_guards(altered)


def test_column_grant_principal_identifier_is_quoted() -> None:
    assert all(
        statement.endswith('TO "probe""suffix"') for statement in grant_statements('probe"suffix')
    )

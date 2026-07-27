"""Exercise the complete Alembic migration cycle in an isolated database."""

from __future__ import annotations

import ast
import re
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from typing import NamedTuple

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql.base import RESERVED_WORDS

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
VERSIONS_ROOT = API_ROOT / "alembic" / "versions"
MODELS_PATH = API_ROOT / "opencanvas_api" / "db" / "models.py"
EXPECTED_HEAD = "20260725_0025"
PREVIOUS_REVISION = "20260725_0024"
POSTGRESQL_SENSITIVE_IDENTIFIER_CANDIDATES = frozenset(
    {
        "authorization",
        "current_catalog",
        "current_role",
        "current_schema",
        "current_user",
        "group",
        "limit",
        "order",
        "role",
        "session_user",
        "user",
    }
)
POSTGRESQL_UNSAFE_IDENTIFIERS = frozenset(RESERVED_WORDS).intersection(
    POSTGRESQL_SENSITIVE_IDENTIFIER_CANDIDATES
)
EXPECTED_MIGRATION_BLOB_HASHES = {
    "20260716_0001_initial_mvp.py": "17f5dcba649b2fa8ec0f2dc4263b26957e29d378",
    "20260717_0002_document_ingestion.py": "8d8cbb2b313df3c33120ee3a7faf18e270dbdef9",
    "20260717_0003_trace_foundation.py": "3cd0be30f4ba6d22da3b611b4bc65e125eee536b",
    "20260717_0004_canonical_persistence.py": "6c2f314573833567db48174c61410406b51d788b",
    "20260718_0005_productization_bridge.py": "79667acf61794c139b2cc27dcf8f2e0598162a5e",
    "20260721_0006_immutable_rerun_snapshots.py": "c805b98075a003324485e49893d45376bb765293",
    "20260721_0007_controlled_agent_persistence.py": "7603f1586256cb21db2ec026535f03ff837b18d7",
    "20260721_0008_agent_request_idempotency.py": "042579b593fb93be9823625846a0b029a06759fb",
    "20260723_0009_agent_lifecycle_transitions.py": "dc1dafa8359dce757d32c9863d270fe61467057d",
    "20260724_0010_agent_prepared_execution.py": "85ca2d48e55918f072fc0dfd166a631ab288bbbf",
    "20260724_0011_reversible_write_proposals.py": "e4f462ecd0d608697092ebc1d3645330bd8a67b5",
    "20260724_0012_reversible_write_effects.py": "a3db71199c596cc6c03d9a3ff22e1051065d7cef",
    "20260724_0013_reversible_write_rollback_evidence.py": (
        "7c61bcc545724538992064c210b754980c17f402"
    ),
    "20260724_0014_reversible_write_rollback_authority.py": (
        "a13937dfec7fe8b84f660d4a80b292c917eab975"
    ),
    "20260724_0015_execution_reliability.py": "8efbf64a9326b6cb18736dd07fd942a84ef5026d",
    "20260725_0016_knowledge_graph_foundation.py": "9279fd9c87564022b5eaf3a2a1be042168b21670",
    "20260725_0017_living_state_event_system.py": "d16915eaed17cc2daa27c0562a5cf6c1ff41faf2",
    "20260725_0018_graph_aware_retrieval.py": "71d4d6fbfd5999f572271ba147e929d120c51bf6",
    "20260725_0019_controlled_ai_workflows.py": "6d9f27f603fc59a9a9be5895ca5542730c858d29",
    "20260725_0020_bounded_agent_studio.py": "9dca4d46d30f2d817c7735fad9e176ba5fbb36e0",
    "20260725_0021_workspace_memberships_invitations.py": (
        "43939e1652e052bbeb3b3de8fd20e052443273d3"
    ),
    "20260725_0022_collaboration_roles_permission_authority.py": (
        "d4a3bfc1bd32b3df9a886645fba318a51d2ed3a0"
    ),
    "20260725_0023_resource_sharing_ownership_revocation.py": (
        "cb7138d9de806e1546c3853944b1816a98da1d67"
    ),
    "20260725_0024_comments_collaboration_activity.py": (
        "cc29d1280af1a4110ec42b7f0fa782f710dcfeb5"
    ),
    "20260725_0025_shared_workflow_agent_governance.py": (
        "b5c71452728cf5c473a017679ebb6f2903a5f9f6"
    ),
}
EXPECTED_REVISION_CHAIN = tuple(
    filename.split("_", 2)[0] + "_" + filename.split("_", 2)[1]
    for filename in EXPECTED_MIGRATION_BLOB_HASHES
)
_SQL_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_INSERT_INTO = re.compile(r"\binsert\s+into\b", re.IGNORECASE)
_SELECT = re.compile(r"\bselect\b", re.IGNORECASE)
_UPDATE = re.compile(r"\bupdate\b", re.IGNORECASE)
_DELETE_FROM = re.compile(r"\bdelete\s+from\b", re.IGNORECASE)
_VALUES = re.compile(r"\bvalues\b", re.IGNORECASE)
_CHECK = re.compile(r"\bcheck\s*\(", re.IGNORECASE)


class SqlFragment(NamedTuple):
    source_name: str
    line: int
    function: str
    context: str
    sql: str


class IdentifierViolation(NamedTuple):
    source_name: str
    line: int
    function: str
    context: str
    identifier: str

    def __str__(self) -> str:
        return (
            f"{self.source_name}:{self.line}: unsafe unquoted PostgreSQL identifier "
            f"{self.identifier!r} in {self.context} ({self.function})"
        )


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _render_sql_expression(
    node: ast.expr,
    bindings: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _render_sql_expression(node.left, bindings)
        right = _render_sql_expression(node.right, bindings)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("__python_expression__")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call) and node.args and _call_name(node.func).split(".")[-1] == "text":
        return _render_sql_expression(node.args[0], bindings)
    return None


class _SqlFragmentCollector(ast.NodeVisitor):
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self.fragments: set[SqlFragment] = set()
        self._bindings: list[dict[str, str]] = [{}]
        self._functions: list[str] = ["<module>"]

    @property
    def bindings(self) -> dict[str, str]:
        return self._bindings[-1]

    @property
    def function(self) -> str:
        return self._functions[-1]

    def _bind(self, target: ast.expr, value: str | None) -> None:
        if value is not None and isinstance(target, ast.Name):
            self.bindings[target.id] = value

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _render_sql_expression(node.value, self.bindings)
        for target in node.targets:
            self._bind(target, value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        value = (
            _render_sql_expression(node.value, self.bindings) if node.value is not None else None
        )
        self._bind(node.target, value)
        self.generic_visit(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        self._bindings.append(dict(self.bindings))
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()
        self._bindings.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        final_name = _call_name(node.func).split(".")[-1]
        context: str | None = None
        if final_name == "CheckConstraint":
            context = "textual check constraint"
        elif final_name in {"text", "execute", "exec_driver_sql"}:
            context = "raw SQL"
        if context is not None and node.args:
            sql = _render_sql_expression(node.args[0], self.bindings)
            if sql is not None:
                self.fragments.add(
                    SqlFragment(
                        source_name=self.source_name,
                        line=node.lineno,
                        function=self.function,
                        context=context,
                        sql=sql,
                    )
                )
                self.visit(node.func)
                for argument in node.args[1:]:
                    self.visit(argument)
                for keyword in node.keywords:
                    self.visit(keyword.value)
                return
        self.generic_visit(node)


def collect_sql_fragments(
    source: str,
    *,
    source_name: str = "<memory>",
) -> tuple[SqlFragment, ...]:
    tree = ast.parse(source, filename=source_name)
    collector = _SqlFragmentCollector(source_name)
    collector.visit(tree)
    return tuple(sorted(collector.fragments))


def _mask_sql_literals_comments_and_binds(sql: str) -> str:
    masked = list(sql)
    index = 0
    while index < len(sql):
        character = sql[index]
        if character in {"'", '"'}:
            quote = character
            masked[index] = " "
            index += 1
            while index < len(sql):
                masked[index] = "\n" if sql[index] == "\n" else " "
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        masked[index + 1] = " "
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if sql.startswith("--", index):
            while index < len(sql) and sql[index] != "\n":
                masked[index] = " "
                index += 1
            continue
        if sql.startswith("/*", index):
            masked[index] = " "
            masked[index + 1] = " "
            index += 2
            depth = 1
            while index < len(sql) and depth:
                if sql.startswith("/*", index):
                    masked[index] = " "
                    masked[index + 1] = " "
                    depth += 1
                    index += 2
                elif sql.startswith("*/", index):
                    masked[index] = " "
                    masked[index + 1] = " "
                    depth -= 1
                    index += 2
                else:
                    masked[index] = "\n" if sql[index] == "\n" else " "
                    index += 1
            continue
        if (
            character == ":"
            and index + 1 < len(sql)
            and sql[index + 1] != ":"
            and (index == 0 or sql[index - 1] != ":")
            and (sql[index + 1].isalpha() or sql[index + 1] == "_")
        ):
            masked[index] = " "
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] in {"_", "$"}):
                masked[index] = " "
                index += 1
            continue
        index += 1
    return "".join(masked)


def _closing_parenthesis(sql: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _top_level_keyword(
    sql: str,
    *,
    start: int,
    keywords: frozenset[str],
) -> tuple[str, int, int] | None:
    depth = 0
    cursor = start
    while cursor < len(sql):
        character = sql[cursor]
        if character == "(":
            depth += 1
            cursor += 1
            continue
        if character == ")":
            if depth == 0:
                return None
            depth -= 1
            cursor += 1
            continue
        if character == ";" and depth == 0:
            return None
        if depth == 0:
            token = _SQL_IDENTIFIER.match(sql, cursor)
            if token is not None:
                identifier = token.group(0).lower()
                if identifier in keywords:
                    return identifier, token.start(), token.end()
                cursor = token.end()
                continue
        cursor += 1
    return None


def _top_level_region_end(
    sql: str,
    *,
    start: int,
    stop_keywords: frozenset[str] = frozenset(),
) -> int:
    depth = 0
    cursor = start
    while cursor < len(sql):
        character = sql[cursor]
        if character == "(":
            depth += 1
            cursor += 1
            continue
        if character == ")":
            if depth == 0:
                return cursor
            depth -= 1
            cursor += 1
            continue
        if character == ";" and depth == 0:
            return cursor
        if depth == 0:
            token = _SQL_IDENTIFIER.match(sql, cursor)
            if token is not None:
                if token.group(0).lower() in stop_keywords:
                    return token.start()
                cursor = token.end()
                continue
        cursor += 1
    return len(sql)


def _delete_identifier_regions(
    masked_sql: str,
    *,
    start: int,
) -> tuple[tuple[str, int, int], ...]:
    regions: list[tuple[str, int, int]] = []
    cursor = start
    boundary = _top_level_keyword(
        masked_sql,
        start=cursor,
        keywords=frozenset({"using", "where", "returning"}),
    )
    target_end = (
        _top_level_region_end(masked_sql, start=cursor) if boundary is None else boundary[1]
    )
    regions.append(("DELETE target", cursor, target_end))

    while boundary is not None:
        keyword, _, expression_start = boundary
        remaining_keywords = (
            frozenset({"where", "returning"}) if keyword == "using" else frozenset({"returning"})
        )
        next_boundary = _top_level_keyword(
            masked_sql,
            start=expression_start,
            keywords=remaining_keywords,
        )
        expression_end = (
            _top_level_region_end(masked_sql, start=expression_start)
            if next_boundary is None
            else next_boundary[1]
        )
        context = "DELETE target" if keyword == "using" else "DELETE expression"
        regions.append((context, expression_start, expression_end))
        boundary = next_boundary
    return tuple(regions)


def _nested_select_ranges(
    masked_sql: str,
    *,
    start: int,
    end: int,
) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    openings: list[int] = []
    cursor = start
    while cursor < end:
        character = masked_sql[cursor]
        if character == "(":
            openings.append(cursor)
            cursor += 1
            continue
        if character == ")":
            if openings:
                openings.pop()
            cursor += 1
            continue
        token = _SQL_IDENTIFIER.match(masked_sql, cursor)
        if token is not None:
            if token.group(0).lower() == "select" and openings:
                opening = openings[-1]
                closing = _closing_parenthesis(masked_sql, opening)
                if closing is not None and closing < end:
                    ranges.append((opening, closing + 1))
                    openings.pop()
                    cursor = closing + 1
                    continue
            cursor = token.end()
            continue
        cursor += 1
    return tuple(ranges)


def _next_top_level_identifier(
    masked_sql: str,
    *,
    start: int,
    end: int,
) -> str | None:
    depth = 0
    cursor = start
    while cursor < end:
        character = masked_sql[cursor]
        if character == "(":
            depth += 1
            cursor += 1
            continue
        if character == ")":
            if depth == 0:
                return None
            depth -= 1
            cursor += 1
            continue
        if character == ";" and depth == 0:
            return None
        if depth == 0:
            token = _SQL_IDENTIFIER.match(masked_sql, cursor)
            if token is not None:
                return token.group(0).lower()
        cursor += 1
    return None


def _is_structural_select_clause(
    masked_sql: str,
    *,
    identifier: str,
    token_start: int,
    token_end: int,
    region_start: int,
    region_end: int,
) -> bool:
    if not masked_sql[region_start:token_start].strip():
        return False
    next_identifier = _next_top_level_identifier(
        masked_sql,
        start=token_end,
        end=region_end,
    )
    if identifier in {"group", "order"}:
        return next_identifier == "by"
    if identifier == "limit":
        following_clause = _next_top_level_identifier(
            masked_sql,
            start=region_end,
            end=len(masked_sql),
        )
        return next_identifier != "from" and following_clause not in {
            "except",
            "for",
            "from",
            "having",
            "intersect",
            "into",
            "returning",
            "union",
            "where",
        }
    return False


def _unsafe_tokens(
    masked_sql: str,
    *,
    start: int,
    end: int,
    context: str,
) -> tuple[tuple[str, int], ...]:
    unsafe: list[tuple[str, int]] = []
    nested_selects = _nested_select_ranges(masked_sql, start=start, end=end)
    for token in _SQL_IDENTIFIER.finditer(masked_sql, start, end):
        if any(
            region_start <= token.start() < region_end
            for region_start, region_end in nested_selects
        ):
            continue
        identifier = token.group(0).lower()
        if identifier not in POSTGRESQL_UNSAFE_IDENTIFIERS:
            continue
        if context == "SELECT expression" and _is_structural_select_clause(
            masked_sql,
            identifier=identifier,
            token_start=token.start(),
            token_end=token.end(),
            region_start=start,
            region_end=end,
        ):
            continue
        previous = token.start() - 1
        while previous >= start and masked_sql[previous].isspace():
            previous -= 1
        if previous >= start and masked_sql[previous] == ".":
            continue
        unsafe.append((identifier, token.start()))
    return tuple(unsafe)


def _identifier_regions(
    fragment: SqlFragment,
    masked_sql: str,
) -> tuple[tuple[str, int, int], ...]:
    if fragment.context == "textual check constraint":
        return ((fragment.context, 0, len(masked_sql)),)

    regions: list[tuple[str, int, int]] = []
    for match in _INSERT_INTO.finditer(masked_sql):
        statement_end = _top_level_region_end(masked_sql, start=match.end())
        source = _top_level_keyword(
            masked_sql,
            start=match.end(),
            keywords=frozenset({"default", "select", "values"}),
        )
        opening = masked_sql.find("(", match.end())
        target_end = statement_end
        if source is not None:
            target_end = min(target_end, source[1])
        if opening != -1:
            target_end = min(target_end, opening)
        regions.append(("INSERT target", match.end(), target_end))

        if opening == -1 or opening >= statement_end:
            continue
        prefix = masked_sql[match.end() : opening]
        if re.search(r"\b(?:default|select|values)\b", prefix, re.IGNORECASE):
            continue
        closing = _closing_parenthesis(masked_sql, opening)
        if closing is not None:
            regions.append(("INSERT target list", opening + 1, closing))
    for match in _VALUES.finditer(masked_sql):
        source_start = match.end()
        source_end = _top_level_region_end(
            masked_sql,
            start=source_start,
            stop_keywords=frozenset({"on", "returning"}),
        )
        regions.append(("INSERT source expression", source_start, source_end))
    for match in _SELECT.finditer(masked_sql):
        expression_start = match.end()
        expression_end = _top_level_region_end(
            masked_sql,
            start=expression_start,
            stop_keywords=frozenset(
                {
                    "except",
                    "for",
                    "from",
                    "having",
                    "intersect",
                    "into",
                    "returning",
                    "union",
                    "where",
                }
            ),
        )
        regions.append(("SELECT expression", expression_start, expression_end))
    for match in _UPDATE.finditer(masked_sql):
        assignment = _top_level_keyword(
            masked_sql,
            start=match.end(),
            keywords=frozenset({"set"}),
        )
        if assignment is None:
            continue
        regions.append(("UPDATE target", match.end(), assignment[1]))
        assignment_start = assignment[2]
        assignment_end = _top_level_region_end(
            masked_sql,
            start=assignment_start,
            stop_keywords=frozenset({"from", "returning", "where"}),
        )
        regions.append(("UPDATE assignment", assignment_start, assignment_end))
    for match in _DELETE_FROM.finditer(masked_sql):
        regions.extend(_delete_identifier_regions(masked_sql, start=match.end()))
    for match in _CHECK.finditer(masked_sql):
        opening = masked_sql.find("(", match.start())
        closing = _closing_parenthesis(masked_sql, opening)
        if closing is not None:
            regions.append(("raw CHECK constraint", opening + 1, closing))
    return tuple(regions)


def find_postgresql_identifier_violations(
    source: str,
    *,
    source_name: str = "<memory>",
) -> tuple[IdentifierViolation, ...]:
    violations: set[IdentifierViolation] = set()
    for fragment in collect_sql_fragments(source, source_name=source_name):
        masked_sql = _mask_sql_literals_comments_and_binds(fragment.sql)
        for context, start, end in _identifier_regions(fragment, masked_sql):
            for identifier, offset in _unsafe_tokens(
                masked_sql,
                start=start,
                end=end,
                context=context,
            ):
                violations.add(
                    IdentifierViolation(
                        source_name=source_name,
                        line=fragment.line + masked_sql.count("\n", 0, offset),
                        function=fragment.function,
                        context=context,
                        identifier=identifier,
                    )
                )
    return tuple(sorted(violations))


def validate_postgresql_identifier_safety() -> None:
    if "current_role" not in POSTGRESQL_UNSAFE_IDENTIFIERS:
        raise RuntimeError("The PostgreSQL reserved-word registry is unavailable or inconsistent.")
    if "role" in POSTGRESQL_UNSAFE_IDENTIFIERS:
        raise RuntimeError("The PostgreSQL reserved-word registry unexpectedly classifies role.")

    violations: list[IdentifierViolation] = []
    paths = [*sorted(VERSIONS_ROOT.glob("*.py")), MODELS_PATH]
    for path in paths:
        source_name = path.relative_to(REPOSITORY_ROOT).as_posix()
        violations.extend(
            find_postgresql_identifier_violations(
                path.read_text(encoding="utf-8"),
                source_name=source_name,
            )
        )
    if violations:
        diagnostics = "\n".join(str(violation) for violation in sorted(violations))
        raise RuntimeError(
            f"Unsafe PostgreSQL-sensitive identifiers were found in migration SQL:\n{diagnostics}"
        )


def _config() -> Config:
    config = Config(API_ROOT / "alembic.ini")
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def validate_migration_history() -> None:
    scripts = ScriptDirectory.from_config(_config())
    if scripts.get_heads() != [EXPECTED_HEAD]:
        raise RuntimeError("The repository must contain exactly the approved Alembic head.")

    reverse_chain: list[str] = []
    current: str | None = EXPECTED_HEAD
    while current is not None:
        revision_script = scripts.get_revision(current)
        if revision_script is None:
            raise RuntimeError(f"Migration revision {current} is missing.")
        reverse_chain.append(revision_script.revision)
        down_revision = revision_script.down_revision
        if down_revision is not None and not isinstance(down_revision, str):
            raise RuntimeError("Branched or merged migration ancestry is not approved.")
        current = down_revision

    if tuple(reversed(reverse_chain)) != EXPECTED_REVISION_CHAIN:
        raise RuntimeError("Migration ancestry differs from the approved linear chain.")


def validate_migration_blob_hashes() -> None:
    actual_files = {path.name for path in VERSIONS_ROOT.glob("*.py")}
    expected_files = set(EXPECTED_MIGRATION_BLOB_HASHES)
    if actual_files != expected_files:
        raise RuntimeError("Migration file inventory differs from the approved hash ledger.")

    for filename, expected_hash in EXPECTED_MIGRATION_BLOB_HASHES.items():
        path = VERSIONS_ROOT / filename
        relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
        completed = subprocess.run(
            [
                "git",
                "hash-object",
                f"--path={relative_path}",
                relative_path,
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        actual_hash = completed.stdout.strip()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Migration {filename} differs from its approved active Git blob hash."
            )


def revision(database_path: Path) -> str:
    with closing(sqlite3.connect(database_path)) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    if row is None or not isinstance(row[0], str):
        raise RuntimeError("Alembic did not record a valid database revision.")
    return row[0]


def main() -> int:
    validate_postgresql_identifier_safety()
    validate_migration_history()
    validate_migration_blob_hashes()
    with tempfile.TemporaryDirectory(prefix="opencanvas-migrations-") as temporary:
        database_path = Path(temporary) / "migration-validation.db"
        config = _config()
        config.set_main_option(
            "sqlalchemy.url",
            f"sqlite+aiosqlite:///{database_path.as_posix()}",
        )

        command.upgrade(config, "head")
        if revision(database_path) != EXPECTED_HEAD:
            raise RuntimeError(f"Migration upgrade did not reach {EXPECTED_HEAD}.")

        command.downgrade(config, PREVIOUS_REVISION)
        if revision(database_path) != PREVIOUS_REVISION:
            raise RuntimeError(f"Migration downgrade did not reach {PREVIOUS_REVISION}.")

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

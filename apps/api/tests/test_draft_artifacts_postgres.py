from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from opencanvas_api.api.dependencies import get_current_principal, get_session
from opencanvas_api.core.config import Settings, get_settings
from opencanvas_api.db.models import AIRequest, AIResponse, Canvas, CanvasNode, User, Workspace
from opencanvas_api.db.session import Database
from opencanvas_api.main import create_app
from opencanvas_api.services.auth import Principal
from tests.postgres_support import disposable_postgres_database

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_url() -> Iterator[str]:
    yield from disposable_postgres_database(upgrade_to="20260726_0029")


def migration():
    path = (
        Path(__file__).parents[1] / "alembic/versions/20261116_0030_controlled_draft_artifacts.py"
    )
    spec = importlib.util.spec_from_file_location("draft_artifact_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_postgres_transition_concurrent_save_and_append_only_guards(postgres_url: str):
    database = Database(postgres_url)
    user, workspace, canvas, source, execution, response, trace = [uuid.uuid4() for _ in range(7)]
    async with database.sessions() as session:
        session.add(
            User(
                id=user,
                email="artifact@example.test",
                email_normalized="artifact@example.test",
                password_hash="test-only",
                display_name="Artifact",
                email_verified=True,
            )
        )
        await session.flush()
        session.add(Workspace(id=workspace, owner_id=user, name="Artifacts"))
        await session.flush()
        session.add(Canvas(id=canvas, workspace_id=workspace, name="Original canvas"))
        await session.flush()
        session.add(
            CanvasNode(
                id=source,
                canvas_id=canvas,
                type="note",
                title="Source",
                text="Unchanged source",
                position_x=0,
                position_y=0,
            )
        )
        session.add(
            AIRequest(
                id=execution,
                trace_id=trace,
                user_id=user,
                workspace_id=workspace,
                canvas_id=canvas,
                instruction="Original instruction",
                selected_node_ids=[str(source)],
                context_snapshot=[],
                provider="mock",
                model="test",
                status="completed",
                execution_mode="controlled_immutable_context",
            )
        )
        await session.flush()
        session.add(AIResponse(id=response, request_id=execution, content="Original result"))
        await session.commit()
    module = migration()
    async with database.engine.begin() as connection:
        before = (
            await connection.execute(
                text("SELECT id, text, revision FROM nodes WHERE id=:id"), {"id": source}
            )
        ).one()

        def upgrade(sync_connection):
            with Operations.context(MigrationContext.configure(sync_connection)):
                module.upgrade()

        await connection.run_sync(upgrade)
        after = (
            await connection.execute(
                text("SELECT id, text, revision FROM nodes WHERE id=:id"), {"id": source}
            )
        ).one()
        assert before == after
        assert await connection.scalar(text("SELECT count(*) FROM controlled_draft_artifacts")) == 0
    app = create_app()

    async def session_override():
        async with database.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: Settings(
        environment="test", ai_provider="mock", auth_test_bypass=True
    )
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=user,
        email="artifact@example.test",
        display_name="Artifact",
        session_id=None,
        csrf_token_hash=None,
        synthetic=True,
    )
    route = f"/api/v1/workspaces/{workspace}/agent-executions/{execution}/artifact"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *[
                    client.post(
                        route, json={"canvasId": str(canvas), "position": {"x": index, "y": 0}}
                    )
                    for index in range(4)
                ]
            )
            assert all(item.status_code == 200 for item in responses), [r.text for r in responses]
            assert len({item.json()["id"] for item in responses}) == 1
        async with database.engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT count(*) FROM controlled_draft_artifacts"))
                == 1
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM nodes WHERE canvas_id=:id"), {"id": canvas}
                )
                == 2
            )
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM edges WHERE canvas_id=:id"), {"id": canvas}
                )
                == 1
            )
            await connection.rollback()
            # The new mapping is readable/appendable by API only. No runtime
            # authority may mutate identities; worker has no table privileges.
            from opencanvas_api.db.role_privileges import (
                API_DELETE_TABLES,
                API_INSERT_TABLES,
                API_SELECT_TABLES,
                API_UPDATE_TABLES,
                WORKER_INSERT_TABLES,
                WORKER_SELECT_TABLES,
            )

            assert "controlled_draft_artifacts" in API_SELECT_TABLES & API_INSERT_TABLES
            assert "controlled_draft_artifacts" not in (
                API_UPDATE_TABLES | API_DELETE_TABLES | WORKER_SELECT_TABLES | WORKER_INSERT_TABLES
            )
            for statement in (
                "UPDATE controlled_draft_artifacts SET node_id=node_id",
                "DELETE FROM controlled_draft_artifacts",
            ):
                with pytest.raises(DBAPIError, match="append-only"):
                    async with connection.begin():
                        await connection.execute(text(statement))
        async with database.sessions() as session:
            original = await session.scalar(select(AIResponse).where(AIResponse.id == response))
            assert original.content == "Original result" and original.node_id is None
            assert (await session.get(Canvas, canvas)).revision == 1
    finally:
        await database.dispose()

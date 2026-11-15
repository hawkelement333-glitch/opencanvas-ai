from __future__ import annotations

import uuid

import httpx
import pytest

from opencanvas_api.db.models import SYSTEM_USER_ID, SYSTEM_WORKSPACE_ID, ControlledWorkflowVersion
from opencanvas_api.db.session import Database
from opencanvas_api.services.workflows import WorkflowNotFoundError
from tests.test_controlled_workflows import _active_workflow, _service
from tests.test_graph_retrieval import _retrieval_foundation
from tests.test_shared_workflow_agent_governance import _add_member, _share_execution_resources


@pytest.mark.anyio
async def test_workflow_list_rejects_unrelated_user_even_when_empty(database: Database) -> None:
    canvas_id, _ = await _retrieval_foundation(database)
    async with database.sessions() as session:
        service = _service(session)
        assert await service.list_definitions(
            user_id=SYSTEM_USER_ID, workspace_id=SYSTEM_WORKSPACE_ID, canvas_id=canvas_id
        ) == []
        with pytest.raises(WorkflowNotFoundError):
            await service.list_definitions(
                user_id=uuid.uuid4(), workspace_id=SYSTEM_WORKSPACE_ID, canvas_id=canvas_id
            )


@pytest.mark.anyio
async def test_workflow_list_api_rejects_forged_scope_and_preserves_visible_records(
    database: Database, client: httpx.AsyncClient, api_prefix: str
) -> None:
    canvas_id, _, _ = await _active_workflow(database, include_bundle=False)
    path = f"{api_prefix}/workspaces/{SYSTEM_WORKSPACE_ID}/canvases/{canvas_id}/workflows"
    response = await client.get(path)
    assert response.status_code == 200
    assert len(response.json()) == 1
    for workspace, canvas in ((uuid.uuid4(), canvas_id), (SYSTEM_WORKSPACE_ID, uuid.uuid4())):
        response = await client.get(
            f"{api_prefix}/workspaces/{workspace}/canvases/{canvas}/workflows"
        )
        assert response.status_code == 404


@pytest.mark.anyio
async def test_workflow_list_preserves_member_visibility_filter(database: Database) -> None:
    canvas_id, _, version_id = await _active_workflow(database, include_bundle=False)
    user_id, membership_id = await _add_member(database)
    async with database.sessions() as session:
        assert await _service(session).list_definitions(
            user_id=user_id, workspace_id=SYSTEM_WORKSPACE_ID, canvas_id=canvas_id
        ) == []
        version = await session.get(ControlledWorkflowVersion, version_id)
        assert version is not None
        definition_id = version.definition_id
    await _share_execution_resources(
        database, canvas_id=canvas_id, object_ids=(), membership_id=membership_id,
        workflow_definition_id=definition_id,
    )
    async with database.sessions() as session:
        records = await _service(session).list_definitions(
            user_id=user_id, workspace_id=SYSTEM_WORKSPACE_ID, canvas_id=canvas_id
        )
        assert [record.definition.definition_id for record in records] == [definition_id]

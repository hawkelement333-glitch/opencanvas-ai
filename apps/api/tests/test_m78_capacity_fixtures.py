from __future__ import annotations

import json
import uuid

import pytest
from infra.milestone_7_8.capacity_fixtures import (
    agent_payload,
    content,
    prepare_stages,
    workflow_payload,
)
from infra.milestone_7_8.capacity_validation import prepare, resolve_templates

from opencanvas_api.api.agent_studio_schemas import AgentCreateIn
from opencanvas_api.api.workflow_schemas import WorkflowDraftCreate
from opencanvas_api.core.config import Settings
from opencanvas_api.db.models import SYSTEM_USER_ID, SYSTEM_WORKSPACE_ID
from opencanvas_api.services.agent_studio import AgentVersionInput, ValidationOutcome
from opencanvas_api.services.workflows import WorkflowVersionInput
from tests.test_agent_studio import _service
from tests.test_controlled_workflows import _activate


def test_prepared_profiles_and_stages_have_finite_real_provider_attempt_bounds(tmp_path):
    capacity = prepare(Settings().model_dump(), request_budget=10000, concurrency_cap=4)
    result = prepare_stages(
        tmp_path / "private", capacity, namespace="localfixture", model="gpt-5.6-terra"
    )
    bounds = result["fixtureBounds"]
    assert bounds["documents"] == 45 and bounds["documentBytes"] == 9176064
    assert bounds["embeddingInputUtf8BytesIncludingOverlap"] == 10777584
    assert bounds["embeddingTokenUpperBoundIncludingSdkRetries"] == 32332752
    assert result["logicalModelCalls"] == 10 and result["maximumSdkModelAttempts"] == 30
    assert 6000 < result["reservedRequests"] <= 10000
    assert len(result["capacityStages"]) == 22
    assert all("fault" in stage for stage in result["capacityStages"][6:])
    fixture = json.loads((tmp_path / "private/capacity-00.json").read_text())
    assert len(fixture["accounts"]) == 4
    assert len({x["password"] for x in fixture["accounts"]}) == 4
    assert all(account["email"].endswith("@example.invalid") for account in fixture["accounts"])
    for profile in fixture["profiles"]:
        raw = content(profile["fileBytes"], profile["name"] + "-0")
        assert len(raw) == profile["fileBytes"] and b"NOVA-731" in raw


def test_generated_model_operations_match_actual_application_request_schemas(tmp_path):
    from opencanvas_api.api.agent_studio_schemas import AgentInvocationIn
    from opencanvas_api.api.workflow_schemas import WorkflowExecutionStart

    capacity = prepare(Settings().model_dump(), request_budget=10000, concurrency_cap=4)
    result = prepare_stages(
        tmp_path / "private", capacity, namespace="localschema", model="gpt-5.6-terra"
    )
    values = {"EXECUTION_ID": "job-local-123"}
    for index in range(21):
        for suffix in (
            "USER",
            "WORKSPACE",
            "CANVAS",
            "WORKFLOW",
            "AGENT",
            "NOTE_0",
            "NOTE_1",
            "DOCUMENT_0",
        ):
            values[f"CAPACITY_{index}_{suffix}"] = str(uuid.uuid4())
    for stage in result["capacityStages"][1:]:
        records = resolve_templates(
            json.loads((tmp_path / "private" / stage["file"]).read_text()), values
        )
        for operation in records:
            if operation["kind"] == "agent":
                AgentInvocationIn.model_validate(operation["payload"])
            elif operation["kind"] == "workflow":
                WorkflowExecutionStart.model_validate(operation["payload"])


async def test_fixture_workflow_and_agent_pass_actual_domain_validation(database):
    payload = WorkflowDraftCreate.model_validate(workflow_payload("capacity-schema-workflow"))
    version = WorkflowVersionInput.model_validate(payload.version.model_dump())
    canvas, _, workflow_id = await _activate(
        database, kind=payload.kind, version=version, key="capacity-active-workflow"
    )
    agent = AgentCreateIn.model_validate(
        agent_payload("capacity-schema-agent", str(workflow_id), "gpt-5.6-terra")
    )
    definition = AgentVersionInput.model_validate(agent.version.model_dump())
    async with database.sessions() as session:
        service = _service(session)
        created = await service.create_agent(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas,
            kind=agent.kind,
            display_name=agent.display_name,
            description=agent.description,
            version=definition,
            idempotency_key=agent.idempotency_key,
        )
        report = await service.validate_version(
            user_id=SYSTEM_USER_ID,
            workspace_id=SYSTEM_WORKSPACE_ID,
            canvas_id=canvas,
            version_id=created.versions[0].version_id,
        )
        assert report.outcome == ValidationOutcome.VALID
        await session.rollback()


def test_fixture_preparation_rejects_insufficient_total_allowance(tmp_path):
    capacity = prepare(Settings().model_dump(), request_budget=100, concurrency_cap=4)
    with pytest.raises(ValueError, match="global request budget"):
        prepare_stages(
            tmp_path / "private", capacity, namespace="localbounds", model="gpt-5.6-terra"
        )


async def test_capacity_setup_uses_actual_workspace_collaboration_workflow_agent_routes(
    client, database
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).parents[1]
        / "alembic/versions/20260725_0023_resource_sharing_ownership_revocation.py"
    )
    spec = importlib.util.spec_from_file_location("capacity_registration_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    # Metadata-only test schemas omit production registration triggers. Install
    # the exact existing migration DDL; never insert fake ownership fixture rows.
    def install(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration._install_resource_registration_triggers()

    async with database.engine.begin() as connection:
        await connection.run_sync(install)

    async def post(path, payload=None, status=200):
        response = await client.post("/api/v1" + path, json=payload)
        assert response.status_code == status, response.text
        return response.json()

    workspace = await post("/workspaces", {"name": "Synthetic capacity route validation"}, 201)
    workspace_id = workspace["id"]
    canvas = await post(
        "/canvases",
        {
            "name": "Synthetic capacity canvas",
            "workspaceId": workspace_id,
            "idempotencyKey": "capacity-route-canvas",
        },
        201,
    )
    base = f"/workspaces/{workspace_id}/canvases/{canvas['id']}"
    await post(
        f"/workspaces/{workspace_id}/resources/canvas/{canvas['id']}/comments",
        {"content": "Synthetic capacity comment.", "idempotencyKey": "capacity-route-comment"},
        201,
    )
    shares = await post(
        f"/workspaces/{workspace_id}/shares",
        {
            "targets": [
                {
                    "resourceKind": "canvas",
                    "resourceId": canvas["id"],
                    "audienceKind": "workspace",
                    "accessLevel": "view",
                }
            ],
            "idempotencyKey": "capacity-route-share",
        },
        201,
    )
    assert shares[0]["state"] == "active"
    workflow = await post(base + "/workflows", workflow_payload("capacity-route-workflow"), 201)
    version = workflow["versions"][0]["versionId"]
    await post(base + f"/workflows/versions/{version}/validate")
    active = await post(base + f"/workflows/versions/{version}/activate")
    assert active["lifecycleState"] == "active"
    agent = await post(
        base + "/agent-studio/agents",
        agent_payload("capacity-route-agent", version, "gpt-5.6-terra"),
        201,
    )
    agent_version = agent["versions"][0]["versionId"]
    validated = await post(base + f"/agent-studio/versions/{agent_version}/validate")
    assert validated["outcome"] == "valid"
    activation = await post(
        base + f"/agent-studio/versions/{agent_version}/activation-requests",
        {"idempotencyKey": "capacity-route-activation"},
    )
    decision = await post(
        base + f"/agent-studio/activation-requests/{activation['activationRequestId']}/decision",
        {"decision": "approved"},
    )
    assert decision["decision"] == "approved"

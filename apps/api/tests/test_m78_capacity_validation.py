from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from infra.milestone_7_8.capacity_validation import (
    Operation,
    Response,
    prepare,
    resolve_templates,
    run_bound_phase,
    run_phase,
    validate_results,
)

from opencanvas_api.core.config import Settings


def plan(budget=100):
    return prepare(Settings().model_dump(), request_budget=budget, concurrency_cap=4)


def test_profiles_are_synthetic_not_supported_user_or_latency_targets():
    prepared = plan()
    assert prepared["profiles"][-1]["fileBytes"] == Settings().document_max_file_size_bytes + 1
    assert prepared["managedAcceptance"] == "unproved"
    assert "No supported cohort" in prepared["interpretation"]
    result = validate_results(prepared, [], {})
    assert result["supportedCohort"] is None and result["fullCapacityClosure"] is False
    assert all(item["status"] == "unproved" for item in result["assertions"].values())


async def test_actual_status_latency_rejection_and_no_mutation_retry(tmp_path):
    calls = []

    async def transport(request):
        calls.append(request)
        if request.url.path.endswith("/unknown"):
            raise httpx.ReadTimeout("uncertain synthetic boundary", request=request)
        return httpx.Response(
            429,
            json={"error": {"code": "rate_limited"}},
            headers={"Retry-After": "3", "x-request-id": "native-fixture"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport), base_url="https://fixture.invalid"
    ) as client:

        async def execute(operation):
            response = await client.request(
                operation.method, operation.path, json=operation.payload
            )
            return Response(
                response.status_code,
                len(response.content),
                hashlib.sha256(response.content).hexdigest(),
                response.headers.get("x-request-id"),
                response.headers.get("retry-after"),
            )

        operations = [
            Operation("r1", "actor", "workspace", "read", "GET", "/api/v1/canvases"),
            Operation(
                "m1",
                "actor",
                "workspace",
                "mutation",
                "POST",
                "/api/v1/unknown",
                {"name": "fixture"},
            ),
        ]
        result = await run_phase(
            operations,
            phase="spike",
            concurrency=2,
            plan=plan(),
            execute=execute,
            evidence_directory=tmp_path / "spike",
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            execution_id="local-focused-test",
        )
    assert len(calls) == 2
    assert result["statusCounts"] == {"429": 1, "None": 1}
    unknown = next(item for item in result["measurements"] if item["status"] is None)
    assert unknown["reconcileBeforeRetry"] is True
    assert len(list((tmp_path / "spike").glob("*.intent.json"))) == 2
    assert result["p95Ms"] >= 0


async def test_total_budget_is_reserved_before_dispatch_across_phases(tmp_path):
    calls = []

    async def execute(operation):
        calls.append(operation.operation_id)
        return Response(200, 2, hashlib.sha256(b"{}").hexdigest(), None, None)

    prepared = plan(2)
    kwargs = {
        "concurrency": 1,
        "plan": prepared,
        "execute": execute,
        "deadline": datetime.now(UTC) + timedelta(seconds=30),
        "execution_id": "local-budget-test",
    }
    await run_phase(
        [Operation("first", "a", "w", "read", "GET", "/api/v1/canvases")],
        phase="baseline",
        evidence_directory=tmp_path / "baseline",
        **kwargs,
    )
    with pytest.raises(ValueError, match="total request budget exhausted"):
        await run_phase(
            [Operation(str(i), "a", "w", "read", "GET", "/api/v1/canvases") for i in range(2)],
            phase="spike",
            evidence_directory=tmp_path / "spike",
            **kwargs,
        )
    assert calls == ["first"]
    assert json.loads((tmp_path / "capacity-budget.json").read_text())["reservedRequests"] == 1


async def test_concurrency_is_bounded_and_existing_intent_not_replayed(tmp_path):
    active = peak = 0

    async def execute(operation):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return Response(200, 2, hashlib.sha256(b"{}").hexdigest(), None, None)

    kwargs = {
        "phase": "ramp",
        "concurrency": 2,
        "plan": plan(),
        "execute": execute,
        "evidence_directory": tmp_path / "ramp",
        "deadline": datetime.now(UTC) + timedelta(seconds=30),
        "execution_id": "local-concurrency-test",
    }
    operations = [Operation(str(i), "a", "w", "read", "GET", "/api/v1/canvases") for i in range(5)]
    await run_phase(operations, **kwargs)
    assert peak == 2
    with pytest.raises(ValueError, match="preserve prior intent"):
        await run_phase(operations, **kwargs)


def test_missing_operational_and_fault_evidence_never_becomes_capacity_acceptance():
    measured = {
        "phase": "baseline",
        "requests": 1,
        "measurements": [{"status": 200, "expectedStatus": True}],
    }
    result = validate_results(plan(), [measured], {})
    assert result["assertions"]["baseline"]["status"] == "accepted"
    assert result["assertions"]["bounded-rejection"]["status"] == "unproved"
    assert result["assertions"]["dimension:poolWaitMs"]["status"] == "unproved"
    assert result["assertions"]["fault:ambiguous-commit"]["status"] == "unproved"
    assert result["fullCapacityClosure"] is False


def test_rejections_do_not_prove_recovery_or_incomplete_ramp():
    phases = [
        {
            "phase": "recovery",
            "requests": 1,
            "measurements": [{"status": 429, "expectedStatus": True}],
        },
        {
            "phase": "ramp",
            "requests": 1,
            "concurrency": 1,
            "measurements": [{"status": 200, "expectedStatus": True}],
        },
    ]
    result = validate_results(plan(), phases, {})
    assert result["assertions"]["recovery"]["status"] == "unproved"
    assert result["assertions"]["ramp"]["status"] == "unproved"
    assert result["assertions"]["profile:large-fixture"]["status"] == "unproved"


def test_approved_template_has_only_exact_fixture_substitutions():
    assert resolve_templates({"path": "${PRIMARY_CANVAS}"}, {"PRIMARY_CANVAS": "actual"}) == {
        "path": "actual"
    }
    with pytest.raises(ValueError, match="unknown operation-template"):
        resolve_templates("${OTHER}", {})


async def test_bound_adapter_preserves_actual_http_result_and_rejects_changed_input(tmp_path):
    calls = []

    async def transport(request):
        calls.append(request)
        return httpx.Response(
            429,
            json={"error": "rate_limited"},
            headers={"Retry-After": "7", "x-request-id": "request-native"},
        )

    fixture = {
        "userId": "u1",
        "workspaceId": "w1",
        "canvasId": "c1",
        "primary": {"documentId": "d1"},
        "foreign": {"userId": "u2", "workspaceId": "w2", "canvasId": "c2"},
    }
    records = [
        {
            "operation_id": "${EXECUTION_ID}-1",
            "actor_id": "${PRIMARY_USER}",
            "workspace_id": "${PRIMARY_WORKSPACE}",
            "kind": "read",
            "method": "GET",
            "path": "/api/v1/canvases/${PRIMARY_CANVAS}/resources",
            "expected_statuses": [429],
            "expected_rejection": True,
        }
    ]
    operations = tmp_path / "operations.json"
    operations.write_text(json.dumps(records))
    prepared = {
        "capacityProof": plan(),
        "capacityStages": [
            {
                "phase": "baseline",
                "concurrency": 1,
                "operationsSha256": hashlib.sha256(operations.read_bytes()).hexdigest(),
            }
        ],
        "applicationResourceId": "/app",
    }
    readbacks = {
        "resources": [
            {
                "request": {"resourceId": "/app"},
                "response": {"body": {"properties": {"template": {"containers": [{"env": []}]}}}},
            }
        ]
    }
    args = SimpleNamespace(
        capacity_stage=0,
        capacity_operations=operations,
        output=tmp_path / "result.json",
        execution_id="native-job-1",
    )

    async def signin(**kwargs):
        return {"id": "u1"}

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport), base_url="https://fixture.invalid"
    ) as client:
        api = SimpleNamespace(
            client=client,
            signin=signin,
            csrf="local-fixture",
            journal=SimpleNamespace(check_time=lambda: None),
        )
        result = await run_bound_phase(
            api, fixture, prepared, readbacks, args, datetime.now(UTC) + timedelta(seconds=30)
        )
        assert result["settingsMatchedNativeReadback"] is True
        row = result["measurements"][0]
        assert row["status"] == 429 and row["retry_after"] == "7" and row["expectedStatus"]
        assert row["request_id"] == "request-native" and row["body_bytes"] > 0
        assert len(calls) == 1
        operations.write_text("[]")
        with pytest.raises(ValueError, match="differs from approval"):
            await run_bound_phase(
                api, fixture, prepared, readbacks, args, datetime.now(UTC) + timedelta(seconds=30)
            )
        assert len(calls) == 1

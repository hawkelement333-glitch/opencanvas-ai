from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT = REPO_ROOT / "performance" / "milestone_7_7"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


framework = _load_module("milestone_7_7_workload_framework", ROOT / "framework.py")


def _manifest():
    return framework.load_json(ROOT / "workload.example.json")


def _write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _observations(manifest, plan, outcomes: dict[int, str] | None = None):
    outcomes = outcomes or {}
    result = []
    for event in plan["events"]:
        sequence = event["sequence"]
        result.append(
            framework.Observation(
                sequence=sequence,
                phase=event["phase"],
                operation_id=event["operationId"],
                tenant_token=event["tenantToken"],
                completed_at_logical_us=event["scheduledAtLogicalUs"] + 10_000 + sequence,
                latency_us=10_000 + sequence,
                outcome=outcomes.get(sequence, "success"),
                retry_count=1 if outcomes.get(sequence) == "timeout" else 0,
                queue_depth=sequence % 5,
                queue_wait_us=sequence * 100,
                saturation_basis_points=sequence * 10,
            )
        )
    return result


def test_schemas_are_versioned_closed_and_machine_readable():
    for name in ("workload.schema.json", "result.schema.json"):
        value = framework.load_json(ROOT / name)
        assert value["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert value["$id"].startswith("urn:solarplexus:mobius:milestone-7.7:")
        assert value["type"] == "object"
        assert value["additionalProperties"] is False


def test_valid_manifest_is_accepted_and_copied():
    value = _manifest()
    validated = framework.validate_manifest(value)
    assert validated == value
    assert validated is not value


@pytest.mark.parametrize("field", ["seed", "limits", "measurement", "dataPolicy"])
def test_manifest_rejects_missing_required_fields(field):
    value = _manifest()
    del value[field]
    with pytest.raises(framework.ContractError, match="missing required field"):
        framework.validate_manifest(value)


def test_manifest_rejects_unknown_fields_at_every_closed_boundary():
    value = _manifest()
    value["unexpected"] = True
    with pytest.raises(framework.ContractError, match="unknown field"):
        framework.validate_manifest(value)
    value = _manifest()
    value["limits"]["unexpected"] = 1
    with pytest.raises(framework.ContractError, match="unknown field"):
        framework.validate_manifest(value)


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("limits", "maximumDurationMs"), 14_400_001),
        (("limits", "maximumRequests"), 10_001),
        (("limits", "maximumConcurrency"), 129),
        (("limits", "maxArrivalRatePerSecond"), 101),
        (("limits", "maxRetries"), 3),
        (("limits", "maxRequestBytes"), 1_048_577),
        (("limits", "maxObjectBytes"), 16_777_217),
        (("limits", "maxTotalObjectBytes"), 134_217_729),
        (("limits", "maxGeneratedEntities"), 4097),
        (("limits", "maxTenantCount"), 17),
        (("limits", "maxMeasurementSeries"), 257),
        (("limits", "maxOutputBytes"), 4_194_305),
    ],
)
def test_hard_configuration_ceilings_fail_closed(location, value):
    manifest = _manifest()
    manifest[location[0]][location[1]] = value
    with pytest.raises(framework.ContractError):
        framework.validate_manifest(manifest)


def test_missing_or_contradictory_bounds_fail_closed():
    manifest = _manifest()
    manifest["phases"][1]["requestCount"] = 33
    manifest["limits"]["maximumRequests"] = 64
    with pytest.raises(framework.ContractError, match="arrival-rate capacity"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["loadModel"]["concurrency"] = 5
    with pytest.raises(framework.ContractError, match="concurrency"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["limits"]["maxObjectBytes"] = 5
    manifest["limits"]["maxTotalObjectBytes"] = 4
    with pytest.raises(framework.ContractError, match="maxObjectBytes"):
        framework.validate_manifest(manifest)


def test_phase_order_and_workload_mix_are_closed():
    manifest = _manifest()
    manifest["phases"].reverse()
    with pytest.raises(framework.ContractError, match="ordered"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["operations"].append(deepcopy(manifest["operations"][0]))
    with pytest.raises(framework.ContractError, match="must not repeat"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["operations"][0]["weight"] = 0
    with pytest.raises(framework.ContractError, match="minimum"):
        framework.validate_manifest(manifest)


@pytest.mark.parametrize("workload_type", framework.SUPPORTED_WORKLOAD_TYPES)
def test_every_required_workload_type_generates_deterministically(workload_type):
    manifest = _manifest()
    manifest["workloadType"] = workload_type
    manifest["workloadId"] = f"synthetic-{workload_type}-v1"
    if workload_type == "noisy-neighbor":
        manifest["tenantDistribution"] = "weighted-noisy-neighbor"
    first = framework.generate_plan(manifest)
    second = framework.generate_plan(manifest)
    assert framework.canonical_bytes(first) == framework.canonical_bytes(second)
    assert first["planSha256"] == second["planSha256"]


def test_noisy_neighbor_distribution_is_explicit_and_not_reusable_elsewhere():
    manifest = _manifest()
    manifest["workloadType"] = "noisy-neighbor"
    with pytest.raises(framework.ContractError, match="require"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["tenantDistribution"] = "weighted-noisy-neighbor"
    with pytest.raises(framework.ContractError, match="reserved"):
        framework.validate_manifest(manifest)


def test_closed_concurrency_model_requires_null_arrival_rate():
    manifest = _manifest()
    manifest["loadModel"]["type"] = "closed-concurrency"
    with pytest.raises(framework.ContractError, match="must set"):
        framework.validate_manifest(manifest)
    manifest["loadModel"]["arrivalRatePerSecond"] = None
    framework.validate_manifest(manifest)


def test_generation_changes_hash_for_material_seed_or_mix_change():
    manifest = _manifest()
    original = framework.generate_plan(manifest)
    changed_seed = deepcopy(manifest)
    changed_seed["seed"] += 1
    changed_weight = deepcopy(manifest)
    changed_weight["operations"][0]["weight"] += 1
    assert framework.generate_plan(changed_seed)["planSha256"] != original["planSha256"]
    assert framework.generate_plan(changed_weight)["planSha256"] != original["planSha256"]
    assert framework.manifest_sha256(changed_weight) != framework.manifest_sha256(manifest)


def test_canonicalization_is_stable_and_rejects_ambiguous_json():
    assert framework.canonical_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}\n'
    with pytest.raises(framework.ContractError, match="duplicate JSON key"):
        framework.loads_json('{"a":1,"a":2}')
    with pytest.raises(framework.ContractError, match="floating-point"):
        framework.loads_json('{"a":1.25}')
    with pytest.raises(framework.ContractError, match="non-finite"):
        framework.loads_json('{"a":NaN}')
    with pytest.raises(framework.ContractError, match="Unicode NFC"):
        framework.canonical_bytes({"text": "e\u0301"})


def test_operation_registry_is_closed_and_matches_real_routes():
    registry = framework.operation_registry()
    assert set(registry) == {
        "agent.invoke",
        "canvas.snapshot",
        "collaboration.list_shares",
        "durable_job.status",
        "graph_retrieval.create",
        "health.live",
        "indexing.request",
        "secure_upload.initiate",
        "workflow.execute",
    }
    for item in registry.values():
        source = REPO_ROOT / item["source"]
        lines = source.read_text(encoding="utf-8").splitlines()
        source_line = item["sourceLine"]
        assert lines[source_line - 1].lstrip().startswith("@router.")
        route_tail = item["route"].rsplit("/", 1)[-1]
        assert route_tail in "\n".join(lines[source_line - 1 : source_line + 5])


def test_external_or_unregistered_targets_are_denied():
    manifest = _manifest()
    manifest["operations"][0]["operationId"] = "external.example"
    with pytest.raises(framework.ContractError, match="unsupported repository operation"):
        framework.validate_manifest(manifest)
    manifest = _manifest()
    manifest["dataPolicy"]["externalTargetsAllowed"] = True
    with pytest.raises(framework.ContractError, match="closed contract"):
        framework.validate_manifest(manifest)


def test_generated_plan_is_bounded_synthetic_and_contains_no_request_material():
    manifest = _manifest()
    plan = framework.generate_plan(manifest)
    assert len(plan["events"]) == 24
    assert len(framework.canonical_bytes(plan)) <= manifest["output"]["maxBytes"]
    text = framework.canonical_bytes(plan).decode()
    assert "Authorization" not in text
    assert "requestBody" not in text
    assert "headers" not in text
    assert "http://" not in text
    assert "https://" not in text
    assert all(event["tenantToken"].startswith("syn-tenant-") for event in plan["events"])


@pytest.mark.parametrize(
    ("samples", "p50", "p95", "p99"),
    [
        ([], None, None, None),
        ([7], 7, 7, 7),
        ([1, 2, 3, 4], 2, 4, 4),
        ([4, 3, 2, 1], 2, 4, 4),
        ([5, 5, 5, 5], 5, 5, 5),
        ([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], 4, 9, 9),
    ],
)
def test_nearest_rank_percentiles_use_fixed_expected_fixtures(samples, p50, p95, p99):
    assert framework.nearest_rank(samples, 5000) == p50
    assert framework.nearest_rank(samples, 9500) == p95
    assert framework.nearest_rank(samples, 9900) == p99


def test_percentiles_reject_negative_noninteger_and_invalid_ranks():
    with pytest.raises(framework.ContractError):
        framework.nearest_rank([-1], 5000)
    with pytest.raises(framework.ContractError):
        framework.nearest_rank([1.0], 5000)
    with pytest.raises(framework.ContractError):
        framework.nearest_rank([1], 0)


def test_measurement_excludes_warmup_and_cooldown_and_accounts_for_failures():
    manifest = _manifest()
    manifest["limits"]["maxRetries"] = 1
    plan = framework.generate_plan(manifest)
    measurement_sequences = [
        event["sequence"] for event in plan["events"] if event["phase"] == "measurement"
    ]
    outcomes = {
        measurement_sequences[0]: "timeout",
        measurement_sequences[1]: "dependency-unavailable",
    }
    observations = _observations(manifest, plan, outcomes)
    result = framework.build_result(manifest, plan, observations)
    aggregate = result["aggregate"]
    assert aggregate["requestCount"] == 16
    assert aggregate["successCount"] == 14
    assert aggregate["failureCount"] == 2
    assert aggregate["timeoutCount"] == 1
    assert aggregate["retryCount"] == 1
    assert aggregate["errorRateBasisPoints"] == 1250
    assert aggregate["latency"]["sampleCount"] == 16
    assert aggregate["queueWait"]["sampleCount"] == 16
    assert aggregate["maximumQueueDepth"] == 4
    assert aggregate["maximumSaturationBasisPoints"] == max(measurement_sequences) * 10


def test_failure_and_timeout_latency_inclusion_is_explicit():
    manifest = _manifest()
    manifest["limits"]["maxRetries"] = 1
    manifest["measurement"]["includeFailureLatencies"] = False
    manifest["measurement"]["includeTimeoutLatencies"] = False
    plan = framework.generate_plan(manifest)
    measured = [event for event in plan["events"] if event["phase"] == "measurement"]
    outcomes = {measured[0]["sequence"]: "timeout", measured[1]["sequence"]: "server-error"}
    result = framework.build_result(manifest, plan, _observations(manifest, plan, outcomes))
    assert result["aggregate"]["latency"]["sampleCount"] == 14


def test_empty_and_single_measurement_sets_have_exact_semantics():
    manifest = _manifest()
    plan = framework.generate_plan(manifest)
    empty = framework.build_result(manifest, plan, [])
    assert empty["aggregate"]["requestCount"] == 0
    assert empty["aggregate"]["latency"] == {
        "sampleCount": 0,
        "minimumUs": None,
        "maximumUs": None,
        "meanUs": None,
        "p50Us": None,
        "p95Us": None,
        "p99Us": None,
    }
    event = next(event for event in plan["events"] if event["phase"] == "measurement")
    one = framework.Observation(
        sequence=event["sequence"],
        phase="measurement",
        operation_id=event["operationId"],
        tenant_token=event["tenantToken"],
        completed_at_logical_us=event["scheduledAtLogicalUs"] + 123,
        latency_us=123,
        outcome="success",
    )
    single = framework.build_result(manifest, plan, [one])
    latency = single["aggregate"]["latency"]
    assert {
        latency["minimumUs"],
        latency["maximumUs"],
        latency["meanUs"],
        latency["p50Us"],
        latency["p95Us"],
        latency["p99Us"],
    } == {123}


def test_throughput_uses_logical_microseconds_and_integer_half_up_rounding():
    observations = [
        framework.Observation(
            0, "measurement", "health.live", "syn-tenant-0000000000000000", 1_500_000, 10, "success"
        ),
        framework.Observation(
            1, "measurement", "health.live", "syn-tenant-0000000000000000", 1_500_000, 10, "success"
        ),
    ]
    result = framework._measurement(
        observations,
        elapsed_us=1_500_000,
        include_timeout_latencies=True,
        include_failure_latencies=True,
    )
    assert result["throughputMilliRequestsPerSecond"] == 1333


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["server-error"] * 5, "max-failures"),
        (["timeout"] * 3, "max-timeouts"),
        (["success", "server-error"], "max-error-rate"),
    ],
)
def test_stop_conditions_have_deterministic_precedence(outcomes, expected):
    stop = {
        "maxFailures": 4,
        "maxTimeouts": 2,
        "maxErrorRateBasisPoints": 2500,
        "stopOnAssertionFailure": True,
    }
    observations = [
        framework.Observation(
            index,
            "measurement",
            "health.live",
            "syn-tenant-0000000000000000",
            index + 1,
            1,
            outcome,
        )
        for index, outcome in enumerate(outcomes)
    ]
    assert framework.evaluate_stop_reason(observations, stop) == expected


def test_tenant_aggregation_is_sorted_bounded_and_exact():
    manifest = _manifest()
    plan = framework.generate_plan(manifest)
    result = framework.build_result(manifest, plan, _observations(manifest, plan))
    tenant_rows = result["tenantMeasurements"]
    assert len(tenant_rows) == 2
    assert [row["tenantToken"] for row in tenant_rows] == sorted(
        row["tenantToken"] for row in tenant_rows
    )
    assert sum(row["measurement"]["requestCount"] for row in tenant_rows) == 16


def test_measurement_cardinality_limit_fails_closed():
    manifest = _manifest()
    manifest["limits"]["maxMeasurementSeries"] = 2
    plan = framework.generate_plan(manifest)
    with pytest.raises(framework.ContractError, match="cardinality"):
        framework.build_result(manifest, plan, _observations(manifest, plan))


def test_output_size_limit_fails_before_generation():
    manifest = _manifest()
    manifest["limits"]["maxOutputBytes"] = 1024
    manifest["output"]["maxBytes"] = 1024
    with pytest.raises(framework.ContractError, match="cannot fit"):
        framework.validate_manifest(manifest)


@pytest.mark.parametrize(
    "unsafe",
    [
        "Authorization: Bearer synthetic-but-prohibited",
        "sk-" + "abcdefghijklmnopqrstuvwxyz123456",
        "C:" + "\\Users\\private\\secret.txt",
    ],
)
def test_secret_bearing_and_private_path_text_is_rejected(unsafe):
    manifest = _manifest()
    manifest["purpose"] = unsafe
    with pytest.raises(framework.ContractError, match="prohibited"):
        framework.validate_manifest(manifest)


def test_result_serialization_and_integrity_are_deterministic():
    manifest = _manifest()
    plan, first = framework.simulate_local(manifest)
    second = framework.build_result(manifest, plan, _observations(manifest, plan))
    third = framework.build_result(manifest, plan, list(reversed(_observations(manifest, plan))))
    assert second == third
    assert framework.validate_result(first) == first
    assert first["integritySha256"] == framework.simulate_local(manifest)[1]["integritySha256"]


def test_result_integrity_detects_material_mutation():
    _, result = framework.simulate_local(_manifest())
    result["aggregate"]["successCount"] -= 1
    with pytest.raises(framework.ContractError, match="integrity hash"):
        framework.validate_result(result)


def test_observation_bounds_and_duplicate_sequences_fail_closed():
    manifest = _manifest()
    plan = framework.generate_plan(manifest)
    observations = _observations(manifest, plan)
    observations[0] = framework.Observation(
        observations[0].sequence,
        observations[0].phase,
        observations[0].operation_id,
        observations[0].tenant_token,
        observations[0].completed_at_logical_us,
        observations[0].latency_us,
        observations[0].outcome,
        retry_count=3,
    )
    with pytest.raises(framework.ContractError, match="retry count"):
        framework.build_result(manifest, plan, observations)
    observations = _observations(manifest, plan)
    observations[-1] = observations[0]
    with pytest.raises(framework.ContractError, match="sequences"):
        framework.build_result(manifest, plan, observations)


def test_observation_attribution_and_time_must_match_the_plan():
    manifest = _manifest()
    plan = framework.generate_plan(manifest)
    observations = _observations(manifest, plan)
    first = observations[0]
    observations[0] = framework.Observation(
        first.sequence,
        first.phase,
        first.operation_id,
        observations[1].tenant_token,
        first.completed_at_logical_us,
        first.latency_us,
        first.outcome,
    )
    with pytest.raises(framework.ContractError, match="attribution"):
        framework.build_result(manifest, plan, observations)
    observations = _observations(manifest, plan)
    first = observations[0]
    observations[0] = framework.Observation(
        first.sequence,
        first.phase,
        first.operation_id,
        first.tenant_token,
        first.completed_at_logical_us,
        manifest["limits"]["requestTimeoutMs"] * 1000 + 1,
        first.outcome,
    )
    with pytest.raises(framework.ContractError, match="request-timeout"):
        framework.build_result(manifest, plan, observations)


def test_local_dry_run_is_reproducible_stdout_only(tmp_path):
    command = [
        sys.executable,
        "-B",
        "-m",
        "performance.milestone_7_7.dry_run",
        str(ROOT / "workload.example.json"),
    ]
    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    second = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert not first.stderr
    assert list(tmp_path.iterdir()) == []
    result = framework.loads_json(first.stdout.decode())
    assert result["runMetadata"]["executionBoundary"] == "synthetic-local-simulator"
    assert result["validationStatus"] == "valid-synthetic-local"


def test_framework_has_no_network_process_or_application_imports():
    source = (ROOT / "framework.py").read_text(encoding="utf-8")
    prohibited = (
        "import socket",
        "import subprocess",
        "import urllib",
        "import httpx",
        "import requests",
        "import opencanvas_api",
        "azure.",
    )
    assert not any(item in source for item in prohibited)


def test_checkpoint_does_not_add_a_migration_and_binds_current_bundle():
    assert not list((REPO_ROOT / "apps" / "api" / "alembic" / "versions").glob("*0029*"))
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPO_ROOT / "infra" / "milestone_7_7" / "scripts" / "preflight.py"),
            "--bundle-root",
            str(REPO_ROOT / "infra" / "milestone_7_7"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    assert "20d5eee8fedf72257c4442b70739d0ce1aa67d1c5533da89ea7d32d3085dbc24" in completed.stdout

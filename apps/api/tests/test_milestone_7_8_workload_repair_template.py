from __future__ import annotations

import copy
import json
from typing import cast

import pytest

from infra.milestone_7_8.campaign import CampaignError
from infra.milestone_7_8.workload_repair_template import (
    MOUNT_OPTIONS,
    RESOURCE_KEYS,
    compile_main,
    derive_template,
    validate_repaired_mount,
)

DIGEST = "sha256:" + "a" * 64


@pytest.fixture(scope="module")
def compiled() -> dict[str, object]:
    try:
        return compile_main()
    except CampaignError as exc:
        if "installed Bicep compiler" in str(exc):
            pytest.skip(str(exc))
        raise


def _parameters(compiled: dict[str, object]) -> dict[str, object]:
    definitions = cast(dict[str, dict[str, object]], compiled["parameters"])
    values: dict[str, object] = {}
    for key, definition in definitions.items():
        if "defaultValue" in definition:
            continue
        kind = definition["type"]
        values[key] = {"value": {} if kind == "object" else 1 if kind == "int" else key}
    values["resourceNameSuffix"] = {"value": "1234567890"}
    return {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/"
            "deploymentParameters.json#", "contentVersion": "1.0.0.0", "parameters": values}


def _module(compiled: dict[str, object]) -> dict[str, object]:
    resources = cast(list[dict[str, object]], compiled["resources"])
    return next(item for item in resources if item["type"] == "Microsoft.Resources/deployments"
                and "m78-campaign" in str(item["name"]))


def _nested(module: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], cast(dict[str, object], module["properties"])["template"])


@pytest.mark.parametrize("missing", [
    ("apiApp", "workerJob"),
    ("apiApp", "workerJob", "evidenceJob", "migrationProbeJob"),
])
def test_actual_compiled_template_repair_preserves_only_selected_resource_bodies(
    compiled: dict[str, object], missing: tuple[str, ...],
) -> None:
    original = copy.deepcopy(compiled)
    parameters = _parameters(compiled)
    original_parameters = copy.deepcopy(parameters)
    repaired, supplied = derive_template(
        compiled, parameters, image_digest=DIGEST, missing=missing,
        repair_name="m78-mount-repair-synthetic",
    )
    assert compiled == original and parameters == original_parameters
    modules = cast(list[dict[str, object]], repaired["resources"])
    assert len(modules) == 1
    module = modules[0]
    assert module["name"] == "m78-mount-repair-synthetic"
    assert "dependsOn" not in module
    assert module["resourceGroup"] == "[parameters('targetResourceGroupName')]"
    props = cast(dict[str, object], module["properties"])
    old_module = _module(compiled)
    old_props = cast(dict[str, object], old_module["properties"])
    assert props["parameters"] == old_props["parameters"]
    assert "m78-identities" in json.dumps(props["parameters"])
    assert "Microsoft.Automation/automationAccounts" in json.dumps(props["parameters"])
    nested = _nested(module)
    old_nested = _nested(old_module)
    selected = cast(list[dict[str, object]], nested["resources"])
    assert len(selected) == len(missing)
    original_resources = cast(list[dict[str, object]], old_nested["resources"])
    selected_names = {item["name"] for item in selected}
    assert len(selected_names) == len(selected)
    assert {item["type"] for item in selected} == {
        "Microsoft.App/containerApps", "Microsoft.App/jobs",
    }
    assert all("roleAssignments" not in str(item["type"]) for item in selected)
    for item in selected:
        old = next(row for row in original_resources if row.get("name") == item["name"])
        assert {k: v for k, v in item.items() if k != "dependsOn"} == {
            k: v for k, v in old.items() if k != "dependsOn"
        }
        for dependency in cast(list[str], item.get("dependsOn", [])):
            assert "Microsoft.App/containerApps" in dependency
        name = str(item["name"])
        if "-evidence" in name or "-probe-migrate" in name:
            assert len(cast(list[str], item["dependsOn"])) == 1
    assert nested["outputs"] == old_nested["outputs"]
    assert nested["parameters"] == old_nested["parameters"]
    assert nested["variables"] == old_nested["variables"]
    outputs = json.dumps(repaired["outputs"])
    assert "m78-campaign-{0}" not in outputs
    assert "m78-mount-repair-synthetic" in outputs
    supplied_values = cast(dict[str, object], supplied["parameters"])
    assert supplied_values["imageDigest"] == {"value": DIGEST}
    assert supplied_values["deploymentStage"] == {"value": "workload"}
    assert {key: value for key, value in supplied_values.items()
            if key not in {"imageDigest", "deploymentStage"}} == original_parameters["parameters"]


@pytest.mark.parametrize("missing", [(), ("workerJob",), ("apiApp", "workerJob", "bootstrapJob"),
                                      ("apiApp", "workerJob", "workerJob")])
def test_unapproved_or_ambiguous_resource_selection_is_rejected(
    compiled: dict[str, object], missing: tuple[str, ...],
) -> None:
    with pytest.raises(CampaignError, match="scope"):
        derive_template(compiled, _parameters(compiled), image_digest=DIGEST,
                        missing=missing, repair_name="m78-repair-test")


@pytest.mark.parametrize("defect", ["seal", "missing-parameter", "unknown-parameter",
                                    "wrong-group", "complete-mode", "duplicate-api"])
def test_unsafe_derivation_is_rejected(compiled: dict[str, object], defect: str) -> None:
    main = copy.deepcopy(compiled)
    parameters = _parameters(main)
    module = _module(main)
    props = cast(dict[str, object], module["properties"])
    nested = _nested(module)
    resources = cast(list[dict[str, object]], nested["resources"])
    api = next(row for row in resources if row["type"] == "Microsoft.App/containerApps")
    if defect == "seal":
        template = cast(dict[str, object], cast(dict[str, object], api["properties"])["template"])
        volumes = cast(list[dict[str, object]], template["volumes"])
        volumes[0]["mountOptions"] = MOUNT_OPTIONS + ",seal"
    elif defect == "missing-parameter":
        cast(dict[str, object], parameters["parameters"]).pop("campaignId")
    elif defect == "unknown-parameter":
        cast(dict[str, object], parameters["parameters"])["arbitrary"] = {"value": "value"}
    elif defect == "wrong-group":
        module["resourceGroup"] = "another-group"
    elif defect == "complete-mode":
        props["mode"] = "Complete"
    else:
        resources.append(copy.deepcopy(api))
    with pytest.raises(CampaignError):
        derive_template(main, parameters, image_digest=DIGEST, missing=tuple(RESOURCE_KEYS),
                        repair_name="m78-repair-test")


def test_readback_requires_exact_corrected_mount(compiled: dict[str, object]) -> None:
    nested = _nested(_module(compiled))
    resources = cast(list[dict[str, object]], nested["resources"])
    api = copy.deepcopy(next(row for row in resources
                             if row["type"] == "Microsoft.App/containerApps"))
    validate_repaired_mount(api)
    template = cast(dict[str, object], cast(dict[str, object], api["properties"])["template"])
    cast(list[dict[str, object]], template["volumes"])[0]["storageName"] = "other-share"
    with pytest.raises(CampaignError, match="document mount"):
        validate_repaired_mount(api)

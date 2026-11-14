"""Derive one bounded workload repair from the current compiled campaign Bicep."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import cast

from infra.milestone_7_8.campaign import CampaignError

ROOT = Path(__file__).resolve().parents[2]
MOUNT_OPTIONS = "uid=100,gid=101,dir_mode=0770,file_mode=0770,vers=3.1.1"
RESOURCE_KEYS = {
    "apiApp": ("Microsoft.App/containerApps", "api"),
    "workerJob": ("Microsoft.App/jobs", "worker"),
    "evidenceJob": ("Microsoft.App/jobs", "evidence"),
    "migrationProbeJob": ("Microsoft.App/jobs", "probe-migration"),
}


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CampaignError(f"workload repair {label} is malformed")
    return cast(dict[str, object], value)


def compile_main() -> dict[str, object]:
    """Compile installed Bicep locally; never install tooling or contact Azure."""
    installed = Path.home() / ".azure" / "bin" / "bicep.exe"
    executable = str(installed) if installed.is_file() else shutil.which("bicep")
    if executable is None:
        raise CampaignError("workload repair requires the installed Bicep compiler")
    result = subprocess.run(
        (executable, "build", str(ROOT / "infra/milestone_7_8/main.bicep"), "--stdout"),
        check=False, capture_output=True, text=True, timeout=90,
    )
    if result.returncode != 0:
        raise CampaignError("workload repair Bicep compilation failed")
    try:
        return _object(json.loads(result.stdout), "compiled main template")
    except json.JSONDecodeError as exc:
        raise CampaignError("workload repair compiler output is malformed") from exc


def validate_repaired_mount(resource: object) -> None:
    """Require the exact corrected API/worker document mount in a full readback."""
    value = _object(resource, "resource")
    properties = _object(value.get("properties"), "resource properties")
    template = _object(properties.get("template"), "resource template")
    volumes = template.get("volumes")
    if volumes != [{
        "name": "documents", "storageType": "AzureFile", "storageName": "m78-documents",
        "mountOptions": MOUNT_OPTIONS,
    }]:
        raise CampaignError("workload repair document mount differs")
    containers = template.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise CampaignError("workload repair container scope differs")
    container = _object(containers[0], "container")
    if container.get("volumeMounts") != [
        {"volumeName": "documents", "mountPath": "/app/data/documents"},
    ]:
        raise CampaignError("workload repair container mount differs")


def _replace_expression(value: object, original: str, replacement: str) -> object:
    if isinstance(value, str):
        return value.replace(original, replacement)
    if isinstance(value, list):
        return [_replace_expression(item, original, replacement) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_expression(item, original, replacement) for key, item in value.items()
        }
    return value


def _drop_generator_hash(template: dict[str, object]) -> None:
    metadata = template.get("metadata")
    if isinstance(metadata, dict):
        generator = metadata.get("_generator")
        if isinstance(generator, dict):
            generator.pop("templateHash", None)


def derive_template(
    compiled_main: dict[str, object],
    prepared_parameters: dict[str, object],
    *,
    image_digest: str,
    missing: tuple[str, ...],
    repair_name: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Keep only approved absent workload declarations and their internal dependencies.

    The caller must prove each selected resource absent and bind the compiler input,
    prepared parameters, admitted digest, and fresh deployment name in its plan.
    Existing identity deployment references and all selected resource bodies remain
    the actual compiler output. No base or identity resource is resubmitted.
    """
    if (
        re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) is None
        or re.fullmatch(r"[a-z][a-z0-9-]{0,62}[a-z0-9]", repair_name) is None
        or not missing or len(set(missing)) != len(missing)
        or set(missing) - set(RESOURCE_KEYS)
        or not {"apiApp", "workerJob"} <= set(missing)
    ):
        raise CampaignError("workload repair scope, digest, or deployment name differs")
    main = copy.deepcopy(compiled_main)
    if main.get("languageVersion") is not None:
        raise CampaignError("workload repair compiler resource encoding is unsupported")
    resources = main.get("resources")
    if not isinstance(resources, list):
        raise CampaignError("workload repair compiler resources are malformed")
    campaign_name = (
        "[format('m78-campaign-{0}', "
        "uniqueString(parameters('campaignId'), parameters('generationId')))]"
    )
    modules = [item for item in resources if isinstance(item, dict)
               and item.get("type") == "Microsoft.Resources/deployments"
               and item.get("name") == campaign_name]
    if len(modules) != 1:
        raise CampaignError("workload repair requires the exact compiled campaign module")
    module = _object(modules[0], "campaign module")
    if module.get("resourceGroup") != "[parameters('targetResourceGroupName')]":
        raise CampaignError("workload repair group scope differs")
    properties = _object(module.get("properties"), "module properties")
    if (properties.get("mode") != "Incremental"
            or properties.get("expressionEvaluationOptions") != {"scope": "inner"}):
        raise CampaignError("workload repair deployment mode differs")
    nested = _object(properties.get("template"), "nested template")
    declarations = nested.get("resources")
    if not isinstance(declarations, list) or nested.get("languageVersion") is not None:
        raise CampaignError("workload repair nested resource encoding is unsupported")
    selected: dict[str, dict[str, object]] = {}
    for raw in declarations:
        resource = _object(raw, "declaration")
        props = resource.get("properties")
        template = props.get("template") if isinstance(props, dict) else None
        containers = template.get("containers") if isinstance(template, dict) else None
        if not isinstance(containers, list) or len(containers) != 1:
            continue
        container = _object(containers[0], "compiled container")
        for key, (kind, container_name) in RESOURCE_KEYS.items():
            if resource.get("type") == kind and container.get("name") == container_name:
                if key in selected or resource.get("apiVersion") != "2024-03-01":
                    raise CampaignError("workload repair declaration is duplicated or differs")
                selected[key] = resource
    if set(selected) != set(RESOURCE_KEYS):
        raise CampaignError("workload repair compiler omitted its expected declarations")
    validate_repaired_mount(selected["apiApp"])
    validate_repaired_mount(selected["workerJob"])
    kept = [selected[key] for key in RESOURCE_KEYS if key in missing]
    dependency_ids: set[str] = set()
    for resource in kept:
        name = resource.get("name")
        if not isinstance(name, str) or not name.startswith("[") or not name.endswith("]"):
            raise CampaignError("workload repair resource name expression differs")
        dependency_ids.add(f"[resourceId('{resource['type']}', {name[1:-1]})]")
    for resource in kept:
        dependencies = resource.get("dependsOn", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) for item in dependencies
        ):
            raise CampaignError("workload repair dependency shape differs")
        retained = [item for item in dependencies if item in dependency_ids]
        if retained:
            resource["dependsOn"] = retained
        else:
            resource.pop("dependsOn", None)
    nested["resources"] = kept
    _drop_generator_hash(nested)
    module.pop("dependsOn", None)
    module["name"] = repair_name
    main["resources"] = [module]
    outputs = _object(main.get("outputs"), "main outputs")
    # Output expressions must read this new nested deployment, not the failed one.
    main["outputs"] = _replace_expression(outputs, campaign_name[1:-1], f"'{repair_name}'")
    _drop_generator_hash(main)
    parameters = copy.deepcopy(prepared_parameters)
    values = _object(parameters.get("parameters"), "prepared parameters")
    definitions = _object(main.get("parameters"), "parameter definitions")
    if set(values) - set(definitions):
        raise CampaignError("workload repair parameters include unknown values")
    for key, definition in definitions.items():
        field = _object(definition, "parameter definition")
        if key not in values and "defaultValue" not in field:
            raise CampaignError("workload repair prepared parameter is missing")
    for value in values.values():
        if set(_object(value, "parameter value")) != {"value"}:
            raise CampaignError("workload repair parameter is not a retained literal value")
    values["deploymentStage"] = {"value": "workload"}
    values["imageDigest"] = {"value": image_digest}
    return main, parameters

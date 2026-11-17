"""Classify the demonstrated pilot bootstrap failure before any database I/O."""

from __future__ import annotations

import json
import re
from copy import deepcopy

from infra.milestone_7_8.campaign import CampaignError

COMMAND = ["python", "-m", "scripts.bootstrap_postgres"]
ROLE = "OPENCANVAS_DATABASE_ROLE"
MARKER = "M78_BOOTSTRAP_DIAGNOSTIC "
PRE_IO = {"errorClass": "RuntimeError", "sqlstate": None, "stage": "configuration"}


def _container(resource: dict, digest: str) -> dict:
    containers = resource["properties"]["template"]["containers"]
    if len(containers) != 1:
        raise CampaignError("exact bootstrap container required")
    item = containers[0]
    if (
        item["name"] != "bootstrap"
        or item["command"] != COMMAND
        or item.get("args")
        or not item["image"].endswith("@" + digest)
    ):
        raise CampaignError("bootstrap command or image differs")
    return item


def require_normal_bootstrap(job: dict, digest: str) -> None:
    env = [x for x in _container(job, digest)["env"] if x["name"] == ROLE]
    if env != [{"name": ROLE, "value": "provisioning"}]:
        raise CampaignError("normal bootstrap requires the provisioning role")


def pre_io_recovery_template(
    job: dict,
    execution: dict,
    inventory: list[dict],
    console: str,
    digest: str,
) -> dict:
    """Return the one allowed template correction for the exact first failed execution.

    The caller must obtain complete native readbacks for this campaign, reconcile
    dispatch and start intents, read back the patch and enforce the approval window.
    All other failures stay on the existing guarded recovery/stop path.
    """
    name = execution["name"]
    resource = f"{job['id']}/executions/{name}"
    if (
        not re.fullmatch(re.escape(job["name"]) + r"-[a-z0-9]+", name)
        or execution["id"].casefold() != resource.casefold()
        or execution["properties"]["status"] != "Failed"
        or len(inventory) != 1
        or inventory[0]["id"].casefold() != resource.casefold()
        or inventory[0]["properties"] != execution["properties"]
    ):
        raise CampaignError("exact sole failed bootstrap execution required")
    bound = re.findall(r"\[Execution: '([a-z0-9-]+)', Replica: '([a-z0-9-]+)'\]", console)
    if (
        len(bound) != 1
        or bound[0][0] != name
        or not bound[0][1].startswith(name + "-")
        or console.count(MARKER) != 1
        or console.count("PostgreSQL principal bootstrap failed safely.") != 1
        or console.index(MARKER) > console.index("PostgreSQL principal bootstrap failed safely.")
    ):
        raise CampaignError("complete exact bootstrap console diagnostic required")
    try:
        payload, _ = json.JSONDecoder().raw_decode(console.split(MARKER, 1)[1])
    except ValueError:
        raise CampaignError("invalid bootstrap diagnostic") from None
    if payload != PRE_IO:
        raise CampaignError("failure did not demonstrate the known pre-I/O stage")
    current, failed = _container(job, digest), _container(execution, digest)
    # ACA adds this read-only annotation to execution containers, not job templates.
    if failed.get("imageType") == 'ContainerImage' and "imageType" not in current:
        failed = {key: value for key, value in failed.items() if key != "imageType"}
    if current != failed:
        raise CampaignError("bootstrap template drift requires reconciliation")
    template = deepcopy(job["properties"]["template"])
    roles = [x for x in template["containers"][0]["env"] if x["name"] == ROLE]
    if roles != [{"name": ROLE, "value": "migration"}]:
        raise CampaignError("failure did not use the known incorrect bootstrap role")
    roles[0]["value"] = "provisioning"
    return template

from __future__ import annotations

import re
from urllib.parse import urlsplit

from infra.milestone_7_8.campaign import CampaignError

PREREQUISITE_MARKER = "M78_DATABASE_PREREQUISITES"
PREREQUISITE_TOKEN = "M78_DATABASE_PREREQUISITE_TOKEN"


def validate_database_template(
    resource: dict[str, object],
    manifest: dict[str, object],
    *,
    operation: str,
    subscription: str,
    group: str,
    server: str,
    registry: str,
    image_digest: str,
) -> str:
    slot = "bootstrap" if operation == "bootstrap" else "migration"
    role = "provisioning" if slot == "bootstrap" else "migration"
    principals = manifest.get("principals")
    principal = principals.get(slot) if isinstance(principals, dict) else None
    identity = resource.get("identity")
    assignments = identity.get("userAssignedIdentities") if isinstance(identity, dict) else None
    properties = resource.get("properties")
    template = properties.get("template") if isinstance(properties, dict) else None
    containers = template.get("containers") if isinstance(template, dict) else None
    if (
        not isinstance(principal, dict)
        or principal.get("role") != slot
        or not isinstance(principal.get("name"), str)
        or not isinstance(identity, dict)
        or identity.get("type") != "UserAssigned"
        or not isinstance(assignments, dict)
        or len(assignments) != 1
        or not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], dict)
    ):
        raise CampaignError("database prerequisite job identity is unproved")
    identity_id, assigned = next(iter(assignments.items()))
    expected_id = (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{principal['name']}"
    )
    container = containers[0]
    entries = container.get("env")
    env: dict[str, object] = {}
    if not isinstance(entries, list):
        raise CampaignError("database prerequisite environment is missing")
    for item in entries:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or item["name"] in env
        ):
            raise CampaignError("database prerequisite environment is ambiguous")
        env[item["name"]] = item.get("value")
    url = urlsplit(str(env.get("OPENCANVAS_DATABASE_URL", "")))
    if (
        str(identity_id).casefold() != expected_id.casefold()
        or not isinstance(assigned, dict)
        or not isinstance(assigned.get("principalId"), str)
        or str(assigned["principalId"]).casefold() != str(principal.get("objectId")).casefold()
        or not isinstance(assigned.get("clientId"), str)
        or env.get("OPENCANVAS_DATABASE_MANAGED_IDENTITY_CLIENT_ID") != assigned["clientId"]
        or env.get("OPENCANVAS_DATABASE_CURRENT_PRINCIPAL_ID") != principal.get("objectId")
        or env.get("OPENCANVAS_DATABASE_ROLE") != role
        or env.get("OPENCANVAS_DATABASE_AUTH_MODE") != "entra"
        or env.get("OPENCANVAS_DATABASE_TLS_MODE") not in {"require", "verify-full"}
        or env.get("OPENCANVAS_CAMPAIGN_ID") != manifest.get("campaignId")
        or env.get("OPENCANVAS_CAMPAIGN_GENERATION_ID") != manifest.get("generationId")
        or url.scheme != "postgresql+asyncpg"
        or url.username != principal["name"]
        or url.password is not None
        or url.hostname != f"{server}.postgres.database.azure.com"
        or url.port != 5432
        or url.path != "/opencanvas"
        or url.query
        or url.fragment
        or container.get("image") != f"{registry}.azurecr.io/mobius-api@{image_digest}"
        or container.get("name") != slot
        or container.get("args") != ["--diagnose-prerequisites"]
    ):
        raise CampaignError("database prerequisite job binding differs")
    return slot


def validate_prerequisite_marker(
    value: object, *, operation: str, campaign_id: str, generation_id: str
) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or set(value) != {
            "version", "operation", "status", "identityDatabase", "applicationDatabase",
            "identityMatches", "applicationBindingMatches", "listingRead", "createExecute",
            "campaignId", "generationId", "vector",
        }
        or value["version"] != "m7.8-database-prerequisites-v1"
        or value["operation"] != operation
        or value["status"] != "read-only-prerequisites-passed"
        or value["identityDatabase"] != "postgres"
        or value["applicationDatabase"] != "opencanvas"
        or value["identityMatches"] is not True
        or value["applicationBindingMatches"] is not True
        or type(value["listingRead"]) is not bool
        or value["campaignId"] != campaign_id
        or value["generationId"] != generation_id
    ):
        raise CampaignError("required read-only database prerequisite evidence is incomplete")
    vector = value["vector"]
    if (
        not isinstance(vector, dict)
        or set(vector) != {
            "version", "trusted", "superuserRequired", "installed", "installerAllowed",
        }
        or re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", str(vector["version"])) is None
        or tuple(int(part) for part in str(vector["version"]).split("."))[:2] < (0, 7)
        or any(type(vector[key]) is not bool for key in (
            "trusted", "superuserRequired", "installed", "installerAllowed",
        ))
    ):
        raise CampaignError("vector packaging or database binding is unproved")
    if operation == "bootstrap":
        if (
            value["listingRead"] is not True
            or value["createExecute"] is not True
            or (vector["installed"] is not True and vector["installerAllowed"] is not True)
        ):
            raise CampaignError("bootstrap identity-management or installation access is unproved")
    elif operation != "migrate" or value["createExecute"] is not None or not vector["installed"]:
        raise CampaignError("migration vector prerequisite is unproved")
    return value

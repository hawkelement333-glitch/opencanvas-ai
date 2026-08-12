"""Closed Generation 4 target-resource adoption projections."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from typing import Final

from performance.milestone_7_7.framework import JsonValue

GENERATION_FOUR_SCANNER_FOUNDATION_RESOURCE_LOCATIONS: Final = (
    ("microsoft.storage/storageaccounts/stmobius7711564669", "southcentralus"),
    (
        "microsoft.eventgrid/systemtopics/stmobius7711564669-e846ac4b-bf07-473f-a3d8-1996a567f485",
        "southcentralus",
    ),
    ("microsoft.insights/privatelinkscopes/ampls-mobius77-staging", "global"),
    *(
        resource
        for zone, link in (
            ("privatelink.blob.core.windows.net", "link-mobius77-storage"),
            ("privatelink.monitor.azure.com", "link-mobius77-monitor"),
            ("privatelink.oms.opinsights.azure.com", "link-mobius77-oms"),
            ("privatelink.ods.opinsights.azure.com", "link-mobius77-ods"),
            (
                "privatelink.agentsvc.azure-automation.net",
                "link-mobius77-agent",
            ),
        )
        for resource in (
            (f"microsoft.network/privatednszones/{zone}", "global"),
            (
                f"microsoft.network/privatednszones/{zone}/virtualnetworklinks/{link}",
                "global",
            ),
        )
    ),
)
POST_BOOTSTRAP: Final = (
    ("microsoft.app/jobs/caj-mobius77-migration", "southcentralus"),
    (
        "microsoft.dbforpostgresql/flexibleservers/psql-mobius77-11564669",
        "centralus",
    ),
    (
        "microsoft.network/privatednszones/privatelink.postgres.database.azure.com",
        "global",
    ),
    (
        "microsoft.network/privatednszones/privatelink.postgres.database.azure.com/"
        "virtualnetworklinks/link-mobius77-postgres",
        "global",
    ),
    (
        "microsoft.network/privatednszones/privatelink.postgres.database.azure.com/"
        "virtualnetworklinks/link-mobius77-staging-postgres",
        "global",
    ),
    ("microsoft.network/virtualnetworks/vnet-mobius77-postgres", "centralus"),
)
_SCANNER_FOUNDATION_RESOURCE_IDS: Final = frozenset(
    relative
    for relative, _location in GENERATION_FOUR_SCANNER_FOUNDATION_RESOURCE_LOCATIONS
)
_ROLE_ASSIGNMENT_NAME: Final = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_OBJECT_ID: Final = re.compile(r"^[0-9a-fA-F-]{36}$")
MANAGED_BINDING_IDENTITY_NAMES: Final = frozenset(
    {
        "id-mobius77-api",
        "id-mobius77-worker",
        "id-mobius77-telemetry",
        "id-mobius77-db-admin",
    }
)


def managed_binding_protected_resources(
    target_scope: str, *, key_vault_role_id: str, acr_pull_role_id: str
) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    """Return the exact protected-resource role projections."""

    return {
        "microsoft.keyvault/vaults/kv-mobius77-11564669": (
            f"{target_scope}/providers/Microsoft.KeyVault/vaults/kv-mobius77-11564669",
            key_vault_role_id,
            ("id-mobius77-api", "id-mobius77-worker", "id-mobius77-telemetry"),
        ),
        "microsoft.containerregistry/registries/acrmobius7711564669": (
            f"{target_scope}/providers/Microsoft.ContainerRegistry/registries/"
            "acrmobius7711564669",
            acr_pull_role_id,
            (
                "id-mobius77-api",
                "id-mobius77-worker",
                "id-mobius77-telemetry",
                "id-mobius77-db-admin",
            ),
        ),
    }


def managed_identity_principal(
    *,
    subscription_id: str,
    identity_name: str,
    read: Callable[[tuple[str, ...]], JsonValue],
) -> str:
    """Read one closed-set workload identity principal."""

    if identity_name not in MANAGED_BINDING_IDENTITY_NAMES:
        raise ValueError("pre-secret-workload-identity-malformed")
    value = read(
        (
            "az",
            "identity",
            "show",
            "--resource-group",
            "rg-solarplexus-mobius-77-staging",
            "--name",
            identity_name,
            "--subscription",
            subscription_id,
            "--query",
            "{principalId:principalId}",
            "--output",
            "json",
            "--only-show-errors",
        )
    )
    if not isinstance(value, dict) or set(value) != {"principalId"}:
        raise ValueError("pre-secret-workload-identity-malformed")
    principal_id = value["principalId"]
    if not isinstance(principal_id, str) or _OBJECT_ID.fullmatch(principal_id) is None:
        raise ValueError("pre-secret-workload-identity-malformed")
    return principal_id


def orphaned_temporary_role_assignment_query(
    *, subscription_id: str, principal_id: str, role_id: str, scope: str
) -> tuple[str, ...]:
    """Build the authoritative exact-scope orphan readback query."""

    return (
        "az",
        "role",
        "assignment",
        "list",
        "--assignee-object-id",
        principal_id,
        "--role",
        role_id,
        "--scope",
        scope,
        "--fill-principal-name",
        "false",
        "--subscription",
        subscription_id,
        "--query",
        "[].{id:id,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
        "--output",
        "json",
        "--only-show-errors",
    )


def orphaned_temporary_key_vault_assignment_id(
    *,
    contract: JsonValue,
    subscription_id: str,
    principal_id: str,
    read: Callable[[tuple[str, ...]], JsonValue],
) -> str | None:
    """Read and select the sole exact orphaned Key Vault assignment."""

    if not isinstance(contract, dict):
        raise ValueError("managed-binding-contract-malformed")
    rbac = contract.get("rbac")
    scopes = contract.get("scopeBinding")
    if not isinstance(rbac, dict) or not isinstance(scopes, dict):
        raise ValueError("managed-binding-contract-malformed")
    role_id = rbac.get("keyVaultSecretsOfficerRoleDefinitionId")
    scope_suffix = scopes.get("keyVault")
    if not isinstance(role_id, str) or not isinstance(scope_suffix, str):
        raise ValueError("managed-binding-contract-malformed")
    scope = f"/subscriptions/{subscription_id}{scope_suffix}"
    role_definition_id = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/"
        f"roleDefinitions/{role_id}"
    )
    return exact_orphaned_temporary_role_assignment_id(
        read(
            orphaned_temporary_role_assignment_query(
                subscription_id=subscription_id,
                principal_id=principal_id,
                role_id=role_id,
                scope=scope,
            )
        ),
        principal_id=principal_id,
        role_definition_id=role_definition_id,
        scope=scope,
    )


def exact_orphaned_temporary_role_assignment_id(
    value: JsonValue,
    *,
    principal_id: str,
    role_definition_id: str,
    scope: str,
) -> str | None:
    """Return the sole exact temporary assignment, rejecting ambiguity or drift."""

    if not isinstance(value, list) or len(value) > 1:
        raise ValueError("orphaned-temporary-role-assignment-drift")
    if not value:
        return None
    row = value[0]
    fields = {"id", "principalId", "roleDefinitionId", "scope"}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError("orphaned-temporary-role-assignment-drift")
    if any(not isinstance(row[field], str) for field in fields):
        raise ValueError("orphaned-temporary-role-assignment-drift")
    if (
        str(row["principalId"]).casefold() != principal_id.casefold()
        or str(row["roleDefinitionId"]).casefold() != role_definition_id.casefold()
        or str(row["scope"]).casefold() != scope.casefold()
    ):
        raise ValueError("orphaned-temporary-role-assignment-drift")
    assignment_id = str(row["id"])
    prefix = f"{scope}/providers/Microsoft.Authorization/roleAssignments/"
    if (
        not assignment_id.casefold().startswith(prefix.casefold())
        or _ROLE_ASSIGNMENT_NAME.fullmatch(assignment_id[len(prefix) :]) is None
    ):
        raise ValueError("orphaned-temporary-role-assignment-drift")
    return assignment_id


def resource_type_matches_relative_id(resource_type: str, relative_id: str) -> bool:
    """Return whether an ARM type exactly describes a relative resource ID."""

    type_parts = resource_type.casefold().split("/")
    relative_parts = relative_id.casefold().split("/")
    return (
        len(type_parts) >= 2
        and len(relative_parts) == (2 * len(type_parts)) - 1
        and relative_parts[0] == type_parts[0]
        and relative_parts[1::2] == type_parts[1:]
    )


def scanner_foundation_projection_is_complete(observed: Collection[str]) -> bool:
    """Accept an empty pre-stage projection or the exact complete stage graph."""

    projected = frozenset(observed) & _SCANNER_FOUNDATION_RESOURCE_IDS
    return not projected or projected == _SCANNER_FOUNDATION_RESOURCE_IDS

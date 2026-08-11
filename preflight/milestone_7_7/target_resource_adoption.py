"""Closed Generation 4 target-resource adoption projections."""

from __future__ import annotations

from collections.abc import Collection
from typing import Final

GENERATION_FOUR_SCANNER_FOUNDATION_RESOURCE_LOCATIONS: Final = (
    ("microsoft.storage/storageaccounts/stmobius7711564669", "southcentralus"),
    (
        "microsoft.eventgrid/systemtopics/"
        "stmobius7711564669-e846ac4b-bf07-"
        "473f-a3d8-1996a567f485",
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
_SCANNER_FOUNDATION_RESOURCE_IDS: Final = frozenset(
    relative
    for relative, _location in GENERATION_FOUR_SCANNER_FOUNDATION_RESOURCE_LOCATIONS
)


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

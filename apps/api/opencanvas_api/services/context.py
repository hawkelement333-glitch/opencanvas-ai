from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from opencanvas_api.db.models import CanvasNode


@dataclass(frozen=True, slots=True)
class ContextBundle:
    node_ids: list[uuid.UUID]
    snapshot: list[dict[str, str]]
    rendered: str


def build_context(
    nodes: Sequence[CanvasNode],
    selected_node_ids: Sequence[uuid.UUID],
    *,
    character_limit: int,
) -> ContextBundle:
    """Build deterministic, bounded context in the user's selection order."""
    by_id = {node.id: node for node in nodes}
    ordered_ids = list(dict.fromkeys(selected_node_ids))
    ordered = [by_id[node_id] for node_id in ordered_ids]
    fixed_parts = [
        f"Node {index}\nTitle: {node.title}\nContent:\n" for index, node in enumerate(ordered, 1)
    ]
    fixed_size = sum(len(part) + 2 for part in fixed_parts)
    text_budget = max(0, character_limit - fixed_size)
    remaining = text_budget
    snapshot: list[dict[str, str]] = []
    rendered_parts: list[str] = []

    for index, (node, prefix) in enumerate(zip(ordered, fixed_parts, strict=True)):
        nodes_left = len(ordered) - index
        share = remaining // nodes_left if nodes_left else 0
        clipped_text = node.text[:share]
        remaining -= len(clipped_text)
        snapshot.append({"nodeId": str(node.id), "title": node.title, "text": clipped_text})
        rendered_parts.append(prefix + clipped_text)

    return ContextBundle(
        node_ids=ordered_ids,
        snapshot=snapshot,
        rendered="\n\n".join(rendered_parts)[:character_limit],
    )

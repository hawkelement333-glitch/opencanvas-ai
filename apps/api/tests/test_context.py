from __future__ import annotations

import uuid

from opencanvas_api.db.models import CanvasNode
from opencanvas_api.services.context import build_context


def _node(title: str, text: str) -> CanvasNode:
    return CanvasNode(
        id=uuid.uuid4(),
        canvas_id=uuid.uuid4(),
        type="note",
        title=title,
        text=text,
        position_x=0,
        position_y=0,
        width=300,
        height=220,
    )


def test_context_preserves_selection_order_and_budget() -> None:
    first = _node("First", "a" * 200)
    second = _node("Second", "b" * 200)

    context = build_context(
        [first, second],
        [second.id, first.id],
        character_limit=150,
    )

    assert context.node_ids == [second.id, first.id]
    assert [item["title"] for item in context.snapshot] == ["Second", "First"]
    assert len(context.rendered) <= 150
    assert context.rendered.index("Second") < context.rendered.index("First")


def test_context_defensively_deduplicates_ids() -> None:
    node = _node("Only", "content")

    context = build_context([node], [node.id, node.id], character_limit=1_000)

    assert context.node_ids == [node.id]
    assert len(context.snapshot) == 1

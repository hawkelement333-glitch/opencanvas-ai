"""Preserve immutable identifiers required by original-context reruns.

Revision ID: 20260721_0006
Revises: 20260718_0005
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_0006"
down_revision: str | None = "20260718_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_execution_nodes", sa.Column("node_id_snapshot", sa.Uuid(), nullable=True))
    op.add_column("ai_execution_nodes", sa.Column("document_id_snapshot", sa.Uuid(), nullable=True))
    op.execute(sa.text("UPDATE ai_execution_nodes SET node_id_snapshot = node_id"))
    op.execute(sa.text("UPDATE ai_execution_nodes SET document_id_snapshot = document_id"))
    op.create_index(
        "ix_ai_execution_nodes_node_id_snapshot",
        "ai_execution_nodes",
        ["node_id_snapshot"],
    )
    op.create_index(
        "ix_ai_execution_nodes_document_id_snapshot",
        "ai_execution_nodes",
        ["document_id_snapshot"],
    )

    op.add_column("ai_execution_chunks", sa.Column("chunk_id_snapshot", sa.Uuid(), nullable=True))
    op.add_column(
        "ai_execution_chunks", sa.Column("document_id_snapshot", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "ai_execution_chunks",
        sa.Column("chunk_index_snapshot", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(sa.text("UPDATE ai_execution_chunks SET chunk_id_snapshot = chunk_id"))
    op.execute(sa.text("UPDATE ai_execution_chunks SET document_id_snapshot = document_id"))
    op.create_index(
        "ix_ai_execution_chunks_chunk_id_snapshot",
        "ai_execution_chunks",
        ["chunk_id_snapshot"],
    )
    op.create_index(
        "ix_ai_execution_chunks_document_id_snapshot",
        "ai_execution_chunks",
        ["document_id_snapshot"],
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ai_execution_chunks", recreate="always") as batch:
            batch.create_check_constraint(
                "ck_ai_execution_chunks_index_nonnegative", "chunk_index_snapshot >= 0"
            )
    else:
        op.create_check_constraint(
            "ck_ai_execution_chunks_index_nonnegative",
            "ai_execution_chunks",
            "chunk_index_snapshot >= 0",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("ai_execution_chunks", recreate="always") as batch:
            batch.drop_constraint("ck_ai_execution_chunks_index_nonnegative", type_="check")
            batch.drop_index("ix_ai_execution_chunks_document_id_snapshot")
            batch.drop_index("ix_ai_execution_chunks_chunk_id_snapshot")
            batch.drop_column("chunk_index_snapshot")
            batch.drop_column("document_id_snapshot")
            batch.drop_column("chunk_id_snapshot")
    else:
        op.drop_constraint(
            "ck_ai_execution_chunks_index_nonnegative", "ai_execution_chunks", type_="check"
        )
        op.drop_index(
            "ix_ai_execution_chunks_document_id_snapshot", table_name="ai_execution_chunks"
        )
        op.drop_index("ix_ai_execution_chunks_chunk_id_snapshot", table_name="ai_execution_chunks")
        op.drop_column("ai_execution_chunks", "chunk_index_snapshot")
        op.drop_column("ai_execution_chunks", "document_id_snapshot")
        op.drop_column("ai_execution_chunks", "chunk_id_snapshot")

    op.drop_index("ix_ai_execution_nodes_document_id_snapshot", table_name="ai_execution_nodes")
    op.drop_index("ix_ai_execution_nodes_node_id_snapshot", table_name="ai_execution_nodes")
    op.drop_column("ai_execution_nodes", "document_id_snapshot")
    op.drop_column("ai_execution_nodes", "node_id_snapshot")

"""Persist server-owned inputs for controlled prepared execution.

Revision ID: 20260724_0010
Revises: 20260723_0009
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260724_0010"
down_revision: str | None = "20260723_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "controlled_agent_request_identities"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("instruction", sa.Text(), nullable=True))
        batch.add_column(sa.Column("client_request_id", sa.String(length=128), nullable=True))
    op.execute(sa.text(f"UPDATE {TABLE} SET instruction = 'Create a grounded draft from the selected evidence.' WHERE instruction IS NULL"))
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("instruction", nullable=False)


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("client_request_id")
        batch.drop_column("instruction")

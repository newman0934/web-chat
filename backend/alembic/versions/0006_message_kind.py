"""messages.kind ('user'|'system')

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="user"),
    )


def downgrade() -> None:
    op.drop_column("messages", "kind")

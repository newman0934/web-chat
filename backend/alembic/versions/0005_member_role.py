"""conversation_members.role + backfill group creators as admin

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversation_members",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
    )
    # 群組建立者回填為 admin（關聯 conversations.creator_id == members.user_id）
    op.execute(
        """
        UPDATE conversation_members
        SET role='admin'
        WHERE conversation_id IN (
            SELECT id FROM conversations
            WHERE type='group' AND creator_id = conversation_members.user_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("conversation_members", "role")

"""messages.pinned_at（訊息置頂）+ (conversation_id, pinned_at) 索引

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_messages_conversation_pinned"


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    # 取對話釘選清單 / 計數:以 (conversation_id, pinned_at) 過濾。
    op.create_index(INDEX_NAME, "messages", ["conversation_id", "pinned_at"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="messages")
    op.drop_column("messages", "pinned_at")

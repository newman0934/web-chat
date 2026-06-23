"""message_reads.user_id 索引(加速 unread_count / mark_read 的 user_id 過濾)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 與 model 端 index=True 產生的預設名一致(ix_<table>_<column>)。
INDEX_NAME = "ix_message_reads_user_id"


def upgrade() -> None:
    op.create_index(INDEX_NAME, "message_reads", ["user_id"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="message_reads")

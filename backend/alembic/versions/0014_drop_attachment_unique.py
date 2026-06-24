"""attachments 改一對多:移除 message_id 唯一約束,改普通索引

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_attachments_message_id"


def upgrade() -> None:
    # 多附件:加 position(同訊息內排序);移除 message_id 唯一約束、改普通索引。
    # SQLite 不支援直接 DROP CONSTRAINT,用 batch 重建表。
    with op.batch_alter_table("attachments") as batch:
        batch.add_column(
            sa.Column("position", sa.Integer(), nullable=False, server_default="0")
        )
        batch.drop_constraint("uq_attachment_message", type_="unique")
        batch.create_index(INDEX_NAME, ["message_id"])


def downgrade() -> None:
    with op.batch_alter_table("attachments") as batch:
        batch.drop_index(INDEX_NAME)
        batch.create_unique_constraint("uq_attachment_message", ["message_id"])
        batch.drop_column("position")

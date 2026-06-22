"""reply_forward 欄位新增

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("reply_to_message_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("forwarded_from_user_id", sa.Uuid(), nullable=True))
        b.create_foreign_key(
            "fk_messages_reply_to_message_id",
            "messages",
            ["reply_to_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        b.create_foreign_key(
            "fk_messages_forwarded_from_user_id",
            "users",
            ["forwarded_from_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        b.create_index("ix_messages_reply_to_message_id", ["reply_to_message_id"])


def downgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.drop_index("ix_messages_reply_to_message_id")
        b.drop_constraint("fk_messages_forwarded_from_user_id", type_="foreignkey")
        b.drop_constraint("fk_messages_reply_to_message_id", type_="foreignkey")
        b.drop_column("forwarded_from_user_id")
        b.drop_column("reply_to_message_id")

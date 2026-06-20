"""group chat: unified conversations, members, message reads

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 新欄位（先可為 NULL，搬移後再視需要約束）
    with op.batch_alter_table("conversations") as b:
        b.add_column(sa.Column("type", sa.String(16), nullable=False, server_default="direct"))
        b.add_column(sa.Column("name", sa.String(100), nullable=True))
        b.add_column(sa.Column("creator_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("direct_key", sa.String(80), nullable=True))

    # 2) 新表
    op.create_table(
        "conversation_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conv_member"),
    )
    op.create_index(op.f("ix_conversation_members_conversation_id"), "conversation_members", ["conversation_id"])
    op.create_index(op.f("ix_conversation_members_user_id"), "conversation_members", ["user_id"])

    op.create_table(
        "message_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_read"),
    )
    op.create_index(op.f("ix_message_reads_message_id"), "message_reads", ["message_id"])

    # 3) 資料搬移
    conn = op.get_bind()
    convs = conn.execute(sa.text(
        "SELECT id, user_a_id, user_b_id FROM conversations"
    )).fetchall()
    for cid, a, b in convs:
        # 正規化成帶連字號的標準 UUID 字串，與 app 的 direct_key() 一致；
        # SQLite 把 Uuid 存成 32 字元 hex（無連字號），若不正規化會與 app 算出的 key 不符，
        # 導致遷移後 app 找不到舊對話而重複建立。
        a_s, b_s = sorted([str(uuid.UUID(str(a))), str(uuid.UUID(str(b)))])
        conn.execute(
            sa.text("UPDATE conversations SET type='direct', direct_key=:k WHERE id=:i"),
            {"k": f"{a_s}:{b_s}", "i": cid},
        )
        for uid in (a, b):
            conn.execute(
                sa.text(
                    "INSERT INTO conversation_members (id, conversation_id, user_id) "
                    "VALUES (:id, :c, :u)"
                ),
                {"id": _uuid(), "c": cid, "u": uid},
            )
    # read_at → message_reads（reader = 非寄件人那位成員）
    msgs = conn.execute(sa.text(
        "SELECT m.id, m.conversation_id, m.sender_id, m.read_at, "
        "c.user_a_id, c.user_b_id FROM messages m "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.read_at IS NOT NULL"
    )).fetchall()
    for mid, _c, sender, read_at, a, b in msgs:
        reader = b if str(sender) == str(a) else a
        conn.execute(
            sa.text(
                "INSERT INTO message_reads (id, message_id, user_id, read_at) "
                "VALUES (:id, :m, :u, :r)"
            ),
            {"id": _uuid(), "m": mid, "u": reader, "r": read_at},
        )

    # 4) 移除舊欄位 / 約束
    with op.batch_alter_table("conversations") as b:
        b.drop_constraint("uq_conversation_pair", type_="unique")
        b.create_unique_constraint("uq_conversation_direct_key", ["direct_key"])
        b.drop_column("user_a_id")
        b.drop_column("user_b_id")
    with op.batch_alter_table("messages") as b:
        b.drop_column("read_at")


def downgrade() -> None:
    raise NotImplementedError("0002 為破壞性遷移，不提供 downgrade")


def _uuid() -> str:
    import uuid
    return str(uuid.uuid4())

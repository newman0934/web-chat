"""全域訊息搜尋:跨「我為成員的對話」以子字串(LIKE)比對內容或寄件者名。

比對用 `lower(col) LIKE lower(:pattern) ESCAPE '\\'`,中文不需斷詞、SQLite 與 Postgres
行為一致(見 spec NFR-1)。關鍵字的 LIKE 萬用字元 `% _ \\` 一律逸出,當一般字元比對。
"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, ConversationMember, Message, User
from app.schemas import (
    ConversationRefOut,
    SearchResponseOut,
    SearchResultOut,
    UserOut,
)
from app.services.conversation_serializers import serialize_messages_out
from app.timeutils import coerce_cursor


def escape_like(term: str) -> str:
    """逸出 LIKE 萬用字元,讓 `% _ \\` 當一般字元比對(先逸出反斜線本身)。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _build_conversation_refs(
    db: AsyncSession, conv_ids: list, me_id
) -> dict:
    """批次組各對話的 ConversationRefOut(direct 帶對方;group 帶 name)。不逐筆查詢。"""
    if not conv_ids:
        return {}
    convs = (
        await db.execute(select(Conversation).where(Conversation.id.in_(conv_ids)))
    ).scalars().all()
    mrows = (
        await db.execute(
            select(ConversationMember.conversation_id, ConversationMember.user_id).where(
                ConversationMember.conversation_id.in_(conv_ids)
            )
        )
    ).all()
    members_by_conv: dict = {}
    user_ids: set = set()
    for cid, uid in mrows:
        members_by_conv.setdefault(cid, []).append(uid)
        user_ids.add(uid)
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
    }
    refs: dict = {}
    for c in convs:
        other = None
        if c.type == "direct":
            oid = next(
                (uid for uid in members_by_conv.get(c.id, []) if uid != me_id), None
            )
            other = users.get(oid) if oid else None
        refs[c.id] = ConversationRefOut(
            id=c.id,
            type=c.type,
            name=c.name,
            other_user=UserOut.model_validate(other) if other else None,
        )
    return refs


async def search_messages(
    db: AsyncSession,
    me_id,
    q: str,
    before: datetime | None,
    limit: int,
) -> SearchResponseOut:
    """跨我的對話搜尋訊息。回傳 SearchResponseOut(items + next_before)。"""
    pattern = f"%{escape_like(q).lower()}%"
    my_convs = select(ConversationMember.conversation_id).where(
        ConversationMember.user_id == me_id
    )
    cond = or_(
        func.lower(Message.content).like(pattern, escape="\\"),
        func.lower(User.display_name).like(pattern, escape="\\"),
    )
    stmt = (
        select(Message)
        .join(User, User.id == Message.sender_id)
        .where(
            Message.conversation_id.in_(my_convs),
            Message.deleted_at.is_(None),
            cond,
        )
    )
    before = coerce_cursor(db, before)
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    stmt = stmt.order_by(Message.created_at.desc()).limit(limit)

    messages = list((await db.execute(stmt)).scalars().all())
    message_outs = await serialize_messages_out(db, messages)
    refs = await _build_conversation_refs(
        db, list({m.conversation_id for m in messages}), me_id
    )
    items = [
        SearchResultOut(message=mo, conversation=refs[m.conversation_id])
        for m, mo in zip(messages, message_outs)
    ]
    # 滿筆 → 給下一頁 cursor(最後一筆 created_at);未滿 → 無更多。
    next_before = messages[-1].created_at if len(messages) == limit else None
    return SearchResponseOut(items=items, next_before=next_before)

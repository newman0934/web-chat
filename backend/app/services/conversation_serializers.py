"""對話 / 訊息 → REST schema 的序列化（ConversationOut / MessageOut）。

與查詢 helper（services.conversations）分層:這裡只負責「組 schema」,查詢都委派過去。
schemas 不 import 任何 app.* → 此處可安全用頂層 import(無循環)。
WS 端 ws/serializers.py 對 serialize_message_out 的結果 model_dump,與 REST 共用同一份外型。
"""

import uuid

from sqlalchemy import func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Attachment,
    Conversation,
    ConversationMember,
    Message,
    MessageRead,
    Reaction,
    User,
)
from app.schemas import (
    AttachmentOut,
    ConversationOut,
    ForwardedFromOut,
    MessageOut,
    ReactionGroupOut,
    ReplyPreviewOut,
    UserOut,
)
from app.services.conversations import (
    build_forwarded_from,
    build_reply_preview,
    get_attachments_for_message,
    get_member_ids,
    get_reaction_groups,
    get_role_map,
    read_count,
    unread_count,
)


async def serialize_message_out(
    db: AsyncSession, m: Message, read_count_value: int | None = None
):
    """把一則 Message 組成 MessageOut（含附件、表情、回覆/轉發預覽）。

    REST 與 WS 共用此單一真相（WS 端再 model_dump(mode="json")）。
    read_count_value 給定時直接採用（如剛送出的新訊息固定為 0，省一次查詢）；None 則查詢。
    """
    deleted = m.deleted_at is not None
    recalled = m.recalled_at is not None
    masked = deleted or recalled  # 已刪除或已撤回:內容/附件/表情一律遮蔽
    atts = [] if masked else await get_attachments_for_message(db, m.id)
    groups = [] if masked else await get_reaction_groups(db, m.id)
    # reply_to / forwarded_from:helper 回傳的 dict 內 uuid 欄位保留原生 uuid.UUID;
    # Pydantic 可直接用 uuid.UUID 填入 uuid 欄位。
    reply_to_d = await build_reply_preview(db, m)
    forwarded_from_d = await build_forwarded_from(db, m)
    rc = read_count_value if read_count_value is not None else await read_count(db, m.id)
    return MessageOut(
        id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
        content="" if masked else m.content, created_at=m.created_at,
        read_count=rc,
        attachments=[AttachmentOut.model_validate(a) for a in atts],
        edited_at=m.edited_at,
        deleted=deleted,
        deleted_at=m.deleted_at,
        reactions=groups,
        kind=m.kind,
        pinned=m.pinned_at is not None,
        recalled=recalled,
        reply_to=ReplyPreviewOut(**reply_to_d) if reply_to_d else None,
        forwarded_from=ForwardedFromOut(**forwarded_from_d) if forwarded_from_d else None,
    )


async def serialize_messages_out(db: AsyncSession, messages: list[Message]):
    """批次版:把一頁 Message 一次組成 MessageOut[]，查詢數固定(不隨訊息數成長)。

    取代「逐則各跑 ~3-6 個查詢」的 N+1(附件 / 表情 / 已讀數 / 回覆預覽 / 轉發來源),
    各只一次。輸出與逐則 serialize_message_out 等價(見 test_messages_batch;表情分組順序
    與逐則版一樣不保證,比較時正規化)。
    """
    if not messages:
        return []
    ids = [m.id for m in messages]
    live_ids = [m.id for m in messages if m.deleted_at is None]
    reply_ids = list({m.reply_to_message_id for m in messages if m.reply_to_message_id is not None})
    fwd_ids = list({m.forwarded_from_user_id for m in messages if m.forwarded_from_user_id is not None})

    # 附件:本頁(非刪)訊息的(供 attachments 欄位)+ 被回覆訊息的(供 reply 預覽 has_attachment)。
    # 一則可有多個附件 → 依 message_id 分組成 list,依 created_at/id 保序(近似送出順序)。
    att_msg_ids = set(live_ids) | set(reply_ids)
    atts_by_msg: dict = {}
    if att_msg_ids:
        arows = (await db.execute(
            select(Attachment)
            .where(Attachment.message_id.in_(att_msg_ids))
            .order_by(Attachment.position, Attachment.id)
        )).scalars().all()
        for a in arows:
            atts_by_msg.setdefault(a.message_id, []).append(a)

    # 表情:本頁非刪訊息,依 message_id 再依 emoji 分組(保留 first-seen 順序,與逐則一致)。
    reactions_by_msg: dict = {}
    if live_ids:
        rrows = (await db.execute(
            select(Reaction.message_id, Reaction.emoji, Reaction.user_id)
            .where(Reaction.message_id.in_(live_ids))
        )).all()
        tmp: dict = {}
        for mid, emoji, uid in rrows:
            tmp.setdefault(mid, {}).setdefault(emoji, []).append(uid)
        reactions_by_msg = {
            mid: [ReactionGroupOut(emoji=e, count=len(us), user_ids=us) for e, us in by_emoji.items()]
            for mid, by_emoji in tmp.items()
        }

    # 已讀數:本頁全部(一次 group by)。
    rc_by_msg: dict = {}
    if ids:
        rc_rows = (await db.execute(
            select(MessageRead.message_id, func.count())
            .where(MessageRead.message_id.in_(ids))
            .group_by(MessageRead.message_id)
        )).all()
        rc_by_msg = {mid: cnt for mid, cnt in rc_rows}

    # 被回覆訊息 / 轉發來源使用者。
    reply_msgs: dict = {}
    if reply_ids:
        reply_msgs = {
            r.id: r for r in
            (await db.execute(select(Message).where(Message.id.in_(reply_ids)))).scalars().all()
        }
    fwd_users: dict = {}
    if fwd_ids:
        fwd_users = {
            u.id: u for u in
            (await db.execute(select(User).where(User.id.in_(fwd_ids)))).scalars().all()
        }

    out = []
    for m in messages:
        deleted = m.deleted_at is not None
        recalled = m.recalled_at is not None
        masked = deleted or recalled
        atts = [] if masked else atts_by_msg.get(m.id, [])
        groups = [] if masked else reactions_by_msg.get(m.id, [])
        reply_to_d = None
        if m.reply_to_message_id is not None:
            orig = reply_msgs.get(m.reply_to_message_id)
            if orig is not None:
                # 被回覆原訊息若已刪除或已撤回,引用塊一律遮蔽。
                odel = orig.deleted_at is not None or orig.recalled_at is not None
                reply_to_d = {
                    "id": orig.id,
                    "sender_id": orig.sender_id,
                    "content": "" if odel else orig.content,
                    "deleted": odel,
                    "has_attachment": (not odel) and bool(atts_by_msg.get(orig.id)),
                }
        forwarded_from_d = None
        if m.forwarded_from_user_id is not None:
            u = fwd_users.get(m.forwarded_from_user_id)
            if u is not None:
                forwarded_from_d = {"id": u.id, "display_name": u.display_name}
        out.append(MessageOut(
            id=m.id, conversation_id=m.conversation_id, sender_id=m.sender_id,
            content="" if masked else m.content, created_at=m.created_at,
            read_count=rc_by_msg.get(m.id, 0),
            attachments=[AttachmentOut.model_validate(a) for a in atts],
            edited_at=m.edited_at,
            deleted=deleted,
            deleted_at=m.deleted_at,
            reactions=groups,
            kind=m.kind,
            pinned=m.pinned_at is not None,
            recalled=recalled,
            reply_to=ReplyPreviewOut(**reply_to_d) if reply_to_d else None,
            forwarded_from=ForwardedFromOut(**forwarded_from_d) if forwarded_from_d else None,
        ))
    return out


def _conv_last_message_out(last: Message, read_count_value: int):
    """對話清單預覽用的 last_message（刻意精簡:不帶 attachment / reactions / reply / edited_at）。

    單一真相,供 serialize_conversation_out 與 serialize_conversations_out 共用,避免兩處外型分歧。
    """
    is_deleted = last.deleted_at is not None
    return MessageOut(
        id=last.id, conversation_id=last.conversation_id, sender_id=last.sender_id,
        content="" if is_deleted else last.content, created_at=last.created_at,
        read_count=read_count_value,
        deleted=is_deleted,
        deleted_at=last.deleted_at,
        kind=last.kind,
    )


async def serialize_conversation_out(db: AsyncSession, conv: Conversation, me: User):
    """把一個 Conversation 組成 REST 的 ConversationOut（成員、對方、最後訊息、未讀數、角色）。"""
    member_ids = await get_member_ids(db, conv.id)
    # 一次撈齊成員（取代逐一 db.get 的 N+1），再依 member_ids 原順序還原。
    rows = await db.execute(select(User).where(User.id.in_(member_ids)))
    by_id = {u.id: u for u in rows.scalars().all()}
    members = [by_id[uid] for uid in member_ids if uid in by_id]
    other = None
    if conv.type == "direct":
        other = next((u for u in members if u.id != me.id), None)

    last_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last = last_res.scalar_one_or_none()
    last_out = _conv_last_message_out(last, await read_count(db, last.id)) if last is not None else None

    roles = await get_role_map(db, conv.id)
    return ConversationOut(
        id=conv.id,
        type=conv.type,
        name=conv.name,
        other_user=UserOut.model_validate(other) if other else None,
        members=[UserOut.model_validate(u) for u in members],
        last_message=last_out,
        unread_count=await unread_count(db, conv.id, me.id),
        roles=roles,
    )


async def serialize_conversations_out(db: AsyncSession, convs: list[Conversation], me: User):
    """批次版:把多個 Conversation 一次組成 ConversationOut[]，查詢數固定(不隨對話數成長)。

    取代「逐對話各跑 ~6 個查詢」的 N+1：成員/角色、使用者、最後訊息、最後訊息已讀數、
    未讀數各只一次。輸出與逐筆 serialize_conversation_out 等價(見 test_conversations_batch)。
    """
    if not convs:
        return []
    conv_ids = [c.id for c in convs]

    # Q1:全部成員 + 角色(一次)。
    mrows = (await db.execute(
        select(
            ConversationMember.conversation_id,
            ConversationMember.user_id,
            ConversationMember.role,
        ).where(ConversationMember.conversation_id.in_(conv_ids))
    )).all()
    members_by_conv: dict[uuid.UUID, list[uuid.UUID]] = {}
    roles_by_conv: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    user_ids: set[uuid.UUID] = set()
    for cid, uid, role in mrows:
        members_by_conv.setdefault(cid, []).append(uid)
        roles_by_conv.setdefault(cid, {})[uid] = role
        user_ids.add(uid)

    # Q2:全部成員 User(一次)。
    urows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    user_by_id = {u.id: u for u in urows}

    # Q3:每對話最後一則訊息(window function 取 partition 內 created_at 最新者,一次)。
    rn = func.row_number().over(
        partition_by=Message.conversation_id,
        order_by=Message.created_at.desc(),
    ).label("rn")
    sub = select(Message.id, Message.conversation_id, rn).where(
        Message.conversation_id.in_(conv_ids)
    ).subquery()
    last_ids = (await db.execute(select(sub.c.id).where(sub.c.rn == 1))).scalars().all()
    last_by_conv: dict[uuid.UUID, Message] = {}
    read_count_by_msg: dict[uuid.UUID, int] = {}
    if last_ids:
        last_msgs = (await db.execute(
            select(Message).where(Message.id.in_(last_ids))
        )).scalars().all()
        last_by_conv = {m.conversation_id: m for m in last_msgs}
        # Q4:這些最後訊息的已讀數(一次 group by)。
        rc_rows = (await db.execute(
            select(MessageRead.message_id, func.count())
            .where(MessageRead.message_id.in_(last_ids))
            .group_by(MessageRead.message_id)
        )).all()
        read_count_by_msg = {mid: cnt for mid, cnt in rc_rows}

    # Q5:每對話未讀數(一次 group by;與 unread_count() 同條件:非自己送、且自己未讀)。
    read_subq = select(MessageRead.message_id).where(MessageRead.user_id == me.id)
    ur_rows = (await db.execute(
        select(Message.conversation_id, func.count())
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.sender_id != me.id,
            not_(Message.id.in_(read_subq)),
        )
        .group_by(Message.conversation_id)
    )).all()
    unread_by_conv = {cid: cnt for cid, cnt in ur_rows}

    out = []
    for c in convs:
        member_ids = members_by_conv.get(c.id, [])
        members = [user_by_id[uid] for uid in member_ids if uid in user_by_id]
        other = None
        if c.type == "direct":
            other = next((u for u in members if u.id != me.id), None)
        last = last_by_conv.get(c.id)
        last_out = (
            _conv_last_message_out(last, read_count_by_msg.get(last.id, 0))
            if last is not None else None
        )
        out.append(ConversationOut(
            id=c.id,
            type=c.type,
            name=c.name,
            other_user=UserOut.model_validate(other) if other else None,
            members=[UserOut.model_validate(u) for u in members],
            last_message=last_out,
            unread_count=unread_by_conv.get(c.id, 0),
            roles=roles_by_conv.get(c.id, {}),
        ))
    return out

"""WS 訊息序列化：把 ORM Message 組成 JSON-ready dict（server→client 用）。

刻意手組 dict（而非走 REST 的 MessageOut）以保留 WS 既有外型；uuid 一律轉 str。
"""

from sqlalchemy import select

from app.models import Attachment, Message
from app.schemas import AttachmentOut
from app.services.conversations import (
    build_forwarded_from,
    build_reply_preview,
    get_reaction_groups,
)
from app.timeutils import to_utc_iso


def _stringify_uuid_dict(d: dict | None, uuid_keys: list[str]) -> dict | None:
    """把 dict 中指定的 uuid 欄位轉為 str，回傳新 dict（原 dict 不變）。

    Helper for WS path: helpers return native uuid.UUID; WS needs str for JSON.
    """
    if d is None:
        return None
    result = dict(d)
    for k in uuid_keys:
        if k in result and result[k] is not None:
            result[k] = str(result[k])
    return result


async def serialize_message(db, msg: Message, read_count: int = 0) -> dict:
    deleted = msg.deleted_at is not None
    attachment = None
    if not deleted:
        att_res = await db.execute(select(Attachment).where(Attachment.message_id == msg.id))
        attachment = att_res.scalar_one_or_none()
    groups = [] if deleted else await get_reaction_groups(db, msg.id)

    # reply_to / forwarded_from: helpers return uuid.UUID; stringify for WS JSON.
    reply_to_raw = await build_reply_preview(db, msg)
    forwarded_from_raw = await build_forwarded_from(db, msg)
    reply_to = _stringify_uuid_dict(reply_to_raw, ["id", "sender_id"])
    forwarded_from = _stringify_uuid_dict(forwarded_from_raw, ["id"])

    return {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "sender_id": str(msg.sender_id),
        "content": "" if deleted else msg.content,
        "created_at": to_utc_iso(msg.created_at),
        "read_count": read_count,
        "attachment": (
            AttachmentOut.model_validate(attachment).model_dump(mode="json")
            if attachment else None
        ),
        "edited_at": to_utc_iso(msg.edited_at),
        "deleted": deleted,
        "deleted_at": to_utc_iso(msg.deleted_at),
        "reactions": [g.model_dump(mode="json") for g in groups],
        "kind": msg.kind,
        "reply_to": reply_to,
        "forwarded_from": forwarded_from,
    }

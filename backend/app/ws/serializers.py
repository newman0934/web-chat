"""WS 訊息序列化：把 ORM Message 組成 JSON-ready dict（server→client 用）。

與 REST 共用單一真相：直接用 services.serialize_message_out 組出 MessageOut，再
model_dump(mode="json")（uuid→str、datetime→tz-aware UTC ISO）。如此 WS 與 REST 的訊息
外型永遠一致，改欄位只需動 schemas.MessageOut 一處。
"""

from app.models import Message
from app.services.conversation_serializers import serialize_message_out


async def serialize_message(db, msg: Message, read_count: int = 0) -> dict:
    """WS 推播用的訊息 dict。read_count 由呼叫端帶入（新訊息固定 0；更新則先算好）。"""
    out = await serialize_message_out(db, msg, read_count)
    return out.model_dump(mode="json")

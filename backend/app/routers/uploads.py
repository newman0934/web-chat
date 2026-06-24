"""檔案上傳與下載：存後端本機檔案系統，下載做對話成員權限檢查。"""

import uuid
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, resolve_user_from_token
from app.db import get_db
from app.models import Attachment, Message, User
from app.schemas import AttachmentOut
from app.services.conversations import get_conversation_for_member
from app.storage import make_stored_name, save_bytes, stored_path

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024


def _content_disposition(filename: str) -> str:
    """組 attachment 的 Content-Disposition。

    HTTP header 值只能是 latin-1,非 ASCII 檔名(如中文)直接放 `filename="..."` 會在
    送出時 UnicodeEncodeError → 下載 500。依 RFC 6266 同時給:
    - `filename=`：ASCII fallback(丟掉非 ASCII 字元,供舊客戶端)
    - `filename*=UTF-8''…`：百分比編碼的 UTF-8 原名(現代瀏覽器優先採用)
    """
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "_")
    ascii_fallback = ascii_fallback or "file"  # 全非 ASCII 時給個保底名
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@router.post("/uploads", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 宣告大小(Content-Length，若有)就先擋掉,連讀都不必。
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="檔案過大（上限 10MB）")
    # 分塊讀取並累計;一超過上限就中止,避免把可能超大(或宣告大小造假)的檔案整個載入記憶體。
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="檔案過大（上限 10MB）")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=400, detail="空檔案")

    content_type = file.content_type or "application/octet-stream"
    original_name = file.filename or "file"
    stored = make_stored_name(original_name)
    save_bytes(stored, data)

    att = Attachment(
        uploader_id=current_user.id,
        message_id=None,
        stored_name=stored,
        original_name=original_name,
        content_type=content_type,
        size=len(data),
        is_image=content_type.startswith("image/"),
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    return att


async def _resolve_user(
    db: AsyncSession, token: str | None, authorization: str | None
) -> User | None:
    """下載端點:token 可走 query(?token=)或 Authorization header;取出 raw 後交共用解析。"""
    raw = token
    if raw is None and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    return await resolve_user_from_token(db, raw)


@router.get("/attachments/{attachment_id}")
async def download(
    attachment_id: uuid.UUID,
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    user = await _resolve_user(db, token, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="未授權")

    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="查無附件")

    # 權限：孤兒附件僅上傳者；已綁定附件須為該對話成員。
    if att.message_id is None:
        if att.uploader_id != user.id:
            raise HTTPException(status_code=404, detail="查無附件")
    else:
        msg = await db.get(Message, att.message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="查無附件")
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="查無附件")

    path = stored_path(att.stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="檔案不存在")

    # 圖片內嵌顯示;其他檔案以附件下載(檔名走 RFC 6266,支援中文等非 ASCII)。
    disposition = "inline" if att.is_image else _content_disposition(att.original_name)
    return FileResponse(
        path,
        media_type=att.content_type,
        headers={"Content-Disposition": disposition},
    )

"""檔案上傳與下載：存後端本機檔案系統，下載做對話成員權限檢查。"""

import uuid

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

from app.auth.deps import get_current_user
from app.auth.security import decode_access_token
from app.db import get_db
from app.models import Attachment, Message, User
from app.schemas import AttachmentOut
from app.services.conversations import get_conversation_for_member
from app.storage import make_stored_name, save_bytes, stored_path

router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/uploads", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空檔案")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="檔案過大（上限 10MB）")

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
    raw = token
    if raw is None and authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    if not raw:
        return None
    sub = decode_access_token(raw)
    if sub is None:
        return None
    try:
        uid = uuid.UUID(sub)
    except ValueError:
        return None
    return await db.get(User, uid)


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
        conv = await get_conversation_for_member(db, msg.conversation_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="查無附件")

    path = stored_path(att.stored_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail="檔案不存在")

    if att.is_image:
        disposition = "inline"
    else:
        disposition = f'attachment; filename="{att.original_name}"'
    return FileResponse(
        path,
        media_type=att.content_type,
        headers={"Content-Disposition": disposition},
    )

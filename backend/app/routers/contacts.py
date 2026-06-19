"""好友清單與加好友。加好友同時確保兩人之間的對話存在。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Contact, User
from app.schemas import AddContactRequest, ContactOut
from app.services.conversations import get_or_create_direct_conversation

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 透過 Contact 表 join 出「我的好友」對應的 User。
    result = await db.execute(
        select(User)
        .join(Contact, Contact.contact_user_id == User.id)
        .where(Contact.user_id == current_user.id)
        .order_by(User.display_name)
    )
    others = result.scalars().all()

    out: list[ContactOut] = []
    for other in others:
        # 一併帶上對話 id，前端點好友即可直接進對話（不存在就建立）。
        conv = await get_or_create_direct_conversation(db, current_user.id, other.id)
        out.append(
            ContactOut(
                user_id=other.id,
                email=other.email,
                display_name=other.display_name,
                conversation_id=conv.id,
            )
        )
    await db.commit()
    return out


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def add_contact(
    payload: AddContactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.email == current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="不能加自己為好友"
        )

    # 用 email 找對方；不存在回 404。
    result = await db.execute(select(User).where(User.email == payload.email))
    other = result.scalar_one_or_none()
    if other is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="查無此 email 的使用者"
        )

    # 已是好友回 409（只需檢查單向，因為加好友一律成對建立）。
    dup = await db.execute(
        select(Contact).where(
            Contact.user_id == current_user.id,
            Contact.contact_user_id == other.id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="已經是好友了"
        )

    # 雙向好友關係
    db.add(Contact(user_id=current_user.id, contact_user_id=other.id))
    db.add(Contact(user_id=other.id, contact_user_id=current_user.id))
    conv = await get_or_create_direct_conversation(db, current_user.id, other.id)
    await db.commit()

    return ContactOut(
        user_id=other.id,
        email=other.email,
        display_name=other.display_name,
        conversation_id=conv.id,
    )

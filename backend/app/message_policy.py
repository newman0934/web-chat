"""訊息動作的時窗與驗證常數（WS 端點共用；前端 contracts 另有同份時窗）。"""

import re
from datetime import timedelta

EDIT_WINDOW = timedelta(minutes=15)
RESTORE_WINDOW = timedelta(minutes=5)

_DISALLOWED_IN_EMOJI = re.compile(r"[A-Za-z0-9\s]")


def is_valid_reaction_emoji(value) -> bool:
    """是否為單一 emoji：strip 後非空、≤ 8 Unicode 字元、不含 ASCII 英數/空白。

    用形狀驗證取代固定白名單：擋住任意文字塞入，但允許白名單外的真 emoji。
    """
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s or len(s) > 2:
        return False
    return _DISALLOWED_IN_EMOJI.search(s) is None

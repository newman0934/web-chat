"""極簡的記憶體滑動視窗速率限制(單程序)。

與 presence 相同限制:存記憶體、單程序、不跨重啟;多 worker / 水平擴充需改用 Redis 之類
共享層。目前只用於「登入失敗次數」,降低暴力破解速度(成功登入不計入)。
"""

import time
from collections import defaultdict, deque

from app.config import get_settings


class SlidingWindowLimiter:
    """每個 key 在 window_seconds 內最多 max_events 次事件。"""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, dq: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()

    def allowed(self, key: str, *, now: float | None = None) -> bool:
        """視窗內事件數是否仍低於上限(只查、不記錄)。"""
        n = now if now is not None else time.monotonic()
        dq = self._events[key]
        self._prune(dq, n)
        return len(dq) < self.max_events

    def record(self, key: str, *, now: float | None = None) -> None:
        """記一次事件(如一次登入失敗)。"""
        n = now if now is not None else time.monotonic()
        dq = self._events[key]
        self._prune(dq, n)
        dq.append(n)

    def reset(self, key: str | None = None) -> None:
        """清空(測試用,或單一 key 解除)。"""
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)


# 登入失敗:每來源 IP 60 秒內最多 10 次,超過即回 429。
login_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60)

# 註冊:每來源 IP 每小時最多 N 個帳號(每次嘗試都計入),擋自動化大量建帳號。
# 上限與視窗可由設定/環境變數調整(E2E 同一 runner IP 會註冊大量帳號,需調高免誤擋)。
_settings = get_settings()
register_limiter = SlidingWindowLimiter(
    max_events=_settings.register_rate_limit_max,
    window_seconds=_settings.register_rate_limit_window_seconds,
)

"""滑動視窗速率限制純邏輯(注入 now,不依賴真實時間)。"""

from app.ratelimit import SlidingWindowLimiter


def test_allows_until_max_then_blocks():
    lim = SlidingWindowLimiter(max_events=3, window_seconds=60)
    for _ in range(3):
        assert lim.allowed("k", now=1000.0)
        lim.record("k", now=1000.0)
    assert lim.allowed("k", now=1000.0) is False  # 第 4 次被擋


def test_window_slides():
    lim = SlidingWindowLimiter(max_events=2, window_seconds=10)
    lim.record("k", now=100.0)
    lim.record("k", now=101.0)
    assert lim.allowed("k", now=105.0) is False  # 視窗內已 2 次 → 擋
    assert lim.allowed("k", now=112.0) is True   # 100/101 已滑出視窗 → 放行


def test_keys_isolated():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
    lim.record("a", now=1.0)
    assert lim.allowed("a", now=1.0) is False
    assert lim.allowed("b", now=1.0) is True  # 不同 key 互不影響


def test_reset():
    lim = SlidingWindowLimiter(max_events=1, window_seconds=60)
    lim.record("a", now=1.0)
    lim.reset("a")
    assert lim.allowed("a", now=1.0) is True
    lim.record("a", now=1.0)
    lim.record("b", now=1.0)
    lim.reset()  # 全清
    assert lim.allowed("a", now=1.0) and lim.allowed("b", now=1.0)

"""應用層 logging:一致格式 + HTTP 請求記錄。

刻意只記 request.url.path(不含 query string),避免把 ?token=... 之類敏感參數寫進 log
(下載 / WebSocket 會用 query token)。WebSocket 連線不經此 HTTP middleware。
"""

import logging
import time

from starlette.requests import Request

logger = logging.getLogger("chatweb")


def configure_logging(level: int = logging.INFO) -> None:
    """設定根 logger 的輸出格式與等級(供 uvicorn/正式環境一致輸出;已設定則不覆蓋)。"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger.setLevel(level)


async def log_requests(request: Request, call_next):
    """HTTP middleware:記 method / path(不含 query)/ status / 耗時(ms)。"""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

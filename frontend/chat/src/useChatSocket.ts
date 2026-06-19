// 管理與後端 /ws 的單一 WebSocket 連線：
// 自動連線、斷線指數退避重連、token 失效（1008）回呼，並提供 send()。
// 注意：開發模式 + React.StrictMode 會故意掛載兩次，因此 console 可能短暫出現
// 一條「connection closed before established」的紅字，屬正常現象（production 不會）。

import { useCallback, useEffect, useRef, useState } from 'react';

import type { ClientWsMessage, ServerWsMessage } from '../../contracts';

export type SocketStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface ChatSocketHandlers {
  onServerMessage: (msg: ServerWsMessage) => void;
  /** 重連成功後觸發，供元件用 REST 補齊期間遺漏的訊息。 */
  onReconnected?: () => void;
  /** token 失效（伺服器以 1008 關閉）時觸發。 */
  onUnauthorized?: () => void;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export interface ChatSocket {
  status: SocketStatus;
  send: (msg: ClientWsMessage) => boolean;
}

/** 管理 /ws 連線：自動重連、處理 1008 未授權，並提供 send()。 */
export function useChatSocket(
  wsBaseUrl: string,
  token: string,
  handlers: ChatSocketHandlers,
): ChatSocket {
  const [status, setStatus] = useState<SocketStatus>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef(handlers);
  const retriesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUnauthRef = useRef(false);
  const manuallyClosedRef = useRef(false);

  handlersRef.current = handlers;

  /** 建立 WebSocket 並註冊 open / message / close / error 處理。 */
  const connect = useCallback(() => {
    manuallyClosedRef.current = false;
    const url = `${wsBaseUrl}/ws?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setStatus(retriesRef.current > 0 ? 'reconnecting' : 'connecting');

    ws.onopen = () => {
      const wasReconnect = retriesRef.current > 0;
      retriesRef.current = 0;
      setStatus('open');
      if (wasReconnect) handlersRef.current.onReconnected?.();
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ServerWsMessage;
        handlersRef.current.onServerMessage(data);
      } catch {
        // 忽略無法解析的訊息
      }
    };

    ws.onclose = (event) => {
      wsRef.current = null;
      if (event.code === 1008) {
        closedByUnauthRef.current = true;
        setStatus('closed');
        handlersRef.current.onUnauthorized?.();
        return;
      }
      if (manuallyClosedRef.current) {
        setStatus('closed');
        return;
      }
      // 指數退避重連
      const delay = Math.min(
        BASE_BACKOFF_MS * 2 ** retriesRef.current,
        MAX_BACKOFF_MS,
      );
      retriesRef.current += 1;
      setStatus('reconnecting');
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [wsBaseUrl, token]);

  useEffect(() => {
    connect();
    return () => {
      manuallyClosedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  /** 若連線已 open 則送出 JSON；否則回傳 false 供呼叫端標記失敗。 */
  const send = useCallback((msg: ClientWsMessage): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(msg));
    return true;
  }, []);

  return { status, send };
}

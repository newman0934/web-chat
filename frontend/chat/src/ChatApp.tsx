// chat remote 對外暴露的主元件（由 shell 以 props 傳入 token / currentUser 等）。
// 職責：組裝 Sidebar + Thread，串接 REST（ApiClient）與 WebSocket（useChatSocket），
// 並以 messageStore 的純函式維護每個對話的訊息清單（含樂觀更新）。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ChatAppProps, Contact, Conversation, ServerWsMessage } from '../../contracts';
import { ApiClient, ApiError, UnauthorizedError } from './api';
import { Sidebar } from './components/Sidebar';
import { Thread } from './components/Thread';
import {
  addIncoming,
  addOptimistic,
  applyReadReceipt,
  fromHistory,
  makeOptimistic,
  markFailed,
  prependHistory,
  reconcileAck,
  type ChatMessage,
} from './messageStore';
import { useChatSocket } from './useChatSocket';

const PAGE_SIZE = 30;

/** chat remote 主元件：串 REST + WebSocket，管理對話與訊息狀態。 */
export default function ChatApp({
  token,
  currentUser,
  apiBaseUrl,
  wsBaseUrl,
  onLogout,
}: ChatAppProps) {
  const api = useMemo(
    () => new ApiClient(apiBaseUrl, token),
    [apiBaseUrl, token],
  );

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({});
  const [hasMore, setHasMore] = useState<Record<string, boolean>>({});
  const [contacts, setContacts] = useState<Contact[]>([]);

  const activeIdRef = useRef<string | null>(null);
  activeIdRef.current = activeId;

  /** 從後端拉對話清單；401 時觸發登出。 */
  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations());
    } catch (err) {
      if (err instanceof UnauthorizedError) onLogout();
    }
  }, [api, onLogout]);

  useEffect(() => {
    void loadConversations();
    void api.listContacts().then(setContacts).catch(() => {});
  }, [loadConversations, api]);

  // ---- WebSocket ----
  /** 分派 WebSocket 推播：ACK 對齊、新訊息、已讀、送訊失敗。 */
  const handleServerMessage = useCallback(
    (msg: ServerWsMessage) => {
      switch (msg.type) {
        case 'ack': {
          const convId = msg.message.conversation_id;
          setMessages((prev) => ({
            ...prev,
            [convId]: reconcileAck(prev[convId] ?? [], msg.temp_id, msg.message),
          }));
          break;
        }
        case 'message': {
          const convId = msg.message.conversation_id;
          setMessages((prev) => ({
            ...prev,
            [convId]: addIncoming(prev[convId] ?? [], msg.message),
          }));
          if (activeIdRef.current === convId) {
            socketRef.current?.send({ type: 'read', conversation_id: convId });
          }
          void loadConversations();
          break;
        }
        case 'read': {
          setMessages((prev) => {
            const list = prev[msg.conversation_id];
            if (!list) return prev;
            return {
              ...prev,
              [msg.conversation_id]: applyReadReceipt(list, msg.message_ids),
            };
          });
          break;
        }
        case 'error': {
          if (msg.temp_id) {
            setMessages((prev) => {
              const next = { ...prev };
              for (const [cid, list] of Object.entries(next)) {
                if (list.some((m) => m.temp_id === msg.temp_id)) {
                  next[cid] = markFailed(list, msg.temp_id!);
                }
              }
              return next;
            });
          }
          break;
        }
        default:
          break;
      }
    },
    [loadConversations],
  );

  const socket = useChatSocket(wsBaseUrl, token, {
    onServerMessage: handleServerMessage,
    /** WS 重連後用 REST 補齊對話清單與目前對話訊息。 */
    onReconnected: () => {
      void loadConversations();
      const active = activeIdRef.current;
      if (active) void refreshMessages(active);
    },
    /** token 失效（WS 1008）時登出。 */
    onUnauthorized: onLogout,
  });
  const socketRef = useRef(socket);
  socketRef.current = socket;

  // ---- 訊息載入 ----
  /** 載入（或重載）指定對話最近一頁歷史訊息。 */
  const refreshMessages = useCallback(
    async (conversationId: string) => {
      try {
        const history = await api.listMessages(conversationId, { limit: PAGE_SIZE });
        setMessages((prev) => ({ ...prev, [conversationId]: fromHistory(history) }));
        setHasMore((prev) => ({ ...prev, [conversationId]: history.length === PAGE_SIZE }));
      } catch (err) {
        if (err instanceof UnauthorizedError) onLogout();
      }
    },
    [api, onLogout],
  );

  /** 切換對話：必要時拉歷史、送 read 事件、清本地未讀數。 */
  const selectConversation = useCallback(
    async (conversationId: string) => {
      setActiveId(conversationId);
      if (!messages[conversationId]) {
        await refreshMessages(conversationId);
      }
      socketRef.current?.send({ type: 'read', conversation_id: conversationId });
      setConversations((prev) =>
        prev.map((c) =>
          c.id === conversationId ? { ...c, unread_count: 0 } : c,
        ),
      );
    },
    [messages, refreshMessages],
  );

  /** 向上分頁：以最早訊息的 created_at 為游標載入更早訊息。 */
  const loadMore = useCallback(async () => {
    if (!activeId) return;
    const list = messages[activeId] ?? [];
    const oldest = list[0];
    if (!oldest) return;
    try {
      const older = await api.listMessages(activeId, {
        before: oldest.created_at,
        limit: PAGE_SIZE,
      });
      setMessages((prev) => ({
        ...prev,
        [activeId]: prependHistory(prev[activeId] ?? [], older),
      }));
      setHasMore((prev) => ({ ...prev, [activeId]: older.length === PAGE_SIZE }));
    } catch (err) {
      if (err instanceof UnauthorizedError) onLogout();
    }
  }, [activeId, messages, api, onLogout]);

  // ---- 送訊息（樂觀更新） ----
  /** 樂觀送出訊息：先插入 UI，再經 WS 送出；連線不可用則標 failed。 */
  const sendMessage = useCallback(
    (content: string) => {
      if (!activeId) return;
      const tempId = crypto.randomUUID();
      const optimistic = makeOptimistic(activeId, currentUser.id, content, tempId);
      setMessages((prev) => ({
        ...prev,
        [activeId]: addOptimistic(prev[activeId] ?? [], optimistic),
      }));
      const ok = socketRef.current?.send({
        type: 'message',
        conversation_id: activeId,
        content,
        temp_id: tempId,
      });
      if (!ok) {
        setMessages((prev) => ({
          ...prev,
          [activeId]: markFailed(prev[activeId] ?? [], tempId),
        }));
      }
    },
    [activeId, currentUser.id],
  );

  /** 重送 failed 訊息：沿用原 temp_id 以便 ACK 對齊。 */
  const retry = useCallback(
    (tempId: string) => {
      if (!activeId) return;
      const list = messages[activeId] ?? [];
      const failed = list.find((m) => m.temp_id === tempId);
      if (!failed) return;
      setMessages((prev) => ({
        ...prev,
        [activeId]: (prev[activeId] ?? []).map((m) =>
          m.temp_id === tempId ? { ...m, status: 'sending' } : m,
        ),
      }));
      const ok = socketRef.current?.send({
        type: 'message',
        conversation_id: activeId,
        content: failed.content,
        temp_id: tempId,
      });
      if (!ok) {
        setMessages((prev) => ({
          ...prev,
          [activeId]: markFailed(prev[activeId] ?? [], tempId),
        }));
      }
    },
    [activeId, messages],
  );

  /** 加好友並刷新對話清單；回傳 null 表示成功，否則為錯誤訊息字串。 */
  const addContact = useCallback(
    async (email: string): Promise<string | null> => {
      try {
        await api.addContact(email);
        await loadConversations();
        return null;
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onLogout();
          return '憑證失效，請重新登入';
        }
        if (err instanceof ApiError) return err.message;
        return '加好友失敗';
      }
    },
    [api, loadConversations, onLogout],
  );

  /** 建立群組對話；回傳 null 表示成功，否則為錯誤訊息字串。 */
  const createGroup = useCallback(
    async (name: string, memberIds: string[]): Promise<string | null> => {
      try {
        const conv = await api.createGroup(name, memberIds);
        await loadConversations();
        setActiveId(conv.id);
        return null;
      } catch (err) {
        if (err instanceof UnauthorizedError) { onLogout(); return '憑證失效'; }
        if (err instanceof ApiError) return err.message;
        return '建立群組失敗';
      }
    },
    [api, loadConversations, onLogout],
  );

  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const isGroup = activeConv?.type === 'group';
  const memberNames = Object.fromEntries(
    (activeConv?.members ?? []).map((m) => [m.id, m.display_name]),
  );
  const title = activeConv
    ? (activeConv.type === 'group' ? activeConv.name ?? '群組' : activeConv.other_user?.display_name ?? '')
    : '';

  return (
    <div className="flex h-screen">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        currentUserName={currentUser.display_name}
        socketStatus={socket.status}
        contacts={contacts}
        onSelect={selectConversation}
        onAddContact={addContact}
        onCreateGroup={createGroup}
        onLogout={onLogout}
      />
      {activeId && activeConv ? (
        <Thread
          title={title}
          isGroup={isGroup}
          memberNames={memberNames}
          messages={messages[activeId] ?? []}
          currentUserId={currentUser.id}
          canLoadMore={hasMore[activeId] ?? false}
          onLoadMore={loadMore}
          onSend={sendMessage}
          onRetry={retry}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-slate-400">
          選擇一個對話開始聊天
        </div>
      )}
    </div>
  );
}

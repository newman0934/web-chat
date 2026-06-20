// chat remote 對外暴露的主元件（由 shell 以 props 傳入 token / currentUser 等）。
// 職責：組裝 Sidebar + Thread，串接 REST（ApiClient）與 WebSocket（useChatSocket）。
// 狀態集中在 zustand（useChatStore）；本元件只負責副作用（fetch / ws.send）與把 store 接到 UI。

import { useCallback, useEffect, useMemo, useRef } from 'react';

import type { ChatAppProps, ServerWsMessage } from '../../contracts';
import { ApiClient, ApiError, UnauthorizedError } from './api';
import { CallOverlay } from './components/CallOverlay';
import { Sidebar } from './components/Sidebar';
import { Thread } from './components/Thread';
import { useCall } from './useCall';
import { makeOptimistic } from './messageStore';
import { useChatStore } from './store';
import { useChatSocket } from './useChatSocket';

const PAGE_SIZE = 30;

/** chat remote 主元件：串 REST + WebSocket，狀態由 useChatStore 管理。 */
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

  // 從 store 訂閱要渲染的狀態；actions 為穩定參考，於 callback 內以 getState() 取用。
  const conversations = useChatStore((s) => s.conversations);
  const activeId = useChatStore((s) => s.activeId);
  const messages = useChatStore((s) => s.messages);
  const hasMore = useChatStore((s) => s.hasMore);
  const contacts = useChatStore((s) => s.contacts);

  /** 從後端拉對話清單；401 時觸發登出。 */
  const loadConversations = useCallback(async () => {
    try {
      useChatStore.getState().setConversations(await api.listConversations());
    } catch (err) {
      if (err instanceof UnauthorizedError) onLogout();
    }
  }, [api, onLogout]);

  // 切換 token（登入/換人）時重置 store，避免殘留上一位使用者的資料，再載入清單與好友。
  useEffect(() => {
    useChatStore.getState().reset();
    void loadConversations();
    void api
      .listContacts()
      .then((c) => useChatStore.getState().setContacts(c))
      .catch(() => {});
  }, [loadConversations, api]);

  // ---- 訊息載入 ----
  /** 載入（或重載）指定對話最近一頁歷史訊息。 */
  const refreshMessages = useCallback(
    async (conversationId: string) => {
      try {
        const history = await api.listMessages(conversationId, { limit: PAGE_SIZE });
        const st = useChatStore.getState();
        st.loadHistory(conversationId, history);
        st.setHasMore(conversationId, history.length === PAGE_SIZE);
      } catch (err) {
        if (err instanceof UnauthorizedError) onLogout();
      }
    },
    [api, onLogout],
  );

  // ---- WebSocket ----
  /** 分派 WebSocket 推播：ACK 對齊、新訊息、已讀、送訊失敗。 */
  const handleServerMessage = useCallback(
    (msg: ServerWsMessage) => {
      const st = useChatStore.getState();
      switch (msg.type) {
        case 'ack':
          st.ackMessage(msg.temp_id, msg.message);
          break;
        case 'message':
          st.receiveMessage(msg.message);
          // 若正開著該對話，立刻回報已讀。
          if (st.activeId === msg.message.conversation_id) {
            socketRef.current?.send({
              type: 'read',
              conversation_id: msg.message.conversation_id,
            });
          }
          void loadConversations();
          break;
        case 'read':
          st.markRead(msg.conversation_id, msg.message_ids);
          break;
        case 'error':
          if (msg.temp_id) st.failMessage(msg.temp_id);
          break;
        case 'message_updated':
          st.updateMessage(msg.message);
          break;
        case 'call_offer':
        case 'call_answer':
        case 'call_ice':
        case 'call_reject':
        case 'call_hangup':
        case 'call_unavailable':
          callRef.current.handleSignal(msg);
          break;
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
      const active = useChatStore.getState().activeId;
      if (active) void refreshMessages(active);
    },
    /** token 失效（WS 1008）時登出。 */
    onUnauthorized: onLogout,
  });
  const socketRef = useRef(socket);
  socketRef.current = socket;

  // 通話：用穩定的 wsSend 包裝 socketRef，讓 useCall 不因 socket 換參考而重建。
  const wsSend = useCallback(
    (m: Parameters<typeof socket.send>[0]) => socketRef.current?.send(m) ?? false,
    [],
  );
  const call = useCall(wsSend);
  const callRef = useRef(call);
  callRef.current = call;

  /** 切換對話：必要時拉歷史、送 read 事件、清本地未讀數。 */
  const selectConversation = useCallback(
    async (conversationId: string) => {
      const st = useChatStore.getState();
      st.setActiveId(conversationId);
      if (!st.hasMessages(conversationId)) {
        await refreshMessages(conversationId);
      }
      socketRef.current?.send({ type: 'read', conversation_id: conversationId });
      useChatStore.getState().clearUnread(conversationId);
    },
    [refreshMessages],
  );

  /** 向上分頁：以最早訊息的 created_at 為游標載入更早訊息。 */
  const loadMore = useCallback(async () => {
    const st = useChatStore.getState();
    const active = st.activeId;
    if (!active) return;
    const oldest = (st.messages[active] ?? [])[0];
    if (!oldest) return;
    try {
      const older = await api.listMessages(active, {
        before: oldest.created_at,
        limit: PAGE_SIZE,
      });
      const s2 = useChatStore.getState();
      s2.loadOlder(active, older);
      s2.setHasMore(active, older.length === PAGE_SIZE);
    } catch (err) {
      if (err instanceof UnauthorizedError) onLogout();
    }
  }, [api, onLogout]);

  const attachmentUrl = useCallback(
    (id: string) => `${apiBaseUrl}/attachments/${id}?token=${encodeURIComponent(token)}`,
    [apiBaseUrl, token],
  );

  const onUpload = useCallback(
    async (file: File) => {
      try {
        return await api.uploadFile(file);
      } catch (err) {
        if (err instanceof UnauthorizedError) onLogout();
        return null;
      }
    },
    [api, onLogout],
  );

  // ---- 送訊息（樂觀更新） ----
  /** 樂觀送出訊息：先插入 UI，再經 WS 送出；連線不可用則標 failed。 */
  const sendMessage = useCallback(
    (content: string, attachmentId?: string) => {
      const st = useChatStore.getState();
      const active = st.activeId;
      if (!active) return;
      const tempId = crypto.randomUUID();
      // 樂觀訊息先不帶附件預覽，待 server ack 帶回正式 attachment 再顯示。
      st.appendOptimistic(active, makeOptimistic(active, currentUser.id, content, tempId));
      const ok = socketRef.current?.send({
        type: 'message',
        conversation_id: active,
        content,
        temp_id: tempId,
        attachment_id: attachmentId,
      });
      if (!ok) useChatStore.getState().failMessage(tempId);
    },
    [currentUser.id],
  );

  /** 重送 failed 訊息：沿用原 temp_id 以便 ACK 對齊。 */
  const retry = useCallback((tempId: string) => {
    const st = useChatStore.getState();
    const active = st.activeId;
    if (!active) return;
    const failed = (st.messages[active] ?? []).find((m) => m.temp_id === tempId);
    if (!failed) return;
    st.resendMessage(active, tempId);
    const ok = socketRef.current?.send({
      type: 'message',
      conversation_id: active,
      content: failed.content,
      temp_id: tempId,
    });
    if (!ok) useChatStore.getState().failMessage(tempId);
  }, []);

  const editMessage = useCallback((id: string, content: string) => {
    socketRef.current?.send({ type: 'edit', message_id: id, content });
  }, []);
  const deleteMessage = useCallback((id: string) => {
    socketRef.current?.send({ type: 'delete', message_id: id });
  }, []);
  const toggleReaction = useCallback((id: string, emoji: string) => {
    socketRef.current?.send({ type: 'react', message_id: id, emoji });
  }, []);

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
        useChatStore.getState().setActiveId(conv.id);
        return null;
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onLogout();
          return '憑證失效';
        }
        if (err instanceof ApiError) return err.message;
        return '建立群組失敗';
      }
    },
    [api, loadConversations, onLogout],
  );

  const activeConv = conversations.find((c) => c.id === activeId) ?? null;
  const otherUser = activeConv && activeConv.type === 'direct' ? activeConv.other_user : null;
  const startCall = useCallback(() => {
    if (otherUser) call.startCall({ id: otherUser.id, display_name: otherUser.display_name });
  }, [otherUser, call]);
  const isGroup = activeConv?.type === 'group';
  const memberNames = Object.fromEntries(
    (activeConv?.members ?? []).map((m) => [m.id, m.display_name]),
  );
  const title = activeConv
    ? activeConv.type === 'group'
      ? activeConv.name ?? '群組'
      : activeConv.other_user?.display_name ?? ''
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
          attachmentUrl={attachmentUrl}
          onUpload={onUpload}
          onEdit={editMessage}
          onDelete={deleteMessage}
          onReact={toggleReaction}
          onStartCall={otherUser ? startCall : undefined}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-slate-400">
          選擇一個對話開始聊天
        </div>
      )}
      <CallOverlay
        status={call.callState}
        peerName={call.peer?.display_name ?? otherUser?.display_name ?? null}
        localStream={call.localStream}
        remoteStream={call.remoteStream}
        micOn={call.micOn}
        cameraOn={call.cameraOn}
        onAccept={call.acceptCall}
        onReject={call.rejectCall}
        onHangup={call.hangup}
        onToggleMic={call.toggleMic}
        onToggleCamera={call.toggleCamera}
      />
    </div>
  );
}

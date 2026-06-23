// chat remote 對外暴露的主元件（由 shell 以 props 傳入 token / currentUser 等）。
// 職責：組裝 Sidebar + Thread，串接 REST（ApiClient）與 WebSocket（useChatSocket）。
// 狀態集中在 zustand（useChatStore）；本元件只負責副作用（fetch / ws.send）與把 store 接到 UI。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { ChatAppProps, ServerWsMessage } from '../../contracts';
import { ApiClient, ApiError, UnauthorizedError } from './api';
import { CallOverlay } from './components/CallOverlay';
import { ForwardPicker } from './components/ForwardPicker';
import { GroupInfoPanel } from './components/GroupInfoPanel';
import { NotificationCenter } from './components/NotificationCenter';
import { Sidebar } from './components/Sidebar';
import { Thread } from './components/Thread';
import type { UploadResult } from './components/Thread';
import { useCall } from './useCall';
import { formatLastSeen } from './presence';
import { useChatStore } from './store';
import { useChatSocket } from './useChatSocket';
import { useMessageActions } from './useMessageActions';
import { dispatchServerMessage } from './wsDispatch';

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
  const presence = useChatStore((s) => s.presence);
  const notifications = useChatStore((s) => s.notifications);
  const unreadCount = useChatStore((s) => s.unreadCount);

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
      .then((c) => {
        const st = useChatStore.getState();
        st.setContacts(c);
        st.setPresenceFromContacts(c);
      })
      .catch(() => {});
    void api
      .listNotifications()
      .then((list) => useChatStore.getState().setNotifications(list))
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
  /** 分派 WebSocket 推播給 wsDispatch（store 變更集中於該模組，副作用由此注入）。 */
  const handleServerMessage = useCallback(
    (msg: ServerWsMessage) =>
      dispatchServerMessage(msg, {
        reloadConversations: () => { void loadConversations(); },
        sendRead: (conversationId) =>
          { socketRef.current?.send({ type: 'read', conversation_id: conversationId }); },
        handleCallSignal: (m) => callRef.current.handleSignal(m),
      }),
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

  // 訊息動作（送出/重試/編輯/刪除/表情/還原/轉發/編輯歷史）集中在 hook，以 wsSend 發訊。
  const {
    sendMessage,
    retry,
    editMessage,
    deleteMessage,
    toggleReaction,
    restoreMessage,
    forwardMessage,
    loadEditHistory,
  } = useMessageActions(wsSend, api, currentUser.id);

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
      // 開啟對話即把指向它的通知標已讀（已讀的唯一來源）。
      void api
        .markNotificationsRead(conversationId)
        .then((r) => useChatStore.getState().markConversationRead(conversationId, r.marked))
        .catch(() => {});
    },
    [refreshMessages, api],
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
    async (file: File): Promise<UploadResult> => {
      try {
        return { ok: true, attachment: await api.uploadFile(file) };
      } catch (err) {
        if (err instanceof UnauthorizedError) {
          onLogout();
          return { ok: false, message: '憑證失效，請重新登入' };
        }
        if (err instanceof ApiError) return { ok: false, message: err.message };
        return { ok: false, message: '上傳失敗' };
      }
    },
    [api, onLogout],
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

  const [showInfo, setShowInfo] = useState(false);
  const [forwarding, setForwarding] = useState<string | null>(null);

  const runGroupOp = useCallback(
    async (op: () => Promise<unknown>) => {
      try {
        await op();
        await loadConversations();
      } catch (err) {
        if (err instanceof UnauthorizedError) { onLogout(); return; }
        if (err instanceof ApiError) alert(err.message);
      }
    },
    [loadConversations, onLogout],
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
  // 1對1 對方的 presence 文案:在線→「在線」、有 last_seen→「最後上線 X」、否則「離線」。群組為 null。
  const statusText = (() => {
    if (!otherUser) return null;
    const p = presence[otherUser.id];
    if (p?.online) return '在線';
    const rel = formatLastSeen(p?.last_seen_at ?? null);
    return rel ? `最後上線 ${rel}` : '離線';
  })();

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
        presence={presence}
        notificationSlot={
          <NotificationCenter
            notifications={notifications}
            unreadCount={unreadCount}
            onOpen={(n) => selectConversation(n.conversation_id)}
          />
        }
      />
      {activeId && activeConv ? (
        <Thread
          title={title}
          statusText={statusText}
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
          onRestore={restoreMessage}
          loadEditHistory={loadEditHistory}
          onStartCall={otherUser ? startCall : undefined}
          onShowGroupInfo={isGroup ? () => setShowInfo(true) : undefined}
          onForward={(m) => setForwarding(m.id)}
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-slate-400">
          選擇一個對話開始聊天
        </div>
      )}
      {forwarding && (
        <ForwardPicker
          conversations={conversations}
          onPick={(convId) => { forwardMessage(forwarding, convId); setForwarding(null); }}
          onClose={() => setForwarding(null)}
        />
      )}
      {showInfo && isGroup && activeConv && (
        <GroupInfoPanel
          conversation={activeConv}
          currentUserId={currentUser.id}
          contacts={contacts}
          onAddMember={(opts) => runGroupOp(() => api.addMember(activeConv.id, opts))}
          onRemoveMember={(uid) => runGroupOp(() => api.removeMember(activeConv.id, uid))}
          onSetRole={(uid, role) => runGroupOp(() => api.setMemberRole(activeConv.id, uid, role))}
          onRename={(name) => runGroupOp(() => api.renameGroup(activeConv.id, name))}
          onLeave={() => runGroupOp(async () => { await api.leaveGroup(activeConv.id); setShowInfo(false); })}
          onClose={() => setShowInfo(false)}
        />
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

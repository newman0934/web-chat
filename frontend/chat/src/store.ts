// chat remote 的狀態以 zustand 集中管理（取代 ChatApp 內的多個 useState）。
// 純粹保管狀態 + 同步 mutation；副作用（fetch / ws.send）留在 ChatApp。
// 訊息層的 mutation 重用 messageStore.ts 的純函式，維持單一真相、與既有單元測試一致。

import { create } from 'zustand';

import type {
  Contact,
  Conversation,
  Message,
  Notification,
  NotificationList,
  ServerWsMessage,
} from '../../contracts';
import {
  addIncoming,
  addOptimistic,
  applyMessageUpdate,
  applyReadReceipt,
  fromHistory,
  markFailed,
  prependHistory,
  reconcileAck,
  type ChatMessage,
} from './messageStore';
import { applyMarkRead, upsertNotification } from './notifications';
import { addPin, removePin } from './pins';
import { applyPresence, presenceFromContacts, type PresenceMap } from './presence';

type PresenceEvent = Extract<ServerWsMessage, { type: 'presence' }>;

interface ChatState {
  conversations: Conversation[];
  activeId: string | null;
  /** conversationId → 訊息清單（由舊到新）。 */
  messages: Record<string, ChatMessage[]>;
  /** conversationId → 是否還有更早的歷史可載入。 */
  hasMore: Record<string, boolean>;
  contacts: Contact[];
  /** 好友線上狀態:user_id → {online, last_seen_at}。 */
  presence: PresenceMap;
  /** conversationId → 釘選訊息清單（pinned_at 由新到舊）。 */
  pins: Record<string, Message[]>;

  // ---- 清單 / 選取 ----
  setConversations: (conversations: Conversation[]) => void;
  setContacts: (contacts: Contact[]) => void;
  /** 由 /contacts 快照建立初始 presence map。 */
  setPresenceFromContacts: (contacts: Contact[]) => void;
  /** 套用一筆 WS presence 事件。 */
  applyPresenceEvent: (evt: PresenceEvent) => void;
  setActiveId: (id: string | null) => void;
  setHasMore: (conversationId: string, hasMore: boolean) => void;
  /** 該對話是否已載過訊息（決定切換時要不要拉歷史）。 */
  hasMessages: (conversationId: string) => boolean;
  /** 把某對話的未讀數歸零（本地樂觀更新）。 */
  clearUnread: (conversationId: string) => void;
  /**
   * 收到新訊息時就地更新對話清單(更新 last_message、必要時未讀 +1、移到最前),
   * 免去每則訊息重抓整份 /conversations。回傳 false 表示該對話不在清單(新對話)
   * → 呼叫端應退回重抓。非 active 且非自己送的訊息才 +1 未讀。
   */
  applyIncomingToConversations: (message: Message, currentUserId: string) => boolean;

  // ---- 訊息 mutation（重用 messageStore 純函式） ----
  loadHistory: (conversationId: string, history: Message[]) => void;
  loadOlder: (conversationId: string, older: Message[]) => void;
  appendOptimistic: (conversationId: string, msg: ChatMessage) => void;
  ackMessage: (tempId: string, message: Message) => void;
  receiveMessage: (message: Message) => void;
  markRead: (conversationId: string, messageIds: string[]) => void;
  /** 把某 temp_id 的訊息標記為 failed（跨所有對話尋找）。 */
  failMessage: (tempId: string) => void;
  /** 把某對話內某 temp_id 的訊息狀態改回 sending（重試用）。 */
  resendMessage: (conversationId: string, tempId: string) => void;
  /** 收到 message_updated 事件：依 id 取代該對話內對應訊息。 */
  updateMessage: (message: Message) => void;

  // ---- 訊息置頂 ----
  /** 開啟對話時由 REST 載入釘選清單。 */
  setPins: (conversationId: string, pins: Message[]) => void;
  /** 收到 message_pinned：加入 pins（去重、最新在前）並更新該訊息 pinned 旗標。 */
  applyPinned: (message: Message) => void;
  /** 收到 message_unpinned：自 pins 移除並把該訊息 pinned 設為 false。 */
  applyUnpinned: (conversationId: string, messageId: string) => void;

  /** 移除某對話（被踢/退出/群解散）；清掉其訊息與 hasMore，若為 active 則切回空畫面。 */
  removeConversation: (conversationId: string) => void;

  // ---- 站內通知 ----
  /** 通知清單（新→舊）與未讀總數（未讀數以伺服器為準，分頁不影響）。 */
  notifications: Notification[];
  unreadCount: number;
  /** 由 REST 載入（含伺服器未讀總數）。 */
  setNotifications: (list: NotificationList) => void;
  /** WS 推來一筆新通知：upsert 到最前、未讀數 +1（同 id 重入不重覆計）。 */
  addNotification: (n: Notification) => void;
  /** 開啟對話後標已讀：本地把該對話通知設 read、未讀數扣掉伺服器回報的 marked 筆數。 */
  markConversationRead: (conversationId: string, marked: number) => void;

  /** 重置成初始狀態（登入切換 / 卸載時呼叫，避免殘留上一位使用者資料）。 */
  reset: () => void;
}

const initialState = {
  conversations: [] as Conversation[],
  activeId: null as string | null,
  messages: {} as Record<string, ChatMessage[]>,
  hasMore: {} as Record<string, boolean>,
  contacts: [] as Contact[],
  presence: {} as PresenceMap,
  pins: {} as Record<string, Message[]>,
  notifications: [] as Notification[],
  unreadCount: 0,
};

export const useChatStore = create<ChatState>((set, get) => ({
  ...initialState,

  setConversations: (conversations) => set({ conversations }),
  setContacts: (contacts) => set({ contacts }),
  setPresenceFromContacts: (contacts) => set({ presence: presenceFromContacts(contacts) }),
  applyPresenceEvent: (evt) => set((s) => ({ presence: applyPresence(s.presence, evt) })),
  setActiveId: (id) => set({ activeId: id }),
  setHasMore: (conversationId, hasMore) =>
    set((s) => ({ hasMore: { ...s.hasMore, [conversationId]: hasMore } })),

  hasMessages: (conversationId) => get().messages[conversationId] !== undefined,

  clearUnread: (conversationId) =>
    set((s) => ({
      conversations: s.conversations.map((c) =>
        c.id === conversationId ? { ...c, unread_count: 0 } : c,
      ),
    })),

  applyIncomingToConversations: (message, currentUserId) => {
    const s = get();
    const idx = s.conversations.findIndex((c) => c.id === message.conversation_id);
    if (idx === -1) return false; // 不在清單(新對話)→ 呼叫端退回重抓
    const conv = s.conversations[idx];
    const isActive = s.activeId === message.conversation_id;
    const fromMe = message.sender_id === currentUserId;
    const updated: Conversation = {
      ...conv,
      last_message: message,
      // active(正在讀)或自己送出 → 不增未讀;否則 +1(與伺服器未讀語意一致)。
      unread_count: isActive || fromMe ? conv.unread_count : conv.unread_count + 1,
    };
    // 移到最前:最新訊息即最新對話(維持「新→舊」排序)。
    const rest = s.conversations.filter((_, i) => i !== idx);
    set({ conversations: [updated, ...rest] });
    return true;
  },

  loadHistory: (conversationId, history) =>
    set((s) => ({
      messages: { ...s.messages, [conversationId]: fromHistory(history) },
    })),

  loadOlder: (conversationId, older) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [conversationId]: prependHistory(s.messages[conversationId] ?? [], older),
      },
    })),

  appendOptimistic: (conversationId, msg) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [conversationId]: addOptimistic(s.messages[conversationId] ?? [], msg),
      },
    })),

  ackMessage: (tempId, message) =>
    set((s) => {
      const convId = message.conversation_id;
      return {
        messages: {
          ...s.messages,
          [convId]: reconcileAck(s.messages[convId] ?? [], tempId, message),
        },
      };
    }),

  receiveMessage: (message) =>
    set((s) => {
      const convId = message.conversation_id;
      return {
        messages: {
          ...s.messages,
          [convId]: addIncoming(s.messages[convId] ?? [], message),
        },
      };
    }),

  markRead: (conversationId, messageIds) =>
    set((s) => {
      const list = s.messages[conversationId];
      if (!list) return s;
      return {
        messages: {
          ...s.messages,
          [conversationId]: applyReadReceipt(list, messageIds),
        },
      };
    }),

  failMessage: (tempId) =>
    set((s) => {
      const next = { ...s.messages };
      for (const [cid, list] of Object.entries(next)) {
        if (list.some((m) => m.temp_id === tempId)) {
          next[cid] = markFailed(list, tempId);
        }
      }
      return { messages: next };
    }),

  resendMessage: (conversationId, tempId) =>
    set((s) => ({
      messages: {
        ...s.messages,
        [conversationId]: (s.messages[conversationId] ?? []).map((m) =>
          m.temp_id === tempId ? { ...m, status: 'sending' as const } : m,
        ),
      },
    })),

  updateMessage: (message) =>
    set((s) => {
      const convId = message.conversation_id;
      const list = s.messages[convId];
      if (!list) return s;
      return { messages: { ...s.messages, [convId]: applyMessageUpdate(list, message) } };
    }),

  setPins: (conversationId, pins) =>
    set((s) => ({ pins: { ...s.pins, [conversationId]: pins } })),

  applyPinned: (message) =>
    set((s) => {
      const convId = message.conversation_id;
      const list = s.messages[convId];
      return {
        pins: { ...s.pins, [convId]: addPin(s.pins[convId] ?? [], message) },
        messages: list
          ? { ...s.messages, [convId]: applyMessageUpdate(list, message) }
          : s.messages,
      };
    }),

  applyUnpinned: (conversationId, messageId) =>
    set((s) => {
      const list = s.messages[conversationId];
      return {
        pins: { ...s.pins, [conversationId]: removePin(s.pins[conversationId] ?? [], messageId) },
        messages: list
          ? {
              ...s.messages,
              [conversationId]: list.map((m) =>
                m.id === messageId ? { ...m, pinned: false } : m,
              ),
            }
          : s.messages,
      };
    }),

  removeConversation: (conversationId) =>
    set((s) => {
      const messages = { ...s.messages };
      delete messages[conversationId];
      const hasMore = { ...s.hasMore };
      delete hasMore[conversationId];
      return {
        conversations: s.conversations.filter((c) => c.id !== conversationId),
        messages,
        hasMore,
        activeId: s.activeId === conversationId ? null : s.activeId,
      };
    }),

  setNotifications: (list) =>
    set({ notifications: list.items, unreadCount: list.unread_count }),

  addNotification: (n) =>
    set((s) => {
      const exists = s.notifications.some((x) => x.id === n.id);
      return {
        notifications: upsertNotification(s.notifications, n),
        unreadCount: exists ? s.unreadCount : s.unreadCount + 1,
      };
    }),

  markConversationRead: (conversationId, marked) =>
    set((s) => ({
      notifications: applyMarkRead(s.notifications, conversationId),
      unreadCount: Math.max(0, s.unreadCount - marked),
    })),

  reset: () => set({ ...initialState }),
}));

// chat remote 的狀態以 zustand 集中管理（取代 ChatApp 內的多個 useState）。
// 純粹保管狀態 + 同步 mutation；副作用（fetch / ws.send）留在 ChatApp。
// 訊息層的 mutation 重用 messageStore.ts 的純函式，維持單一真相、與既有單元測試一致。

import { create } from 'zustand';

import type { Contact, Conversation, Message } from '../../contracts';
import {
  addIncoming,
  addOptimistic,
  applyReadReceipt,
  fromHistory,
  markFailed,
  prependHistory,
  reconcileAck,
  type ChatMessage,
} from './messageStore';

interface ChatState {
  conversations: Conversation[];
  activeId: string | null;
  /** conversationId → 訊息清單（由舊到新）。 */
  messages: Record<string, ChatMessage[]>;
  /** conversationId → 是否還有更早的歷史可載入。 */
  hasMore: Record<string, boolean>;
  contacts: Contact[];

  // ---- 清單 / 選取 ----
  setConversations: (conversations: Conversation[]) => void;
  setContacts: (contacts: Contact[]) => void;
  setActiveId: (id: string | null) => void;
  setHasMore: (conversationId: string, hasMore: boolean) => void;
  /** 該對話是否已載過訊息（決定切換時要不要拉歷史）。 */
  hasMessages: (conversationId: string) => boolean;
  /** 把某對話的未讀數歸零（本地樂觀更新）。 */
  clearUnread: (conversationId: string) => void;

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

  /** 重置成初始狀態（登入切換 / 卸載時呼叫，避免殘留上一位使用者資料）。 */
  reset: () => void;
}

const initialState = {
  conversations: [] as Conversation[],
  activeId: null as string | null,
  messages: {} as Record<string, ChatMessage[]>,
  hasMore: {} as Record<string, boolean>,
  contacts: [] as Contact[],
};

export const useChatStore = create<ChatState>((set, get) => ({
  ...initialState,

  setConversations: (conversations) => set({ conversations }),
  setContacts: (contacts) => set({ contacts }),
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

  reset: () => set({ ...initialState }),
}));

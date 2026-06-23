// WebSocket server→client 訊息分派（純邏輯，與 React 解耦、可單獨測試）。
// 把 store 變更集中在此；需要與外界互動的副作用（重載清單、送 read、轉交通話訊號）由 deps 注入。

import type { ServerWsMessage } from '../../contracts';
import { useChatStore } from './store';

export interface DispatchDeps {
  /** 重新載入對話清單（收到新訊息 / 對話變動時）。 */
  reloadConversations: () => void;
  /** 對「正開著的對話」回報已讀。 */
  sendRead: (conversationId: string) => void;
  /** 把通話訊號轉交 useCall 處理。 */
  handleCallSignal: (msg: ServerWsMessage) => void;
}

/** 依 server 推播類型更新 store / 觸發副作用。 */
export function dispatchServerMessage(msg: ServerWsMessage, deps: DispatchDeps): void {
  const st = useChatStore.getState();
  switch (msg.type) {
    case 'ack':
      st.ackMessage(msg.temp_id, msg.message);
      break;
    case 'message':
      st.receiveMessage(msg.message);
      // 若正開著該對話，立刻回報已讀。
      if (st.activeId === msg.message.conversation_id) {
        deps.sendRead(msg.message.conversation_id);
      }
      deps.reloadConversations();
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
    case 'notification':
      st.addNotification(msg.notification);
      break;
    case 'presence':
      st.applyPresenceEvent(msg);
      break;
    case 'conversation_updated':
      deps.reloadConversations();
      break;
    case 'conversation_removed':
      st.removeConversation(msg.conversation_id);
      break;
    case 'call_offer':
    case 'call_answer':
    case 'call_ice':
    case 'call_reject':
    case 'call_hangup':
    case 'call_unavailable':
      deps.handleCallSignal(msg);
      break;
    default:
      break;
  }
}

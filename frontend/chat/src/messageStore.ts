// 訊息清單的純函式操作（不依賴 React），方便單元測試。
// 樂觀更新流程：送出時先以 temp_id 插入 'sending' 訊息 → 收到 ACK 換成正式訊息('sent')
// → 失敗則標記 'failed' 供重試。

import type { Attachment, Message } from '../../contracts';

export type MessageStatus = 'sending' | 'sent' | 'failed';

export interface ChatMessage extends Message {
  /** 樂觀更新用的暫時 id；對齊 ACK 後保留以利重試識別。 */
  temp_id?: string;
  status: MessageStatus;
}

/** 建立一則樂觀訊息（尚未落庫，先顯示）。 */
export function makeOptimistic(
  conversationId: string,
  senderId: string,
  content: string,
  tempId: string,
  attachment: Attachment | null = null,
): ChatMessage {
  return {
    id: tempId,
    conversation_id: conversationId,
    sender_id: senderId,
    content,
    created_at: new Date().toISOString(),
    read_count: 0,
    attachment,
    temp_id: tempId,
    status: 'sending',
  };
}

/** 將樂觀訊息追加到清單尾端（送出當下先顯示在 UI）。 */
export function addOptimistic(list: ChatMessage[], msg: ChatMessage): ChatMessage[] {
  return [...list, msg];
}

/** 收到 ACK：把對應 temp_id 的樂觀訊息換成正式訊息。 */
export function reconcileAck(
  list: ChatMessage[],
  tempId: string,
  real: Message,
): ChatMessage[] {
  let replaced = false;
  const next = list.map((m) => {
    if (m.temp_id === tempId) {
      replaced = true;
      return { ...real, status: 'sent' as const };
    }
    return m;
  });
  // 若找不到對應（例如重整後），就當作新訊息補上（去重）。
  if (!replaced && !next.some((m) => m.id === real.id)) {
    next.push({ ...real, status: 'sent' });
  }
  return next;
}

/** 將對應 temp_id 的樂觀訊息標記為 failed，供 UI 顯示重試。 */
export function markFailed(list: ChatMessage[], tempId: string): ChatMessage[] {
  return list.map((m) =>
    m.temp_id === tempId ? { ...m, status: 'failed' as const } : m,
  );
}

/** 收到對方推送的新訊息：去重後追加。 */
export function addIncoming(list: ChatMessage[], real: Message): ChatMessage[] {
  if (list.some((m) => m.id === real.id)) return list;
  return [...list, { ...real, status: 'sent' }];
}

/** 載入歷史：插到最前面，依 id 去重。 */
export function prependHistory(
  list: ChatMessage[],
  older: Message[],
): ChatMessage[] {
  const existing = new Set(list.map((m) => m.id));
  const prefix = older
    .filter((m) => !existing.has(m.id))
    .map((m) => ({ ...m, status: 'sent' as const }));
  return [...prefix, ...list];
}

/** 初始化歷史訊息（由舊到新）。 */
export function fromHistory(history: Message[]): ChatMessage[] {
  return history.map((m) => ({ ...m, status: 'sent' as const }));
}

/** 收到 read 事件：把被讀到的訊息 read_count + 1（用於「已讀 N」/「已讀」）。 */
export function applyReadReceipt(
  list: ChatMessage[],
  messageIds: string[],
): ChatMessage[] {
  const ids = new Set(messageIds);
  return list.map((m) =>
    ids.has(m.id) ? { ...m, read_count: m.read_count + 1 } : m,
  );
}

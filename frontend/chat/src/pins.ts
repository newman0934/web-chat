// 訊息置頂的純邏輯(抽離 React,便於單元測試):釘選權限、釘選列 view model、pins 清單增減。

import type { Conversation, Message } from '../../contracts';

/** 是否可釘選/取消:1對1 雙方皆可;群組僅 admin。 */
export function canPin(conversation: Conversation, userId: string): boolean {
  if (conversation.type === 'direct') return true;
  return conversation.roles[userId] === 'admin';
}

export interface PinnedBarView {
  latest: Message;
  count: number;
}

/** 釘選列顯示資料:最新一則(清單第一筆,後端已 pinned_at desc)+ 總數;空清單回 null。 */
export function pinnedBarView(pins: Message[]): PinnedBarView | null {
  if (pins.length === 0) return null;
  return { latest: pins[0], count: pins.length };
}

/** 新增釘選:置於最前(最新),並依 id 去重。 */
export function addPin(pins: Message[], message: Message): Message[] {
  return [message, ...pins.filter((p) => p.id !== message.id)];
}

/** 移除釘選:濾掉該 id(不存在則原樣回)。 */
export function removePin(pins: Message[], messageId: string): Message[] {
  return pins.filter((p) => p.id !== messageId);
}

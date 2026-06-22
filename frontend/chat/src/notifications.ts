// 站內通知的純邏輯，與 React 解耦、可單獨測試（沿用 messageStore 的純函式慣例）。

import type { Notification } from '../../contracts';

/** 依 id upsert：已存在則就地取代，否則插到最前（新→舊）。 */
export function upsertNotification(list: Notification[], n: Notification): Notification[] {
  const idx = list.findIndex((x) => x.id === n.id);
  if (idx === -1) return [n, ...list];
  const next = list.slice();
  next[idx] = n;
  return next;
}

/** 把某對話的（未讀）通知標為已讀。 */
export function applyMarkRead(list: Notification[], conversationId: string): Notification[] {
  return list.map((n) =>
    n.conversation_id === conversationId && !n.read ? { ...n, read: true } : n,
  );
}

/** 清單內的未讀數（注意：清單可能分頁，未讀總數以伺服器回傳為準）。 */
export function countUnread(list: Notification[]): number {
  return list.reduce((acc, n) => acc + (n.read ? 0 : 1), 0);
}

/** 動作文案（不含 actor 名；UI 自行組「{actor} {文案}」）。 */
export function describeNotification(n: Notification): string {
  switch (n.type) {
    case 'reply':
      return '回覆了你的訊息';
    case 'reaction':
      return `對你的訊息按了 ${n.emoji ?? '表情'}`;
    case 'forward':
      return '轉發了你的訊息';
    default:
      return '與你的訊息互動';
  }
}

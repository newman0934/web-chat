// 線上狀態(presence)的純邏輯,與 React 解耦、可單獨測試(沿用 messageStore/notifications 慣例)。

import type { Contact, ServerWsMessage } from '../../contracts';

/** 單一使用者的 presence 狀態。 */
export interface PresenceState {
  online: boolean;
  last_seen_at: string | null;
}

export type PresenceMap = Record<string, PresenceState>;

type PresenceEvent = Extract<ServerWsMessage, { type: 'presence' }>;

/** 由 /contacts 快照建出初始 presence map(user_id → {online, last_seen_at})。 */
export function presenceFromContacts(contacts: Contact[]): PresenceMap {
  const map: PresenceMap = {};
  for (const c of contacts) {
    map[c.user_id] = { online: c.online, last_seen_at: c.last_seen_at };
  }
  return map;
}

/** 套用一筆 WS presence 事件,回傳新的 map(不可變更新)。 */
export function applyPresence(map: PresenceMap, evt: PresenceEvent): PresenceMap {
  return {
    ...map,
    [evt.user_id]: { online: evt.online, last_seen_at: evt.last_seen_at },
  };
}

/**
 * 最後上線的相對時間文案。
 * < 1 分鐘「剛剛」、< 60 分鐘「N 分鐘前」、< 24 小時「N 小時前」、否則「M/D」。
 * ts 為 null(從未離線過)時回傳 null,讓 UI 顯示「離線」而非「最後上線 (空)」。
 */
export function formatLastSeen(ts: string | null, now: number = Date.now()): string | null {
  if (!ts) return null;
  const then = new Date(ts).getTime();
  if (Number.isNaN(then)) return null;
  const diffMs = now - then;
  const min = Math.floor(diffMs / 60000);
  if (min < 1) return '剛剛';
  if (min < 60) return `${min} 分鐘前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小時前`;
  const d = new Date(then);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

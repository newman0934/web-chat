import { describe, expect, it } from 'vitest';

import type { Contact, ServerWsMessage } from '../../contracts';
import { applyPresence, formatLastSeen, presenceFromContacts, type PresenceMap } from './presence';

function contact(over: Partial<Contact> = {}): Contact {
  return {
    user_id: 'u1',
    email: 'u1@example.com',
    display_name: 'U1',
    conversation_id: 'c1',
    online: false,
    last_seen_at: null,
    ...over,
  };
}

function evt(over: Partial<Extract<ServerWsMessage, { type: 'presence' }>> = {}) {
  return { type: 'presence' as const, user_id: 'u1', online: true, last_seen_at: null, ...over };
}

describe('presence pure fns', () => {
  it('presenceFromContacts 建出 user_id → state map', () => {
    const map = presenceFromContacts([
      contact({ user_id: 'a', online: true }),
      contact({ user_id: 'b', online: false, last_seen_at: '2026-06-23T00:00:00Z' }),
    ]);
    expect(map.a).toEqual({ online: true, last_seen_at: null });
    expect(map.b).toEqual({ online: false, last_seen_at: '2026-06-23T00:00:00Z' });
  });

  it('applyPresence 不可變更新單一使用者', () => {
    const base: PresenceMap = { a: { online: false, last_seen_at: null } };
    const next = applyPresence(base, evt({ user_id: 'a', online: true }));
    expect(next.a).toEqual({ online: true, last_seen_at: null });
    expect(base.a.online).toBe(false); // 原 map 不被改動
  });

  it('applyPresence 套用 offline + last_seen', () => {
    const next = applyPresence({}, evt({ online: false, last_seen_at: '2026-06-23T01:00:00Z' }));
    expect(next.u1).toEqual({ online: false, last_seen_at: '2026-06-23T01:00:00Z' });
  });

  describe('formatLastSeen', () => {
    const now = new Date('2026-06-23T12:00:00Z').getTime();

    it('null → null(讓 UI 顯示「離線」)', () => {
      expect(formatLastSeen(null, now)).toBeNull();
    });
    it('< 1 分鐘 → 剛剛', () => {
      expect(formatLastSeen('2026-06-23T11:59:30Z', now)).toBe('剛剛');
    });
    it('< 60 分鐘 → N 分鐘前', () => {
      expect(formatLastSeen('2026-06-23T11:30:00Z', now)).toBe('30 分鐘前');
    });
    it('< 24 小時 → N 小時前', () => {
      expect(formatLastSeen('2026-06-23T09:00:00Z', now)).toBe('3 小時前');
    });
    it('>= 24 小時 → M/D', () => {
      expect(formatLastSeen('2026-06-20T09:00:00Z', now)).toBe('6/20');
    });
    it('無效字串 → null', () => {
      expect(formatLastSeen('not-a-date', now)).toBeNull();
    });
  });
});

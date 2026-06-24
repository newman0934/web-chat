import { describe, expect, it } from 'vitest';

import type { Conversation, Message } from '../../contracts';
import { addPin, canPin, pinnedBarView, removePin } from './pins';

function mkConv(over: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1', type: 'direct', name: null, other_user: null, members: [],
    last_message: null, unread_count: 0, roles: {}, ...over,
  };
}

function mkMsg(id: string): Message {
  return {
    id, conversation_id: 'c1', sender_id: 'u', content: id, created_at: '2026-06-24T12:00:00+00:00',
    read_count: 0, attachments: [], edited_at: null, deleted: false, reactions: [],
  };
}

describe('canPin', () => {
  it('1對1 雙方皆可', () => {
    expect(canPin(mkConv({ type: 'direct' }), 'anyone')).toBe(true);
  });
  it('群組僅 admin', () => {
    const conv = mkConv({ type: 'group', roles: { ua: 'admin', ub: 'member' } });
    expect(canPin(conv, 'ua')).toBe(true);
    expect(canPin(conv, 'ub')).toBe(false);
    expect(canPin(conv, 'unknown')).toBe(false);
  });
});

describe('pinnedBarView', () => {
  it('空清單回 null', () => {
    expect(pinnedBarView([])).toBeNull();
  });
  it('回最新一則 + 總數', () => {
    const v = pinnedBarView([mkMsg('m2'), mkMsg('m1')]);
    expect(v?.latest.id).toBe('m2');
    expect(v?.count).toBe(2);
  });
});

describe('addPin / removePin', () => {
  it('addPin 置於最前並去重', () => {
    const pins = [mkMsg('m1')];
    expect(addPin(pins, mkMsg('m2')).map((p) => p.id)).toEqual(['m2', 'm1']);
    // 已存在 → 移到最前不重複
    expect(addPin([mkMsg('m1'), mkMsg('m2')], mkMsg('m2')).map((p) => p.id)).toEqual(['m2', 'm1']);
  });
  it('removePin 濾掉指定 id', () => {
    expect(removePin([mkMsg('m1'), mkMsg('m2')], 'm1').map((p) => p.id)).toEqual(['m2']);
    expect(removePin([mkMsg('m1')], 'nope').map((p) => p.id)).toEqual(['m1']);
  });
});

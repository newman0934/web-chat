import { describe, expect, it } from 'vitest';

import type { Notification } from '../../contracts';
import { applyMarkRead, countUnread, describeNotification, upsertNotification } from './notifications';

function notif(id: string, over: Partial<Notification> = {}): Notification {
  return {
    id,
    type: 'reply',
    actor: { id: 'a1', display_name: 'Alice' },
    conversation_id: 'c1',
    message_id: 'm1',
    message_preview: 'hi',
    emoji: null,
    read: false,
    created_at: '2026-06-22T00:00:00Z',
    ...over,
  };
}

describe('notifications pure fns', () => {
  it('upsertNotification 插入新筆到最前、相同 id 取代', () => {
    const a = notif('1');
    const b = notif('2');
    const list = upsertNotification([a], b);
    expect(list.map((n) => n.id)).toEqual(['2', '1']);
    const replaced = upsertNotification(list, notif('1', { read: true }));
    expect(replaced.find((n) => n.id === '1')!.read).toBe(true);
    expect(replaced).toHaveLength(2);
  });

  it('applyMarkRead 只標該對話的未讀', () => {
    const list = [
      notif('1', { conversation_id: 'c1' }),
      notif('2', { conversation_id: 'c2' }),
    ];
    const out = applyMarkRead(list, 'c1');
    expect(out.find((n) => n.id === '1')!.read).toBe(true);
    expect(out.find((n) => n.id === '2')!.read).toBe(false);
  });

  it('countUnread 數未讀', () => {
    expect(countUnread([notif('1'), notif('2', { read: true }), notif('3')])).toBe(2);
  });

  it('describeNotification 依 type 給文案（reaction 帶 emoji）', () => {
    expect(describeNotification(notif('1', { type: 'reply' }))).toContain('回覆');
    expect(describeNotification(notif('2', { type: 'reaction', emoji: '👍' }))).toContain('👍');
    expect(describeNotification(notif('3', { type: 'forward' }))).toContain('轉發');
  });
});

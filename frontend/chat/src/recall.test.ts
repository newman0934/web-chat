import { describe, expect, it } from 'vitest';

import type { ChatMessage } from './messageStore';
import { canRecall } from './recall';

const NOW = new Date('2026-06-24T12:00:00Z').getTime();

function mkMsg(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'm1', conversation_id: 'c1', sender_id: 'me', content: 'hi',
    created_at: '2026-06-24T11:59:00Z', // 1 分鐘前
    read_count: 0, attachments: [], edited_at: null, deleted: false, reactions: [],
    status: 'sent', ...over,
  } as ChatMessage;
}

describe('canRecall', () => {
  it('本人、已送出、時窗內 → true', () => {
    expect(canRecall(mkMsg(), 'me', NOW)).toBe(true);
  });
  it('非本人 → false', () => {
    expect(canRecall(mkMsg({ sender_id: 'other' }), 'me', NOW)).toBe(false);
  });
  it('未送達(sending/failed)→ false', () => {
    expect(canRecall(mkMsg({ status: 'sending' }), 'me', NOW)).toBe(false);
    expect(canRecall(mkMsg({ status: 'failed' }), 'me', NOW)).toBe(false);
  });
  it('已刪除 / 已撤回 → false', () => {
    expect(canRecall(mkMsg({ deleted: true }), 'me', NOW)).toBe(false);
    expect(canRecall(mkMsg({ recalled: true }), 'me', NOW)).toBe(false);
  });
  it('超過 2 分鐘 → false', () => {
    expect(canRecall(mkMsg({ created_at: '2026-06-24T11:57:00Z' }), 'me', NOW)).toBe(false);
  });
  it('剛好 2 分鐘(端點)→ true', () => {
    expect(canRecall(mkMsg({ created_at: '2026-06-24T11:58:00Z' }), 'me', NOW)).toBe(true);
  });
});

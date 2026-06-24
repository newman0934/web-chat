import { describe, expect, it } from 'vitest';

import type { Message, SearchResult } from '../../contracts';
import { highlightParts, nextSearchCursor, toSearchResultView } from './search';

describe('highlightParts', () => {
  it('命中關鍵字切成 hit / 非 hit 段', () => {
    expect(highlightParts('明天的會議改期', '會議')).toEqual([
      { text: '明天的', hit: false },
      { text: '會議', hit: true },
      { text: '改期', hit: false },
    ]);
  });

  it('不分大小寫，且保留原文大小寫', () => {
    expect(highlightParts('Hello World', 'hello')).toEqual([
      { text: 'Hello', hit: true },
      { text: ' World', hit: false },
    ]);
  });

  it('多次出現都命中', () => {
    const parts = highlightParts('aXaXa', 'x');
    expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(['X', 'X']);
    expect(parts.map((p) => p.text).join('')).toBe('aXaXa');
  });

  it('無命中回整串非 hit', () => {
    expect(highlightParts('abc', 'z')).toEqual([{ text: 'abc', hit: false }]);
  });

  it('空白關鍵字回整串非 hit', () => {
    expect(highlightParts('abc', '   ')).toEqual([{ text: 'abc', hit: false }]);
  });

  it('特殊字元當一般字串比對（50% 字面）', () => {
    const parts = highlightParts('折扣 50% 起', '50%');
    expect(parts.find((p) => p.hit)?.text).toBe('50%');
  });
});

function mkMessage(over: Partial<Message> = {}): Message {
  return {
    id: 'm1',
    conversation_id: 'c1',
    sender_id: 'u-bob',
    content: '內容',
    created_at: '2026-06-24T12:00:00+00:00',
    read_count: 0,
    attachment: null,
    edited_at: null,
    deleted: false,
    reactions: [],
    ...over,
  };
}

describe('toSearchResultView', () => {
  it('1對1：標題為對方名、帶寄件者名', () => {
    const item: SearchResult = {
      message: mkMessage({ id: 'm9', content: '會議紀錄' }),
      conversation: {
        id: 'c1',
        type: 'direct',
        name: null,
        other_user: { id: 'u-bob', email: 'b@e.com', display_name: 'Bob' },
      },
      sender_name: 'Bob',
    };
    const v = toSearchResultView(item);
    expect(v).toMatchObject({
      messageId: 'm9',
      conversationId: 'c1',
      conversationTitle: 'Bob',
      senderName: 'Bob',
      content: '會議紀錄',
    });
  });

  it('群組：標題為群組名', () => {
    const item: SearchResult = {
      message: mkMessage({ sender_id: 'u-carol' }),
      conversation: { id: 'c2', type: 'group', name: '專案群', other_user: null },
      sender_name: 'Carol',
    };
    expect(toSearchResultView(item).conversationTitle).toBe('專案群');
    expect(toSearchResultView(item).senderName).toBe('Carol');
  });
});

describe('nextSearchCursor', () => {
  it('回 next_before', () => {
    expect(nextSearchCursor({ items: [], next_before: '2026-06-20T00:00:00+00:00' })).toBe(
      '2026-06-20T00:00:00+00:00',
    );
    expect(nextSearchCursor({ items: [], next_before: null })).toBeNull();
  });
});

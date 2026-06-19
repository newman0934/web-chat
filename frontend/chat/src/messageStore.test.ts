import { describe, expect, it } from 'vitest';

import type { Message } from '../../contracts';
import {
  addIncoming,
  addOptimistic,
  applyReadReceipt,
  fromHistory,
  makeOptimistic,
  markFailed,
  prependHistory,
  reconcileAck,
} from './messageStore';

function realMessage(id: string, content: string): Message {
  return {
    id,
    conversation_id: 'conv-1',
    sender_id: 'me',
    content,
    created_at: '2026-06-19T00:00:00Z',
    read_count: 0,
  };
}

describe('messageStore 樂觀更新', () => {
  it('makeOptimistic 產生 sending 狀態且帶 temp_id', () => {
    const m = makeOptimistic('conv-1', 'me', 'hi', 'tmp-1');
    expect(m.status).toBe('sending');
    expect(m.temp_id).toBe('tmp-1');
    expect(m.id).toBe('tmp-1');
  });

  it('reconcileAck 把樂觀訊息換成正式訊息', () => {
    let list = addOptimistic([], makeOptimistic('conv-1', 'me', 'hi', 'tmp-1'));
    list = reconcileAck(list, 'tmp-1', realMessage('real-1', 'hi'));
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('real-1');
    expect(list[0].status).toBe('sent');
  });

  it('reconcileAck 找不到 temp_id 時補上（去重）', () => {
    const real = realMessage('real-1', 'hi');
    let list = reconcileAck([], 'unknown', real);
    expect(list).toHaveLength(1);
    // 再來一次不應重複
    list = reconcileAck(list, 'unknown', real);
    expect(list).toHaveLength(1);
  });

  it('markFailed 標記對應訊息為 failed', () => {
    let list = addOptimistic([], makeOptimistic('conv-1', 'me', 'hi', 'tmp-1'));
    list = markFailed(list, 'tmp-1');
    expect(list[0].status).toBe('failed');
  });

  it('addIncoming 對重複 id 不重覆加入', () => {
    const real = realMessage('real-1', 'hi');
    let list = addIncoming([], real);
    list = addIncoming(list, real);
    expect(list).toHaveLength(1);
  });

  it('prependHistory 把較舊訊息插到前面並去重', () => {
    const current = fromHistory([realMessage('b', 'second')]);
    const merged = prependHistory(current, [
      realMessage('a', 'first'),
      realMessage('b', 'second'),
    ]);
    expect(merged.map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('applyReadReceipt 對指定訊息 read_count +1', () => {
    const list = fromHistory([realMessage('m1', 'a'), realMessage('m2', 'b')]);
    const next = applyReadReceipt(list, ['m1']);
    expect(next.find((m) => m.id === 'm1')!.read_count).toBe(1);
    expect(next.find((m) => m.id === 'm2')!.read_count).toBe(0);
  });
});

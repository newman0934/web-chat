import { beforeEach, describe, expect, it } from 'vitest';

import type { Conversation, Message } from '../../contracts';
import { makeOptimistic } from './messageStore';
import { useChatStore } from './store';

function realMsg(id: string, conversationId = 'c1', over: Partial<Message> = {}): Message {
  return {
    id,
    conversation_id: conversationId,
    sender_id: 'me',
    content: 'hi',
    created_at: '2026-06-20T00:00:00Z',
    read_count: 0,
    attachment: null,
    edited_at: null,
    deleted: false,
    reactions: [],
    ...over,
  };
}

function conv(id: string, unread: number): Conversation {
  return {
    id,
    type: 'direct',
    name: null,
    other_user: null,
    members: [],
    last_message: null,
    unread_count: unread,
    roles: {},
  };
}

beforeEach(() => {
  useChatStore.getState().reset();
});

describe('useChatStore', () => {
  it('reset 清空所有狀態', () => {
    const s = useChatStore.getState();
    s.setContacts([{ user_id: 'u', email: 'e', display_name: 'd', conversation_id: 'c' }]);
    s.setActiveId('c1');
    s.reset();
    const after = useChatStore.getState();
    expect(after.contacts).toEqual([]);
    expect(after.activeId).toBeNull();
    expect(after.messages).toEqual({});
  });

  it('appendOptimistic 後 ackMessage 把樂觀訊息換成正式訊息', () => {
    const s = useChatStore.getState();
    s.appendOptimistic('c1', makeOptimistic('c1', 'me', 'hi', 't1'));
    expect(useChatStore.getState().messages['c1']).toHaveLength(1);

    s.ackMessage('t1', realMsg('r1'));
    const list = useChatStore.getState().messages['c1'];
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('r1');
    expect(list[0].status).toBe('sent');
  });

  it('receiveMessage 依 id 去重', () => {
    const s = useChatStore.getState();
    s.receiveMessage(realMsg('r1'));
    s.receiveMessage(realMsg('r1'));
    expect(useChatStore.getState().messages['c1']).toHaveLength(1);
  });

  it('markRead 對指定訊息 read_count +1', () => {
    const s = useChatStore.getState();
    s.loadHistory('c1', [realMsg('m1'), realMsg('m2')]);
    s.markRead('c1', ['m1']);
    const list = useChatStore.getState().messages['c1'];
    expect(list.find((m) => m.id === 'm1')!.read_count).toBe(1);
    expect(list.find((m) => m.id === 'm2')!.read_count).toBe(0);
  });

  it('failMessage 跨對話把 temp_id 標記為 failed', () => {
    const s = useChatStore.getState();
    s.appendOptimistic('c2', makeOptimistic('c2', 'me', 'x', 'tmp-9'));
    s.failMessage('tmp-9');
    expect(useChatStore.getState().messages['c2'][0].status).toBe('failed');
  });

  it('clearUnread 將指定對話未讀數歸零', () => {
    const s = useChatStore.getState();
    s.setConversations([conv('c1', 3), conv('c2', 5)]);
    s.clearUnread('c1');
    const cs = useChatStore.getState().conversations;
    expect(cs.find((c) => c.id === 'c1')!.unread_count).toBe(0);
    expect(cs.find((c) => c.id === 'c2')!.unread_count).toBe(5);
  });

  it('updateMessage 套用到正確對話', () => {
    const s = useChatStore.getState();
    s.loadHistory('c1', [realMsg('m1')]);
    s.updateMessage({ ...realMsg('m1'), content: 'edited', conversation_id: 'c1' });
    expect(useChatStore.getState().messages['c1'][0].content).toBe('edited');
  });
});

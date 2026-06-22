import { beforeEach, describe, expect, it } from 'vitest';

import type { Conversation, Message, Notification } from '../../contracts';
import { makeOptimistic } from './messageStore';
import { useChatStore } from './store';

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

function convG(id: string): Conversation {
  return {
    id, type: 'group', name: 'G', other_user: null, members: [],
    last_message: null, unread_count: 0, roles: {},
  };
}

describe('removeConversation', () => {
  beforeEach(() => useChatStore.getState().reset());

  it('移除對話並清掉其訊息；若為 active 則清空 activeId', () => {
    const st = useChatStore.getState();
    st.setConversations([convG('c1'), convG('c2')]);
    st.loadHistory('c1', []);
    st.setActiveId('c1');
    st.removeConversation('c1');
    const s = useChatStore.getState();
    expect(s.conversations.map((c) => c.id)).toEqual(['c2']);
    expect(s.messages['c1']).toBeUndefined();
    expect(s.activeId).toBeNull();
  });

  it('移除非 active 對話不動 activeId', () => {
    const st = useChatStore.getState();
    st.setConversations([convG('c1'), convG('c2')]);
    st.setActiveId('c2');
    st.removeConversation('c1');
    expect(useChatStore.getState().activeId).toBe('c2');
  });
});

describe('useChatStore 站內通知', () => {
  it('setNotifications 帶入清單與伺服器未讀數', () => {
    const st = useChatStore.getState();
    st.setNotifications({ items: [notif('1'), notif('2', { read: true })], unread_count: 5 });
    const s = useChatStore.getState();
    expect(s.notifications).toHaveLength(2);
    expect(s.unreadCount).toBe(5); // 以伺服器為準(可能大於本頁未讀)
  });

  it('addNotification 插到最前、未讀 +1;同 id 不重覆計', () => {
    const st = useChatStore.getState();
    st.setNotifications({ items: [], unread_count: 0 });
    st.addNotification(notif('1'));
    st.addNotification(notif('2'));
    expect(useChatStore.getState().notifications.map((n) => n.id)).toEqual(['2', '1']);
    expect(useChatStore.getState().unreadCount).toBe(2);
    st.addNotification(notif('2', { read: true })); // 同 id 重入
    expect(useChatStore.getState().unreadCount).toBe(2);
  });

  it('markConversationRead 標已讀並扣掉 marked 筆未讀', () => {
    const st = useChatStore.getState();
    st.setNotifications({
      items: [notif('1', { conversation_id: 'c1' }), notif('2', { conversation_id: 'c2' })],
      unread_count: 2,
    });
    st.markConversationRead('c1', 1);
    const s = useChatStore.getState();
    expect(s.notifications.find((n) => n.id === '1')!.read).toBe(true);
    expect(s.notifications.find((n) => n.id === '2')!.read).toBe(false);
    expect(s.unreadCount).toBe(1);
  });
});

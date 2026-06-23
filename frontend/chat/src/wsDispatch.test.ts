import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Conversation, Message } from '../../contracts';
import { useChatStore } from './store';
import { dispatchServerMessage, type DispatchDeps } from './wsDispatch';

function msg(id: string, conversationId = 'c1', over: Partial<Message> = {}): Message {
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

function deps(over: Partial<DispatchDeps> = {}): DispatchDeps {
  return {
    currentUserId: 'me',
    reloadConversations: vi.fn(),
    sendRead: vi.fn(),
    handleCallSignal: vi.fn(),
    ...over,
  };
}

function conv(id: string, over: Partial<Conversation> = {}): Conversation {
  return {
    id, type: 'direct', name: null, other_user: null, members: [],
    last_message: null, unread_count: 0, roles: {}, ...over,
  };
}

beforeEach(() => {
  useChatStore.getState().reset();
});

describe('dispatchServerMessage', () => {
  it('ack 把樂觀訊息換成正式訊息', () => {
    const st = useChatStore.getState();
    st.appendOptimistic('c1', {
      id: 't1', temp_id: 't1', conversation_id: 'c1', sender_id: 'me', content: 'hi',
      created_at: '2026-06-20T00:00:00Z', read_count: 0, attachment: null, edited_at: null,
      deleted: false, reactions: [], status: 'sending',
    });
    dispatchServerMessage({ type: 'ack', temp_id: 't1', message: msg('r1') }, deps());
    const list = useChatStore.getState().messages['c1'];
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('r1');
  });

  it('message:對話不在清單(新對話)→ 退回重抓', () => {
    const d = deps();
    dispatchServerMessage({ type: 'message', message: msg('m1', 'c1') }, d);
    expect(useChatStore.getState().messages['c1']).toHaveLength(1);
    expect(d.sendRead).not.toHaveBeenCalled();
    expect(d.reloadConversations).toHaveBeenCalledOnce();
  });

  it('message:對話在清單 → 就地更新(last_message/未讀/置頂)、不重抓', () => {
    useChatStore.getState().setConversations([conv('c0'), conv('c1')]);
    const d = deps();
    dispatchServerMessage(
      { type: 'message', message: msg('m1', 'c1', { sender_id: 'other' }) },
      d,
    );
    expect(d.reloadConversations).not.toHaveBeenCalled();
    const convs = useChatStore.getState().conversations;
    expect(convs[0].id).toBe('c1'); // 置頂
    expect(convs[0].last_message?.id).toBe('m1');
    expect(convs[0].unread_count).toBe(1);
  });

  it('message:自己送出的廣播(轉發回聲)不增未讀', () => {
    useChatStore.getState().setConversations([conv('c1')]);
    dispatchServerMessage(
      { type: 'message', message: msg('m1', 'c1', { sender_id: 'me' }) },
      deps(),
    );
    expect(useChatStore.getState().conversations[0].unread_count).toBe(0);
  });

  it('message:正開著該對話時送 read', () => {
    useChatStore.getState().setActiveId('c1');
    const d = deps();
    dispatchServerMessage({ type: 'message', message: msg('m1', 'c1') }, d);
    expect(d.sendRead).toHaveBeenCalledWith('c1');
  });

  it('error 帶 temp_id 標記失敗', () => {
    const st = useChatStore.getState();
    st.appendOptimistic('c1', {
      id: 't1', temp_id: 't1', conversation_id: 'c1', sender_id: 'me', content: 'hi',
      created_at: '2026-06-20T00:00:00Z', read_count: 0, attachment: null, edited_at: null,
      deleted: false, reactions: [], status: 'sending',
    });
    dispatchServerMessage({ type: 'error', reason: 'db_error', temp_id: 't1' }, deps());
    expect(useChatStore.getState().messages['c1'][0].status).toBe('failed');
  });

  it('notification 加入並累計未讀', () => {
    dispatchServerMessage({
      type: 'notification',
      notification: {
        id: 'n1', type: 'reply', actor: { id: 'a', display_name: 'A' },
        conversation_id: 'c1', message_id: 'm1', message_preview: 'x', emoji: null,
        read: false, created_at: '2026-06-20T00:00:00Z',
      },
    }, deps());
    expect(useChatStore.getState().unreadCount).toBe(1);
  });

  it('presence 更新 presence map', () => {
    dispatchServerMessage(
      { type: 'presence', user_id: 'u1', online: true, last_seen_at: null },
      deps(),
    );
    expect(useChatStore.getState().presence.u1.online).toBe(true);
  });

  it('conversation_updated 重載清單', () => {
    const d = deps();
    dispatchServerMessage({ type: 'conversation_updated', conversation_id: 'c1' }, d);
    expect(d.reloadConversations).toHaveBeenCalledOnce();
  });

  it('call_* 轉交 handleCallSignal', () => {
    const d = deps();
    const callMsg = { type: 'call_offer' as const, from: { id: 'a', display_name: 'A' }, sdp: { type: 'offer' as const, sdp: 'x' } };
    dispatchServerMessage(callMsg, d);
    expect(d.handleCallSignal).toHaveBeenCalledWith(callMsg);
  });
});

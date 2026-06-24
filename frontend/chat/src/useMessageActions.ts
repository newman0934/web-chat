// 訊息相關的 WS 動作（送出 / 重試 / 編輯 / 刪除 / 表情 / 還原 / 轉發）與編輯歷史載入，集中成 hook。
// 以注入的 stable `send`（包裝 socketRef）發訊，故各 callback 參考穩定、不因 socket 換參考而重建。

import { useCallback } from 'react';

import type { ClientWsMessage, MessageVersion, ReplyPreview } from '../../contracts';
import type { ApiClient } from './api';
import { makeOptimistic } from './messageStore';
import { useChatStore } from './store';

type Send = (m: ClientWsMessage) => boolean;

export function useMessageActions(send: Send, api: ApiClient, currentUserId: string) {
  /** 樂觀送出訊息：先插入 UI，再經 WS 送出；連線不可用則標 failed。 */
  const sendMessage = useCallback(
    (content: string, attachmentId?: string, replyToMessageId?: string, replyPreview?: ReplyPreview | null) => {
      const st = useChatStore.getState();
      const active = st.activeId;
      if (!active) return;
      const tempId = crypto.randomUUID();
      // 樂觀訊息先不帶附件預覽，待 server ack 帶回正式 attachment 再顯示。
      st.appendOptimistic(active, makeOptimistic(active, currentUserId, content, tempId, null, replyPreview ?? null));
      const ok = send({
        type: 'message',
        conversation_id: active,
        content,
        temp_id: tempId,
        attachment_id: attachmentId,
        ...(replyToMessageId !== undefined ? { reply_to_message_id: replyToMessageId } : {}),
      });
      if (!ok) useChatStore.getState().failMessage(tempId);
    },
    [send, currentUserId],
  );

  /** 重送 failed 訊息：沿用原 temp_id 以便 ACK 對齊。 */
  const retry = useCallback(
    (tempId: string) => {
      const st = useChatStore.getState();
      const active = st.activeId;
      if (!active) return;
      const failed = (st.messages[active] ?? []).find((m) => m.temp_id === tempId);
      if (!failed) return;
      st.resendMessage(active, tempId);
      const ok = send({
        type: 'message',
        conversation_id: active,
        content: failed.content,
        temp_id: tempId,
      });
      if (!ok) useChatStore.getState().failMessage(tempId);
    },
    [send],
  );

  const editMessage = useCallback(
    (id: string, content: string) => { send({ type: 'edit', message_id: id, content }); },
    [send],
  );
  const deleteMessage = useCallback(
    (id: string) => { send({ type: 'delete', message_id: id }); },
    [send],
  );
  const toggleReaction = useCallback(
    (id: string, emoji: string) => { send({ type: 'react', message_id: id, emoji }); },
    [send],
  );
  const restoreMessage = useCallback(
    (id: string) => { send({ type: 'restore', message_id: id }); },
    [send],
  );
  const forwardMessage = useCallback(
    (messageId: string, toConversationId: string) => {
      send({ type: 'forward', message_id: messageId, to_conversation_id: toConversationId });
    },
    [send],
  );
  const pinMessage = useCallback(
    (id: string) => { send({ type: 'pin', message_id: id }); },
    [send],
  );
  const unpinMessage = useCallback(
    (id: string) => { send({ type: 'unpin', message_id: id }); },
    [send],
  );
  const loadEditHistory = useCallback(
    (id: string): Promise<MessageVersion[]> => api.getMessageEdits(id),
    [api],
  );

  return {
    sendMessage,
    retry,
    editMessage,
    deleteMessage,
    toggleReaction,
    restoreMessage,
    forwardMessage,
    pinMessage,
    unpinMessage,
    loadEditHistory,
  };
}

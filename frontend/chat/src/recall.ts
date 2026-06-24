// 訊息撤回的純邏輯(抽離 React,便於單元測試)。

import { RECALL_WINDOW_MS } from '../../contracts';
import type { ChatMessage } from './messageStore';

/**
 * 是否可撤回:本人送出、已送達(sent)、未刪除、未撤回,且距送出未超過時窗。
 * now 注入以利測試。
 */
export function canRecall(
  message: ChatMessage,
  currentUserId: string,
  now: number = Date.now(),
): boolean {
  if (message.sender_id !== currentUserId) return false;
  if (message.status !== 'sent') return false;
  if (message.deleted || message.recalled) return false;
  return now - new Date(message.created_at).getTime() <= RECALL_WINDOW_MS;
}

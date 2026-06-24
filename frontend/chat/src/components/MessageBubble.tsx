// 單則訊息泡泡：區分我方/對方，我方顯示傳送狀態與重試；含附件、回覆引用、表情、編輯/刪除/還原、回覆/轉發。

import { useState } from 'react';

import { EDIT_WINDOW_MS, RESTORE_WINDOW_MS } from '../../../contracts';
import type { MessageVersion } from '../../../contracts';
import type { ChatMessage } from '../messageStore';
import { EditHistoryPopover } from './EditHistoryPopover';
import { ReactionPicker } from './ReactionPicker';
import { ReplyQuoteBlock } from './ReplyQuoteBlock';

/** 單則訊息泡泡：區分我方/對方，我方顯示傳送狀態與重試。 */
export function MessageBubble({
  message, mine, isGroup, senderName, memberNames, onRetry, attachmentUrl,
  currentUserId, onEdit, onDelete, onReact, onRestore, loadEditHistory,
  onReply, onForward, onScrollToMessage, bubbleRef, highlighted = false,
}: {
  message: ChatMessage; mine: boolean; isGroup: boolean;
  senderName?: string;
  memberNames: Record<string, string>;
  onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  currentUserId: string;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
  onRestore: (id: string) => void;
  loadEditHistory: (id: string) => Promise<MessageVersion[]>;
  onReply: (message: ChatMessage) => void;
  onForward?: (message: ChatMessage) => void;
  onScrollToMessage: (id: string) => void;
  bubbleRef: (el: HTMLDivElement | null) => void;
  /** 搜尋跳轉時暫時高亮命中訊息（數秒後由 Thread 清除）。 */
  highlighted?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [showHistory, setShowHistory] = useState(false);

  // 系統訊息：置中灰字一行，無泡泡 / 狀態 / 編輯刪除 / 表情。
  if (message.kind === 'system') {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">
          {message.content}
        </span>
      </div>
    );
  }

  // 已刪除：整個泡泡換成佔位，寄件人且在還原時窗內顯示還原鈕
  if (message.deleted) {
    const canRestore =
      mine && message.deleted_at != null &&
      Date.now() - new Date(message.deleted_at).getTime() < RESTORE_WINDOW_MS;
    return (
      <div className={`flex items-center gap-2 ${mine ? 'justify-end' : 'justify-start'}`}>
        <div className="max-w-[70%] rounded-2xl bg-slate-100 px-4 py-2 text-sm italic text-slate-400">
          此訊息已刪除
        </div>
        {canRestore && (
          <button
            type="button"
            onClick={() => onRestore(message.id)}
            className="text-xs text-indigo-600 underline"
          >
            還原
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      data-message-id={message.id}
      data-highlighted={highlighted ? 'true' : undefined}
      ref={bubbleRef}
      className={`flex flex-col rounded-xl transition-colors duration-500 ${
        mine ? 'items-end' : 'items-start'
      } ${highlighted ? 'bg-yellow-100 ring-2 ring-yellow-400' : ''}`}
    >
      <div className={`relative max-w-[70%] rounded-2xl px-4 py-2 ${mine ? 'bg-indigo-600 text-white' : 'bg-white text-slate-800 shadow'}`}>
        {isGroup && !mine && senderName && (
          <p className="mb-0.5 text-xs font-medium text-indigo-500">{senderName}</p>
        )}
        {message.forwarded_from && (
          <p className="mb-1 text-xs text-slate-400">↪ 轉發自 {message.forwarded_from.display_name}</p>
        )}
        {message.reply_to && (
          <ReplyQuoteBlock
            replyTo={message.reply_to}
            memberNames={memberNames}
            onScrollToMessage={onScrollToMessage}
          />
        )}
        {message.attachment && (
          message.attachment.is_image ? (
            <a href={attachmentUrl(message.attachment.id)} target="_blank" rel="noreferrer">
              <img
                src={attachmentUrl(message.attachment.id)}
                alt={message.attachment.original_name}
                className="mb-1 max-h-60 max-w-full rounded-lg"
              />
            </a>
          ) : (
            <a
              href={attachmentUrl(message.attachment.id)}
              target="_blank"
              rel="noreferrer"
              className="mb-1 flex items-center gap-2 rounded-lg bg-black/10 px-3 py-2 text-sm underline"
            >
              📎 {message.attachment.original_name}
              <span className="opacity-70">({message.attachment.size} bytes)</span>
            </a>
          )
        )}
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {mine && (
          <p className="mt-1 text-right text-xs opacity-80">
            {message.edited_at && (
              <button type="button" onClick={() => setShowHistory((v) => !v)} className="mr-1 underline opacity-70">
                已編輯
              </button>
            )}
            {message.status === 'sending' && '傳送中…'}
            {message.status === 'sent' && (
              isGroup
                ? (message.read_count > 0 ? `已讀 ${message.read_count}` : '已送出')
                : (message.read_count > 0 ? '已讀' : '已送出')
            )}
            {message.status === 'failed' && (
              <button onClick={() => message.temp_id && onRetry(message.temp_id)} className="underline">
                未送出，點擊重試
              </button>
            )}
          </p>
        )}
        {!mine && message.edited_at && (
          <button type="button" onClick={() => setShowHistory((v) => !v)} className="mt-0.5 text-xs underline opacity-70">
            已編輯
          </button>
        )}
        {showHistory && (
          <EditHistoryPopover
            messageId={message.id}
            load={loadEditHistory}
            onClose={() => setShowHistory(false)}
          />
        )}
      </div>

      {/* 表情列 */}
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {message.reactions.map((r) => {
          const mineReacted = r.user_ids.includes(currentUserId);
          return (
            <button
              key={r.emoji}
              type="button"
              aria-label={`${r.emoji} 反應 ${r.count} 人${mineReacted ? '(含你)' : ''}，點擊切換`}
              aria-pressed={mineReacted}
              onClick={() => onReact(message.id, r.emoji)}
              className={`rounded-full px-2 py-0.5 text-xs ${
                mineReacted ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'
              }`}
            >
              {r.emoji} {r.count}
            </button>
          );
        })}
        <ReactionPicker onPick={(e) => onReact(message.id, e)} />
      </div>

      {/* 自己、已送達（sent）且未刪：刪除恆顯示；編輯僅 15 分鐘內 */}
      {mine && message.status === 'sent' && (
        editing ? (
          <form
            className="mt-1 flex gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              const v = draft.trim();
              if (v) onEdit(message.id, v);
              setEditing(false);
            }}
          >
            <input
              className="input text-slate-800"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="編輯訊息"
            />
            <button type="submit" className="text-xs text-indigo-600">儲存</button>
            <button type="button" onClick={() => setEditing(false)} className="text-xs text-slate-500">取消</button>
          </form>
        ) : (
          <div className="mt-0.5 flex gap-2 text-xs opacity-70">
            {Date.now() - new Date(message.created_at).getTime() < EDIT_WINDOW_MS && (
              <button
                type="button"
                onClick={() => { setDraft(message.content); setEditing(true); }}
              >
                編輯
              </button>
            )}
            <button
              type="button"
              onClick={() => onDelete(message.id)}
            >
              刪除
            </button>
          </div>
        )
      )}

      {/* 回覆 / 轉發鈕：未刪且非系統訊息（含自己/對方皆顯示） */}
      {message.status !== 'sending' && (
        <div className="mt-0.5 flex gap-2 text-xs opacity-60">
          <button
            type="button"
            aria-label="回覆"
            onClick={() => onReply(message)}
            className="hover:opacity-100"
          >
            回覆
          </button>
          {onForward && (
            <button
              type="button"
              aria-label="轉發"
              onClick={() => onForward(message)}
              className="hover:opacity-100"
            >
              轉發
            </button>
          )}
        </div>
      )}
    </div>
  );
}

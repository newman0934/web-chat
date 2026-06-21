// 右側對話視窗：訊息泡泡串、載入更早訊息、輸入框；
// 我方訊息顯示傳送狀態（傳送中 / 已送出 / 已讀 / 未送出可重試）。

import { useEffect, useRef, useState } from 'react';

import { QUICK_REACTIONS } from '../../../contracts';
import type { Attachment } from '../../../contracts';
import type { ChatMessage } from '../messageStore';

interface ThreadProps {
  title: string;
  isGroup: boolean;
  memberNames: Record<string, string>;
  messages: ChatMessage[];
  currentUserId: string;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onSend: (content: string, attachmentId?: string) => void;
  onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  onUpload: (file: File) => Promise<Attachment | null>;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
  onStartCall?: () => void;
  onShowGroupInfo?: () => void;
}

/** 右側對話視窗：訊息列表、載入更多、輸入框與送出。 */
export function Thread({
  title,
  isGroup,
  memberNames,
  messages,
  currentUserId,
  canLoadMore,
  onLoadMore,
  onSend,
  onRetry,
  attachmentUrl,
  onUpload,
  onEdit,
  onDelete,
  onReact,
  onStartCall,
  onShowGroupInfo,
}: ThreadProps) {
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // 新訊息加入時自動捲到底部。
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages.length]);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    setUploading(true);
    const att = await onUpload(f);
    setUploading(false);
    if (att) setPending(att);
  };

  /** 送出輸入框內容並清空 draft。 */
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content && !pending) return;
    onSend(content, pending?.id);
    setDraft('');
    setPending(null);
  };

  return (
    <section className="flex h-full flex-1 flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <h2 className="font-semibold text-slate-800">{title}</h2>
        <div className="flex items-center gap-1">
          {onStartCall && (
            <button
              type="button"
              aria-label="視訊通話"
              onClick={onStartCall}
              className="rounded-lg px-3 py-1 text-lg hover:bg-slate-100"
            >
              📞
            </button>
          )}
          {onShowGroupInfo && (
            <button
              type="button"
              aria-label="群組資訊"
              onClick={onShowGroupInfo}
              className="rounded-lg px-3 py-1 text-lg hover:bg-slate-100"
            >
              ⓘ
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 space-y-2 overflow-y-auto px-6 py-4">
        {canLoadMore && (
          <div className="text-center">
            <button
              onClick={onLoadMore}
              className="rounded-full bg-white px-4 py-1 text-sm text-indigo-600 shadow hover:bg-indigo-50"
            >
              載入更早的訊息
            </button>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble
            key={m.temp_id ?? m.id}
            message={m}
            mine={m.sender_id === currentUserId}
            isGroup={isGroup}
            senderName={memberNames[m.sender_id]}
            onRetry={onRetry}
            attachmentUrl={attachmentUrl}
            currentUserId={currentUserId}
            onEdit={onEdit}
            onDelete={onDelete}
            onReact={onReact}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={submit}
        className="flex gap-2 border-t border-slate-200 bg-white p-4"
      >
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          onChange={onPick}
        />
        <button
          type="button"
          aria-label="附加檔案"
          onClick={() => fileRef.current?.click()}
          className="rounded-lg px-3 text-slate-500 hover:bg-slate-100"
        >
          📎
        </button>
        <div className="flex flex-1 flex-col gap-1">
          {pending && (
            <div className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-1 text-sm text-slate-700">
              <span className="truncate">{pending.original_name}</span>
              <button
                type="button"
                aria-label="移除附件"
                onClick={() => setPending(null)}
                className="ml-auto text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>
          )}
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="輸入訊息…"
            aria-label="訊息輸入"
            className="input flex-1"
          />
        </div>
        <button
          type="submit"
          disabled={uploading}
          className="rounded-lg bg-indigo-600 px-5 font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          送出
        </button>
      </form>
    </section>
  );
}

/** 小元件：快速表情選擇器，點「＋」展開 QUICK_REACTIONS。 */
function ReactionPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative">
      <button
        type="button"
        aria-label="新增表情"
        onClick={() => setOpen((v) => !v)}
        className="rounded-full px-2 py-0.5 text-xs bg-slate-100 text-slate-500 hover:bg-slate-200"
      >
        ＋
      </button>
      {open && (
        <span className="absolute bottom-full left-0 z-10 mb-1 flex gap-1 rounded-xl bg-white p-1 shadow-lg">
          {QUICK_REACTIONS.map((e) => (
            <button
              key={e}
              type="button"
              onClick={() => { onPick(e); setOpen(false); }}
              className="rounded px-1 hover:bg-slate-100"
            >
              {e}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}

/** 單則訊息泡泡：區分我方/對方，我方顯示傳送狀態與重試。 */
function MessageBubble({
  message, mine, isGroup, senderName, onRetry, attachmentUrl,
  currentUserId, onEdit, onDelete, onReact,
}: {
  message: ChatMessage; mine: boolean; isGroup: boolean;
  senderName?: string; onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  currentUserId: string;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');

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

  // 已刪除：整個泡泡換成佔位
  if (message.deleted) {
    return (
      <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
        <div className="max-w-[70%] rounded-2xl bg-slate-100 px-4 py-2 text-sm italic text-slate-400">
          此訊息已刪除
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-col ${mine ? 'items-end' : 'items-start'}`}>
      <div className={`max-w-[70%] rounded-2xl px-4 py-2 ${mine ? 'bg-indigo-600 text-white' : 'bg-white text-slate-800 shadow'}`}>
        {isGroup && !mine && senderName && (
          <p className="mb-0.5 text-xs font-medium text-indigo-500">{senderName}</p>
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
            {message.edited_at && <span className="text-xs opacity-70">已編輯</span>}
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
          <p className="mt-0.5 text-xs opacity-70">已編輯</p>
        )}
      </div>

      {/* 表情列 */}
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {message.reactions.map((r) => (
          <button
            key={r.emoji}
            type="button"
            onClick={() => onReact(message.id, r.emoji)}
            className={`rounded-full px-2 py-0.5 text-xs ${
              r.user_ids.includes(currentUserId) ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'
            }`}
          >
            {r.emoji} {r.count}
          </button>
        ))}
        <ReactionPicker onPick={(e) => onReact(message.id, e)} />
      </div>

      {/* 自己、已送達（sent）且未刪：編輯/刪除（樂觀訊息尚未落庫，不顯示） */}
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
            <button
              type="button"
              onClick={() => { setDraft(message.content); setEditing(true); }}
            >
              編輯
            </button>
            <button
              type="button"
              onClick={() => onDelete(message.id)}
            >
              刪除
            </button>
          </div>
        )
      )}
    </div>
  );
}

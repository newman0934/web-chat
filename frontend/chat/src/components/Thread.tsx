// 右側對話視窗：訊息泡泡串、載入更早訊息、輸入框；
// 我方訊息顯示傳送狀態（傳送中 / 已送出 / 已讀 / 未送出可重試）。

import { useEffect, useRef, useState } from 'react';

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
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <h2 className="font-semibold text-slate-800">{title}</h2>
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

/** 單則訊息泡泡：區分我方/對方，我方顯示傳送狀態與重試。 */
function MessageBubble({ message, mine, isGroup, senderName, onRetry, attachmentUrl }: {
  message: ChatMessage; mine: boolean; isGroup: boolean;
  senderName?: string; onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
}) {
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
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
      </div>
    </div>
  );
}

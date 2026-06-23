// 右側對話視窗：訊息泡泡串、載入更早訊息、輸入框；
// 我方訊息顯示傳送狀態（傳送中 / 已送出 / 已讀 / 未送出可重試）。

import { useEffect, useRef, useState } from 'react';

import type { Attachment, MessageVersion, ReplyPreview } from '../../../contracts';
import type { ChatMessage } from '../messageStore';
import { MessageBubble } from './MessageBubble';

interface ThreadProps {
  title: string;
  /** 1對1 對方的 presence 文案（「在線」/「最後上線 X」/「離線」）；群組或無對象時為 null。 */
  statusText?: string | null;
  isGroup: boolean;
  memberNames: Record<string, string>;
  messages: ChatMessage[];
  currentUserId: string;
  canLoadMore: boolean;
  onLoadMore: () => void;
  onSend: (content: string, attachmentId?: string, replyToMessageId?: string, replyPreview?: ReplyPreview | null) => void;
  onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  onUpload: (file: File) => Promise<Attachment | null>;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
  onRestore?: (id: string) => void;
  loadEditHistory?: (id: string) => Promise<MessageVersion[]>;
  onStartCall?: () => void;
  onShowGroupInfo?: () => void;
  onForward?: (message: ChatMessage) => void;
}

/** 右側對話視窗：訊息列表、載入更多、輸入框與送出。 */
export function Thread({
  title,
  statusText = null,
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
  onRestore = () => {},
  loadEditHistory = async () => [],
  onStartCall,
  onShowGroupInfo,
  onForward,
}: ThreadProps) {
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState(false);
  const [replyingTo, setReplyingTo] = useState<ChatMessage | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // Map from message id to DOM element ref, used for scroll-to-original.
  const bubbleRefs = useRef<Record<string, HTMLDivElement | null>>({});

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

  /** 捲動到指定訊息（若在清單內），否則 no-op。 */
  const scrollToMessage = (messageId: string) => {
    const el = bubbleRefs.current[messageId];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  /** 送出輸入框內容並清空 draft。 */
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content && !pending) return;
    if (replyingTo) {
      const preview: ReplyPreview = {
        id: replyingTo.id,
        sender_id: replyingTo.sender_id,
        content: replyingTo.content,
        deleted: !!replyingTo.deleted,
        has_attachment: !!replyingTo.attachment,
      };
      onSend(content, pending?.id, replyingTo.id, preview);
      setReplyingTo(null);
    } else {
      onSend(content, pending?.id);
    }
    setDraft('');
    setPending(null);
  };

  return (
    <section className="flex h-full flex-1 flex-col bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div className="min-w-0">
          <h2 className="font-semibold text-slate-800">{title}</h2>
          {statusText && (
            <p data-testid="presence-status" className="text-xs text-slate-400">
              {statusText}
            </p>
          )}
        </div>
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
            memberNames={memberNames}
            onRetry={onRetry}
            attachmentUrl={attachmentUrl}
            currentUserId={currentUserId}
            onEdit={onEdit}
            onDelete={onDelete}
            onReact={onReact}
            onRestore={onRestore}
            loadEditHistory={loadEditHistory}
            onReply={setReplyingTo}
            onForward={onForward}
            onScrollToMessage={scrollToMessage}
            bubbleRef={(el) => { bubbleRefs.current[m.id] = el; }}
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
          {replyingTo && (
            <div
              data-testid="reply-banner"
              className="flex items-center gap-2 rounded-lg bg-indigo-50 border-l-4 border-indigo-400 px-3 py-1 text-sm text-slate-700"
            >
              <span className="font-medium text-indigo-600 shrink-0">
                {memberNames[replyingTo.sender_id] ?? '對方'}
              </span>
              <span className="truncate opacity-80">{replyingTo.content}</span>
              <button
                type="button"
                aria-label="取消回覆"
                onClick={() => setReplyingTo(null)}
                className="ml-auto text-slate-400 hover:text-slate-600 shrink-0"
              >
                ✕
              </button>
            </div>
          )}
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

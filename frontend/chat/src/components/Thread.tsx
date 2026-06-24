// 右側對話視窗：訊息泡泡串、載入更早訊息、輸入框；
// 我方訊息顯示傳送狀態（傳送中 / 已送出 / 已讀 / 未送出可重試）。

import { useEffect, useRef, useState } from 'react';

import type { Attachment, Message, MessageVersion, ReplyPreview } from '../../../contracts';
import { validateAttachments } from '../attachments';
import type { ChatMessage } from '../messageStore';
import { MessageBubble } from './MessageBubble';
import { PinnedBar } from './PinnedBar';

/** 上傳結果：成功帶 attachment，失敗帶可顯示的訊息（如「檔案過大」）。 */
export type UploadResult =
  | { ok: true; attachment: Attachment }
  | { ok: false; message: string };

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
  onSend: (content: string, attachmentIds?: string[], replyToMessageId?: string, replyPreview?: ReplyPreview | null) => void;
  onRetry: (tempId: string) => void;
  attachmentUrl: (id: string) => string;
  onUpload: (file: File) => Promise<UploadResult>;
  onEdit: (id: string, content: string) => void;
  onDelete: (id: string) => void;
  onReact: (id: string, emoji: string) => void;
  onRestore?: (id: string) => void;
  loadEditHistory?: (id: string) => Promise<MessageVersion[]>;
  onStartCall?: () => void;
  onShowGroupInfo?: () => void;
  onForward?: (message: ChatMessage) => void;
  /** 搜尋跳轉目標訊息 id；nonce 每次跳轉遞增以便重跳同一則。 */
  jumpToMessageId?: string | null;
  jumpNonce?: number;
  // ---- 釘選 ----
  pins?: Message[];
  canPin?: boolean;
  onPin?: (id: string) => void;
  onUnpin?: (id: string) => void;
  onRecall?: (id: string) => void;
  /** 釘選列點擊：跳轉到該訊息（沿用搜尋跳轉機制）。 */
  onJumpToMessage?: (id: string) => void;
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
  jumpToMessageId = null,
  jumpNonce = 0,
  pins = [],
  canPin = false,
  onPin,
  onUnpin,
  onRecall,
  onJumpToMessage,
}: ThreadProps) {
  const [draft, setDraft] = useState('');
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [pending, setPending] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [replyingTo, setReplyingTo] = useState<ChatMessage | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // message id → DOM 元素 ref 對照,用於捲動到原訊息。
  const bubbleRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // 新訊息加入時自動捲到底部。
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: 'smooth' });
  }, [messages.length]);

  // 搜尋跳轉:目標訊息渲染後捲動定位並高亮,約 2 秒後清除高亮。
  // 依賴 messages 確保視窗載入後(bubble 進 DOM)才執行;delay 讓它贏過上面的捲到底部。
  useEffect(() => {
    if (!jumpToMessageId) return;
    if (!bubbleRefs.current[jumpToMessageId]) return;
    const scrollTimer = setTimeout(() => {
      bubbleRefs.current[jumpToMessageId]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 80);
    setHighlightId(jumpToMessageId);
    const clearTimer = setTimeout(() => setHighlightId(null), 2000);
    return () => {
      clearTimeout(scrollTimer);
      clearTimeout(clearTimer);
    };
    // jumpNonce 變動代表一次新的跳轉(即使目標同一則也重觸發)。
  }, [jumpNonce, jumpToMessageId, messages]);

  const onPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (files.length === 0) return;
    setUploadError(null);
    // 前端即時驗證:數量 / 單檔 / 總量(以目前待送 + 新選取)。
    const check = validateAttachments(pending.map((p) => p.size), files.map((f) => f.size));
    if (!check.ok) {
      setUploadError(check.error ?? '附件不符限制');
      return;
    }
    setUploading(true);
    for (const f of files) {
      const res = await onUpload(f);
      if (res.ok) setPending((prev) => [...prev, res.attachment]);
      else { setUploadError(res.message); break; }
    }
    setUploading(false);
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
    if (!content && pending.length === 0) return;
    const ids = pending.map((p) => p.id);
    if (replyingTo) {
      const preview: ReplyPreview = {
        id: replyingTo.id,
        sender_id: replyingTo.sender_id,
        content: replyingTo.content,
        deleted: !!replyingTo.deleted,
        has_attachment: (replyingTo.attachments?.length ?? 0) > 0,
      };
      onSend(content, ids, replyingTo.id, preview);
      setReplyingTo(null);
    } else {
      onSend(content, ids);
    }
    setDraft('');
    setPending([]);
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

      <PinnedBar
        pins={pins}
        canManage={canPin}
        onJump={(id) => onJumpToMessage?.(id)}
        onUnpin={(id) => onUnpin?.(id)}
      />

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
            highlighted={m.id === highlightId}
            canPin={canPin}
            onPin={onPin}
            onUnpin={onUnpin}
            onRecall={onRecall}
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
          multiple
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
          {pending.length > 0 && (
            <ul className="flex flex-wrap gap-1" data-testid="pending-attachments">
              {pending.map((p) => (
                <li key={p.id} className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-1 text-sm text-slate-700">
                  <span className="max-w-[12rem] truncate">{p.original_name}</span>
                  <button
                    type="button"
                    aria-label={`移除附件 ${p.original_name}`}
                    onClick={() => setPending((prev) => prev.filter((x) => x.id !== p.id))}
                    className="text-slate-400 hover:text-slate-600"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
          {uploadError && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-lg bg-red-50 border-l-4 border-red-400 px-3 py-1 text-sm text-red-700"
            >
              <span className="truncate">{uploadError}</span>
              <button
                type="button"
                aria-label="關閉上傳錯誤"
                onClick={() => setUploadError(null)}
                className="ml-auto text-red-400 hover:text-red-600 shrink-0"
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

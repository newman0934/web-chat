// 訊息泡泡內的引用塊：顯示被回覆訊息的寄件人名與摘要，可點擊捲動到原訊息。

import type { ReplyPreview } from '../../../contracts';

/** 引用塊：顯示被回覆訊息的寄件人名與摘要，可點擊捲動到原訊息。 */
export function ReplyQuoteBlock({
  replyTo,
  memberNames,
  onScrollToMessage,
}: {
  replyTo: ReplyPreview;
  memberNames: Record<string, string>;
  onScrollToMessage: (id: string) => void;
}) {
  const senderName = memberNames[replyTo.sender_id] ?? '對方';
  return (
    <button
      type="button"
      onClick={() => onScrollToMessage(replyTo.id)}
      className="mb-1 w-full text-left rounded-lg border-l-4 border-indigo-300 bg-black/5 px-2 py-1 text-xs"
    >
      <span className="block font-medium text-indigo-500">{senderName}</span>
      <span className="block truncate opacity-80">
        {replyTo.deleted ? '原訊息已刪除' : replyTo.content}
      </span>
    </button>
  );
}

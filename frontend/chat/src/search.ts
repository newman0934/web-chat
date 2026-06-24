// 訊息搜尋的純邏輯（抽離 React，便於單元測試）：高亮切片、結果 view model、分頁游標。

import type { SearchResponse, SearchResult } from '../../contracts';

export interface HighlightPart {
  text: string;
  hit: boolean;
}

/**
 * 把 text 依關鍵字 q 切成片段，命中段（不分大小寫、當一般字串比對）標 hit=true，供渲染高亮。
 * q 空白或無命中時回單一非命中段（整串原文）。
 */
export function highlightParts(text: string, q: string): HighlightPart[] {
  const query = q.trim();
  if (!query) return [{ text, hit: false }];

  const parts: HighlightPart[] = [];
  const lowerText = text.toLowerCase();
  const lowerQ = query.toLowerCase();
  let i = 0;
  while (i < text.length) {
    const idx = lowerText.indexOf(lowerQ, i);
    if (idx === -1) {
      parts.push({ text: text.slice(i), hit: false });
      break;
    }
    if (idx > i) parts.push({ text: text.slice(i, idx), hit: false });
    parts.push({ text: text.slice(idx, idx + query.length), hit: true });
    i = idx + query.length;
  }
  return parts.length > 0 ? parts : [{ text, hit: false }];
}

export interface SearchResultView {
  messageId: string;
  conversationId: string;
  /** 群組顯示群組名、1對1 顯示對方名。 */
  conversationTitle: string;
  senderName: string;
  content: string;
  createdAt: string;
}

/** 搜尋結果 → 畫面 view model（決定對話標題、寄件者、片段等顯示用欄位）。 */
export function toSearchResultView(item: SearchResult): SearchResultView {
  const conv = item.conversation;
  const title =
    conv.type === 'group'
      ? conv.name ?? '群組'
      : conv.other_user?.display_name ?? '對話';
  return {
    messageId: item.message.id,
    conversationId: conv.id,
    conversationTitle: title,
    senderName: item.sender_name,
    content: item.message.content,
    createdAt: item.message.created_at,
  };
}

/** 取下一頁游標；無更多回 null。 */
export function nextSearchCursor(resp: SearchResponse): string | null {
  return resp.next_before;
}

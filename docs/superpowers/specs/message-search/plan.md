# 訊息搜尋（message-search）Plan

## 架構決策

- **比對**：`lower(col) LIKE lower(:pattern)`，pattern 由關鍵字逸出 `% _ \` 後包成 `%kw%`。
  中文不需斷詞；SQLite 與 Postgres 皆支援，行為一致。
- **無資料模型變更**、無新索引（前綴萬用字元，B-tree 無效）。
- **權限**：以子查詢限定 `conversation_id IN (我為成員的對話)`。
- **序列化**：沿用 `serialize_messages_out` 批次化訊息；對話資訊另以一次查詢批次組裝成
  `ConversationRefOut`。
- **跳轉**：`list_messages` 擴充 `around` / `after`，與既有 `before` 互斥。

## 後端檔案

- `app/schemas.py`
  - 新增 `ConversationRefOut`、`SearchResultOut { message: MessageOut; conversation: ConversationRefOut }`、
    `SearchResponseOut { items: list[SearchResultOut]; next_before: datetime | None }`。
- `app/services/search.py`（新檔）
  - `escape_like(term: str) -> str`：逸出 `\ % _`。
  - `async def search_messages(db, user_id, q, before, limit) -> SearchResponseOut`：
    組查詢（content/display_name LIKE、排除 deleted、限定我的對話、desc、limit+1 判斷下一頁）、
    批次序列化訊息與對話 ref、算 `next_before`。
  - 對話 ref 批次：對結果涉及的 conversation_id 集合，一次查 conversations + members + 對方 user，
    組 `ConversationRefOut`（沿用 `serialize_conversations` 既有批次手法，必要時抽共用）。
- `app/routers/search.py`（新檔）
  - `GET /search/messages`：`q: str = Query(min_length=1, max_length=100)`、`before`、`limit`、
    `current_user`、`db`。handler 先 `q.strip()`，空 → 422。呼叫 service。
- `app/main.py`：掛載 `search.router`。
- `app/routers/conversations.py`：`list_messages` 加 `around` / `after`：
  - 互斥檢查（>1 個非 None → 422）。
  - `around`：查 target（不存在/非成員 → 404）；`k = limit // 2`；
    `older = created_at <= target.created_at desc limit (limit - k)`（含 target）、
    `newer = created_at > target.created_at asc limit k`；合併升序。
  - `after`：`created_at > after asc limit`，coerce_cursor 處理方言。

## 前端檔案（frontend/chat）

- `src/api.ts`（或對應 API 模組）：`searchMessages(token, q, before?)`、
  `loadMessagesAround(token, convId, messageId)`、`loadMessagesAfter(...)`。
- `src/search.ts`（新檔，純函式）：
  - `highlightParts(text, q) -> Array<{ text, hit: boolean }>`：大小寫不敏感切片，供渲染高亮。
  - `toSearchResultView(item) -> {...}`：API → 畫面 view model（對話標題、寄件者、時間、片段）。
  - `nextSearchCursor(resp) -> string | null`。
  - 萬用字元/特殊字元在前端僅作顯示，不參與後端逸出（逸出在後端）。
- `src/components/SearchBox.tsx`（新）：輸入框 + debounce。
- `src/components/SearchResults.tsx`（新）：結果清單 + 高亮 + 向下分頁 + 點擊 callback。
- `Sidebar.tsx`：整合搜尋框；有關鍵字時以結果清單取代對話清單。
- `ChatApp.tsx` / `Thread.tsx`：
  - 點結果 → 切換對話 + `loadMessagesAround` → 設定 `pendingHighlightMessageId`。
  - `Thread` 收到 `pendingHighlightMessageId` → 該則 render 後 `scrollIntoView` + 加高亮 class，
    setTimeout 約 2s 後清除。

## 測試策略

- **後端 pytest**（`tests/test_search.py`、`tests/test_messages_around.py`）：
  內容/寄件者命中、權限隔離、排除刪除、逸出、422/401、分頁不重不漏；around/after/互斥/404。
  以既有 file-SQLite 為主，關鍵命中/分頁另跑 Postgres（沿用既有雙環境測試手法）。
- **前端 vitest**（`src/search.test.ts`）：highlightParts（含大小寫、無命中、特殊字元）、
  view model 組裝、nextSearchCursor。
- **e2e Playwright**：
  - `search-api.spec.ts`：MS-01/02/03/04/05/06/09/10（REST，對應 BDD）。
  - `search-ui.spec.ts`：MS-07 點結果跳轉並高亮（瀏覽器 UI）。
- 每個 BDD 場景 ≥ 1 對應測試，維持 BDD → Playwright → Acceptance 追溯。

## 風險與緩解

- **跳轉高亮的 UI 時序**（MF + dev StrictMode）：沿用既有 e2e UI 重試手法；高亮以「該訊息已在 DOM」
  為前提，scrollIntoView 後加 class。
- **分頁 created_at 同值邊界**：與既有 `list_messages` 同一限制，文件已標註，不在此修。
- **search 與 around 的權限**：一律後端強制成員過濾。

## 不做（YAGNI）

附件檔名搜尋、FTS / 索引、AND/OR 查詢語法、搜尋歷史、跨關鍵字排序加權。

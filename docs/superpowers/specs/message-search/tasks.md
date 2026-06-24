# 訊息搜尋（message-search）Tasks

依序執行；每完成一個 Task 跑相關測試並更新 progress.md。

## Task 0：Playwright Skeleton（先寫骨架，由 BDD 衍生）

- 新增 `e2e/tests/search-api.spec.ts` 與 `e2e/tests/search-ui.spec.ts` 的 **骨架**：
  每個 BDD 場景（MS-01..11）一個 `test(...)`，先 `test.fixme` 或最小斷言佔位，
  確立 BDD → Playwright 追溯。
- 驗收：`npx playwright test --list` 列得到對應測試名稱。

## Task 1：後端搜尋 service + schema

- `app/schemas.py`：`ConversationRefOut`、`SearchResultOut`、`SearchResponseOut`。
- `app/services/search.py`：`escape_like`、`search_messages`（查詢 + 批次序列化 + next_before）。
- 單元/整合測試 `tests/test_search.py`：內容命中、寄件者命中、大小寫、排除刪除、權限隔離、
  逸出（`50%`）、分頁不重不漏。
- 驗收：`test_search.py` 綠；無 N+1（查詢數固定）。

## Task 2：後端搜尋端點

- `app/routers/search.py`：`GET /search/messages`（`q` strip 後空 → 422）。
- `app/main.py` 掛載 router。
- 測試補：401（未授權）、422（空 / 過長 q）。
- 驗收：端點測試綠；`search-api.spec.ts` 對應場景可轉綠（MS-01..06、09、10）。

## Task 3：訊息列表 around / after

- `app/routers/conversations.py`：`list_messages` 加 `around` / `after`，互斥檢查（422）、
  `around` 404（不存在 / 非成員）、視窗與向下分頁查詢。
- 測試 `tests/test_messages_around.py`：視窗載入、邊界（首 / 末則）、404、互斥 422、after 分頁。
- 驗收：測試綠；雙環境關鍵案例驗過。

## Task 4：前端搜尋純函式 + API

- `src/search.ts`：`highlightParts`、`toSearchResultView`、`nextSearchCursor`。
- API：`searchMessages`、`loadMessagesAround`、`loadMessagesAfter`。
- `src/search.test.ts`（vitest）：highlightParts（大小寫 / 無命中 / 特殊字元）、view model、cursor。
- 驗收：vitest 綠、tsc 乾淨。

## Task 5：前端 UI（搜尋框 + 結果 + 跳轉高亮）

- `SearchBox.tsx`（debounce）、`SearchResults.tsx`（高亮 + 向下分頁 + 點擊）。
- `Sidebar.tsx` 整合：有關鍵字顯示結果、清空還原對話清單。
- `ChatApp.tsx` / `Thread.tsx`：點結果 → 切換對話 + `loadMessagesAround` →
  `pendingHighlightMessageId` → `Thread` scrollIntoView + 暫時高亮（~2s 清除）。
- 驗收：元件測試（可行範圍）綠；tsc 乾淨。

## Task 6：E2E 補完 + 驗證 + 文件

- 完成 `search-api.spec.ts`（MS-01..06、09、10）與 `search-ui.spec.ts`（MS-07 跳轉高亮）。
- 跑全套：backend pytest、chat vitest、三 app tsc、e2e。
- 勾選 acceptance.md、更新 progress.md。
- 驗收：acceptance 全勾、三條 CI workflow（含 e2e）綠。

## Approval Gate

spec.md / bdd.feature / acceptance.md / plan.md / tasks.md 皆已具備。
**取得使用者明確批准後才進入 Task 0 之後的實作。**

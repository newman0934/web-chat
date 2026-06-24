# 訊息撤回（message-recall）Spec

## Overview

讓寄件人在送出後 2 分鐘內「撤回」訊息：徹底移除內容與附件、不可復原，該訊息位置顯示
系統提示「XXX 撤回了一則訊息」。與現有「刪除/還原」並存且語義不同（刪除可在 5 分內還原、
顯示泡泡佔位；撤回不可復原、顯示系統訊息）。

## Business Requirements

- BR-1：使用者誤傳訊息時可在短時間內「收回」，且雙方都不再看得到內容。
- BR-2：撤回需與「刪除」區隔：撤回是不可復原的徹底收回，刪除仍可在時窗內還原。

## Functional Requirements

- FR-1：寄件人可撤回自己 2 分鐘內送出的訊息（走 WebSocket，即時廣播）。
- FR-2：撤回後清空 `content`、移除附件與表情回應；不可復原。
- FR-3：撤回的訊息在所有成員端顯示為系統提示「{寄件人} 撤回了一則訊息」（本人端顯示「你撤回了一則訊息」）。
- FR-4：撤回的訊息視同已移除：不可編輯 / 刪除 / 表情 / 釘選 / 轉發；搜尋不納入。
- FR-5：撤回已釘選的訊息 → 自動取消釘選。
- FR-6：被回覆訊息若已撤回，引用塊顯示為不可用（如同已刪除）。

## Acceptance Criteria

- AC-1：寄件人 2 分內撤回 → 廣播、`recalled=true`、`content` 為空、無附件/表情。
- AC-2：非寄件人撤回 → 被拒（forbidden）。
- AC-3：超過 2 分鐘撤回 → 被拒（recall_window_passed）。
- AC-4：撤回後該訊息不可編輯 / 表情 / 釘選（被拒）。
- AC-5：撤回已刪除訊息 → 被拒；撤回已撤回訊息 → 被拒。
- AC-6：已撤回訊息不出現在搜尋結果。
- AC-7：撤回已釘選訊息 → 自動取消釘選並廣播。
- AC-8：前端撤回後顯示系統提示「{寄件人} 撤回了一則訊息」。

詳見 [acceptance.md](acceptance.md)。

## Edge Cases

- EC-1：撤回剛好在第 120 秒邊界 → 以 `now - created_at <= 2min` 判定（含端點視為可撤回）。
- EC-2：撤回帶附件的訊息 → 附件列一併移除（下載端點對該附件回 404）。
- EC-3：撤回後再嘗試任何操作（edit/delete/react/pin/forward）→ 一律被拒。
- EC-4：非成員 / 不存在訊息撤回 → 被拒（forbidden / not_found），不洩漏。
- EC-5：撤回的訊息作為他人回覆的來源 → 該回覆的引用塊顯示不可用（deleted 視之）。
- EC-6：撤回不影響已送達語義（不重算未讀；本就已存在的 read 記錄保留）。

## API Contracts

### WebSocket（client → server）

```
{ "type": "recall", "message_id": "uuid" }
```

### WebSocket（server → 對話所有成員，含操作者）

```
{ "type": "message_updated", "message": { /* MessageOut，recalled=true、content="" */ } }
{ "type": "message_unpinned", "conversation_id": "uuid", "message_id": "uuid" }   # 若原為釘選
{ "type": "error", "reason": "forbidden | recall_window_passed | not_found | invalid_payload" }
```

- 撤回沿用 `message_updated` 廣播（前端依 `recalled` 旗標改渲染）。
- 失敗只回操作者本人 `error`。

### MessageOut

新增 `recalled: bool`。`recalled=true` 時 `content=""`、`attachment=null`、`reactions=[]`、
`reply_to/forwarded_from` 比照已刪除遮蔽。

## Data Model Changes

- `messages` 新增 `recalled_at: timestamptz | null`（migration `0013`）；`recalled = recalled_at IS NOT NULL`。
- 不新增索引（撤回判斷與序列化都依既有主鍵 / conversation_id 查詢）。

## State Changes

- 撤回 → 設 `recalled_at = now()`、`content = ""`、刪除該訊息的 `attachments` 與 `reactions` 列；
  若 `pinned_at` 非空一併清空。
- 不可逆：無對應的「還原撤回」。

## UI Behaviour

- 訊息泡泡動作加「撤回」：僅寄件人本人、訊息已送出（sent）、距送出 ≤ 2 分鐘、且未刪除/未撤回時顯示。
- 撤回後該訊息渲染為置中系統列：本人「你撤回了一則訊息」、他人「{寄件人} 撤回了一則訊息」。
- 撤回的訊息不顯示附件、表情列、編輯/刪除/回覆/轉發/釘選等動作。

## Non-Functional Requirements

- NFR-1：時窗與權限後端強制（前端僅作顯隱與即時提示）。
- NFR-2：撤回沿用既有 `message_updated` 廣播路徑，前端不新增 WS 事件處理（除既有 message_unpinned）。
- NFR-3：撤回判斷的純邏輯（`canRecall`）抽離可單元測試。
- NFR-4：SQLite 開發 / Postgres 正式雙環境一致。

## 追溯

BDD 場景見 [bdd.feature](bdd.feature)，每場景至少對應一個 Playwright 測試。

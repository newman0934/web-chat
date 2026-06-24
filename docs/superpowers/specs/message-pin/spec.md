# 訊息置頂（message-pin）Spec

## Overview

讓使用者把對話中的重要訊息「釘選」，在對話頂部以釘選列常駐顯示；點擊可跳轉並高亮原訊息。
群組僅管理員可釘選/取消，1對1 雙方皆可。每對話最多釘選 10 則。

## Business Requirements

- BR-1：重要訊息（公告、連結、結論）可被釘住，成員一進對話就看得到，不必往回捲。
- BR-2：群組由管理員掌控釘選，避免成員互相覆蓋；1對1 為對等關係，雙方皆可。
- BR-3：釘選即時同步給對話所有在線成員。

## Functional Requirements

- FR-1：成員可對對話內訊息釘選 / 取消釘選（走 WebSocket，即時廣播）。
- FR-2：權限 —— direct 兩位成員皆可；group 僅 `role == "admin"` 可。
- FR-3：每對話釘選上限 10 則；達上限再釘 → 拒絕並提示。
- FR-4：對話頂部顯示釘選列：最新一則釘選 + 「共 N 則」；點擊跳轉並高亮；可展開列出全部。
- FR-5：已釘訊息被刪除時自動取消釘選（釘選列不顯示已刪訊息）。
- FR-6：開啟對話時載入該對話的釘選清單（REST）。
- FR-7：訊息泡泡顯示已釘標記（📌）。

## Acceptance Criteria

- AC-1：釘選成功 → 對話所有在線成員收到廣播、訊息 `pinned=true`、出現在釘選清單。
- AC-2：取消釘選 → 廣播、`pinned=false`、自釘選清單移除。
- AC-3：群組非 admin 釘選/取消 → 被拒（forbidden），狀態不變。
- AC-4：已達 10 則上限再釘 → 被拒（pin_limit）。
- AC-5：釘不存在或非成員對話的訊息 → 被拒（not_found / forbidden）。
- AC-6：刪除已釘訊息 → 自動取消釘選並廣播。
- AC-7：`GET /conversations/{id}/pins` 回該對話釘選訊息（新釘在前）。
- AC-8：點釘選列 → 切到該訊息位置、可見且高亮。

詳見 [acceptance.md](acceptance.md)。

## Edge Cases

- EC-1：重複釘選已釘訊息 → 冪等（維持已釘，不重複計數、不報錯）。
- EC-2：取消未釘訊息 → 冪等（維持未釘，不報錯）。
- EC-3：達上限時取消某則後再釘新則 → 成功（上限為當下計數）。
- EC-4：釘選後該訊息被編輯 → 釘選維持，釘選列顯示更新後內容。
- EC-5：非成員嘗試釘選 → forbidden（與一般訊息操作一致，不洩漏對話存在）。
- EC-6：釘選列為空（無釘選）→ 不顯示釘選列。

## API Contracts

### WebSocket（client → server）

```
{ "type": "pin",   "message_id": "uuid" }
{ "type": "unpin", "message_id": "uuid" }
```

### WebSocket（server → 對話所有成員）

```
{ "type": "message_pinned",   "message": { /* MessageOut，pinned=true */ } }
{ "type": "message_unpinned", "conversation_id": "uuid", "message_id": "uuid" }
{ "type": "error", "reason": "forbidden | pin_limit | not_found | invalid_payload" }
```

- `unpin` 與「刪除已釘訊息」皆廣播 `message_unpinned`。
- 失敗只回操作者本人 `error`。

### REST

```
GET /conversations/{conversation_id}/pins
Authorization: Bearer <token>
→ 200 list[MessageOut]   # 釘選訊息，pinned_at 由新到舊；非成員 → 404
```

## Data Model Changes

- `messages` 新增 `pinned_at: timestamptz | null`（migration `0012`）；`pinned = pinned_at IS NOT NULL`。
- 索引：`ix_messages_conversation_pinned`（`conversation_id`, `pinned_at`）以利「取對話釘選清單」與計數。
- `MessageOut` 新增 `pinned: bool`（由 `pinned_at` 推導）。

## State Changes

- 釘選 → 設 `pinned_at = now()`；取消 / 刪除已釘 → 設 `pinned_at = NULL`。
- 前端 store 維護 `pins[conversationId]`（釘選訊息清單），由 REST 載入、WS 事件增減。

## UI Behaviour

- 訊息泡泡動作選單加「釘選 / 取消釘選」（依 `canPin` 權限顯隱）；已釘泡泡顯示 📌。
- Thread header 下方釘選列：顯示最新釘選（內容截斷）+「共 N 則」；
  點擊 → 沿用搜尋的 `around` 跳轉 + 高亮；可展開列出全部釘選（各自可跳、可取消）。
- 釘選清單為空時不顯示釘選列。
- 達上限 / 無權限的錯誤以提示呈現（沿用既有 WS error 處理）。

## Non-Functional Requirements

- NFR-1：權限後端強制（group admin / 成員），不信任前端。
- NFR-2：釘選清單查詢固定查詢數（無 N+1，沿用 `serialize_messages_out`）。
- NFR-3：上限檢查在後端（前端僅作即時提示）。
- NFR-4：前端業務邏輯（權限判斷、釘選列 view model、pins 增減）以純函式實作可測。
- NFR-5：雙環境一致（SQLite 開發 / Postgres 正式）。

## 追溯

BDD 場景見 [bdd.feature](bdd.feature)，每場景至少對應一個 Playwright 測試。

# 訊息搜尋（message-search）Spec

## Overview

提供「全域訊息搜尋」：使用者在側欄輸入關鍵字，跨自己參與的所有對話（1對1 與群組）
搜尋訊息，結果可點擊跳轉至該訊息所在對話並高亮定位。

比對採子字串包含（`LIKE`），中文不需斷詞、SQLite（開發）與 PostgreSQL（正式）行為一致。
不引入全文索引（FTS）。

## Business Requirements

- BR-1：使用者能快速找到過去說過 / 收到的訊息，不必手動往回捲。
- BR-2：搜尋只能看到自己有權限的對話內容（隱私）。
- BR-3：在開發（SQLite）與正式（Postgres）環境行為一致，維持本專案雙環境可測的原則。

## Functional Requirements

- FR-1：搜尋跨「目前使用者為成員」的所有對話。
- FR-2：關鍵字比對 `message.content` **或** 寄件者 `User.display_name`（任一包含即命中），
  大小寫不敏感（兩邊 `lower()`）。
- FR-3：排除已刪除訊息（`deleted_at IS NULL`）。
- FR-4：結果以 `created_at` 由新到舊排序，keyset 分頁（`before` cursor）。
- FR-5：每筆結果附所屬對話資訊（id / type / 群組名稱或對方使用者），供前端顯示「來自哪個對話」。
- FR-6：點結果可跳轉：開啟該對話、載入以該訊息為中心的訊息視窗、捲動定位並短暫高亮該則訊息。
- FR-7：為支援 FR-6，訊息列表端點新增 `around=<message_id>` 視窗載入與 `after` 向下分頁 cursor。
- FR-8：前端搜尋框輸入採 debounce；清空關鍵字即清空結果。

## Acceptance Criteria

- AC-1：以內容關鍵字搜尋，回傳所有命中且未刪除、且我有權限的訊息。
- AC-2：以寄件者名稱關鍵字搜尋，回傳該寄件者在我對話中的訊息。
- AC-3：他人對話（我非成員）的訊息永不出現在我的結果。
- AC-4：已刪除訊息不出現在結果。
- AC-5：空白 / 全空白關鍵字 → 422，不執行搜尋。
- AC-6：未帶 token → 401。
- AC-7：分頁：`limit` 筆滿時回 `next_before`；以該 cursor 取下一頁不重不漏。
- AC-8：點結果 → 對話切換、命中訊息可見且高亮，高亮數秒後自動消失。

詳細逐項見 [acceptance.md](acceptance.md)。

## Edge Cases

- EC-1：關鍵字含 `LIKE` 萬用字元 `%`、`_`、`\` → 需逸出，當一般字元比對（搜 `50%` 不應變成萬用）。
- EC-2：關鍵字僅空白 → 視為空 → 422。
- EC-3：關鍵字過長（> 100 字）→ 422。
- EC-4：命中訊息屬於對方已封存 / 已退出之群組但我仍是成員 → 仍可命中（以「我是成員」為準）。
- EC-5：`around` 指向的訊息不存在 / 我無權限 → 404。
- EC-6：`around` 指向對話中第一則或最後一則 → 視窗只有單側鄰居，不報錯。
- EC-7：`before`、`after`、`around` 同時帶入 → 422（互斥）。
- EC-8：同一 `created_at` 的多則訊息落在分頁邊界 → 沿用現有訊息分頁的 `created_at` cursor 行為
  （罕見；以 MVP 可接受，與既有 `list_messages` 一致）。
- EC-9：寄件者名稱命中但內容不含關鍵字 → 結果片段顯示內容原文（無高亮亦可）。

## API Contracts

### 1. 搜尋訊息

```
GET /search/messages?q=<str>&before=<iso8601?>&limit=<int?>
Authorization: Bearer <token>
```

- `q`：必填，strip 後長度 1–100，否則 422。
- `before`：選填，不透明游標（上一頁回傳的 `next_before`，內容為錨點訊息 id）；
  以 `(created_at, id)` keyset 取更舊的結果。
- `limit`：選填，預設 20，範圍 1–50。

**200 回應**：

```json
{
  "items": [
    {
      "message": { /* MessageOut（沿用既有 schema） */ },
      "conversation": {
        "id": "uuid",
        "type": "direct | group",
        "name": "群組名稱或 null",
        "other_user": { "id": "uuid", "email": "...", "display_name": "..." }
      },
      "sender_name": "寄件者顯示名"
    }
  ],
  "next_before": "<不透明游標：錨點訊息 id> 或 null"
}
```

- `conversation.other_user`：`direct` 才有（對方）；`group` 為 `null`，以 `name` 顯示。
- `sender_name`：寄件者顯示名（群組成員不在 `conversation` 內，故每筆獨立帶上）。
- `next_before`：當 `len(items) == limit` 時為不透明游標（錨點訊息 id），否則 `null`。
  改用 `(created_at, id)` 複合 keyset，避免 `created_at` 同值（秒級 server_default）時漏/重。

**錯誤**：401（未授權）、422（`q` 空 / 過長 / 同時帶互斥參數）。

### 2. 訊息列表新增視窗載入與向下分頁

```
GET /conversations/{conversation_id}/messages?around=<message_id>&limit=<int?>
GET /conversations/{conversation_id}/messages?after=<iso8601>&limit=<int?>
```

- `around`：以該訊息為中心回傳視窗，約 `ceil(limit/2)` 則（含該則）+ `floor(limit/2)` 則較新，
  以 `created_at` 升序回傳 `list[MessageOut]`。
- `after`：回 `created_at > after` 的較新訊息，升序，最多 `limit` 則（向下分頁）。
- `before`（既有）：回 `created_at < before` 的較舊訊息。
- `before` / `after` / `around` 三者互斥；同時帶 → 422。
- `around` 指向訊息不存在或我非該對話成員 → 404。

## Data Model Changes

無。搜尋與視窗載入皆使用既有 `messages` / `conversations` / `conversation_members` / `users` 表。

> 不新增索引：`content LIKE '%q%'` 為前綴萬用字元，B-tree 索引無效；維持現狀，
> 大量資料時的效能優化（FTS / 三元組索引）列為未來工作（見 NFR）。

## State Changes

無持久化狀態變更。搜尋為唯讀查詢；前端高亮為暫態 UI 狀態（數秒後消失）。

## UI Behaviour

- 側欄頂部新增搜尋框（放大鏡 icon）。輸入經 debounce（約 300ms）後呼叫搜尋。
- 有關鍵字時，側欄改顯示「搜尋結果」清單，取代對話清單；清空關鍵字 → 還原對話清單。
- 每筆結果顯示：對話標題（群組名 / 對方名）、寄件者名、內容片段（命中關鍵字以 `<mark>` 高亮）、時間。
- 點結果：切換到該對話 → 以 `around` 載入 → 捲動定位該訊息 → 該訊息泡泡加暫時高亮樣式
  （背景閃黃，約 2 秒後移除）。
- 結果可向下捲動分頁（`next_before`）。
- 載入中 / 無結果 / 錯誤各有對應提示。

## Non-Functional Requirements

- NFR-1：雙環境一致 —— SQLite 與 Postgres 皆以 `lower(col) LIKE lower(:pattern)` 比對；
  pattern 逸出 `% _ \`。
- NFR-2：避免 N+1 —— 結果訊息以 `serialize_messages_out` 批次序列化；對話資訊一次查詢批次組裝。
- NFR-3：權限 —— 一律以「目前使用者為 `conversation_members` 成員」過濾，後端強制，不信任前端。
- NFR-4：前端業務邏輯（高亮切片、結果 view model 組裝、cursor 串接）以純函式實作，可單元測試。
- NFR-5：效能上限 —— 本功能針對 MVP 規模；超大資料量的全文檢索屬未來工作，不在此範圍。

## 追溯

BDD 場景見 [bdd.feature](bdd.feature)，每個場景至少對應一個 Playwright 測試（見 plan/tasks）。

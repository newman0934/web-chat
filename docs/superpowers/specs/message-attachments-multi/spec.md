# 多附件（message-attachments-multi）Spec

## Overview

讓一則訊息可夾帶多個附件（最多 5 個），取代現有「一則一附件」的限制。每檔上限下調為
1MB、整則總量上限 10MB。`MessageOut.attachment`（單一）改為 `attachments`（陣列）。

## Business Requirements

- BR-1：使用者能一次傳送多張圖片 / 多個檔案，不必逐則發送。
- BR-2：限制檔案大小與數量，避免濫用與儲存膨脹。

## Functional Requirements

- FR-1：一則訊息可夾帶 1–5 個附件。
- FR-2：每個附件上傳上限 1MB；整則訊息所有附件總量上限 10MB。
- FR-3：上傳維持「先上傳取得 attachment_id，送訊時以 `attachment_ids` 綁定」流程。
- FR-4：序列化回傳 `attachments: AttachmentOut[]`（依上傳順序）。
- FR-5：轉發訊息複製其全部附件。
- FR-6：已刪除 / 已撤回訊息 `attachments` 為空（沿用既有遮蔽）。
- FR-7：前端可多選檔案、顯示待送清單（可移除）、圖片以格狀縮圖呈現、其他檔案以下載列呈現。

## Acceptance Criteria

- AC-1：帶 2–5 個附件送出 → 訊息 `attachments` 含全部，順序一致。
- AC-2：附件數 > 5 → 被拒（too_many_attachments）。
- AC-3：單檔 > 1MB → 上傳被拒（413）。
- AC-4：整則總量 > 10MB → 送訊被拒（attachments_too_large）。
- AC-5：轉發帶多附件訊息 → 新訊息含全部附件。
- AC-6：撤回 / 刪除帶多附件訊息 → `attachments` 為空。
- AC-7：附件非本人上傳或已被綁定 → 被拒（invalid_attachment）。
- AC-8：既有單附件訊息序列化為 `attachments:[單一]`（相容）。

詳見 [acceptance.md](acceptance.md)。

## Edge Cases

- EC-1：只帶附件、無文字 → 可送出（沿用既有 content 或附件擇一即可）。
- EC-2：附件清單含重複 attachment_id → 去重後綁定（或視為 invalid）；採去重綁定。
- EC-3：5 個各 1MB（總 5MB）→ 通過（未達總量上限）。
- EC-4：附件 id 格式錯誤 / 不存在 → invalid_attachment。
- EC-5：部分附件有效、部分無效 → 整體拒絕（不部分綁定），回 invalid_attachment。
- EC-6：被回覆原訊息有多附件 → 引用塊 `has_attachment=true`（只需布林,不列全部）。

## API Contracts

### 上傳（不變，限制調整）

```
POST /uploads   (multipart, 單檔)
→ 201 AttachmentOut    # 每檔上限 1MB,超過 413
```

### WebSocket 送訊

```
{ "type": "message", "conversation_id": "...", "content": "...",
  "attachment_ids": ["uuid", ...], "temp_id": "..." }
```

- `attachment_ids`：0–5 個；每個須屬發送者、未綁定；總量 ≤ 10MB。
- 取代舊的單一 `attachment_id`（不再支援）。
- 失敗：`{type:"error", reason:"too_many_attachments | attachments_too_large | invalid_attachment", temp_id}`。

### MessageOut

`attachment: AttachmentOut | null` → **`attachments: list[AttachmentOut]`**（空陣列表示無附件）。

## Data Model Changes

- 移除 `attachments.message_id` 的唯一約束 `uq_attachment_message`（migration `0014`）→ 一對多。
- 保留 `message_id` 索引（撈某訊息全部附件）。

## State Changes

- 送訊：把多個 attachment 的 `message_id` 設為新訊息 id（單一 transaction）。
- 撤回 / 刪除：附件遮蔽於序列化（撤回另刪除 attachment 列，沿用既有 recall 行為）。

## UI Behaviour

- 附件按鈕改可多選（`<input multiple>`）；待送區顯示縮圖 / 檔名清單,可逐一移除。
- 前端即時驗證:數量 ≤5、單檔 ≤1MB、總量 ≤10MB;超過顯示提示、不送出。
- 泡泡:圖片附件以格狀縮圖（點開原圖新分頁）、非圖片以下載列；混合則上圖下檔。

## Non-Functional Requirements

- NFR-1：附件數量 / 大小 / 歸屬與總量上限後端強制（前端僅即時提示）。
- NFR-2：序列化批次撈附件，無 N+1（沿用既有批次手法）。
- NFR-3：附件驗證的純邏輯（`validateAttachments`）抽離可單元測試。
- NFR-4：SQLite 開發 / Postgres 正式雙環境一致。

## 追溯

BDD 場景見 [bdd.feature](bdd.feature)，每場景至少對應一個 Playwright 測試。

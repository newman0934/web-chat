# 多附件（message-attachments-multi）Plan

## 架構決策

- 一對多:移除 `attachments.message_id` 唯一約束;一則訊息可有多列 attachment。
- 上傳維持單檔端點(每檔 1MB);訊息以 `attachment_ids` 一次綁定多個。
- 限制後端強制:數量 ≤5、每檔 ≤1MB(上傳端)、總量 ≤10MB(送訊端)。
- 序列化 `attachment`(單) → `attachments`(陣列),批次撈避免 N+1。

## 後端檔案

- `alembic/versions/0014_drop_attachment_unique.py`(新):`op.drop_constraint("uq_attachment_message", "attachments")`;
  downgrade 重建。SQLite 批次模式(`op.batch_alter_table`)以相容。
- `app/models/attachment.py`:移除 `UniqueConstraint("message_id", ...)`(保留 index)。
- `app/routers/uploads.py`:`MAX_UPLOAD_BYTES = 1 * 1024 * 1024`。
- `app/schemas.py`:`MessageOut.attachment` → `attachments: list[AttachmentOut]`(預設 [])。
- `app/services/conversations.py`:新增 `get_attachments_for_message`(回 list);
  保留 / 調整 `get_attachment_for_message`(reply 預覽只需布林 has_attachment)。
- `app/services/conversation_serializers.py`:
  - 單筆 / 批次序列化改填 `attachments`(masked → []);批次以 `message_id IN (...)` 一次撈、
    依 message 分組並保序(以 id 或上傳順序;用 attachment.id 排序近似上傳序)。
  - reply 預覽 `has_attachment` = 該訊息有任一附件。
- `app/ws/handlers/messages.py`:
  - `handle_send`:讀 `attachment_ids`(list);驗證數量 ≤5、各屬本人且 message_id 為 null、
    去重、總 size ≤10MB;否則回對應 error;通過後逐一設 message_id。
  - `handle_forward`:複製來源訊息的「全部」附件列。
  - `handle_recall`(既有):已刪除 attachment 列 — 多附件一併刪(WHERE message_id)。
- 既有 `attachment_id`(單)路徑移除。

## 前端檔案（frontend/chat）

- `contracts/index.ts`:`Message.attachment` → `attachments: Attachment[]`;
  `ClientWsMessage` message 的 `attachment_id?` → `attachment_ids?: string[]`;
  新增上限常數 `MAX_ATTACHMENTS=5`、`MAX_FILE_BYTES=1MB`、`MAX_TOTAL_BYTES=10MB`。
- `src/attachments.ts`(新純函式):`validateAttachments(current, incoming)` →
  `{ ok, error? }`(擋數量/單檔/總量);`src/attachments.test.ts`。
- `src/components/Thread.tsx`:
  - 檔案 input 加 `multiple`;`pending` 由單一改 `Attachment[]`;逐一上傳、即時驗證、可移除;
    送出帶 `attachment_ids`。
- `src/messageStore.ts` / `makeOptimistic`:樂觀訊息 attachments 預設 [](待 ack 帶回)。
- `src/components/MessageBubble.tsx`:渲染 `attachments[]` —— 圖片格狀(grid)、其他下載列;
  `ReplyQuoteBlock` / reply 預覽用 has_attachment 不變。
- `src/useMessageActions.ts` / `ChatApp`:`sendMessage` 改傳 `attachmentIds: string[]`。

## 測試策略

- **後端 pytest**（`tests/test_attachments_multi.py`、`tests/test_migration_0014.py`、
  更新 `tests/test_uploads.py`）：多附件綁定+序列化順序、數量/總量/歸屬/已綁定拒絕、去重、
  轉發複製全部、撤回/刪除清空、單附件相容、上傳 1MB 邊界。雙環境關鍵案例。
- **前端 vitest**（`src/attachments.test.ts`）：validateAttachments 各邊界。
- **e2e**（`attachments-multi-api.spec.ts`、`attachments-multi-ui.spec.ts`）：MA-01..08。

## 風險與緩解

- `MessageOut` 欄位更名(attachment→attachments)觸及前後端多處渲染/測試 —— 逐處改並跑既有
  attachment 測試確認相容(單附件→陣列)。
- SQLite 移除 unique 需 `batch_alter_table`(SQLite 不支援 ALTER DROP CONSTRAINT 直接)。
- 既有上傳 10MB→1MB 行為變更 —— 更新相關測試與 README/CLAUDE 限制描述。

## 不做（YAGNI）

拖放上傳、上傳進度條、送出後增刪附件、相簿打包下載。

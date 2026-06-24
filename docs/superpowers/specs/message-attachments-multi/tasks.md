# 多附件（message-attachments-multi）Tasks

依序執行；每完成一個 Task 跑相關測試並更新 progress.md。

## Task 0：Playwright Skeleton

- 新增 `e2e/tests/attachments-multi-api.spec.ts`、`attachments-multi-ui.spec.ts` 骨架
  （MA-01..08 各一 `test.fixme`）。
- 驗收：`npx playwright test --list` 列得到對應測試名稱。

## Task 1：資料模型 + migration + 上傳限制 + 序列化

- `models/attachment.py` 移除唯一約束；`alembic 0014`（batch_alter_table drop/復建）。
- `uploads.py` 每檔上限 1MB。
- `schemas.MessageOut.attachments`（陣列）。
- `services/conversations.get_attachments_for_message`；序列化（單筆+批次）填 `attachments`，
  批次一次撈、依 message 分組保序；reply 預覽 has_attachment = 有任一附件。
- `tests/test_migration_0014.py`；更新 `tests/test_uploads.py`（1MB 邊界）。
- 驗收：migration 過；既有訊息序列化為 attachments 陣列（單附件相容）；upload 1MB 測試綠。

## Task 2：WS 多附件送訊 + 轉發 + 撤回/刪除

- `handle_send`：`attachment_ids`（≤5、屬本人未綁定、去重、總 ≤10MB）；error 分類。
- `handle_forward`：複製全部附件；`handle_recall`/delete 一併刪/遮蔽全部附件。
- `tests/test_attachments_multi.py`：MA-01/02/04/05/06/07 + 去重 + 只附件無文字。
- 驗收：測試綠；`attachments-multi-api.spec.ts` 對應場景可轉綠；MA-03(上傳 413)由 uploads 測試/ e2e 覆蓋。

## Task 3：前端契約 + 純函式 + API

- `contracts`：Message.attachments、attachment_ids、上限常數。
- `src/attachments.ts`：`validateAttachments`；`src/attachments.test.ts`。
- `useMessageActions.sendMessage` 改 attachmentIds 陣列。
- 驗收：vitest 綠、tsc 乾淨。

## Task 4：前端 UI（多選 + 待送清單 + 格狀渲染）

- `Thread`：input multiple、pending 陣列、即時驗證、可移除、送出帶 attachment_ids。
- `MessageBubble`：attachments 格狀圖片 + 下載列。
- 驗收：元件測試（可行範圍）綠；tsc 乾淨。

## Task 5：E2E 補完 + 驗證 + 文件

- 完成 `attachments-multi-api.spec.ts`（MA-01..07）與 `attachments-multi-ui.spec.ts`（MA-08）。
- 跑全套：backend pytest、chat vitest、三 app tsc、e2e。
- 勾選 acceptance.md、更新 progress.md、CLAUDE.md（限制：一則多附件、每檔 1MB / 總 10MB）。
- 驗收：acceptance 全勾、CI 三 workflow 綠；SQLite + Postgres 雙環境一致。

## Approval Gate

spec.md / bdd.feature / acceptance.md / plan.md / tasks.md 皆已具備。
**取得使用者明確批准後才進入 Task 0 之後的實作。**

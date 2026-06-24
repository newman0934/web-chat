# 訊息撤回（message-recall）Tasks

依序執行；每完成一個 Task 跑相關測試並更新 progress.md。

## Task 0：Playwright Skeleton

- 新增 `e2e/tests/recall-api.spec.ts`、`recall-ui.spec.ts` 骨架（MR-01..09 各一 `test.fixme`）。
- 驗收：`npx playwright test --list` 列得到對應測試名稱。

## Task 1：資料模型 + migration + 序列化遮蔽

- `models/message.py` 加 `recalled_at`；`schemas.MessageOut` 加 `recalled`；
  `message_policy.RECALL_WINDOW`。
- `alembic/versions/0013_message_recalled_at.py`（可逆）。
- `conversation_serializers`：以 `masked = deleted or recalled` 驅動遮蔽；填 `recalled`。
- `services/conversations.build_reply_preview`：recalled 原訊息視為 deleted 遮蔽。
- `tests/test_migration_0013.py`；既有序列化測試仍綠（recalled 預設 false）。

## Task 2：WS 撤回 + 操作守衛 + 搜尋排除

- `ws/handlers/messages.py`：`handle_recall`（權限、時窗、清 content/附件/表情、解釘、廣播）；
  edit/delete/react/pin/forward 守衛擴為「deleted 或 recalled」。
- `ws/router.py` dispatch 加 `recall`。
- `services/search.py`：搜尋排除 `recalled_at IS NOT NULL`。
- `tests/test_recall.py`：MR-01..08（撤回、權限、逾時、互斥、解釘、搜尋排除）。
- 驗收：測試綠；`recall-api.spec.ts` 對應場景可轉綠。

## Task 3：前端純函式 + 動作

- `contracts`：Message.recalled、recall WS、`RECALL_WINDOW_MS`。
- `src/recall.ts`：`canRecall`；`src/recall.test.ts`（vitest）。
- `useMessageActions`：`recallMessage`。
- 驗收：vitest 綠、tsc 乾淨。

## Task 4：前端 UI（撤回動作 + 系統列呈現）

- `MessageBubble`：recalled 分支渲染置中系統列；動作列加「撤回」（依 canRecall）。
- `Thread` / `ChatApp`：把 recall 接到 bubble（沿用既有 onDelete 等的傳遞方式）。
- 驗收：元件測試（可行範圍）綠；tsc 乾淨。

## Task 5：E2E 補完 + 驗證 + 文件

- 完成 `recall-api.spec.ts`（MR-01..08）與 `recall-ui.spec.ts`（MR-09）。
- 跑全套：backend pytest、chat vitest、三 app tsc、e2e。
- 勾選 acceptance.md、更新 progress.md、CLAUDE.md（功能移入已完成）。
- 驗收：acceptance 全勾、CI 三 workflow 綠；SQLite + Postgres 雙環境一致。

## Approval Gate

spec.md / bdd.feature / acceptance.md / plan.md / tasks.md 皆已具備。
**取得使用者明確批准後才進入 Task 0 之後的實作。**

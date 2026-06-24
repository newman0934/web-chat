# 訊息置頂（message-pin）Tasks

依序執行；每完成一個 Task 跑相關測試並更新 progress.md。

## Task 0：Playwright Skeleton

- 新增 `e2e/tests/pin-api.spec.ts`、`pin-ui.spec.ts` 骨架（MP-01..10 各一 `test.fixme`），
  確立 BDD → Playwright 追溯。
- 驗收：`npx playwright test --list` 列得到對應測試名稱。

## Task 1：資料模型 + migration + 序列化

- `models/message.py` 加 `pinned_at`；`schemas.MessageOut` 加 `pinned`。
- `alembic/versions/0012_message_pinned_at.py`（add column + index；可逆）。
- `conversation_serializers` 兩個序列化器填 `pinned`。
- `tests/test_migration_0012.py`（shell-out alembic smoke，斷言欄/索引存在）。
- 驗收：migration clean DB + dev.db upgrade 過；既有訊息序列化測試仍綠（pinned 預設 false）。

## Task 2：後端 pins service + REST 清單

- `services/pins.py`：`PIN_LIMIT`、`can_pin`、`list_pins`、`count_pins`。
- `routers/conversations.py`：`GET /{id}/pins`（非成員 404、批次序列化）。
- `tests/test_pins.py`（service + REST 部分）：can_pin 各情境、list_pins 排序、非成員 404。
- 驗收：相關測試綠；無 N+1。

## Task 3：後端 WS pin / unpin + 刪除自動解釘

- `ws/handlers/messages.py`：`handle_pin` / `handle_unpin`（權限、上限、冪等、廣播）。
- `ws/router.py` dispatch 加 `pin` / `unpin`。
- 既有 delete handler：已釘則清 `pinned_at` 並廣播 `message_unpinned`。
- `tests/test_pins.py`（WS 部分）：MP-01..06、09、10（廣播、權限、上限、冪等、刪除解釘）。
- 驗收：WS 測試綠；`pin-api.spec.ts` 對應場景可轉綠。

## Task 4：前端契約 + 純函式 + API

- `contracts`：Message.pinned、WS pin/unpin/message_pinned/message_unpinned。
- `src/pins.ts`：`canPin`、`pinnedBarView`、`addPin`/`removePin`。
- `src/api.ts`：`listPins`。
- `src/pins.test.ts`（vitest）。
- 驗收：vitest 綠、tsc 乾淨。

## Task 5：前端 UI（釘選列 + 泡泡動作 + 即時更新）

- store `pins` + actions；`wsDispatch` 接 pin/unpin；`useMessageActions` 加 pin/unpin。
- `PinnedBar.tsx`（最新 + 共 N 則 + 展開 + 跳轉/取消）；`MessageBubble` 動作 + 📌；
  `Thread` 掛 PinnedBar；`ChatApp` 開對話載入 pins、接線跳轉。
- 驗收：元件測試（可行範圍）綠；tsc 乾淨；手動或元件測試驗釘選列顯示與點擊跳轉。

## Task 6：E2E 補完 + 驗證 + 文件

- 完成 `pin-api.spec.ts`（MP-01..06、09、10）與 `pin-ui.spec.ts`（MP-08 點釘選列跳轉高亮）。
- 跑全套：backend pytest、chat vitest、三 app tsc、e2e。
- 勾選 acceptance.md、更新 progress.md、CLAUDE.md（功能移入已完成）。
- 驗收：acceptance 全勾、三條 CI workflow（含 e2e）綠；SQLite + Postgres 雙環境一致。

## Approval Gate

spec.md / bdd.feature / acceptance.md / plan.md / tasks.md 皆已具備。
**取得使用者明確批准後才進入 Task 0 之後的實作。**

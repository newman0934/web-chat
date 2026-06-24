# 訊息撤回（message-recall）Plan

## 架構決策

- 撤回狀態存 `messages.recalled_at`（nullable）；`recalled = recalled_at IS NOT NULL`。
- 撤回走 WebSocket，沿用 `message_updated` 廣播（前端依 `recalled` 改渲染）。
- 撤回 = 設 `recalled_at`、清空 content、刪除 attachments/reactions 列、若釘選則解釘。
- 「已撤回」在序列化、各 WS 操作守衛、搜尋過濾上比照「已刪除」一併處理。
- 時窗 RECALL_WINDOW = 2 分鐘，與 EDIT/RESTORE 並列於 `message_policy.py`。

## 後端檔案

- `alembic/versions/0013_message_recalled_at.py`（新）：`add_column recalled_at`；downgrade 反向。
- `app/models/message.py`：加 `recalled_at`。
- `app/message_policy.py`：加 `RECALL_WINDOW = timedelta(minutes=2)`。
- `app/schemas.py`：`MessageOut` 加 `recalled: bool`。
- `app/services/conversation_serializers.py`：
  - `recalled = m.recalled_at is not None`；recalled 時 `masked = deleted or recalled`，
    content/attachment/reactions/reply/forwarded 一律遮蔽（把現有 `deleted` 遮蔽條件改成
    `deleted or recalled`）。
  - 兩個序列化器（單筆 + 批次）一致處理。
- `app/services/conversations.py`：`build_reply_preview` 對 recalled 原訊息也視為 deleted（遮蔽）。
- `app/ws/handlers/messages.py`：
  - `handle_recall`：寄件人本人、`now - created_at <= RECALL_WINDOW`、未刪除/未撤回 →
    設 recalled_at、content=""、`DELETE attachments WHERE message_id`、`DELETE reactions WHERE message_id`、
    若 pinned_at 非空則清空，commit，`_broadcast_updated`；若原為釘選再 `_broadcast_unpinned`。
  - 在 `handle_edit / handle_delete / handle_react / handle_pin / handle_forward` 的既有
    `deleted_at is not None` 守衛改為「deleted 或 recalled」一律擋。
- `app/ws/router.py`：dispatch 加 `recall`。
- `app/services/search.py`：搜尋 WHERE 加 `Message.recalled_at.is_(None)`（與排除 deleted 並列）。

## 前端檔案（frontend/chat）

- `contracts/index.ts`：`Message.recalled?: boolean`；`ClientWsMessage` 加 `{type:'recall', message_id}`。
- `src/messagePolicy.ts`（或新 `src/recall.ts` 純函式）：
  `canRecall(message, currentUserId, now)` —— mine && status==='sent' && !deleted && !recalled &&
  `now - created_at <= RECALL_WINDOW_MS`。常數 `RECALL_WINDOW_MS` 放 contracts（與 EDIT/RESTORE 並列）。
- `src/useMessageActions.ts`：`recallMessage(id)`（wsSend recall）。
- `src/components/MessageBubble.tsx`：
  - recalled 分支（在 deleted 分支旁）：渲染置中系統列
    「你撤回了一則訊息 / {senderName} 撤回了一則訊息」。
  - 動作列加「撤回」（依 `canRecall`）。
- store / wsDispatch 無需新增（recalled 經 `message_updated` → updateMessage 既有路徑）。

## 測試策略

- **後端 pytest**（`tests/test_recall.py`、`tests/test_migration_0013.py`）：
  撤回成功（recalled/content/無附件表情）、非本人 forbidden、逾時 recall_window_passed
  （以可調 now 或直接設 created_at 過去）、撤回後 edit/react/pin 被拒、撤回已刪/已撤回被拒、
  撤回已釘自動解釘、搜尋排除已撤回。雙環境關鍵案例。
- **前端 vitest**（`src/recall.test.ts`）：canRecall（本人/非本人、未送出、逾時、已刪/已撤回）。
- **e2e**（`recall-api.spec.ts` WS+REST、`recall-ui.spec.ts` UI）：對應 MR-01..09。
  逾時案例以 backend pytest 覆蓋（需操弄時間），e2e 不寫逾時以免 flaky。

## 風險與緩解

- 多處守衛改動（edit/delete/react/pin/forward）：把「deleted」判斷統一擴為「deleted 或 recalled」，
  逐一加測試確認不誤擋正常訊息。
- 序列化遮蔽：以 `masked = deleted or recalled` 單一變數驅動，避免兩套遮蔽邏輯分歧。

## 不做（YAGNI）

撤回通知、撤回給自己、保留撤回前內容、撤回提示音、可還原撤回。

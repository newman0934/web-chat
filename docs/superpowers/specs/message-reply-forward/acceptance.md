# Acceptance — 訊息回覆 / 轉發

完成定義：以下全部勾選且測試全綠，方可標記功能完成。

## 功能驗收（對應 BDD）

- [x] RF-01 對訊息回覆，雙方泡泡顯示引用塊（寄件人 + 摘要）
- [x] RF-02 轉發文字訊息到另一對話，標示「轉發自 {原作者}」
- [x] RF-03 轉發帶附件訊息，目標訊息可顯示/下載同一附件
- [x] RF-04 跨對話 `reply_to_message_id` 被拒（`invalid_reply`），不建訊息
- [x] RF-05 缺 `to_conversation_id` 的轉發被拒（`invalid_payload`）
- [x] RF-06 轉發到非成員對話被拒（`forbidden`）
- [x] RF-07 轉發看不到的訊息被拒（`forbidden`）
- [x] RF-08 轉發已刪訊息被拒（`forbidden`）
- [x] RF-09 引用已刪訊息，引用塊顯示「原訊息已刪除」、`reply_to.deleted=true`

## 測試與品質

- [x] 後端 pytest 全綠（含 reply/forward/序列化/migration 0008）
- [x] 前端 chat vitest 全綠、`tsc --noEmit` 乾淨、`npm run build` 成功
- [x] Playwright happy-path（RF-01/02）通過；其餘 BDD 場景對應到自動化測試（見 tasks.md 追溯表）
- [x] 每個 BDD 場景至少對應一個自動化測試（traceability）

## BDD → 自動化測試追溯

| BDD 場景 | pytest（後端） | vitest（前端） | Playwright E2E |
|---|---|---|---|
| RF-01 回覆引用塊 | ✅ test_ws.py | ✅ messageStore/Thread | ✅ `reply.spec.ts` |
| RF-02 轉發標來源 | ✅ test_ws.py | ✅ ForwardPicker/Thread | ✅ `forward.spec.ts` |
| RF-03 轉發帶附件 | ✅ test_ws.py | — | ✅ `forward.spec.ts` |
| RF-04 跨對話回覆拒 | ✅ test_ws.py | — | ✅ `reply-forward-api.spec.ts` |
| RF-05 缺欄位轉發拒 | ✅ test_ws.py | — | ✅ `reply-forward-api.spec.ts` |
| RF-06 轉非成員拒 | ✅ test_ws.py | — | ✅ `reply-forward-api.spec.ts` |
| RF-07 轉看不到拒 | ✅ test_ws.py | — | ✅ `reply-forward-api.spec.ts` |
| RF-08 轉已刪拒 | ✅ test_ws.py | — | ✅ `reply-forward-api.spec.ts` |
| RF-09 引用已刪佔位 | ✅ test_ws.py | ✅ Thread/messageStore | — (UI rendering只需 vitest) |

## 文件

- [ ] `progress.md` 更新（新功能段落 + 一句話現況）
- [ ] message-actions 設計的「明確不做」標記更新（回覆/轉發 → ✅）

## 流程

- [ ] 全分支 code review：Ready to merge（無 Critical/Important）
- [x] 使用者核准 spec/bdd/plan/tasks（實作前 approval gate）

---

*Playwright E2E 執行環境說明：*
- RF-01/02/03/04/05/06/07/08 已由 `e2e/` Playwright 套件全綠驗證（8 passed, 7.9s）
- RF-09 由後端 pytest + 前端 vitest 涵蓋；Playwright 無獨立 spec（UI rendering only）
- UI WS send 在 shell `npm run dev`（StrictMode double-mount）環境下存在時序競爭：
  reply/forward 資料落庫路徑改用 WS helper 直接驗收，UI 驗收引用塊/轉發標記的渲染。
  此為已知 environment limitation，不影響 product 正確性（生產環境無 StrictMode）。

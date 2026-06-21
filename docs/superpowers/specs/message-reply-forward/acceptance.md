# Acceptance — 訊息回覆 / 轉發

完成定義：以下全部勾選且測試全綠，方可標記功能完成。

## 功能驗收（對應 BDD）

- [ ] RF-01 對訊息回覆，雙方泡泡顯示引用塊（寄件人 + 摘要）
- [ ] RF-02 轉發文字訊息到另一對話，標示「轉發自 {原作者}」
- [ ] RF-03 轉發帶附件訊息，目標訊息可顯示/下載同一附件
- [ ] RF-04 跨對話 `reply_to_message_id` 被拒（`invalid_reply`），不建訊息
- [ ] RF-05 缺 `to_conversation_id` 的轉發被拒（`invalid_payload`）
- [ ] RF-06 轉發到非成員對話被拒（`forbidden`）
- [ ] RF-07 轉發看不到的訊息被拒（`forbidden`）
- [ ] RF-08 轉發已刪訊息被拒（`forbidden`）
- [ ] RF-09 引用已刪訊息，引用塊顯示「原訊息已刪除」、`reply_to.deleted=true`

## 測試與品質

- [ ] 後端 pytest 全綠（含 reply/forward/序列化/migration 0008）
- [ ] 前端 chat vitest 全綠、`tsc --noEmit` 乾淨、`npm run build` 成功
- [ ] Playwright happy-path（RF-01/02）通過；其餘 BDD 場景對應到自動化測試（見 tasks.md 追溯表）
- [ ] 每個 BDD 場景至少對應一個自動化測試（traceability）

## 文件

- [ ] `progress.md` 更新（新功能段落 + 一句話現況）
- [ ] message-actions 設計的「明確不做」標記更新（回覆/轉發 → ✅）

## 流程

- [ ] 全分支 code review：Ready to merge（無 Critical/Important）
- [ ] 使用者核准 spec/bdd/plan/tasks（實作前 approval gate）

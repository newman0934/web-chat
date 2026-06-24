# 多附件（message-attachments-multi）Acceptance

功能完成的唯一驗收來源。每項打勾才算完成；全部通過前不得標記功能完成。

## 後端 — 資料模型 / migration

- [ ] 移除 `attachments.message_id` 唯一約束（migration `0014`，可逆）
- [ ] `message_id` 索引保留
- [ ] `MessageOut.attachments: list[AttachmentOut]`（取代單一 `attachment`）
- [ ] migration 於 clean DB 與既有 `dev.db` upgrade 皆過

## 後端 — 上傳

- [ ] 每檔上限改 1MB；> 1MB → 413
- [ ] 既有上傳測試（10MB 邊界）已更新為新限制

## 後端 — WS 送訊（多附件）

- [ ] `attachment_ids`（0–5）綁定到新訊息；序列化回傳全部 `attachments`，順序一致
- [ ] 數量 > 5 → `error: too_many_attachments`
- [ ] 總量 > 10MB → `error: attachments_too_large`
- [ ] 任一附件非本人 / 已綁定 / 不存在 → `error: invalid_attachment`，且不部分綁定
- [ ] 重複 attachment_id → 去重綁定（或視為 invalid，擇一並有測試）
- [ ] 只帶附件、無文字 → 可送出

## 後端 — 與其他功能

- [ ] 轉發帶多附件訊息 → 新訊息含全部附件
- [ ] 撤回 / 刪除帶多附件訊息 → `attachments` 為空
- [ ] 被回覆原訊息有附件 → 引用塊 `has_attachment=true`
- [ ] 序列化批次撈附件，無 N+1
- [ ] 既有單附件訊息序列化為 `attachments:[單一]`

## 前端（chat）

- [ ] 附件可多選；待送清單顯示（縮圖/檔名）可逐一移除
- [ ] 前端即時擋：數量 > 5 / 單檔 > 1MB / 總量 > 10MB（顯示提示、不送出）
- [ ] 送出帶 `attachment_ids`
- [ ] 泡泡渲染 `attachments[]`：圖片格狀縮圖、其他檔案下載列
- [ ] reply / forward 預覽改用 attachments
- [ ] `validateAttachments` 純函式實作並有單元測試

## 測試與追溯

- [ ] 每個 BDD 場景（MA-01..08）至少對應一個 Playwright 測試
- [ ] backend pytest 全綠、chat vitest 全綠、三 app tsc 乾淨
- [ ] e2e Playwright（含 UI）綠
- [ ] SQLite + Postgres 雙環境一致
- [ ] progress.md 更新本功能狀態

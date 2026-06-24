# 多附件（message-attachments-multi）Acceptance

功能完成的唯一驗收來源。每項打勾才算完成；全部通過前不得標記功能完成。

## 後端 — 資料模型 / migration

- [x] 移除 `attachments.message_id` 唯一約束（migration `0014`，可逆）
- [x] `message_id` 索引保留
- [x] `MessageOut.attachments: list[AttachmentOut]`（取代單一 `attachment`）
- [x] migration 於 clean DB 與既有 `dev.db` upgrade 皆過

## 後端 — 上傳

- [x] 每檔上限改 1MB；> 1MB → 413
- [x] 既有上傳測試（10MB 邊界）已更新為新限制

## 後端 — WS 送訊（多附件）

- [x] `attachment_ids`（0–5）綁定到新訊息；序列化回傳全部 `attachments`，順序一致
- [x] 數量 > 5 → `error: too_many_attachments`
- [x] 總量 > 10MB → `error: attachments_too_large`
- [x] 任一附件非本人 / 已綁定 / 不存在 → `error: invalid_attachment`，且不部分綁定
- [x] 重複 attachment_id → 去重綁定（或視為 invalid，擇一並有測試）
- [x] 只帶附件、無文字 → 可送出

## 後端 — 與其他功能

- [x] 轉發帶多附件訊息 → 新訊息含全部附件
- [x] 撤回 / 刪除帶多附件訊息 → `attachments` 為空
- [x] 被回覆原訊息有附件 → 引用塊 `has_attachment=true`
- [x] 序列化批次撈附件，無 N+1
- [x] 既有單附件訊息序列化為 `attachments:[單一]`

## 前端（chat）

- [x] 附件可多選；待送清單顯示（縮圖/檔名）可逐一移除
- [x] 前端即時擋：數量 > 5 / 單檔 > 1MB / 總量 > 10MB（顯示提示、不送出）
- [x] 送出帶 `attachment_ids`
- [x] 泡泡渲染 `attachments[]`：圖片格狀縮圖、其他檔案下載列
- [x] reply / forward 預覽改用 attachments
- [x] `validateAttachments` 純函式實作並有單元測試

## 測試與追溯

- [x] 每個 BDD 場景（MA-01..08）至少對應一個 Playwright 測試
- [x] backend pytest 全綠、chat vitest 全綠、三 app tsc 乾淨
- [x] e2e Playwright（含 UI）綠
- [x] SQLite + Postgres 雙環境一致
- [x] progress.md 更新本功能狀態

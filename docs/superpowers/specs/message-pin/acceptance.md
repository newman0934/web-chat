# 訊息置頂（message-pin）Acceptance

功能完成的唯一驗收來源。每項打勾才算完成；全部通過前不得標記功能完成。

## 後端 — 資料模型 / migration

- [ ] `messages` 新增 `pinned_at`（nullable）+ migration `0012`（up/down 可逆）
- [ ] `ix_messages_conversation_pinned` 索引存在
- [ ] `MessageOut` 含 `pinned: bool`（由 `pinned_at` 推導）
- [ ] migration 於 clean DB 與既有 `dev.db` upgrade 皆過

## 後端 — WS 釘選 / 取消

- [ ] `pin` 成功 → 廣播 `message_pinned`（含 `pinned=true` 的 message）給對話所有在線成員
- [ ] `unpin` 成功 → 廣播 `message_unpinned`（conversation_id + message_id）
- [ ] direct：兩位成員皆可釘 / 取消
- [ ] group：僅 `role == "admin"` 可；一般成員 → `error: forbidden`，狀態不變
- [ ] 非成員操作 → `error`（forbidden / not_found），不洩漏
- [ ] 釘不存在的訊息 → `error: not_found`
- [ ] 達上限（10）再釘 → `error: pin_limit`，釘選數維持 10
- [ ] 取消一則後再釘新則 → 皆成功，維持 10
- [ ] 重複釘已釘 → 冪等（不報錯、不重複計數）；取消未釘 → 冪等
- [ ] 刪除已釘訊息 → 自動 `pinned_at=NULL` 並廣播 `message_unpinned`

## 後端 — REST 釘選清單

- [ ] `GET /conversations/{id}/pins` → 釘選訊息（`pinned_at` 由新到舊）
- [ ] 非成員 → 404
- [ ] 批次序列化（無 N+1）

## 前端（chat）

- [ ] 泡泡動作選單有「釘選 / 取消釘選」（依 `canPin` 權限顯隱）
- [ ] 已釘泡泡顯示 📌
- [ ] Thread 頂部釘選列：最新釘選 + 「共 N 則」；空清單不顯示
- [ ] 點釘選列 → `around` 跳轉並高亮該訊息
- [ ] 可展開列出全部釘選，各自可跳 / 取消
- [ ] WS `message_pinned` / `message_unpinned` 即時更新釘選列與泡泡標記
- [ ] `canPin` / 釘選列 view model / pins 增減以純函式實作並有單元測試

## 測試與追溯

- [ ] 每個 BDD 場景（MP-01..10）至少對應一個 Playwright 測試
- [ ] backend pytest 全綠、chat vitest 全綠、三 app tsc 乾淨
- [ ] e2e Playwright（含 UI 跳轉）綠
- [ ] SQLite + Postgres 雙環境一致
- [ ] progress.md 更新本功能狀態

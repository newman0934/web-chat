# 訊息撤回（message-recall）Acceptance

功能完成的唯一驗收來源。每項打勾才算完成；全部通過前不得標記功能完成。

## 後端 — 資料模型 / migration

- [x] `messages` 新增 `recalled_at`（nullable）+ migration `0013`（可逆）
- [x] `MessageOut` 含 `recalled: bool`
- [x] migration 於 clean DB 與既有 `dev.db` upgrade 皆過

## 後端 — WS 撤回

- [x] 寄件人 2 分內撤回 → 廣播 `message_updated`，`recalled=true`、`content=""`、無附件/表情
- [x] 撤回移除該訊息的 attachments 與 reactions 列
- [x] 非寄件人撤回 → `error: forbidden`，狀態不變
- [x] 超過 2 分鐘 → `error: recall_window_passed`
- [x] 撤回已刪除訊息 → 被拒；撤回已撤回訊息 → 被拒
- [x] 非成員 / 不存在訊息撤回 → `error`（forbidden / not_found）
- [x] 撤回已釘選訊息 → 自動 `pinned_at=NULL` 並廣播 `message_unpinned`

## 後端 — 與其他操作的互斥

- [x] 已撤回訊息：edit / delete / react / pin / forward 一律被拒
- [x] 已撤回訊息不出現在 `GET /search/messages` 結果
- [x] 被回覆的原訊息若已撤回，引用塊以不可用呈現

## 前端（chat）

- [x] 泡泡動作有「撤回」（僅寄件人、已送出、2 分內、未刪未撤回時顯示）
- [x] 撤回後渲染為置中系統列：本人「你撤回了一則訊息」、他人「{寄件人} 撤回了一則訊息」
- [x] 撤回後不顯示原內容、附件、表情列與動作鈕
- [x] WS `message_updated`（recalled=true）即時更新
- [x] `canRecall` 純函式實作並有單元測試

## 測試與追溯

- [x] 每個 BDD 場景（MR-01..09）至少對應一個 Playwright 測試
- [x] backend pytest 全綠、chat vitest 全綠、三 app tsc 乾淨
- [x] e2e Playwright（含 UI）綠
- [x] SQLite + Postgres 雙環境一致
- [x] progress.md 更新本功能狀態

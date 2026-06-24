# 訊息搜尋（message-search）Acceptance

功能完成的唯一驗收來源。每項打勾才算完成；全部通過前不得標記功能完成。

## 後端 — 搜尋端點

- [x] `GET /search/messages?q=會議` 回傳含「會議」的訊息（內容命中）
- [x] `GET /search/messages?q=Bob` 回傳寄件者 display_name 含「Bob」的訊息（寄件者命中）
- [x] 大小寫不敏感：`q=bob` 與 `q=BOB` 結果一致
- [x] 結果排除 `deleted_at` 非空（已刪除）的訊息
- [x] 只回傳目前使用者為成員之對話的訊息；他人對話不外洩
- [x] 每筆結果含 `conversation`（id / type / name / other_user）
- [x] `direct` 結果的 `conversation.other_user` 為對方；`group` 的 `other_user` 為 null、有 `name`
- [x] 關鍵字含 `%` / `_` / `\` 時逸出，視為一般字元比對（`50%` 不誤命中）
- [x] `q` 為空或全空白 → 422
- [x] `q` 長度 > 100 → 422
- [x] 未帶 token → 401
- [x] `limit=20` 滿筆時回 `next_before`；以該 cursor 取下一頁不重不漏；無更多時 `next_before=null`
- [x] 結果以 `created_at` 由新到舊排序

## 後端 — 訊息列表視窗載入 / 向下分頁

- [x] `?around=<message_id>` 回傳以該訊息為中心的視窗（含該則 + 前後鄰居），升序
- [x] `around` 指向對話第一則 / 最後一則 → 僅單側鄰居，不報錯
- [x] `around` 指向不存在的訊息或非成員對話 → 404
- [x] `?after=<created_at>` 回傳較新訊息（向下分頁），升序
- [x] `before` / `after` / `around` 同時帶入 → 422

## 後端 — 品質

- [x] 結果訊息以 `serialize_messages_out` 批次序列化（無 N+1）
- [x] 對話資訊批次組裝（不逐筆查詢）
- [x] SQLite 與 Postgres 雙環境結果一致（關鍵測試於兩環境綠）

## 前端（chat）

- [x] 側欄有搜尋框；輸入經 debounce 後觸發搜尋
- [x] 有關鍵字時顯示搜尋結果清單，清空關鍵字還原對話清單
- [x] 結果顯示對話標題、寄件者、內容片段（命中字以高亮呈現）、時間
- [x] 點結果 → 切換對話 → 以 `around` 載入 → 命中訊息可見且高亮
- [x] 高亮數秒後自動消失
- [x] 結果可向下分頁（next_before）
- [x] 高亮切片 / 結果 view model 組裝 / cursor 串接以純函式實作並有單元測試

## 測試與追溯

- [x] 每個 BDD 場景（MS-01..11）至少對應一個 Playwright 測試
- [x] backend pytest 全綠、chat vitest 全綠、三 app tsc 乾淨
- [x] e2e Playwright（含跳轉高亮 UI）綠
- [x] progress.md 更新本功能狀態

# 站內通知 — 驗收清單(acceptance)

實作完成前逐項打勾。對應 [spec.md](spec.md) 的 Acceptance Criteria 與 [bdd.feature](bdd.feature)。

## 功能

- [x] AC-1 / NB-01：被回覆 → 收件人得到 type=reply 通知(actor/message/conversation 正確)
- [x] AC-2 / NB-02：被加表情 → type=reaction + emoji
- [x] NB-07：表情 toggle 移除 → 不新增、不刪除既有通知
- [x] AC-3 / NB-03：被轉發 → type=forward,conversation 為原訊息所在對話
- [x] AC-4 / NB-06：對自己的訊息互動 → 不產生通知
- [x] AC-7 / NB-05：未讀數 = read_at IS NULL 的數量;列表新→舊、可分頁
- [x] NB-08：多筆互動 → 各自獨立通知(不聚合)

## 已讀語意

- [x] AC-6 / NB-04：開啟對話 → 該對話通知標已讀、未讀數下降
- [x] NB-04:開啟通知中心本身**不**標已讀
- [x] 點擊一筆通知 → 導向對應對話(隨即已讀)

## 即時與離線

- [x] AC-5：收件人在線 → 立即收到 WS `notification`
- [x] NB-14：離線期間的通知,上線後 `GET /notifications` 補得回、計入未讀
- [x] EC-5:多連線在線 → 所有連線都收到推播

## 邊界與權限

- [x] EC-1 / NB-09：被互動訊息已刪 → 通知仍在、preview="",點擊仍可開對話
- [x] NB-10：`GET /notifications` 只回自己的
- [x] NB-11：未授權 401
- [x] NB-12：標非自己對話 → marked=0、不洩漏存在性
- [x] NB-13：`POST /notifications/read` 缺 conversation_id → 422

## 非功能

- [x] NFR-1：列表/未讀走索引;通知建立未在訊息熱路徑引入 N+1
- [x] NFR-3：通知與觸發訊息同一 transaction(不會一成一敗)
- [x] NFR-4：0009 遷移於 SQLite 與 Postgres 皆成功;datetime tz-aware

## 測試與流程

- [x] backend pytest 全綠(含 test_notifications)
- [x] chat vitest 全綠(store / notifications 純函式 / NotificationCenter)
- [x] 三個前端 app `tsc --noEmit` 乾淨
- [x] e2e:notifications-api + notifications-ui 綠;每個 BDD scenario 對到測試
- [x] e2e/README 追溯表、progress.md 更新
- [ ] 最終全分支 review:Ready to merge

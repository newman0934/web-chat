# 線上狀態 — 驗收清單(acceptance)

對應 [spec.md](spec.md) 的 Acceptance Criteria 與 [bdd.feature](bdd.feature)。

## 功能

- [x] AC-1 / PR-01：好友首條連線上線 → 在線的我收到 presence online
- [x] AC-2 / PR-02：好友末條連線斷開 → 我收到 offline + last_seen_at;manager(記憶體)記下 last_seen
- [x] AC-3 / PR-04：第二條連線不重播 online
- [x] AC-3 / PR-05：仍有連線時不誤報 offline
- [x] AC-4 / PR-03：GET /contacts 每筆含 online / last_seen_at
- [x] PR-08：從未上線好友 → online=false、last_seen_at=null

## 隱私 / 權限

- [x] AC-5 / PR-06：非好友上下線不廣播給我
- [x] PR-07：非好友不出現在 /contacts
- [x] PR-09：廣播只送在線好友(離線好友靠下次 /contacts 快照)

## 前端呈現

- [x] AC-6 / PR-10：Sidebar 1對1 對方綠點(online)/灰點(offline)
- [x] AC-6 / PR-11：Thread header「在線」/「最後上線 X」/「離線」
- [x] 群組 header 不顯示 presence

## 非功能

- [x] NFR-3：末條離線先在記憶體寫 last_seen 再廣播(事件時間與 manager 一致)
- [x] NFR-4：last_seen tz-aware(to_utc_iso);SQLite/Postgres 皆正確
- [x] 0010 遷移於 SQLite 與 Postgres 皆成功(欄位保留,執行期不寫)

## 測試與流程

- [x] backend pytest 全綠(含 test_presence、manager first/last)
- [x] chat vitest 全綠(presence 純函式 / store / Sidebar 點 / Thread header)
- [x] 三個前端 app `tsc --noEmit` 乾淨
- [x] e2e:presence-api 綠;每個 BDD scenario 對到測試;SQLite + Postgres 雙環境
- [x] e2e/README 追溯表、progress.md 更新
- [ ] 最終全分支 review:Ready to merge

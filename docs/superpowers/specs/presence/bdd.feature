Feature: 線上狀態(presence)
  顯示好友的線上/離線與最後上線時間;只對好友廣播與顯示。

  Background:
    Given 使用者 Alice 與 Bob 已註冊且為好友
    And 使用者 Carol 已註冊,但與 Alice 非好友

  # ── Happy Path ──────────────────────────────────────────────────────────
  Scenario: PR-01 好友上線即時通知
    Given Alice 有一條在線的 WS 連線
    When Bob 建立第一條 WS 連線
    Then Alice 收到 {type:"presence", user_id:Bob, online:true}

  Scenario: PR-02 好友離線通知並記錄最後上線
    Given Alice 在線、Bob 有一條在線連線
    When Bob 的最後一條連線斷開
    Then Alice 收到 {type:"presence", user_id:Bob, online:false} 且帶 last_seen_at
    And 資料庫中 Bob 的 last_seen_at 被更新為約當下時間

  Scenario: PR-03 初始快照併進 contacts
    When Alice 呼叫 GET /contacts
    Then 每筆好友含 online 與 last_seen_at 欄位
    And Bob 在線時其 online 為 true

  # ── Boundary：多連線只在首尾廣播 ──────────────────────────────────────────
  Scenario: PR-04 第二條連線不重複廣播上線
    Given Bob 已有一條在線連線,Alice 在線
    When Bob 再建立第二條連線
    Then Alice 不會收到新的 online presence 事件

  Scenario: PR-05 仍有連線時不誤報離線
    Given Bob 有兩條在線連線,Alice 在線
    When Bob 關閉其中一條(仍剩一條)
    Then Alice 不會收到 offline presence 事件
    And Bob 仍為 online

  # ── Permission / Privacy ────────────────────────────────────────────────
  Scenario: PR-06 非好友的狀態不外洩(廣播)
    Given Alice 在線
    When 非好友 Carol 上線或離線
    Then Alice 不會收到 Carol 的任何 presence 事件

  Scenario: PR-07 非好友不出現在 contacts
    When Alice 呼叫 GET /contacts
    Then 回傳清單不含 Carol

  # ── Edge ────────────────────────────────────────────────────────────────
  Scenario: PR-08 從未上線的好友
    Given Bob 從未建立過連線(last_seen_at 為 null)且目前離線
    When Alice 取得 contacts
    Then Bob 的 online 為 false 且 last_seen_at 為 null

  Scenario: PR-09 廣播只送在線好友
    Given Alice 目前離線
    When Bob 上線
    Then 系統不嘗試推 presence 給離線的 Alice(Alice 下次載入 contacts 取得快照)

  # ── 前端呈現(UI/單元) ──────────────────────────────────────────────────
  Scenario: PR-10 Sidebar 綠/灰點
    Given Alice 已登入並看到與 Bob 的 1對1 對話
    When Bob 為 online
    Then 對話列 Bob 旁顯示綠點
    When Bob 轉為 offline
    Then 綠點變灰點

  Scenario: PR-11 Thread header 文案
    Given Alice 開啟與 Bob 的 1對1 對話
    When Bob online
    Then header 顯示「在線」
    When Bob offline 且 last_seen_at 為 5 分鐘前
    Then header 顯示「最後上線 5 分鐘前」

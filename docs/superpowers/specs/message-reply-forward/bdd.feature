Feature: 訊息回覆 / 轉發
  作為聊天使用者，我可以對訊息行內引用回覆，或把訊息轉發到我參與的另一個對話。

  Background:
    Given Alice 與 Bob 是好友且有一個 1對1 對話
    And Alice 已登入

  # ---------- Happy Path ----------

  Scenario: 對訊息回覆顯示引用塊 (RF-01)
    Given Bob 在對話中送出訊息 "晚上要開會嗎"
    When Alice 回覆該訊息並輸入 "好，七點"
    Then Alice 與 Bob 都看到 "好，七點" 的泡泡上方有引用塊，內容為 "晚上要開會嗎" 與寄件人 Bob

  Scenario: 轉發文字訊息到另一個對話標示來源 (RF-02)
    Given Alice 與 Carol 也有一個對話
    And Bob 在 Alice↔Bob 對話送出訊息 "週報連結在這"
    When Alice 把該訊息轉發到 Alice↔Carol 對話
    Then Alice↔Carol 對話出現新訊息 "週報連結在這"
    And 該訊息標示 "轉發自 Bob"

  Scenario: 轉發帶附件的訊息一併帶附件 (RF-03)
    Given Bob 在 Alice↔Bob 對話送出一則帶圖片附件的訊息
    And Alice 與 Carol 有一個對話
    When Alice 把該訊息轉發到 Alice↔Carol 對話
    Then Alice↔Carol 對話的新訊息帶有同一個圖片附件且可顯示
    And 該訊息標示 "轉發自 Bob"

  # ---------- Validation Failure ----------

  Scenario: 跨對話回覆被拒 (RF-04)
    Given 存在一則屬於 Alice↔Carol 對話的訊息 M
    When Alice 在 Alice↔Bob 對話送訊息並把 reply_to_message_id 指向 M
    Then 後端回覆錯誤 reason "invalid_reply"
    And 不建立任何新訊息

  Scenario: 缺欄位的轉發被拒 (RF-05)
    When Alice 送出 forward 但缺少 to_conversation_id
    Then 後端回覆錯誤 reason "invalid_payload"

  # ---------- Permission / Authorization ----------

  Scenario: 轉發到非自己參與的對話被拒 (RF-06)
    Given 存在一個 Alice 不是成員的對話 T
    And Bob 在 Alice↔Bob 對話送出訊息 M
    When Alice 嘗試把 M 轉發到 T
    Then 後端回覆錯誤 reason "forbidden"

  Scenario: 轉發看不到的訊息被拒 (RF-07)
    Given 存在一則屬於 Bob↔Carol 對話的訊息 M（Alice 非成員）
    And Alice 與 Carol 有一個對話 D
    When Alice 嘗試把 M 轉發到 D
    Then 後端回覆錯誤 reason "forbidden"

  # ---------- Error Handling ----------

  Scenario: 轉發已刪除的訊息被拒 (RF-08)
    Given Bob 在 Alice↔Bob 對話送出訊息 M 後 M 被刪除
    And Alice 與 Carol 有一個對話 D
    When Alice 嘗試把 M 轉發到 D
    Then 後端回覆錯誤 reason "forbidden"

  # ---------- Boundary Conditions ----------

  Scenario: 引用已刪除的訊息顯示佔位 (RF-09)
    Given Bob 送出訊息 "舊訊息"，Alice 回覆它，之後 Bob 刪除 "舊訊息"
    When Alice 重新載入該對話歷史
    Then 該回覆的引用塊顯示 "原訊息已刪除"
    And reply_to.deleted 為 true

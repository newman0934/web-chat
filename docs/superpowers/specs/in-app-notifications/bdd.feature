Feature: 站內通知(in-app notifications)
  別人對我的訊息 reply / reaction / forward 時,我會收到一筆持久化的通知;
  開啟該訊息所在的對話即標為已讀。

  Background:
    Given 使用者 Alice 與 Bob 已註冊且為好友
    And 兩人之間有一個 1對1 對話 C
    And Bob 在 C 送出一則訊息 M

  # ── Happy Path ──────────────────────────────────────────────────────────
  Scenario: NB-01 被回覆產生通知(reply)
    When Alice 在 C 回覆 M(reply_to_message_id = M)
    Then Bob 得到一筆通知,type 為 "reply"
    And 該通知的 actor 是 Alice、conversation_id 是 C、message_id 是 M
    And 若 Bob 在線,Bob 透過 WS 收到 {type:"notification"}

  Scenario: NB-02 被按表情產生通知(reaction)
    When Alice 對 M 加上 👍
    Then Bob 得到一筆通知,type 為 "reaction" 且 emoji 為 "👍"

  Scenario: NB-03 被轉發產生通知(forward)
    Given Alice 與 Bob 另有一個對話 D
    When Alice 把 M 轉發到 D
    Then Bob 得到一筆通知,type 為 "forward"
    And 該通知的 conversation_id 是 M 原本所在的對話 C

  Scenario: NB-04 開啟對話標已讀
    Given Bob 有一筆指向 C 的未讀通知
    When Bob 開啟對話 C
    Then 該通知的 read_at 被填入,Bob 的未讀數下降
    But 只是開啟通知中心並不會把通知標為已讀

  Scenario: NB-05 未讀數與列表
    Given Bob 有 3 筆未讀通知與 1 筆已讀通知
    When Bob 呼叫 GET /notifications
    Then 回應的 items 依時間新到舊
    And 回應的 unread_count 為 3

  # ── Validation / Boundary ───────────────────────────────────────────────
  Scenario: NB-06 對自己的訊息互動不產生通知
    When Bob 自己對 M reply / 加表情 / 轉發
    Then 不產生任何通知(actor == 收件人)

  Scenario: NB-07 表情 toggle 移除不刪通知
    Given Alice 對 M 加 👍,Bob 已得到一筆 reaction 通知
    When Alice 再按一次 👍(移除)
    Then 不新增通知,且原本那筆通知仍存在

  Scenario: NB-08 一事件一通知(不聚合)
    When Alice 與 Carol 先後對 M 加表情
    Then Bob 得到 2 筆獨立的 reaction 通知

  Scenario: NB-09 被互動訊息已刪仍可運作
    Given Bob 有一筆指向 M 的通知
    And M 已被軟刪
    When Bob 取得通知列表
    Then 該通知仍在,message_preview 為空字串
    And 點擊仍可開啟對話 C

  # ── Permission / Authorization ──────────────────────────────────────────
  Scenario: NB-10 只能存取自己的通知
    When Bob 呼叫 GET /notifications
    Then 只回傳 user_id == Bob 的通知,不含他人的

  Scenario: NB-11 未帶有效 token 被拒
    When 以無效或缺少的 JWT 呼叫 GET /notifications
    Then 回應 401

  Scenario: NB-12 標他人對話已讀無效果
    When Bob 對「自己非成員的對話」呼叫 POST /notifications/read
    Then 不標記任何通知(marked = 0),且不洩漏該對話存在性

  # ── Error Handling ──────────────────────────────────────────────────────
  Scenario: NB-13 POST /notifications/read 缺 conversation_id
    When Bob 呼叫 POST /notifications/read 但未帶 conversation_id
    Then 回應 422(驗證錯誤)

  # ── 離線補齊 ─────────────────────────────────────────────────────────────
  Scenario: NB-14 離線期間的通知上線後補得回來
    Given Bob 離線
    When Alice 回覆了 Bob 的訊息 M
    And Bob 稍後重新載入(GET /notifications)
    Then Bob 看得到那筆 reply 通知並計入未讀

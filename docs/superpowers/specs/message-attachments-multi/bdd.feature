# language: zh-TW
功能: 多附件
  作為使用者
  我想在一則訊息夾帶多個附件
  以便一次傳送多張圖片或多個檔案

  背景:
    假設 已有使用者 Alice、Bob，互為好友且有一個 1對1 對話

  # ---- Happy Path ----
  場景: MA-01 多附件送出並顯示
    假設 Alice 上傳 3 個各 0.5MB 的檔案,取得 3 個 attachment_id
    當 Alice 送出帶這 3 個附件的訊息
    那麼 該訊息的 attachments 含 3 個,順序與上傳一致

  場景: MA-08 多選送出並以格狀渲染（UI）
    假設 Alice 已登入並開啟對話
    當 Alice 一次選取 2 張圖片並送出
    那麼 訊息泡泡以格狀縮圖顯示 2 張圖片

  # ---- Boundary ----
  場景: MA-02 超過 5 個附件被拒
    假設 Alice 上傳了 6 個附件
    當 Alice 送出帶 6 個附件的訊息
    那麼 被拒（too_many_attachments）

  場景: MA-03 單檔超過 1MB 被拒
    當 Alice 上傳一個 1.5MB 的檔案
    那麼 上傳被拒（413）

  場景: MA-04 整則總量超過 10MB 被拒
    假設 Alice 上傳的附件總量超過 10MB
    當 Alice 送出帶這些附件的訊息
    那麼 被拒（attachments_too_large）

  # ---- Error Handling ----
  場景: MA-07 非本人或已綁定的附件被拒
    假設 其中一個 attachment_id 不屬於 Alice 或已綁定其他訊息
    當 Alice 送出帶該附件的訊息
    那麼 被拒（invalid_attachment）並且不部分綁定

  # ---- 與其他功能互動 ----
  場景: MA-05 轉發複製全部附件
    假設 有一則帶 3 個附件的訊息
    當 Alice 轉發該訊息到另一個對話
    那麼 新訊息含全部 3 個附件

  場景: MA-06 撤回 / 刪除清空附件
    假設 Alice 送出一則帶 2 個附件的訊息
    當 Alice 撤回（或刪除）該訊息
    那麼 該訊息 attachments 為空

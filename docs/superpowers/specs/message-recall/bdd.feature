# language: zh-TW
功能: 訊息撤回
  作為寄件人
  我想在送出後短時間內撤回訊息
  以便徹底收回誤傳的內容

  背景:
    假設 已有使用者 Alice、Bob，互為好友且有一個 1對1 對話

  # ---- Happy Path ----
  場景: MR-01 寄件人 2 分內撤回成功並廣播
    假設 Alice 送出訊息 "誤傳的內容"
    當 Alice 撤回該訊息
    那麼 對話在線成員收到 message_updated 廣播
    並且 該訊息 recalled 為 true、content 為空

  場景: MR-09 撤回後顯示系統訊息（UI）
    假設 Alice 已登入並開啟對話、且送出一則訊息
    當 Alice 點擊該訊息的「撤回」
    那麼 該訊息位置顯示「你撤回了一則訊息」
    並且 不再顯示原內容與動作鈕

  # ---- Authorization ----
  場景: MR-02 非寄件人撤回被拒
    假設 Alice 送出訊息 "abc"
    當 Bob 嘗試撤回該訊息
    那麼 被拒（forbidden）
    並且 該訊息維持未撤回

  # ---- Boundary ----
  場景: MR-03 逾時撤回被拒
    假設 Alice 有一則送出已超過 2 分鐘的訊息
    當 Alice 嘗試撤回該訊息
    那麼 被拒（recall_window_passed）

  # ---- Error Handling ----
  場景: MR-04 撤回後不可再編輯/表情/釘選
    假設 Alice 已撤回自己的一則訊息
    當 對該訊息送出 edit / react / pin
    那麼 皆被拒

  場景: MR-05 撤回已刪除訊息被拒
    假設 Alice 已刪除自己的一則訊息
    當 Alice 嘗試撤回該訊息
    那麼 被拒

  場景: MR-06 重複撤回被拒
    假設 Alice 已撤回一則訊息
    當 Alice 再次撤回同一則
    那麼 被拒

  場景: MR-07 已撤回訊息不出現在搜尋
    假設 Alice 送出含關鍵字的訊息後將其撤回
    當 Alice 以該關鍵字搜尋
    那麼 結果不包含該訊息

  場景: MR-08 撤回已釘選訊息自動取消釘選
    假設 群組管理員釘選了一則訊息
    當 該訊息的寄件人在時窗內撤回它
    那麼 該訊息自動取消釘選
    並且 成員收到 message_unpinned 廣播

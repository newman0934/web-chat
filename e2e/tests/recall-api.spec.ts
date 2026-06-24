/**
 * E2E spec: 訊息撤回 後端 API 驗收(WS + REST,無 UI)
 *
 * 對應 BDD(docs/superpowers/specs/message-recall/bdd.feature)MR-01..08。
 * 逾時(MR-03)由 backend pytest 覆蓋(需操弄時間),e2e 不寫以免 flaky。
 * Task 0 骨架;Task 2/5 實作轉綠。
 */
import { test } from "@playwright/test";

test.fixme("MR-01 寄件人 2 分內撤回成功並廣播", async () => {});
test.fixme("MR-02 非寄件人撤回被拒(forbidden)", async () => {});
test.fixme("MR-04 撤回後不可再編輯/表情/釘選", async () => {});
test.fixme("MR-05 撤回已刪除訊息被拒", async () => {});
test.fixme("MR-06 重複撤回被拒", async () => {});
test.fixme("MR-07 已撤回訊息不出現在搜尋", async () => {});
test.fixme("MR-08 撤回已釘選訊息自動取消釘選", async () => {});

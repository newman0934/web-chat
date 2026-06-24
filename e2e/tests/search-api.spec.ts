/**
 * E2E spec: 訊息搜尋 後端 API 驗收(REST,無 UI)
 *
 * 對應 BDD(docs/superpowers/specs/message-search/bdd.feature)MS-01..11 的 API 部分。
 * Task 0 骨架:先以 test.fixme 佔位確立 BDD → Playwright 追溯;Task 2/3/6 逐一實作轉綠。
 */
import { test } from "@playwright/test";

test.fixme("MS-01 以內容關鍵字命中", async () => {});
test.fixme("MS-02 以寄件者名稱命中", async () => {});
test.fixme("MS-03 排除已刪除訊息", async () => {});
test.fixme("MS-04 不外洩他人對話", async () => {});
test.fixme("MS-06 未授權搜尋被拒 → 401", async () => {});
test.fixme("MS-05a 空白關鍵字 → 422", async () => {});
test.fixme("MS-05b 過長關鍵字 → 422", async () => {});
test.fixme("MS-09 萬用字元逸出(50%)", async () => {});
test.fixme("MS-10 分頁不重不漏", async () => {});
test.fixme("MS-08 互斥分頁參數 → 422", async () => {});
test.fixme("MS-11 around 視窗載入邊界", async () => {});

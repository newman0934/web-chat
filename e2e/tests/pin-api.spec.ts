/**
 * E2E spec: 訊息置頂 後端 API 驗收(WS + REST,無 UI)
 *
 * 對應 BDD(docs/superpowers/specs/message-pin/bdd.feature)MP-01..10 的 API 部分。
 * Task 0 骨架:test.fixme 佔位確立追溯;Task 3/6 實作轉綠。
 */
import { test } from "@playwright/test";

test.fixme("MP-01 釘選訊息並廣播", async () => {});
test.fixme("MP-02 取消釘選並廣播", async () => {});
test.fixme("MP-07 取得釘選清單(新釘在前)", async () => {});
test.fixme("MP-03 群組非管理員釘選被拒(forbidden)", async () => {});
test.fixme("MP-05 非成員釘選被拒", async () => {});
test.fixme("MP-04 超過上限被拒(pin_limit)", async () => {});
test.fixme("MP-04b 取消後可再釘", async () => {});
test.fixme("MP-06 刪除已釘訊息自動取消釘選", async () => {});
test.fixme("MP-09 重複釘選為冪等", async () => {});
test.fixme("MP-10 釘選不存在的訊息被拒(not_found)", async () => {});

/**
 * E2E spec: 訊息搜尋 前端 UI 驗收(瀏覽器)
 *
 * MS-07:登入 → 在側欄搜尋 → 點結果 → 切到該對話、命中訊息可見且高亮。
 * 種一則「未開啟對話」中的訊息,驗證搜尋可直接跳轉(免先手動開對話)。
 */
import { test, expect } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, uiLogin } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";
const KW = `跳轉測試${TS}`;

const alice = { email: `sui-alice-${TS}@example.com`, name: `SUI-Alice-${TS}` };
const bob = { email: `sui-bob-${TS}@example.com`, name: `SUI-Bob-${TS}` };

test.beforeAll(async ({ request, browser }) => {
  const ta = await apiRegister(request, alice.email, alice.name, PW);
  await apiRegister(request, bob.email, bob.name, PW);
  const tb = await apiRegister(request, bob.email, bob.name, PW); // 取 Bob token(冪等→login)
  await apiAddContact(request, ta, bob.email);
  const convAB = (await apiAddContact(request, ta, bob.email)).conversation_id;

  // Bob 在 Alice↔Bob 送一則含關鍵字的訊息(Alice 尚未開啟此對話)。
  const ctx = await browser.newContext();
  const seedPage = await ctx.newPage();
  await seedPage.goto(`${API}/health`);
  await wsSendMessage(seedPage, tb, convAB, `${KW} 這是要被搜尋並跳轉的訊息`);
  await ctx.close();
});

test("MS-07 點搜尋結果跳轉並高亮", async ({ page }) => {
  await uiLogin(page, alice.email, PW);

  // 在側欄搜尋框輸入關鍵字(debounce 後出結果)。
  await page.getByLabel("搜尋訊息").fill(KW);
  const results = page.getByTestId("search-results");
  await expect(results).toBeVisible();
  const resultBtn = results.locator("button").first();
  await expect(resultBtn).toBeVisible();

  // 點結果 → 切到對話、跳轉並高亮命中訊息。
  await resultBtn.click();
  await expect(page.getByText(`${KW} 這是要被搜尋並跳轉的訊息`)).toBeVisible();
  // 命中訊息泡泡帶高亮標記(數秒後會自動消失,故立即斷言)。
  await expect(page.locator('[data-highlighted="true"]')).toBeVisible();
});

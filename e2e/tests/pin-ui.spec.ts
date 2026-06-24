/**
 * E2E spec: 訊息置頂 前端 UI 驗收(瀏覽器)
 *
 * MP-08:開對話 → 頂部釘選列 → 點擊 → 跳轉到該訊息且高亮。
 * 預先(WS)釘好一則訊息,登入後開對話即見釘選列。
 */
import { test, expect } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, wsRequest, uiLogin } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";
const KW = `釘選跳轉${TS}`;

const alice = { email: `pui-a-${TS}@example.com`, name: `PUI-Alice-${TS}` };
const bob = { email: `pui-b-${TS}@example.com`, name: `PUI-Bob-${TS}` };

test.beforeAll(async ({ request, browser }) => {
  const ta = await apiRegister(request, alice.email, alice.name, PW);
  const tb = await apiRegister(request, bob.email, bob.name, PW);
  await apiAddContact(request, ta, bob.email);
  const convAB = (await apiAddContact(request, ta, bob.email)).conversation_id;

  const ctx = await browser.newContext();
  const seedPage = await ctx.newPage();
  await seedPage.goto(`${API}/health`);
  const msg = await wsSendMessage(seedPage, tb, convAB, `${KW} 這是被釘選要跳轉的訊息`);
  await wsRequest(seedPage, ta, { type: "pin", message_id: msg.id }, "message_pinned");
  await ctx.close();
});

test("MP-08 點釘選列跳轉並高亮", async ({ page }) => {
  await uiLogin(page, alice.email, PW);

  // 開啟與 Bob 的對話
  await page.getByText(bob.name).first().click();

  // 頂部釘選列出現,點擊最新釘選 → 跳轉並高亮
  const bar = page.getByTestId("pinned-bar");
  await expect(bar).toBeVisible();
  await bar.getByRole("button").first().click();

  // 命中訊息泡泡被高亮(暫時),且內容為被釘選的那則。
  const highlighted = page.locator('[data-highlighted="true"]');
  await expect(highlighted).toBeVisible();
  await expect(highlighted).toContainText(KW);
});

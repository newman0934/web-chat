/**
 * E2E spec: 站內通知 — 瀏覽器 UI(鈴鐺紅點 + 點擊導向 + 清未讀)
 *
 * 與 notifications-api.spec.ts 互補:真的開瀏覽器看鈴鐺未讀紅點、展開通知中心、
 * 點一筆 → 導向對應對話並清未讀。
 *
 * 策略:通知在 Alice 登入「前」就用 WS helper 種好(Bob 回覆 Alice 的訊息),
 * Alice 登入後由 mount 的 listNotifications(REST)載入 → 紅點穩定顯示
 * (不依賴 dev StrictMode 下的即時 WS 推播時序)。標已讀也走 REST,故穩定。
 *
 * 對應:NB-04(開對話標已讀)/ 鈴鐺紅點 / 點擊導向 的 UI 版。
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, wsRequest, uiLogin } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const ALICE = `nui-alice-${TS}@example.com`;
const BOB = `nui-bob-${TS}@example.com`;
const PW = "TestPass123!";

let aliceCtx: BrowserContext;
let alicePage: Page;

test.beforeAll(async ({ request, browser }) => {
  const aliceToken = await apiRegister(request, ALICE, "Alice-NUI", PW);
  const bobToken = await apiRegister(request, BOB, "Bob-NUI", PW);
  const conv = (await apiAddContact(request, aliceToken, BOB)).conversation_id;

  aliceCtx = await browser.newContext();
  alicePage = await aliceCtx.newPage();
  await alicePage.goto(`${API}/health`);

  // 種通知:Alice 送一則 M,Bob 回覆 M → Alice 得一筆 reply 通知(此刻 Alice 離線)。
  const m = await wsSendMessage(alicePage, aliceToken, conv, "Alice 的訊息");
  await wsRequest(alicePage, bobToken, {
    type: "message", conversation_id: conv, content: "Bob 回覆", reply_to_message_id: m.id,
    temp_id: `t-${TS}`,
  }, "ack");
});

test.afterAll(async () => {
  await aliceCtx?.close();
});

test("NUI 鈴鐺紅點 → 展開 → 點通知導向對話並清未讀", async () => {
  await uiLogin(alicePage, ALICE, PW);
  await alicePage.waitForSelector("aside", { timeout: 15_000 });

  // 鈴鐺出現未讀紅點(載入自 REST)
  const badge = alicePage.getByTestId("notif-badge");
  await expect(badge).toBeVisible({ timeout: 15_000 });
  await expect(badge).toHaveText("1");

  // 展開通知中心,看到 Bob 的回覆通知(用 dropdown 專屬的「回覆了你」文案定位,
  // 避免與側欄對話清單的「Bob-NUI」撞名)
  await alicePage.getByRole("button", { name: "通知" }).click();
  const item = alicePage.getByText(/回覆了你/);
  await expect(item).toBeVisible();
  await expect(item).toContainText("Bob-NUI");

  // 點該通知 → 導向與 Bob 的對話(Thread 出現),紅點清掉
  await item.click();
  await expect(alicePage.locator("section header h2")).toContainText("Bob-NUI", { timeout: 10_000 });
  await expect(alicePage.getByTestId("notif-badge")).toHaveCount(0, { timeout: 10_000 });
});

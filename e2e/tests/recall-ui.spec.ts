/**
 * E2E spec: 訊息撤回 前端 UI 驗收(瀏覽器)
 *
 * MR-09:寄件人送出訊息 → 點「撤回」→ 該訊息顯示系統訊息「你撤回了一則訊息」。
 * 訊息於登入後(stack 已暖)才送出,確保仍在 2 分時窗內;撤回採 retryAction(dev/StrictMode
 * 下 chat send() 在 socket 未 OPEN 時靜默丟棄,故重做到 server 反映為止)。
 */
import { test, expect } from "@playwright/test";
import { apiRegister, apiAddContact, uiLogin } from "./helpers";

const TS = Date.now();
const PW = "TestPass123!";
const MSG = `撤回UI測試${TS}`;

const alice = { email: `rui-a-${TS}@example.com`, name: `RUI-Alice-${TS}` };
const bob = { email: `rui-b-${TS}@example.com`, name: `RUI-Bob-${TS}` };

test.beforeAll(async ({ request }) => {
  const ta = await apiRegister(request, alice.email, alice.name, PW);
  await apiRegister(request, bob.email, bob.name, PW);
  await apiAddContact(request, ta, bob.email);
});

test("MR-09 撤回後顯示系統訊息", async ({ page }) => {
  await uiLogin(page, alice.email, PW);
  await page.getByText(bob.name).first().click();

  // 登入後才送訊息(stack 已暖、計時從現在起算,確保 2 分時窗充足)。
  const input = page.getByLabel("訊息輸入");
  const send = page.getByRole("button", { name: "送出" });
  const bubble = page.locator("[data-message-id]").filter({ hasText: MSG });
  const recalled = page.getByTestId("recalled-message");

  // 送出 → 等到出現「撤回」鈕(代表訊息已 sent 且在時窗內)。
  // dev/StrictMode 下 send() 可能落空 → 訊息變「未送出」;此時點重試,直到成功 sent。
  await expect(async () => {
    if ((await bubble.count()) === 0) {
      await input.fill(MSG);
      await send.click();
    } else if ((await bubble.getByText("未送出，點擊重試").count()) > 0) {
      await bubble.getByText("未送出，點擊重試").click();
    }
    await expect(bubble.getByRole("button", { name: "撤回" })).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 30000 });

  // 點「撤回」直到該訊息變成系統訊息。
  await expect(async () => {
    await page.getByRole("button", { name: "撤回" }).first().click({ timeout: 2000 }).catch(() => {});
    await expect(recalled).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 20000 });
  await expect(recalled).toContainText("你撤回了一則訊息");
});

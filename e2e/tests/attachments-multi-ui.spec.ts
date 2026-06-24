/**
 * E2E spec: 多附件 前端 UI 驗收(瀏覽器)
 *
 * MA-08:一次選取 2 張圖片送出,泡泡以格狀縮圖顯示。
 * 送出前先等 WS「已連線」,避免 dev/StrictMode 下 send() 在 socket 未 OPEN 時靜默丟棄。
 */
import { test, expect } from "@playwright/test";
import { apiRegister, apiAddContact, uiLogin } from "./helpers";

const TS = Date.now();
const PW = "TestPass123!";

const alice = { email: `aui-a-${TS}@example.com`, name: `AUI-Alice-${TS}` };
const bob = { email: `aui-b-${TS}@example.com`, name: `AUI-Bob-${TS}` };

const PNG = Buffer.alloc(2048, 1);

test.beforeAll(async ({ request }) => {
  const ta = await apiRegister(request, alice.email, alice.name, PW);
  await apiRegister(request, bob.email, bob.name, PW);
  await apiAddContact(request, ta, bob.email);
});

test("MA-08 多選圖片送出並以格狀渲染", async ({ page }) => {
  await uiLogin(page, alice.email, PW);
  await page.getByText(bob.name).first().click();

  // 選 2 張圖片 → 待送區出現 2 個
  await page.locator('input[type="file"]').setInputFiles([
    { name: "p1.png", mimeType: "image/png", buffer: PNG },
    { name: "p2.png", mimeType: "image/png", buffer: PNG },
  ]);
  await expect(page.getByTestId("pending-attachments").locator("li")).toHaveCount(2);

  // 等 WS 已連線再送出(避免 send 落空)
  await expect(page.getByText("已連線")).toBeVisible({ timeout: 15000 });
  await page.getByRole("button", { name: "送出" }).click();

  // 泡泡內出現含 2 張圖片的格狀附件區
  const gallery = page.getByTestId("attachments").last();
  await expect(gallery).toBeVisible({ timeout: 15000 });
  await expect(gallery.locator("img")).toHaveCount(2);
});

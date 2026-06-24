/**
 * E2E spec: 多附件 前端 UI 驗收(瀏覽器)
 *
 * MA-08:含 2 張圖片的訊息,泡泡以格狀縮圖顯示。
 * 訊息經 WS 種入(可靠),登入後驗證 UI 以格狀渲染 2 張圖片(本測試重點為「格狀呈現」);
 * 多選待送清單由 setInputFiles 直接驗證(REST 上傳,可靠,不依賴 dev WS 送訊)。
 */
import { test, expect } from "@playwright/test";
import { apiRegister, apiAddContact, wsRequest, uiLogin } from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";
const PNG = Buffer.alloc(2048, 1);

const alice = { email: `aui-a-${TS}@example.com`, name: `AUI-Alice-${TS}` };
const bob = { email: `aui-b-${TS}@example.com`, name: `AUI-Bob-${TS}` };

async function upload(request: any, token: string, name: string): Promise<string> {
  const resp = await request.post(`${API}/uploads`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: { file: { name, mimeType: "image/png", buffer: PNG } },
  });
  expect(resp.status()).toBe(201);
  return (await resp.json()).id;
}

test.beforeAll(async ({ request, browser }) => {
  const ta = await apiRegister(request, alice.email, alice.name, PW);
  const tb = await apiRegister(request, bob.email, bob.name, PW);
  const convAB = (await apiAddContact(request, ta, bob.email)).conversation_id;
  // Bob 上傳 2 張圖、(經 WS)送一則含 2 附件的訊息。
  const a1 = await upload(request, tb, "p1.png");
  const a2 = await upload(request, tb, "p2.png");
  const ctx = await browser.newContext();
  const seedPage = await ctx.newPage();
  await seedPage.goto(`${API}/health`);
  await wsRequest(
    seedPage, tb,
    { type: "message", conversation_id: convAB, content: "看圖", attachment_ids: [a1, a2], temp_id: "seed" },
    "ack",
  );
  await ctx.close();
});

test("MA-08 多附件以格狀縮圖顯示 + 多選待送清單", async ({ page, request }) => {
  await uiLogin(page, alice.email, PW);
  await page.getByText(bob.name).first().click();

  // 含 2 圖的訊息泡泡以格狀渲染 2 張圖片。
  const gallery = page.getByTestId("attachments").last();
  await expect(gallery).toBeVisible({ timeout: 15000 });
  await expect(gallery.locator("img")).toHaveCount(2);

  // 多選 → 待送清單即時顯示 2 個(REST 上傳,不依賴 WS 送訊)。
  await page.locator('input[type="file"]').setInputFiles([
    { name: "x1.png", mimeType: "image/png", buffer: PNG },
    { name: "x2.png", mimeType: "image/png", buffer: PNG },
  ]);
  await expect(page.getByTestId("pending-attachments").locator("li")).toHaveCount(2);
});

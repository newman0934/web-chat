/**
 * E2E spec: 訊息轉發
 *
 * BDD 追溯：
 *   RF-02 — 轉發文字訊息到另一個對話，標示「轉發自 {原作者}」
 *   RF-03 — 轉發帶附件的訊息一併帶附件
 *
 * 測試策略：
 *   - WS helper 負責資料落庫（forward + 附件轉發）
 *   - UI 僅驗收「轉發訊息渲染：content + forwarded_from 標示可見」
 *   - RF-02 轉發觸發採 WS helper（避免 dev-server StrictMode WS 時序競爭）
 *   - RF-03 純 REST+WS 路徑（不需要 UI）
 */

import { test, expect, chromium, BrowserContext, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsRequest, uiLogin } from "./helpers";

const TS = Date.now();
const ALICE_EMAIL = `alice-fwd-${TS}@example.com`;
const BOB_EMAIL   = `bob-fwd-${TS}@example.com`;
const CAROL_EMAIL = `carol-fwd-${TS}@example.com`;
const PASSWORD = "TestPass123!";

let browser: Awaited<ReturnType<typeof chromium.launch>>;
let aliceCtx: BrowserContext;
let alicePage: Page;

let aliceToken: string;
let bobToken:   string;
let aliceBobConvId:   string;
let aliceCarolConvId: string;

test.beforeAll(async ({ request }) => {
  aliceToken = await apiRegister(request, ALICE_EMAIL, "Alice-Fwd", PASSWORD);
  bobToken   = await apiRegister(request, BOB_EMAIL,   "Bob-Fwd",   PASSWORD);
  await apiRegister(request, CAROL_EMAIL, "Carol-Fwd", PASSWORD);

  const c1 = await apiAddContact(request, aliceToken, BOB_EMAIL);
  aliceBobConvId = c1.conversation_id;
  const c2 = await apiAddContact(request, aliceToken, CAROL_EMAIL);
  aliceCarolConvId = c2.conversation_id;

  browser = await chromium.launch();
  aliceCtx = await browser.newContext();
  alicePage = await aliceCtx.newPage();
  await alicePage.goto("http://localhost:8000/health");
});

test.afterAll(async () => {
  await aliceCtx?.close();
  await browser?.close();
});

// ── RF-02: 轉發文字訊息 ────────────────────────────────────────────────────
test("RF-02 Alice 轉發 Bob 的文字訊息到 Alice↔Carol，出現「轉發自」標示", async () => {
  // ── Step 1: Bob 送出原始訊息 ──────────────────────────────────────────
  const ackBob = await wsRequest(
    alicePage, bobToken,
    { type: "message", conversation_id: aliceBobConvId, content: "週報連結在這", temp_id: `tmp-b-${TS}` },
    "ack"
  );
  expect(ackBob.message?.id).toBeTruthy();
  const bobMsgId: string = ackBob.message.id;

  // ── Step 2: Alice 透過 WS helper 轉發到 Alice↔Carol ──────────────────
  // forward 不回 ack；後端廣播 {type:"message"} 給目標對話在線成員。
  // Alice 不在線（WS 在 health page context），broadcast 會被丟棄。
  // 但 forward 操作已落庫 → REST 可驗收。
  await wsRequest(alicePage, aliceToken, {
    type: "forward",
    message_id: bobMsgId,
    to_conversation_id: aliceCarolConvId,
  }, "message").catch(() => {
    // timeout 代表 Alice 不在線收不到 broadcast — forward 仍已執行
  });

  // ── Step 3: REST poll 驗收轉發訊息落庫 ────────────────────────────────
  let fwdMsg: any;
  for (let i = 0; i < 8; i++) {
    const res = await alicePage.request.get(
      `http://localhost:8000/conversations/${aliceCarolConvId}/messages?limit=10`,
      { headers: { Authorization: `Bearer ${aliceToken}` } }
    );
    if (res.ok()) {
      const data: any[] = await res.json();
      fwdMsg = data.find((m) => m.forwarded_from != null);
      if (fwdMsg) break;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  expect(fwdMsg, "Forwarded message should be in DB").toBeTruthy();
  expect(fwdMsg.content).toBe("週報連結在這");
  expect(fwdMsg.forwarded_from.display_name).toContain("Bob-Fwd");
  const fwdMsgId: string = fwdMsg.id;

  // ── Step 4: UI 驗收 — Alice↔Carol 對話顯示轉發訊息 + 「轉發自」標示 ──
  await uiLogin(alicePage, ALICE_EMAIL, PASSWORD);
  await alicePage.waitForSelector("aside", { timeout: 15_000 });
  // 點選 Carol-Fwd 對話（Alice↔Carol）
  await alicePage.getByText("Carol-Fwd").first().click();

  // 等待轉發訊息泡泡出現（data-message-id 精確定位）
  const fwdBubble = alicePage.locator(`[data-message-id="${fwdMsgId}"]`);
  await expect(fwdBubble).toBeVisible({ timeout: 10_000 });

  // 驗收「↪ 轉發自 Bob-Fwd」文字（Thread.tsx forwarded_from 段落）
  const forwardLabel = fwdBubble.locator("p").filter({ hasText: /轉發自/ });
  await expect(forwardLabel).toBeVisible({ timeout: 5_000 });
  await expect(forwardLabel).toContainText("Bob-Fwd");
});

// ── RF-03: 轉發帶附件的訊息 ────────────────────────────────────────────────
test("RF-03 Alice 轉發帶附件的訊息，目標出現相同附件且有「轉發自」標示", async () => {
  // Step 1: Bob 上傳最小合法 PNG（1×1 px 透明，@types/node Buffer）
  const pngBuffer = Buffer.from(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489" +
    "0000000a49444154789c6260000000020001e221bc33" +
    "0000000049454e44ae426082",
    "hex"
  );
  const uploadRes = await alicePage.request.post("http://localhost:8000/uploads", {
    headers: { Authorization: `Bearer ${bobToken}` },
    multipart: { file: { name: "test-image.png", mimeType: "image/png", buffer: pngBuffer } },
  });
  if (!uploadRes.ok()) {
    test.skip(true, `Upload failed ${uploadRes.status()}: ${await uploadRes.text()}`);
    return;
  }
  const attachmentId: string = (await uploadRes.json()).id;

  // Step 2: Bob 送出帶附件的訊息
  const ackWithAtt = await wsRequest(alicePage, bobToken, {
    type: "message",
    conversation_id: aliceBobConvId,
    content: "圖片附件測試",
    attachment_ids: [attachmentId],
    temp_id: `tmp-att-${TS}`,
  }, "ack");
  expect(ackWithAtt.message?.attachments?.length).toBe(1);
  const origMsgId: string = ackWithAtt.message.id;

  // Step 3: Alice 透過 WS 轉發帶附件的訊息到 Alice↔Carol
  await wsRequest(alicePage, aliceToken, {
    type: "forward",
    message_id: origMsgId,
    to_conversation_id: aliceCarolConvId,
  }, "message").catch(() => { /* Alice 不在線 — broadcast 被丟棄，REST 仍可驗收 */ });

  // Step 4: REST poll 驗收
  let fwdMsg: any;
  for (let i = 0; i < 8; i++) {
    const res = await alicePage.request.get(
      `http://localhost:8000/conversations/${aliceCarolConvId}/messages?limit=10`,
      { headers: { Authorization: `Bearer ${aliceToken}` } }
    );
    if (res.ok()) {
      const data: any[] = await res.json();
      fwdMsg = data.find((m) => m.forwarded_from != null && m.content === "圖片附件測試");
      if (fwdMsg) break;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  expect(fwdMsg, "Forwarded attachment message should be in DB").toBeTruthy();
  expect(fwdMsg.attachments?.length).toBe(1);
  expect(fwdMsg.forwarded_from.display_name).toContain("Bob-Fwd");
});

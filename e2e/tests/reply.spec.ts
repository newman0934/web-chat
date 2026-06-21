/**
 * E2E spec: 訊息回覆
 *
 * BDD 追溯：
 *   RF-01 — 對訊息回覆顯示引用塊（寄件人 + 摘要）
 *
 * 測試策略：
 *   - REST/WS helper 負責資料落庫（register/login/contact/sendMsg/reply）
 *   - UI（Alice + Bob 兩個 context）負責驗收 quote block 可見性
 *   - 避免依賴 shell dev-server StrictMode 下 WS 雙掛載的時序競爭：
 *     reply 訊息用 WS helper 直接送，不經 UI 送出鈕，
 *     UI 僅負責「載入歷史 → 顯示引用塊」的渲染驗收。
 *   - RF-01 要求「Alice 與 Bob 都看到引用塊」→ 分別用兩個 context 登入驗收。
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsRequest, uiLogin } from "./helpers";

const TS = Date.now();
const ALICE_EMAIL = `alice-reply-${TS}@example.com`;
const BOB_EMAIL   = `bob-reply-${TS}@example.com`;
const PASSWORD = "TestPass123!";

let aliceCtx: BrowserContext;
let bobCtx:   BrowserContext;
let alicePage: Page;
let bobPage:   Page;
let aliceToken: string;
let bobToken:   string;
let convId: string;

test.beforeAll(async ({ request, browser }) => {
  aliceToken = await apiRegister(request, ALICE_EMAIL, "Alice-Reply", PASSWORD);
  bobToken   = await apiRegister(request, BOB_EMAIL,   "Bob-Reply",   PASSWORD);
  const contact = await apiAddContact(request, aliceToken, BOB_EMAIL);
  convId = contact.conversation_id;

  aliceCtx = await browser.newContext();
  bobCtx   = await browser.newContext();
  alicePage = await aliceCtx.newPage();
  bobPage   = await bobCtx.newPage();
  // 預先導航到 backend origin，讓 page.evaluate 內的 WS evaluate 可通
  await alicePage.goto("http://localhost:8000/health");
  await bobPage.goto("http://localhost:8000/health");
});

test.afterAll(async () => {
  await aliceCtx?.close();
  await bobCtx?.close();
});

// ── RF-01: 對訊息回覆顯示引用塊 ────────────────────────────────────────────
test("RF-01 Bob 送訊息、Alice 回覆，雙方泡泡出現引用塊", async () => {
  // ── Step 1: Bob 透過 WS helper 送出原始訊息 ─────────────────────────────
  const ackBob = await wsRequest(
    alicePage,
    bobToken,
    { type: "message", conversation_id: convId, content: "晚上要開會嗎", temp_id: `tmp-bob-${TS}` },
    "ack"
  );
  expect(ackBob.message?.id).toBeTruthy();
  const bobMsgId: string = ackBob.message.id;

  // ── Step 2: Alice 透過 WS helper 回覆（reply_to_message_id = bobMsgId）─
  // 直接走 WS helper，避免 shell dev-server StrictMode double-mount 的 WS 時序競爭
  const ackAlice = await wsRequest(
    alicePage,
    aliceToken,
    {
      type: "message",
      conversation_id: convId,
      content: "好，七點",
      reply_to_message_id: bobMsgId,
      temp_id: `tmp-alice-${TS}`,
    },
    "ack"
  );
  expect(ackAlice.message?.id).toBeTruthy();
  expect(ackAlice.message.reply_to).toBeTruthy();
  expect(ackAlice.message.reply_to.content).toContain("晚上要開會嗎");
  const aliceMsgId: string = ackAlice.message.id;

  // ── Step 3: REST 確認 DB 有 reply_to ────────────────────────────────────
  const msgsRes = await alicePage.request.get(
    `http://localhost:8000/conversations/${convId}/messages?limit=10`,
    { headers: { Authorization: `Bearer ${aliceToken}` } }
  );
  expect(msgsRes.ok()).toBeTruthy();
  const msgs: any[] = await msgsRes.json();
  const replyMsg = msgs.find((m) => m.id === aliceMsgId);
  expect(replyMsg?.reply_to).toBeTruthy();
  expect(replyMsg.reply_to.content).toContain("晚上要開會嗎");

  // ── Step 4: Alice UI 驗收 — 載入歷史後 quote block 可見 ──────────────
  await uiLogin(alicePage, ALICE_EMAIL, PASSWORD);
  await alicePage.waitForSelector("aside", { timeout: 15_000 });
  await alicePage.getByText("Bob-Reply").first().click();

  // 等待 Alice 的回覆泡泡出現（用 data-message-id 精確定位）
  const aliceBubble = alicePage.locator(`[data-message-id="${aliceMsgId}"]`);
  await expect(aliceBubble).toBeVisible({ timeout: 10_000 });

  // 引用塊（border-l-4 button）應在泡泡內
  const quoteBlock = aliceBubble.locator("button.border-l-4");
  await expect(quoteBlock).toBeVisible({ timeout: 5_000 });
  await expect(quoteBlock).toContainText("晚上要開會嗎");
  await expect(quoteBlock).toContainText("Bob-Reply");

  // ── Step 5: Bob UI 驗收 — 同一引用塊在 Bob 的視窗也可見 ───────────────
  await uiLogin(bobPage, BOB_EMAIL, PASSWORD);
  await bobPage.waitForSelector("aside", { timeout: 15_000 });
  await bobPage.getByText("Alice-Reply").first().click();

  const bobAliceBubble = bobPage.locator(`[data-message-id="${aliceMsgId}"]`);
  await expect(bobAliceBubble).toBeVisible({ timeout: 10_000 });
  const bobQuoteBlock = bobAliceBubble.locator("button.border-l-4");
  await expect(bobQuoteBlock).toBeVisible({ timeout: 5_000 });
  await expect(bobQuoteBlock).toContainText("晚上要開會嗎");
});

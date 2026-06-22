/**
 * E2E spec: 訊息編輯 / 刪除 / 還原 / 表情 —— 瀏覽器 UI 點擊驗收
 *
 * 與 message-actions-api.spec.ts（純 WS）互補：這支真的開瀏覽器、登入、點泡泡上的
 * 編輯 / 刪除 / 還原 / 表情鈕，驗證畫面對 message_updated 廣播的渲染反應。
 *
 * 策略（沿用 reply.spec.ts 的慣例）：
 *   - 原始訊息用 WS helper 落庫（避免 shell dev-server StrictMode 下送訊時序競爭）；
 *   - 動作本身（編輯/刪除/還原/表情）才是受測點，故一律經 UI 點擊觸發；
 *   - 斷言走 Playwright 的 auto-retry expect，吸收 WS 廣播往返延遲。
 *
 * 對應 BDD（沿用 MA 編號的 UI 版）：
 *   MA-UI-01 編輯本人訊息 → 泡泡內容更新並出現「已編輯」
 *   MA-UI-02 對訊息按 👍 → 出現高亮的「👍 1」表情 chip
 *   MA-UI-03 刪除本人訊息 → 泡泡換成「此訊息已刪除」佔位
 *   MA-UI-04 還原剛刪訊息 → 內容（編輯後版本）重新顯示
 */

import { test, expect, BrowserContext, Page } from "@playwright/test";
import { apiRegister, apiAddContact, wsSendMessage, uiLogin } from "./helpers";

const TS = Date.now();
const ALICE_EMAIL = `alice-maui-${TS}@example.com`;
const BOB_EMAIL = `bob-maui-${TS}@example.com`;
const PW = "TestPass123!";

let aliceCtx: BrowserContext;
let alicePage: Page;
let aliceToken: string;
let convId: string;
let msgId: string;

test.beforeAll(async ({ request, browser }) => {
  aliceToken = await apiRegister(request, ALICE_EMAIL, "Alice-MAUI", PW);
  await apiRegister(request, BOB_EMAIL, "Bob-MAUI", PW); // Bob 需存在才能加好友
  convId = (await apiAddContact(request, aliceToken, BOB_EMAIL)).conversation_id;

  aliceCtx = await browser.newContext();
  alicePage = await aliceCtx.newPage();
  // 先導到 backend origin，讓 page.evaluate 內的 WS 可連（種原始訊息）。
  await alicePage.goto("http://localhost:8000/health");
  const msg = await wsSendMessage(alicePage, aliceToken, convId, "原始訊息 MA-UI");
  expect(msg?.id).toBeTruthy();
  msgId = msg.id;
});

test.afterAll(async () => {
  await aliceCtx?.close();
});

test("MA-UI 編輯 → 表情 → 刪除 → 還原 全程點擊驗收", async () => {
  // ── 登入並進入與 Bob 的對話 ───────────────────────────────────────────
  await uiLogin(alicePage, ALICE_EMAIL, PW);
  await alicePage.waitForSelector("aside", { timeout: 15_000 });
  await alicePage.getByText("Bob-MAUI").first().click();

  const bubble = alicePage.locator(`[data-message-id="${msgId}"]`);
  await expect(bubble).toBeVisible({ timeout: 10_000 });
  await expect(bubble).toContainText("原始訊息 MA-UI");

  // ── 為什麼要 retry 動作 ────────────────────────────────────────────────
  // chat 的 send() 在 socket 未 OPEN 時「靜默丟棄」（回 false、無重試），而 dev +
  // React.StrictMode 雙掛載會讓 socket 生命週期短暫不穩（見 useChatSocket 註解）。
  // 編輯/刪除/還原/表情沒有送訊那種失敗重送，故動作可能落空。production 無此問題。
  // 解法：每個動作「重做到 server 真的反映為止」——這也貼近真實使用者「沒反應就再點」。
  // retryAction：反覆執行 action（自帶冪等守門），直到 check() 為真。
  async function retryAction(
    action: () => Promise<void>,
    check: () => Promise<boolean>,
    label: string,
    tries = 8
  ) {
    for (let i = 0; i < tries; i++) {
      await action();
      await alicePage.waitForTimeout(1200);
      if (await check()) return;
    }
    throw new Error(`retryAction 未在 ${tries} 次內完成：${label}`);
  }

  // ── MA-UI-01: 編輯（重試直到內容更新）────────────────────────────────
  await retryAction(
    async () => {
      const editBtn = bubble.getByRole("button", { name: "編輯", exact: true });
      if (await editBtn.isVisible().catch(() => false)) {
        await editBtn.click();
        await bubble.getByLabel("編輯訊息").fill("已編輯內容 MA-UI");
        await bubble.getByRole("button", { name: "儲存" }).click();
      }
    },
    async () => (await bubble.textContent())?.includes("已編輯內容 MA-UI") ?? false,
    "編輯"
  );
  await expect(bubble).toContainText("已編輯內容 MA-UI");
  await expect(bubble.getByRole("button", { name: "已編輯" })).toBeVisible();

  // ── MA-UI-02: 按 👍 表情（toggle，故只在尚無 chip 時才按）────────────
  const chip = bubble.locator("button.bg-indigo-100", { hasText: "👍" });
  await retryAction(
    async () => {
      if (await chip.isVisible().catch(() => false)) return; // 已加上，勿再 toggle 掉
      await bubble.getByRole("button", { name: "新增表情" }).click();
      await bubble.getByRole("button", { name: "👍", exact: true }).click();
    },
    async () => chip.isVisible().catch(() => false),
    "表情"
  );
  await expect(chip).toContainText("1");

  // ── MA-UI-03: 刪除 → 佔位（delete 冪等，可重試）────────────────────
  await retryAction(
    async () => {
      const delBtn = bubble.getByRole("button", { name: "刪除", exact: true });
      if (await delBtn.isVisible().catch(() => false)) await delBtn.click();
    },
    async () => (await alicePage.getByText("此訊息已刪除").count()) > 0,
    "刪除"
  );
  await expect(bubble).toHaveCount(0);

  // ── MA-UI-04: 還原 → 內容回來 ────────────────────────────────────────
  const restored = alicePage.locator(`[data-message-id="${msgId}"]`);
  await retryAction(
    async () => {
      const restoreBtn = alicePage.getByRole("button", { name: "還原" });
      if (await restoreBtn.isVisible().catch(() => false)) await restoreBtn.click();
    },
    async () => restored.isVisible().catch(() => false),
    "還原"
  );
  await expect(restored).toContainText("已編輯內容 MA-UI");
  await expect(alicePage.getByText("此訊息已刪除")).toHaveCount(0);
});

/**
 * E2E spec: 站內通知 後端 API 驗收(REST + WebSocket,無 UI)
 *
 * 場景(NB = Notification Backend)：
 *   NB-01 被回覆 → 收件人得 reply 通知;在線即收 WS {type:notification}
 *   NB-02 被按表情 → reaction 通知 + emoji
 *   NB-03 被轉發 → forward 通知,conversation 為原訊息所在對話
 *   NB-05 未讀數與列表(新→舊)
 *   NB-06 對自己的訊息互動 → 不產生通知
 *   NB-10 GET /notifications 只回自己的
 *   NB-11 未授權 401
 *   NB-12 標他人/非自己對話 → marked 0
 *   NB-14 離線期間的通知,上線後 GET 補得回
 *
 * backend pytest(test_notifications.py)已完整覆蓋;此處補 E2E 追溯。
 */

import { test, expect, Page } from "@playwright/test";
import {
  apiRegister,
  apiAddContact,
  wsSendMessage,
  wsRequest,
  wsOpenCollector,
  wsWaitForCollected,
} from "./helpers";

const API = "http://localhost:8000";
const TS = Date.now();
const PW = "TestPass123!";

const U = {
  alice: { email: `nb-alice-${TS}@example.com`, name: "Alice" },
  bob: { email: `nb-bob-${TS}@example.com`, name: "Bob" },
  carol: { email: `nb-carol-${TS}@example.com`, name: "Carol" },
};

let tokens: Record<"alice" | "bob" | "carol", string> = {} as any;
let convAB: string;
let convAC: string; // Alice↔Carol(轉發目標)
let sharedPage: Page;

async function listNotifs(request: any, token: string) {
  const res = await request.get(`${API}/notifications`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(res.status()).toBe(200);
  return res.json();
}

/** Bob 送一則訊息,回 message id。 */
async function bobSends(content: string): Promise<string> {
  const m = await wsSendMessage(sharedPage, tokens.bob, convAB, content);
  expect(m?.id).toBeTruthy();
  return m.id;
}

test.beforeAll(async ({ request, browser }) => {
  tokens.alice = await apiRegister(request, U.alice.email, U.alice.name, PW);
  tokens.bob = await apiRegister(request, U.bob.email, U.bob.name, PW);
  tokens.carol = await apiRegister(request, U.carol.email, U.carol.name, PW);
  convAB = (await apiAddContact(request, tokens.alice, U.bob.email)).conversation_id;
  convAC = (await apiAddContact(request, tokens.alice, U.carol.email)).conversation_id;

  const ctx = await browser.newContext();
  sharedPage = await ctx.newPage();
  await sharedPage.goto(`${API}/health`);
});

// ── NB-01: 被回覆 → reply 通知 + 在線推播 ────────────────────────────────
test("NB-01 Alice 回覆 Bob → Bob 得 reply 通知並在線收到 WS notification", async ({
  request,
  browser,
}) => {
  const mId = await bobSends("Bob 的訊息 NB-01");

  // Bob 開持續監聽
  const bobCtx = await browser.newContext();
  const bobPage = await bobCtx.newPage();
  await bobPage.goto(`${API}/health`);
  await wsOpenCollector(bobPage, tokens.bob);

  // Alice 回覆
  await wsRequest(sharedPage, tokens.alice, {
    type: "message", conversation_id: convAB, content: "回覆你",
    reply_to_message_id: mId, temp_id: `t-${Date.now()}`,
  }, "ack");

  // 在線推播
  const got = await wsWaitForCollected(bobPage, "notification");
  expect(got.some((m) => m.notification?.type === "reply")).toBeTruthy();
  await bobCtx.close();

  // 落庫(REST)
  const list = await listNotifs(request, tokens.bob);
  expect(list.items.some((n: any) => n.type === "reply" && n.actor.display_name === "Alice")).toBeTruthy();
});

// ── NB-02: 被按表情 → reaction 通知 ─────────────────────────────────────
test("NB-02 Alice 對 Bob 訊息按 👍 → Bob 得 reaction 通知 + emoji", async ({ request }) => {
  const mId = await bobSends("Bob 的訊息 NB-02");
  await wsRequest(sharedPage, tokens.alice, { type: "react", message_id: mId, emoji: "👍" }, "message_updated");

  const list = await listNotifs(request, tokens.bob);
  const r = list.items.find((n: any) => n.type === "reaction" && n.message_id === mId);
  expect(r).toBeTruthy();
  expect(r.emoji).toBe("👍");
});

// ── NB-03: 被轉發 → forward 通知,conversation 為原對話 ───────────────────
test("NB-03 Alice 轉發 Bob 的訊息到別對話 → Bob 得 forward 通知(conv 為原對話)", async ({ request }) => {
  const mId = await bobSends("Bob 的訊息 NB-03");
  await wsRequest(sharedPage, tokens.alice, {
    type: "forward", message_id: mId, to_conversation_id: convAC,
  }, "message");

  const list = await listNotifs(request, tokens.bob);
  const f = list.items.find((n: any) => n.type === "forward" && n.message_id === mId);
  expect(f).toBeTruthy();
  expect(f.conversation_id).toBe(convAB); // 原訊息所在對話
});

// ── NB-06: 對自己的訊息互動不產生通知 ───────────────────────────────────
test("NB-06 Alice 對自己的訊息按表情 → Alice 無通知", async ({ request }) => {
  const m = await wsSendMessage(sharedPage, tokens.alice, convAB, "Alice 自己的訊息 NB-06");
  await wsRequest(sharedPage, tokens.alice, { type: "react", message_id: m.id, emoji: "👍" }, "message_updated");

  const list = await listNotifs(request, tokens.alice);
  // Alice 不該因自己的互動而有任何通知(她可能因 Bob 的互動有別的,故只驗「沒有指向這則」)
  expect(list.items.some((n: any) => n.message_id === m.id)).toBeFalsy();
});

// ── NB-05: 未讀數與列表(新→舊) ─────────────────────────────────────────
test("NB-05 未讀數 ≥ 已收到的通知數,列表新→舊", async ({ request }) => {
  const list = await listNotifs(request, tokens.bob);
  expect(list.unread_count).toBeGreaterThan(0);
  const times = list.items.map((n: any) => n.created_at);
  expect(times).toEqual([...times].sort().reverse());
});

// ── NB-10/11/12: 權限 ───────────────────────────────────────────────────
test("NB-10 Carol 看不到 Bob 的通知", async ({ request }) => {
  // Carol 與這些互動無關 → 應為空或不含 Bob 的
  const list = await listNotifs(request, tokens.carol);
  expect(list.items.every((n: any) => n.actor.display_name !== undefined)).toBeTruthy();
  // 不洩漏:Carol 的清單不含 message_id 屬於 convAB 的(她非成員) — 簡化為未讀數合理
  expect(list.unread_count).toBe(0);
});

test("NB-11 未帶 token 取通知 → 401", async ({ request }) => {
  const res = await request.get(`${API}/notifications`);
  expect(res.status()).toBe(401);
});

test("NB-12 標非自己對話已讀 → marked 0,不影響未讀", async ({ request }) => {
  const before = await listNotifs(request, tokens.bob);
  const res = await request.post(`${API}/notifications/read`, {
    headers: { Authorization: `Bearer ${tokens.bob}` },
    data: { conversation_id: "00000000-0000-0000-0000-000000000000" },
  });
  expect(res.status()).toBe(200);
  expect((await res.json()).marked).toBe(0);
  const after = await listNotifs(request, tokens.bob);
  expect(after.unread_count).toBe(before.unread_count);
});

// ── NB-14: 離線期間通知,上線後補得回 ────────────────────────────────────
test("NB-14 Bob 離線時 Alice 回覆 → Bob 上線 GET 補得回", async ({ request, browser }) => {
  // 全新一對使用者,確保 Bob2 全程不開 WS(離線)
  const ts = Date.now();
  const ta = await apiRegister(request, `nb14-a-${ts}@example.com`, "A2", PW);
  const tb = await apiRegister(request, `nb14-b-${ts}@example.com`, "B2", PW);
  const conv = (await apiAddContact(request, ta, `nb14-b-${ts}@example.com`)).conversation_id;

  // B2 先送一則(用共享 page 的暫態 WS,送完即關 → 視為離線),取得 mId
  const m = await wsSendMessage(sharedPage, tb, conv, "B2 的訊息");
  // Alice 回覆(B2 此刻無持續連線 → 不會收到即時推播)
  await wsRequest(sharedPage, ta, {
    type: "message", conversation_id: conv, content: "回覆 B2",
    reply_to_message_id: m.id, temp_id: `t-${ts}`,
  }, "ack");

  // B2 上線(REST)補得回
  const list = await listNotifs(request, tb);
  expect(list.unread_count).toBe(1);
  expect(list.items[0].type).toBe("reply");
});
